using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Web.Script.Serialization;
using SolidWorks.Interop.sldworks;

public sealed partial class V03Native
{
    private const int Part = 1;
    private const int Assembly = 2;
    private const int Drawing = 3;
    private const int Silent = 1;
    private const int ReadOnly = 2;
    private const int PromptForDimension = 10;
    private const double DimensionTolerance = 0.003;
    private readonly ISldWorks app;
    private readonly IDictionary evidence;
    private readonly ArrayList calls = new ArrayList();
    private readonly List<IModelDoc2> outstanding = new List<IModelDoc2>();
    private readonly Dictionary<string, double> elevations = new Dictionary<string, double>();
    private readonly string output;
    private readonly string template;
    private IModelDoc2 model;
    private int rebuilds;

    private V03Native(ISldWorks app, string template, string output, IDictionary evidence)
    {
        this.app = app;
        this.template = template;
        this.output = output;
        this.evidence = evidence;
        evidence["trackedCalls"] = calls;
    }

    public static void Run(int revision, string executable, string template, string output, string spec, IDictionary evidence)
    {
        Run(revision, executable, template, output, spec, evidence, 0);
    }

    public static void Run(int revision, string executable, string template, string output, string spec, IDictionary evidence, int targetPid)
    {
        evidence["stage"] = "attach";
        var active = Process.GetProcessesByName("SLDWORKS")
            .Where(process => targetPid == 0 || process.Id == targetPid).ToArray();
        if (active.Length != 1 || !String.Equals(active[0].MainModule.FileName, executable, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Open exactly one configured interactive SolidWorks window.");
        var app = V03NativeHost.Attach(revision, targetPid);
        string actual = app.RevisionNumber();
        int pid = app.GetProcessID();
        if (!actual.StartsWith(revision + ".", StringComparison.Ordinal) || pid != active[0].Id)
            throw new InvalidOperationException("Unexpected COM revision or PID.");
        int documents = app.GetDocumentCount();
        evidence["revision"] = actual;
        evidence["pid"] = pid;
        evidence["documentCountBefore"] = documents;
        if (documents != 0)
            throw new InvalidOperationException("Use an empty interactive SolidWorks session for an automated job.");
        var serializer = new JavaScriptSerializer { RecursionLimit = 32, MaxJsonLength = 4 * 1024 * 1024 };
        var data = serializer.DeserializeObject(File.ReadAllText(spec)) as IDictionary;
        if (data == null)
            throw new InvalidOperationException("Missing normalized CAD job.");
        RequireFileId(Text(Child(data, "outputs"), "name"));
        if (data["dependencies"] != null)
            foreach (IDictionary dependency in Items(data["dependencies"]))
                RequireFileId(Text(dependency, "id"));
        if (data["hierarchy"] is bool && (bool)data["hierarchy"])
        {
            RequireFileId(Text(data, "subassembly"));
            foreach (string id in Items(data["child_parts"])) RequireFileId(id);
        }
        var run = new V03Native(app, template, output, evidence);
        run.Execute(data);
    }

    private static void RequireFileId(string name)
    {
        if (String.IsNullOrEmpty(name) || !System.Text.RegularExpressions.Regex.IsMatch(name,
            @"\A[A-Za-z][A-Za-z0-9_-]{0,63}\z") ||
            System.Text.RegularExpressions.Regex.IsMatch(name,
            @"\A(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])\z",
            System.Text.RegularExpressions.RegexOptions.IgnoreCase))
            throw new InvalidDataException("Invalid native artifact identifier.");
    }

    private void Execute(IDictionary job)
    {
        bool previous = app.GetUserPreferenceToggle(PromptForDimension);
        try
        {
            if (previous)
                app.SetUserPreferenceToggle(PromptForDimension, false);
            if (app.GetUserPreferenceToggle(PromptForDimension))
                throw new InvalidOperationException("Cannot suppress the sketch dimension input prompt.");
            Dispatch(job);
        }
        catch (Exception failure)
        {
            evidence["operationError"] = failure.Message;
            throw;
        }
        finally
        {
            try { CloseOwnedDocuments(); }
            finally
            {
                if (app.GetUserPreferenceToggle(PromptForDimension) != previous)
                    app.SetUserPreferenceToggle(PromptForDimension, previous);
                evidence["preferencesRestored"] = app.GetUserPreferenceToggle(PromptForDimension) == previous;
                evidence["documentCountAfter"] = app.GetDocumentCount();
                evidence["rebuildCount"] = rebuilds;
                evidence["trackedComInvocations"] = calls.Count;
            }
        }
        if (app.GetDocumentCount() != 0 || !(bool)evidence["preferencesRestored"])
            throw new InvalidOperationException("The original SolidWorks job session state was not restored.");
        if (evidence.Contains("nativeOpen")) VerifyNativeFile();
        evidence["stage"] = "complete";
    }

    private void Dispatch(IDictionary job)
    {
        if (Text(job, "document_type") == "gear")
            BuildGear(job);
        else if (Text(job, "document_type") == "part")
            BuildPart(job);
        else if (Text(job, "document_type") == "assembly")
            BuildAssembly(job);
        else if (Text(job, "document_type") == "drawing")
            BuildDrawing(job);
        else
            throw new InvalidOperationException("Unsupported native document type.");
    }

    private void BuildPart(IDictionary job)
    {
        string name = Text(Child(job, "outputs"), "name");
        var validation = Child(job, "validation");
        evidence["stage"] = "new_part";
        model = NewModel(Part);
        var basePlane = Features().First(feature => feature.GetTypeName2() == "RefPlane");
        var expected = new List<IDictionary>();
        foreach (IDictionary operation in Items(job["features"]))
        {
            string id = Text(operation, "id");
            evidence["stage"] = "feature:" + id;
            RequireActive(model);
            string plane = Text(operation, "plane");
            double elevation = plane == "base" ? 0 : elevations[plane];
            var profile = Child(operation, "profile");
            model.ClearSelection2(true);
            if (plane == "base")
                Selected(basePlane.Select2(false, 0));
            else
                SelectEntity(SingleTopFace(elevation, ProfileCenter(profile)), false, 0);
            string op = Text(operation, "operation");
            ISketchSegment axis;
            var sketch = DrawProfile(id, profile, elevation, op == "boss_revolve", out axis);
            model.ClearSelection2(true);
            Selected(sketch.Select2(false, 0));
            IFeature feature;
            if (op == "boss_extrude")
            {
                double depth = Number(operation, "depth");
                elevations.Add(id, elevation + M(depth));
                feature = Track("FeatureExtrusion3", () => model.FeatureManager.FeatureExtrusion3(
                    true, false, false, 0, 0, M(depth), 0, false, false, false, false, 0, 0,
                    false, false, false, false, true, true, true, 0, 0, false));
            }
            else if (op == "through_cut")
            {
                feature = Track("FeatureCut3", () => model.FeatureManager.FeatureCut3(
                    true, false, false, 1, 0, 0.01, 0, false, false, false, false, 0, 0, false, false,
                    false, false, false, true, true, false, false, false, 0, 0, false));
            }
            else if (op == "boss_revolve")
            {
                Selected(axis.Select4(true, Selection(4)));
                feature = Track("FeatureRevolve2", () => model.FeatureManager.FeatureRevolve2(
                    true, true, false, false, false, false, 0, 0, 2 * Math.PI, 0,
                    false, false, 0, 0, 0, 0, 0, true, true, true));
            }
            else
                throw new InvalidOperationException("Invalid native feature operation.");
            NameFeature(feature, id);
            expected.Add(operation);
            Rebuild();
            ReadNativeFeatures(expected);
            SolidBody();
        }

        evidence["stage"] = "verify_initial_geometry";
        evidence["geometry"] = VerifyGeometry(validation);
        evidence["features"] = ReadNativeFeatures(expected);
        string nativePath = Path.Combine(output, name + ".SLDPRT");
        string stepPath = Path.Combine(output, name + ".STEP");
        evidence["stage"] = "save_part";
        Save(nativePath, "nativeSave");
        Save(stepPath, "stepSave");
        CloseModel(model);
        evidence["stage"] = "reopen_part";
        model = Open(nativePath, Part, false, "nativeOpen");
        Rebuild();
        evidence["reopenedGeometry"] = VerifyGeometry(validation);
        evidence["reopenedFeatures"] = ReadNativeFeatures(expected);
        if (validation.Contains("edit"))
            ProbeDimension(Child(validation, "edit"), validation);
        CloseModel(model);
        evidence["stage"] = "reimport_step";
        model = ImportStep(stepPath);
        Rebuild();
        evidence["stepGeometry"] = VerifyGeometry(validation);
        CloseModel(model);
    }

    private IFeature DrawProfile(string name, IDictionary profile, double elevation, bool axial, out ISketchSegment axis)
    {
        Track("InsertSketch", () => model.SketchManager.InsertSketch(true));
        var manager = model.SketchManager;
        var sketch = manager.ActiveSketch;
        if (sketch == null)
            throw new InvalidOperationException("SolidWorks did not enter the selected plane sketch.");
        axis = null;
        string kind = Text(profile, "kind");
        if (kind == "circle")
        {
            double[] center = Vector(profile["center"]);
            double diameter = Number(profile, "diameter");
            double radius = diameter / 2;
            double[] point = ToSketch(sketch, center, elevation);
            var circle = Track("CreateCircleByRadius", () => manager.CreateCircleByRadius(point[0], point[1], 0, M(radius)));
            model.ClearSelection2(true);
            Selected(((ISketchSegment)circle).Select4(false, null));
            var dimension = Track("AddDiameterDimension2", () => model.AddDiameterDimension2(M(center[0] + radius * 1.2),
                M(center[1] + radius), elevation)) as IDisplayDimension;
            if (dimension == null)
                throw new InvalidOperationException("The circle diameter dimension was not retained.");
            Near(Mm(dimension.GetDimension2(0).SystemValue), diameter, DimensionTolerance, "circle diameter");
        }
        else if (kind == "rectangle")
        {
            double[] lower = Vector(profile["lower"]);
            double[] upper = Vector(profile["upper"]);
            double[] a = ToSketch(sketch, lower, elevation);
            double[] b = ToSketch(sketch, upper, elevation);
            var lines = Track("CreateCornerRectangle", () => manager.CreateCornerRectangle(a[0], a[1], 0, b[0], b[1], 0)) as Array;
            if (lines == null || lines.Length != 4)
                throw new InvalidOperationException("SolidWorks did not create the expected rectangle.");
            AddRectangleDimensions(lines, lower, upper, elevation);
        }
        else
        {
            var points = Items(profile["points"]).Select(Vector).ToArray();
            for (int index = 0; index < points.Length; index++)
            {
                double[] a = ToSketch(sketch, points[index], elevation);
                double[] b = ToSketch(sketch, points[(index + 1) % points.Length], elevation);
                if (Track("CreateLine", () => manager.CreateLine(a[0], a[1], 0, b[0], b[1], 0)) == null)
                    throw new InvalidOperationException("SolidWorks could not create a profile segment.");
            }
            if (axial)
            {
                double[] a = ToSketch(sketch, new[] { -25.0, 0.0 }, elevation);
                double[] b = ToSketch(sketch, new[] { 25.0, 0.0 }, elevation);
                axis = Track("CreateCenterLine", () => manager.CreateCenterLine(a[0], a[1], 0, b[0], b[1], 0));
                if (axis == null || !axis.ConstructionGeometry)
                    throw new InvalidOperationException("The legal revolution axis did not create construction geometry.");
            }
        }
        Track("CloseSketch", () => manager.InsertSketch(true));
        var feature = model.Extension.GetLastFeatureAdded() as IFeature;
        if (feature == null || feature.GetTypeName2() != "ProfileFeature")
            throw new InvalidOperationException("Could not find the finished profile sketch.");
        NameFeature(feature, name + " Profile");
        return feature;
    }

    private void AddRectangleDimensions(Array lines, double[] lower, double[] upper, double z)
    {
        ISketchSegment horizontal = null;
        ISketchSegment vertical = null;
        foreach (ISketchSegment segment in lines)
        {
            var line = (ISketchLine)segment;
            var start = (ISketchPoint)line.GetStartPoint2();
            var end = (ISketchPoint)line.GetEndPoint2();
            if (Math.Abs(start.Y - end.Y) < 1e-9) horizontal = segment;
            if (Math.Abs(start.X - end.X) < 1e-9) vertical = segment;
        }
        if (horizontal == null || vertical == null)
            throw new InvalidOperationException("Rectangle does not include horizontal and vertical segments in sketch space.");
        model.ClearSelection2(true);
        Selected(horizontal.Select4(false, null));
        var width = Track("AddHorizontalDimension2", () => model.AddHorizontalDimension2(
            M((lower[0] + upper[0]) / 2), M(lower[1] - 5), z)) as IDisplayDimension;
        model.ClearSelection2(true);
        Selected(vertical.Select4(false, null));
        var height = Track("AddVerticalDimension2", () => model.AddVerticalDimension2(
            M(upper[0] + 5), M((lower[1] + upper[1]) / 2), z)) as IDisplayDimension;
        if (width == null || height == null)
            throw new InvalidOperationException("Native rectangle dimensions were not created.");
        Near(Mm(width.GetDimension2(0).SystemValue), upper[0] - lower[0], DimensionTolerance, "rectangle width");
        Near(Mm(height.GetDimension2(0).SystemValue), upper[1] - lower[1], DimensionTolerance, "rectangle height");
    }

    private void ProbeDimension(IDictionary edit, IDictionary original)
    {
        evidence["stage"] = "dimension_edit";
        var feature = Find(Text(edit, "feature_id"));
        var display = feature.GetFirstDisplayDimension() as IDisplayDimension;
        if (display == null)
            throw new InvalidOperationException("Cannot find the extrusion dimension.");
        var dimension = display.GetDimension2(0);
        double start = dimension.SystemValue;
        double updated = Number(edit, "depth_mm");
        var result = new Hashtable { {"name", dimension.FullName}, {"initialMm", Mm(start)}, {"requestedMm", updated} };
        evidence["edit"] = result;
        int editCode = Track("SetSystemValue3", () => dimension.SetSystemValue3(M(updated), 1, null));
        result["changeCode"] = editCode;
        if (editCode != 0)
            throw new InvalidOperationException("SolidWorks refused the temporary dimension edit: " + editCode);
        try
        {
            Rebuild();
            Near(Mm(dimension.SystemValue), updated, DimensionTolerance, "edited driving dimension");
            result["geometry"] = VerifyGeometry(Child(edit, "geometry"));
        }
        finally
        {
            int restore = Track("RestoreDimension", () => dimension.SetSystemValue3(start, 1, null));
            result["restoreCode"] = restore;
            if (restore != 0)
                throw new InvalidOperationException("SolidWorks refused to restore the temporary edit: " + restore);
            Rebuild();
            result["restoredGeometry"] = VerifyGeometry(original);
        }
    }

    private IList ReadNativeFeatures(IEnumerable<IDictionary> expected)
    {
        var result = new ArrayList();
        foreach (IDictionary operation in expected)
        {
            string name = Text(operation, "id");
            var feature = Find(name);
            string original = feature.GetTypeName();
            string kind = Text(operation, "operation");
            if (kind == "boss_extrude" && original != "Boss" && original != "Extrusion" ||
                kind == "through_cut" && original != "Cut" ||
                kind == "boss_revolve" && original != "Revolution" && original != "Revolute" && original != "RevBoss")
                throw new InvalidOperationException("Unexpected feature type for " + name + ": " + original);
            bool warning;
            int error = feature.GetErrorCode2(out warning);
            if (error != 0)
                throw new InvalidOperationException("Feature health failure on " + name + ": " + error);
            var dimensions = new ArrayList();
            for (object item = feature.GetFirstDisplayDimension(); item != null; item = feature.GetNextDisplayDimension(item))
            {
                var dimension = ((IDisplayDimension)item).GetDimension2(0);
                dimensions.Add(new Hashtable { {"name", dimension.FullName}, {"systemValue", dimension.SystemValue} });
            }
            var profile = ((IPartDoc)model).FeatureByName(name + " Profile") as IFeature;
            if (profile == null)
                throw new InvalidOperationException("Could not read the saved profile for " + name);
            int profileCode = profile.GetErrorCode2(out warning);
            if (profileCode != 0)
                throw new InvalidOperationException("Profile health failure on " + name + ": " + profileCode);
            var profileDimensions = new ArrayList();
            for (object item = profile.GetFirstDisplayDimension(); item != null; item = profile.GetNextDisplayDimension(item))
            {
                var dimension = ((IDisplayDimension)item).GetDimension2(0);
                profileDimensions.Add(new Hashtable { {"name", dimension.FullName}, {"systemValue", dimension.SystemValue} });
            }
            string sketchKind = Text(Child(operation, "profile"), "kind");
            if (profileDimensions.Count < (sketchKind == "rectangle" ? 2 : sketchKind == "circle" ? 1 : 0))
                throw new InvalidOperationException("Missing native driving sketch dimensions for " + name);
            result.Add(new Hashtable { {"id", name}, {"type", original}, {"error", error}, {"dimensions", dimensions},
                {"profileError", profileCode}, {"profileDimensions", profileDimensions} });
        }
        return result;
    }

    private IDictionary VerifyGeometry(IDictionary expected)
    {
        IBody2 body = SolidBody();
        int code = Track("Check2", () => body.Check2());
        if (code != 0)
            throw new InvalidOperationException("Solid body integrity check failed: " + code);
        var mass = Track("CreateMassProperty", () => model.Extension.CreateMassProperty());
        mass.UseSystemUnits = true;
        double volume = mass.Volume * 1e9;
        Near(volume, Number(expected, "volume_mm3"), 0.02, "solid volume mm3");
        double[][] actualBounds = { new double[3], new double[3] };
        for (int axis = 0; axis < 3; axis++)
        {
            actualBounds[0][axis] = Extreme(body, axis, -1);
            actualBounds[1][axis] = Extreme(body, axis, 1);
        }
        double[][] targetBounds = Items(expected["bounds_mm"]).Select(Vector).ToArray();
        for (int side = 0; side < 2; side++)
            for (int axis = 0; axis < 3; axis++)
                Near(actualBounds[side][axis], targetBounds[side][axis], DimensionTolerance, "solid bound");
        var holes = new ArrayList();
        if (Items(expected["cylinders"]).Any())
            holes = VerifyCylinders(body, expected["cylinders"]);
        var result = new Hashtable { {"verified", true}, {"volumeMm3", volume}, {"boundsMm", actualBounds},
            {"solids", 1}, {"bodyCheckCode", code}, {"cylinders", holes} };
        if (expected.Contains("centroid_mm"))
        {
            // A unit density gives the geometric centroid without a material assignment.
            var bodyProperties = Vector(Track("BodyGetMassProperties", () => body.GetMassProperties(1)));
            if (bodyProperties.Length != 12)
                throw new InvalidOperationException("Unexpected native body mass property data.");
            double[] centroid = bodyProperties.Take(3).Select(Mm).ToArray();
            double[] target = Vector(expected["centroid_mm"]);
            for (int axis = 0; axis < 3; axis++)
                Near(centroid[axis], target[axis], DimensionTolerance, "solid centroid axis " + axis);
            Near(bodyProperties[3] * 1e9, volume, .02, "independent native volume query");
            result["centroidMm"] = centroid;
            result["volumeCrossCheckMm3"] = bodyProperties[3] * 1e9;
        }
        return result;
    }

    private double Extreme(IBody2 body, int index, int sign)
    {
        double x, y, z;
        calls.Add("GetExtremePoint");
        if (!body.GetExtremePoint(index == 0 ? sign : 0, index == 1 ? sign : 0, index == 2 ? sign : 0, out x, out y, out z))
            throw new InvalidOperationException("SolidWorks refused an exact bound query.");
        return Mm(index == 0 ? x : index == 1 ? y : z);
    }

    private IBody2 SolidBody()
    {
        var bodies = Track("GetBodies2", () => ((IPartDoc)model).GetBodies2(0, false)) as Array;
        if (bodies == null || bodies.Length != 1)
            throw new InvalidOperationException("The part must have exactly one solid body.");
        return (IBody2)bodies.GetValue(0);
    }

    private double[] ProfileCenter(IDictionary profile)
    {
        string kind = Text(profile, "kind");
        if (kind == "circle") return Vector(profile["center"]);
        if (kind == "polygon")
        {
            var points = Items(profile["points"]).Select(Vector).ToArray();
            return new[] { points.Average(point => point[0]), points.Average(point => point[1]) };
        }
        double[] lower = Vector(profile["lower"]), upper = Vector(profile["upper"]);
        return new[] { (lower[0] + upper[0]) / 2, (lower[1] + upper[1]) / 2 };
    }

    private IFace2 SingleTopFace(double z, double[] point)
    {
        double x = M(point[0]), y = M(point[1]);
        var candidates = Items(SolidBody().GetFaces()).Cast<IFace2>().Where(face => {
            if (!((ISurface)face.GetSurface()).IsPlane()) return false;
            double[] box = Vector(face.GetBox());
            if (Math.Abs(box[2] - z) >= 1e-8 || Math.Abs(box[5] - z) >= 1e-8) return false;
            double[] nearest = Vector(face.GetClosestPointOn(x, y, z));
            return Math.Abs(nearest[0] - x) < 1e-8 && Math.Abs(nearest[1] - y) < 1e-8 && Math.Abs(nearest[2] - z) < 1e-8;
        }).ToArray();
        if (candidates.Length != 1)
            throw new InvalidOperationException("The referenced extrusion did not give one unambiguous planar face at " + Mm(z) + " mm.");
        return candidates[0];
    }

    private double[] ToSketch(ISketch sketch, double[] point, double z)
    {
        var utility = (IMathUtility)app.GetMathUtility();
        var world = (IMathPoint)utility.CreatePoint(new[] { M(point[0]), M(point[1]), z });
        return Vector(((IMathPoint)world.MultiplyTransform(sketch.ModelToSketchTransform)).ArrayData);
    }

    private SelectData Selection(int mark)
    {
        SelectData data = ((ISelectionMgr)model.SelectionManager).CreateSelectData();
        data.Mark = mark;
        return data;
    }

    private void SelectEntity(object entity, bool append, int mark)
    {
        Selected(((IEntity)entity).Select4(append, Selection(mark)));
    }

    private IEnumerable<IFeature> Features()
    {
        for (var feature = model.FirstFeature() as IFeature; feature != null; feature = feature.GetNextFeature() as IFeature)
            yield return feature;
    }

    private IFeature Find(string name)
    {
        var feature = Features().FirstOrDefault(f => f.Name == name);
        if (feature == null) throw new InvalidOperationException("Missing feature: " + name);
        return feature;
    }

    private static void Selected(bool ok) { if (!ok) throw new InvalidOperationException("Required SolidWorks selection failed."); }

    private static void NameFeature(IFeature feature, string name)
    {
        if (feature == null) throw new InvalidOperationException("SolidWorks did not create " + name);
        feature.Name = name;
        if (feature.Name != name) throw new InvalidOperationException("Cannot establish unique native feature name " + name);
    }

    private IModelDoc2 NewModel(int kind, string selectedTemplate = null)
    {
        var doc = (IModelDoc2)Track("NewDocument", () => app.NewDocument(selectedTemplate ?? template, 0, 0, 0));
        Own(doc);
        if (doc.GetType() != kind) throw new InvalidOperationException("The template returned the wrong document type.");
        Activate(doc);
        return doc;
    }

    private void Own(IModelDoc2 doc)
    {
        if (doc == null) throw new InvalidOperationException("A native document was not returned by SolidWorks.");
        if (!outstanding.Any(item => Object.ReferenceEquals(item, doc))) outstanding.Add(doc);
    }

    private void RequireActive(IModelDoc2 doc)
    {
        if (doc == null || !Object.ReferenceEquals(doc, app.ActiveDoc))
            throw new InvalidOperationException("The current job document is not active.");
    }

    private void Rebuild()
    {
        RequireActive(model);
        rebuilds++;
        if (!Track("ForceRebuild3", () => model.ForceRebuild3(false)))
            throw new InvalidOperationException("Native rebuild failed.");
    }

    private void Save(string path, string key)
    {
        Save(path, key, null);
    }

    private void Save(string path, string key, object exportData)
    {
        RequireActive(model);
        if (File.Exists(path)) throw new IOException("The artifact already exists: " + path);
        model.ClearSelection2(true);
        int errors = 0, warnings = 0;
        calls.Add("SaveAs");
        bool saved = model.Extension.SaveAs(path, 0, Silent, exportData, ref errors, ref warnings);
        evidence[key] = new Hashtable { {"path", path}, {"ok", saved}, {"errors", errors}, {"warnings", warnings} };
        if (!saved || errors != 0 || warnings != 0 || !File.Exists(path) || new FileInfo(path).Length == 0)
            throw new IOException("Native save or export failed: " + errors + "/" + warnings + ", " + Path.GetFileName(path));
    }

    private IModelDoc2 Open(string path, int kind, bool readOnly, string key, int allowedWarnings = 0)
    {
        if (app.GetOpenDocumentByName(path) != null)
            throw new InvalidOperationException("Reopen proof requires a closed artifact.");
        int errors = 0, warnings = 0;
        var file = key == "nativeOpen" ? ReadNativeFile(path) : null;
        calls.Add("OpenDoc6");
        var doc = (IModelDoc2)app.OpenDoc6(path, kind, Silent | (readOnly ? ReadOnly : 0), "", ref errors, ref warnings);
        if (doc != null) Own(doc);
        int actualType = doc == null ? 0 : doc.GetType();
        var opened = new Hashtable { {"path", path}, {"ok", doc != null}, {"errors", errors},
            {"warnings", warnings}, {"documentType", actualType} };
        evidence[key] = opened;
        if (doc == null || actualType != kind || errors != 0 || (warnings & ~allowedWarnings) != 0 ||
            !String.Equals(doc.GetPathName(), path, StringComparison.OrdinalIgnoreCase))
            throw new IOException("Native open failed: " + errors + "/" + warnings + ", type " + actualType +
                " (expected " + kind + "), " + Path.GetFileName(path));
        if (file != null)
        {
            file["documentType"] = actualType;
            opened["fileBeforeReopen"] = file;
        }
        return doc;
    }

    private static Hashtable ReadNativeFile(string path)
    {
        using (var file = File.OpenRead(path))
        using (var hash = SHA256.Create())
        {
            if (file.Length == 0) throw new IOException("Empty native artifact: " + Path.GetFileName(path));
            return new Hashtable { {"name", Path.GetFileName(path)}, {"bytes", file.Length},
                {"sha256", BitConverter.ToString(hash.ComputeHash(file)).Replace("-", "").ToLowerInvariant()} };
        }
    }

    private void VerifyNativeFile()
    {
        var opened = Child(evidence, "nativeOpen");
        var before = Child(opened, "fileBeforeReopen");
        string path = Text(opened, "path");
        var after = ReadNativeFile(path);
        if (!String.Equals(Text(Child(evidence, "nativeSave"), "path"), path, StringComparison.OrdinalIgnoreCase) ||
            !Object.Equals(before["bytes"], after["bytes"]) || !Object.Equals(before["sha256"], after["sha256"]))
            throw new IOException("Native artifact changed during reopen verification: " + Path.GetFileName(path));
        after["documentType"] = opened["documentType"];
        evidence["nativeFile"] = after;
    }

    private void Activate(IModelDoc2 doc)
    {
        if (Object.ReferenceEquals(doc, app.ActiveDoc)) return;
        int errors = 0;
        calls.Add("ActivateDoc3");
        var activated = app.ActivateDoc3(doc.GetTitle(), false, 1, ref errors);
        if (errors != 0 || !Object.ReferenceEquals(activated, doc))
            throw new InvalidOperationException("Could not activate the owned document: " + errors);
        RequireActive(doc);
    }

    private IModelDoc2 ImportStep(string path)
    {
        const int defaultPart = 8, alwaysDefault = 111;
        string previous = app.GetUserPreferenceStringValue(defaultPart);
        bool previousToggle = app.GetUserPreferenceToggle(alwaysDefault);
        int error = 0;
        IModelDoc2 doc = null;
        try
        {
            if (!File.Exists(previous)) app.SetUserPreferenceStringValue(defaultPart, template);
            if (!previousToggle) app.SetUserPreferenceToggle(alwaysDefault, true);
            if (!File.Exists(app.GetUserPreferenceStringValue(defaultPart)) || !app.GetUserPreferenceToggle(alwaysDefault))
                throw new InvalidOperationException("Cannot establish a valid STEP import template.");
            calls.Add("LoadFile4");
            doc = (IModelDoc2)app.LoadFile4(path, "r", app.GetImportFileData(path), ref error);
            if (doc != null) Own(doc);
            evidence["stepOpen"] = new Hashtable { {"ok", doc != null}, {"errors", error} };
            if (doc == null || error != 0) throw new IOException("STEP import failed: " + error);
        }
        finally
        {
            if (app.GetUserPreferenceStringValue(defaultPart) != previous) app.SetUserPreferenceStringValue(defaultPart, previous);
            if (app.GetUserPreferenceToggle(alwaysDefault) != previousToggle) app.SetUserPreferenceToggle(alwaysDefault, previousToggle);
            evidence["stepPreferencesRestored"] = app.GetUserPreferenceStringValue(defaultPart) == previous &&
                app.GetUserPreferenceToggle(alwaysDefault) == previousToggle;
        }
        if (!(bool)evidence["stepPreferencesRestored"]) throw new InvalidOperationException("STEP import preferences were not restored.");
        return doc;
    }

    private void CloseModel(IModelDoc2 doc)
    {
        if (!outstanding.Any(item => Object.ReferenceEquals(item, doc)))
            throw new InvalidOperationException("Refused to close a document outside this job.");
        string title = doc.GetTitle();
        string path = doc.GetPathName();
        Track("CloseDoc", () => app.CloseDoc(title));
        if (!String.IsNullOrEmpty(path) && app.GetOpenDocumentByName(path) != null)
            throw new InvalidOperationException("The job document did not close: " + title);
        outstanding.Remove(doc);
    }

    private void CloseOwnedDocuments()
    {
        foreach (var item in outstanding.ToArray().Reverse())
        {
            try { CloseModel(item); }
            catch (COMException ex)
            {
                if (ex.ErrorCode != unchecked((int)0x80010108) || app.GetDocumentCount() != 0) throw;
                outstanding.Clear();
                break;
            }
        }
    }

    private string lastLoggedStage;
    private DateTime lastProgressAt;

    private void TrackCall(string name)
    {
        calls.Add(name);
        if (!evidence.Contains("streamProgress")) return;
        string stage = evidence["stage"] as string ?? "";
        DateTime now = DateTime.UtcNow;
        if (stage == lastLoggedStage && (now - lastProgressAt).TotalSeconds < 5) return;
        lastLoggedStage = stage;
        lastProgressAt = now;
        Console.WriteLine("SW_PROGRESS\t" + now.ToString("o") + "\t" + stage + "\t" + name);
    }

    private T Track<T>(string name, Func<T> call) { TrackCall(name); return call(); }
    private void Track(string name, Action call) { TrackCall(name); call(); }
    private static IEnumerable<object> Items(object values) { return ((IEnumerable)values).Cast<object>(); }
    private static double[] Vector(object values) { return Items(values).Select(value => Convert.ToDouble(value, CultureInfo.InvariantCulture)).ToArray(); }
    private static IDictionary Child(IDictionary row, string key) { return (IDictionary)row[key]; }
    private static string Text(IDictionary row, string key) { return (string)row[key]; }
    private static double Number(IDictionary row, string key) { return Convert.ToDouble(row[key], CultureInfo.InvariantCulture); }
    private static double M(double mm) { return mm / 1000.0; }
    private static double Mm(double m) { return m * 1000.0; }
    private static bool Close(double a, double b) { return Math.Abs(a - b) <= DimensionTolerance; }
    private static void Near(double actual, double expected, double tolerance, string label)
    {
        if (Double.IsNaN(actual) || Double.IsInfinity(actual) || Math.Abs(actual - expected) > tolerance)
            throw new InvalidOperationException(String.Format(CultureInfo.InvariantCulture, "{0}: measured {1:R}, expected {2:R}", label, actual, expected));
    }
}
