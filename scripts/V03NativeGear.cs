using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;
using SolidWorks.Interop.sldworks;

public sealed partial class V03Native
{
    public static void RunGear(int release, string executable, string template, string output, string request, int pid, IDictionary evidence)
    {
        evidence["stage"]="attach";
        using (var process=Process.GetProcessById(pid))
            if (!String.Equals(process.MainModule.FileName,executable,StringComparison.OrdinalIgnoreCase) ||
                FileVersionInfo.GetVersionInfo(executable).FileMajorPart!=release)
                throw new InvalidOperationException("Unexpected SolidWorks executable or release");
        var app=(ISldWorks)Marshal.GetActiveObject("SldWorks.Application."+release);
        string revision=app.RevisionNumber();
        if (app.GetProcessID()!=pid || !revision.StartsWith(release+".",StringComparison.Ordinal) || app.GetDocumentCount()!=0)
            throw new InvalidOperationException("The selected COM session changed or contains open documents");
        evidence["revision"]=revision;
        evidence["pid"]=pid;
        evidence["documentCountBefore"]=0;
        var job=(IDictionary)new JavaScriptSerializer().DeserializeObject(File.ReadAllText(request));
        new V03Native(app,template,output,evidence).Execute(job);
    }

    private void BuildGear(IDictionary job)
    {
        string name=Text(job,"name");
        if (!System.Text.RegularExpressions.Regex.IsMatch(name,@"\A[A-Za-z][A-Za-z0-9_]{0,47}\z"))
            throw new InvalidOperationException("Unsafe gear filename");
        evidence["stage"]="root_blank";
        model=NewModel(Part);
        IFeature basePlane=Features().First(f=>f.GetTypeName2()=="RefPlane");
        double width=Number(job,"width"), root=Number(job,"root");
        IFeature blank=GearSketch(basePlane,"RootBlank",0,null,root);
        GearBoss(blank,"RootDiameter",width);
        GearSolid();
        evidence["stage"]="seed_tooth";
        double twist=Number(job,"twist");
        var sections=Items(job["sections"]).Cast<IDictionary>().ToArray();
        IFeature seed;
        if (Math.Abs(twist)<1e-8)
        {
            IFeature sketch=GearSketch(basePlane,"ToothSection",0,sections[0]["points"],0);
            seed=GearBoss(sketch,"InvoluteTooth",width);
        }
        else
        {
            var profiles=new List<IFeature>();
            foreach (var section in sections)
                profiles.Add(GearSketch(basePlane,"ToothSection"+profiles.Count,Number(section,"z"),section["points"],0));
            model.ClearSelection2(true);
            foreach (var sketch in profiles) Selected(sketch.Select2(true,1));
            seed=Track("InsertProtrusionBlend2",()=>model.FeatureManager.InsertProtrusionBlend2(
                false,false,false,1,0,0,1,1,false,false,false,0,0,0,true,true,true,0));
            NameFeature(seed,"InvoluteTooth");
            Rebuild();
        }
        GearSolid();
        bool only=(bool)job["seed_only"];
        if (!only)
        {
            evidence["stage"]="tooth_pattern";
            IFace2 cylinder=Items(GearSolid().GetFaces()).Cast<IFace2>().First(face=>{
                var surface=(ISurface)face.GetSurface();
                return surface.IsCylinder() && Math.Abs(Vector(surface.CylinderParams)[6]-M(root))<1e-8;
            });
            model.ClearSelection2(true);
            SelectEntity(cylinder,false,1);
            Selected(seed.Select2(true,4));
            var pattern=Track("FeatureCircularPattern4",()=>model.FeatureManager.FeatureCircularPattern4(
                (int)Number(job,"teeth"),2*Math.PI,false,"",true,true,false));
            NameFeature(pattern,"ToothCircularPattern");
            Rebuild();
            GearSolid();

            evidence["stage"]="bore";
            GearCut(GearSketch(basePlane,"BoreSection",width,null,Number(job,"bore")/2),"ShaftBore",width);
            double key=Number(job,"key"), r=Number(job,"bore")/2;
            if (key>0)
            {
                double[] p={r-key*0.26,-key/2,r+Number(job,"key_depth"),key/2};
                var points=new[]{new[]{p[0],p[1]},new[]{p[2],p[1]},new[]{p[2],p[3]},new[]{p[0],p[3]}};
                evidence["stage"]="keyway";
                GearCut(GearSketch(basePlane,"KeywaySection",width,points,0),"ParallelKeyway",width);
            }
        }
        evidence["stage"]="verify_gear";
        evidence["geometry"]=ReadGear(job);
        string path=Path.Combine(output,name+".SLDPRT");
        evidence["stage"]="save_gear";
        Save(path,"nativeSave");
        CloseModel(model);
        evidence["stage"]="reopen_gear";
        model=Open(path,Part,true,"nativeOpen");
        Activate(model);
        Rebuild();
        evidence["reopenedGeometry"]=ReadGear(job);
        CloseModel(model);
    }

    private IFeature GearSketch(IFeature basePlane,string name,double z,object points,double radius)
    {
        model.ClearSelection2(true);
        Selected(basePlane.Select2(false,0));
        if(z>0)
        {
            var plane=Track("InsertRefPlane",()=>model.FeatureManager.InsertRefPlane(8,M(z),0,0,0,0)) as IFeature;
            if(plane==null) plane=model.Extension.GetLastFeatureAdded() as IFeature;
            if(plane==null || plane.GetTypeName2()!="RefPlane") throw new InvalidOperationException("Offset plane failed");
            model.ClearSelection2(true);
            Selected(plane.Select2(false,0));
        }
        var manager=model.SketchManager;
        manager.InsertSketch(true);
        var sketch=manager.ActiveSketch;
        if(sketch==null) throw new InvalidOperationException("Could not open sketch");
        manager.AddToDB=true;
        try
        {
            if(points==null)
            {
                var p=ToSketch(sketch,new[]{0d,0d},M(z));
                if(manager.CreateCircleByRadius(p[0],p[1],0,M(radius))==null)
                    throw new InvalidOperationException("Circle creation failed");
            }
            else
            {
                var local=Items(points).Select(Vector).Select(p=>ToSketch(sketch,p,M(z))).ToArray();
                for(int i=0;i<local.Length;i++)
                {
                    var p=local[i]; var q=local[(i+1)%local.Length];
                    if(manager.CreateLine(p[0],p[1],0,q[0],q[1],0)==null)
                        throw new InvalidOperationException("Tooth contour could not close");
                }
            }
        }
        finally {manager.AddToDB=false;}
        manager.InsertSketch(true);
        var feature=model.Extension.GetLastFeatureAdded() as IFeature;
        if(feature==null || feature.GetTypeName2()!="ProfileFeature") throw new InvalidOperationException("Sketch missing");
        NameFeature(feature,name);
        return feature;
    }

    private IFeature GearBoss(IFeature sketch,string name,double width)
    {
        model.ClearSelection2(true);
        Selected(sketch.Select2(false,0));
        var feature=Track("FeatureExtrusion3",()=>model.FeatureManager.FeatureExtrusion3(true,false,false,0,0,M(width),0,
            false,false,false,false,0,0,false,false,false,false,true,true,true,0,0,false));
        NameFeature(feature,name);
        Rebuild();
        return feature;
    }

    private void GearCut(IFeature sketch,string name,double width)
    {
        model.ClearSelection2(true);
        Selected(sketch.Select2(false,0));
        var feature=Track("FeatureCut3",()=>model.FeatureManager.FeatureCut3(true,false,false,0,0,M(width),0,
            false,false,false,false,0,0,false,false,false,false,false,true,true,false,false,false,0,0,false));
        NameFeature(feature,name);
        Rebuild();
        GearSolid();
    }

    private IBody2 GearSolid()
    {
        var body=SolidBody();
        int code=Track("Check2",()=>body.Check2());
        if(code!=0)
        {
            evidence["bodyCheckCode"]=code;
            try {evidence["faultEntityAvailable"]=body.Check3!=null;}
            catch(COMException ex){evidence["faultQueryHResult"]=ex.HResult;}
            throw new InvalidOperationException("Native gear body check returned "+code);
        }
        return body;
    }

    private IDictionary ReadGear(IDictionary job)
    {
        IBody2 body=GearSolid();
        double width=Number(job,"width"), tip=Number(job,"tip"), angle=Number(job,"tip_half_angle");
        int count=(bool)job["seed_only"]?1:(int)Number(job,"teeth");
        double bottom=Extreme(body,2,-1), top=Extreme(body,2,1);
        Near(bottom,0,0.006,"gear width origin");
        Near(top,width,0.006,"gear width");
        var stations=new[]{new List<double>(),new List<double>()};
        foreach(IEdge edge in Items(body.GetEdges()).OfType<IEdge>())
            foreach(var end in new[]{edge.GetStartVertex() as IVertex,edge.GetEndVertex() as IVertex})
            {
                if(end==null) continue;
                var p=Vector(end.GetPoint()).Select(Mm).ToArray();
                if(Math.Abs(Math.Sqrt(p[0]*p[0]+p[1]*p[1])-tip)>0.006) continue;
                int station=Math.Abs(p[2])<0.006?0:Math.Abs(p[2]-width)<0.006?1:-1;
                if(station<0) continue;
                double a=Math.Atan2(p[1],p[0]);
                if(!stations[station].Any(other=>Math.Abs(Wrap(other-a))<1e-5)) stations[station].Add(a);
            }
        for(int end=0;end<stations.Length;end++)
        {
            if(stations[end].Count!=2*count)
                throw new InvalidOperationException("Tip vertices at station "+end+": "+stations[end].Count+" (expected "+(2*count)+")");
            for(int i=0;i<count;i++)
                foreach(double edge in new[]{-angle,angle})
                {
                    double expected=Number(job,"phase")+end*Number(job,"twist")+2*Math.PI*i/(int)Number(job,"teeth")+edge;
                    if(!stations[end].Any(a=>Math.Abs(Wrap(a-expected))<0.00025))
                        throw new InvalidOperationException("Angular tooth station or handedness differs from requested profile");
                }
        }
        var ids=new List<string>{"RootDiameter","InvoluteTooth"};
        if(count>1){ids.Add("ToothCircularPattern");ids.Add("ShaftBore");if(Number(job,"key")>0)ids.Add("ParallelKeyway");}
        var health=new Hashtable();
        foreach(string id in ids)
        {
            var feature=Find(id);
            bool warning;
            int error=feature.GetErrorCode2(out warning);
            if(error!=0 || warning) throw new InvalidOperationException("Native feature unhealthy: "+id);
            health[id]=feature.GetTypeName2();
        }
        if(count>1)
        {
            var bore=Items(body.GetFaces()).OfType<IFace2>().Select(f=>(ISurface)f.GetSurface())
                .Where(s=>s.IsCylinder()).Select(s=>Vector(s.CylinderParams))
                .Where(p=>Math.Abs(p[5])>0.999 && Math.Abs(Mm(p[0]))<0.006 && Math.Abs(Mm(p[1]))<0.006)
                .Any(p=>Math.Abs(Mm(p[6]*2)-Number(job,"bore"))<0.006);
            if(!bore) throw new InvalidOperationException("Native shaft bore diameter is missing");
        }
        return new Hashtable{{"solids",1},{"bodyCheckCode",0},{"verifiedTeeth",count},{"widthMm",top-bottom},
            {"tipVertexCounts",stations.Select(s=>s.Count).ToArray()},{"twistDeg",Number(job,"twist")*180/Math.PI},
            {"verifiedPhase",true},{"features",health}};
    }

    private static double Wrap(double radians) { return Math.Atan2(Math.Sin(radians),Math.Cos(radians)); }
}

