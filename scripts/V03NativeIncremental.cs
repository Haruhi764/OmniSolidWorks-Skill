using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using SolidWorks.Interop.sldworks;

public sealed partial class V03Native
{
    private void CaptureExplosion(IAssemblyDoc assembly, Dictionary<string, string> names,
        IDictionary[] steps, IDictionary validation)
    {
        evidence["stage"] = "capture_reused_explosion";
        evidence["capturedAssembly"] = evidence["assembly"];
        evidence["baselineExplosion"] = ReadExplosion(assembly, names, steps, validation);
        evidence["componentBoxesMm"] = Track("GetComponentBoxes", () => ComponentBoxes(assembly, names));
        evidence["collapsedTransforms"] = ComponentTransforms(assembly, names, false);
        model.ShowNamedView2("", 7);
        var window = (IModelView)model.ActiveView;
        evidence["baselineCamera"] = Vector(window.Orientation3.ArrayData);
    }

    private double NativeExplosionPreview(IAssemblyDoc assembly, string name, double[] camera, double requestedScale, bool exploded = true)
    {
        evidence["stage"] = name == "BeforeExploded.bmp" ? "preview_baseline" : "preview_candidate";
        var config = Items(assembly.GetExplodedViewNames()).Cast<string>().Single();
        SetExploded(assembly, exploded, config);
        try
        {
            model.ShowNamedView2("", 7);
            var window = (IModelView)model.ActiveView;
            if (camera != null) SetPreviewCamera(window, camera);
            window.DisplayMode = 7;
            model.ViewZoomtofit2();
            double fitScale = window.Scale2;
            if (requestedScale > fitScale)
                throw new InvalidOperationException("The comparison view does not fit at the baseline scale.");
            window.Scale2 = requestedScale > 0 ? requestedScale : fitScale * 0.72;
            model.GraphicsRedraw2();
            string path = Path.Combine(output, name);
            if (!Track("SaveBMP", () => model.SaveBMP(path, 1800, 1300)) ||
                !File.Exists(path) || new FileInfo(path).Length == 0)
                throw new IOException("The native explosion bitmap could not be saved.");
            double actual = window.Scale2;
            evidence[name] = new Hashtable { {"scale", actual}, {"fitScale", fitScale},
                {"camera", Vector(window.Orientation3.ArrayData)}, {"width", 1800}, {"height", 1300} };
            if (requestedScale > 0) Near(actual, requestedScale, 1e-8, "comparison preview scale");
            return actual;
        }
        finally { SetExploded(assembly, false, config); }
    }

    private void SetPreviewCamera(IModelView window, double[] camera)
    {
        if (camera.Length != 16) throw new InvalidDataException("Expected a native camera transform");
        var utility = (IMathUtility)app.GetMathUtility();
        window.Orientation3 = (MathTransform)utility.CreateTransform(camera);
    }

    private void NativeInterference(IAssemblyDoc assembly)
    {
        evidence["stage"] = "native_static_interference";
        var manager = (IInterferenceDetectionMgr)assembly.InterferenceDetectionManager;
        if (manager == null) throw new InvalidOperationException("No native interference manager.");
        var rows = new ArrayList();
        try
        {
            manager.TreatCoincidenceAsInterference = false;
            manager.TreatSubAssembliesAsComponents = false;
            manager.IgnoreHiddenBodies = false;
            var hits = Track("GetInterferences", () => manager.GetInterferences()) as Array;
            if (hits != null)
                foreach (IInterference hit in hits)
                    rows.Add(new Hashtable { {"volumeMm3", hit.Volume * 1e9},
                        {"components", Items(hit.Components).Cast<IComponent2>().Select(c => c.Name2).ToArray()} });
            evidence["solidInterferences"] = rows;
            evidence["solidInterferenceQuery"] = true;
        }
        finally { manager.Done(); }
        if (rows.Count != 0)
            throw new InvalidOperationException("The saved collapsed assembly has native volume interference.");
    }
}

