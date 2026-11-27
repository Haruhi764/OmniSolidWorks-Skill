using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;

public sealed class NativePartJob
{
    private const int PartType = 1;
    private const int Silent = 1;
    private const int ThisConfiguration = 1;
    private const int InputDimensionValue = 10;
    private const int AlwaysUseDefaultTemplates = 111;
    private const int DefaultPartTemplate = 8;
    private const double ToleranceMm = 0.002;
    private readonly ISldWorks app;
    private readonly IDictionary evidence;
    private IModelDoc2 model;

    private NativePartJob(ISldWorks application, IDictionary runEvidence)
    {
        app = application;
        evidence = runEvidence;
    }

    public static void Run(int revisionMajor, string executable, string template, string output, string kind, double[] values, IDictionary evidence)
    {
        evidence["stage"] = "bind_instance";
        Process[] processes = Process.GetProcessesByName("SLDWORKS");
        string progId = "SldWorks.Application." + revisionMajor;
        if (processes.Length != 1 || !String.Equals(processes[0].MainModule.FileName, executable, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Open one interactive SolidWorks instance from the configured installation before running the job.");
        var application = (ISldWorks)Marshal.GetActiveObject(progId);
        string revision = application.RevisionNumber();
        int pid = application.GetProcessID();
        if (!revision.StartsWith(revisionMajor + ".", StringComparison.Ordinal) || pid != processes[0].Id)
            throw new InvalidOperationException("COM PID or revision does not match the target instance.");
        evidence["progId"] = progId;
        evidence["revision"] = revision;
        evidence["pid"] = pid;
        evidence["language"] = application.GetCurrentLanguage();
        evidence["template"] = template;
        evidence["documentCountBefore"] = application.GetDocumentCount();
        if (application.GetDocumentCount() != 0)
            throw new InvalidOperationException("The native benchmark requires an empty SolidWorks session.");
        new NativePartJob(application, evidence).Execute(template, output, kind, values);
    }

    private void Execute(string template, string output, string kind, double[] values)
    {
        bool previous = app.GetUserPreferenceToggle(InputDimensionValue);
        string nativePath = Path.Combine(output, kind + ".SLDPRT");
        string stepPath = Path.Combine(output, kind + ".STEP");
        string thicknessFeature = kind == "Shaft" ? "Journal 3" : "Flange Blank";
        int lengthIndex = kind == "Shaft" ? 5 : 1;
        try
        {
            evidence["stage"] = "create_part";
            if (previous)
                app.SetUserPreferenceToggle(InputDimensionValue, false);
            if (app.GetUserPreferenceToggle(InputDimensionValue))
                throw new InvalidOperationException("Cannot disable the interactive dimension prompt for this job.");
            model = (IModelDoc2)app.NewDocument(template, 0, 0, 0);
            RequireOwnedDocument(null);
            if (model.GetType() != PartType || SolidBodies().Length != 0)
                throw new InvalidOperationException("The template did not create a blank part.");

            evidence["stage"] = "build_features";
            var plane = FindFeature(null, "RefPlane");
            if (kind == "Shaft")
                MakeShaft(plane, values);
            else
                MakeFlange(plane, values);
            evidence["licenseType"] = model.Extension.GetLicenseType();
            evidence["documentUnits"] = model.GetUnits();
            evidence["beforeSave"] = Inspect(kind, values, true);

            evidence["stage"] = "save_native_and_step";
            Save(nativePath, "nativeSave");
            RequireOwnedDocument(nativePath);
            Save(stepPath, "stepSave");
            RequireOwnedDocument(nativePath);
            CloseOwned();
            if (app.GetOpenDocumentByName(nativePath) != null || app.GetDocumentCount() != 0)
                throw new InvalidOperationException("The saved document remained open.");
            evidence["closedBeforeNativeReopen"] = true;

            evidence["stage"] = "reopen_native";
            int openError = 0;
            int openWarning = 0;
            model = app.OpenDoc6(nativePath, PartType, Silent, "", ref openError, ref openWarning);
            evidence["nativeOpen"] = new Hashtable { {"errors", openError}, {"warnings", openWarning}, {"loaded", model != null} };
            if (openError != 0 || openWarning != 0)
                throw new IOException("SolidWorks reported a native reopen error or warning.");
            RequireOwnedDocument(nativePath);
            evidence["afterNativeReopen"] = Inspect(kind, values, true);

            evidence["stage"] = "dimension_round_trip";
            var length = FirstDriver(FindFeature(thicknessFeature, null));
            Near(Millimeters(length.SystemValue), values[lengthIndex], "loaded extrusion length");
            double[] changed = (double[])values.Clone();
            changed[lengthIndex] += 1;
            var edit = new Hashtable { {"dimension", length.FullName}, {"requestedMm", changed[lengthIndex]} };
            evidence["edit"] = edit;
            int editCode = length.SetSystemValue3(Meters(changed[lengthIndex]), ThisConfiguration, null);
            edit["changeCode"] = editCode;
            if (editCode != 0)
                throw new InvalidOperationException("SolidWorks refused the edit to the native dimension.");
            edit["afterChange"] = Inspect(kind, changed, true);
            int restoreCode = length.SetSystemValue3(Meters(values[lengthIndex]), ThisConfiguration, null);
            edit["restoreCode"] = restoreCode;
            if (restoreCode != 0)
                throw new InvalidOperationException("SolidWorks refused to restore the original dimension.");
            edit["afterRestore"] = Inspect(kind, values, true);
            CloseOwned();

            evidence["stage"] = "reopen_step";
            ImportStep(stepPath, template);
            RequireOwnedDocument(null);
            evidence["afterStepImport"] = Inspect(kind, values, false);
            CloseOwned();
            evidence["stage"] = "complete";
        }
        finally
        {
            try { CloseOwned(); }
            finally
            {
                if (app.GetUserPreferenceToggle(InputDimensionValue) != previous)
                    app.SetUserPreferenceToggle(InputDimensionValue, previous);
                evidence["dimensionPromptRestored"] = app.GetUserPreferenceToggle(InputDimensionValue) == previous;
                evidence["documentCountAfter"] = app.GetDocumentCount();
            }
        }
        if (app.GetDocumentCount() != 0 || app.GetUserPreferenceToggle(InputDimensionValue) != previous)
            throw new InvalidOperationException("Job cleanup did not restore the original session state.");
    }

    private void ImportStep(string path, string template)
    {
        bool originalToggle = app.GetUserPreferenceToggle(AlwaysUseDefaultTemplates);
        string originalTemplate = app.GetUserPreferenceStringValue(DefaultPartTemplate);
        bool temporaryTemplate = !File.Exists(originalTemplate);
        var preferences = new Hashtable { {"missingDefaultPartTemplate", temporaryTemplate}, {"originalAlwaysUseDefault", originalToggle} };
        evidence["stepTemplateRecovery"] = preferences;
        try
        {
            if (temporaryTemplate)
                app.SetUserPreferenceStringValue(DefaultPartTemplate, template);
            if (!originalToggle)
                app.SetUserPreferenceToggle(AlwaysUseDefaultTemplates, true);
            string selected = app.GetUserPreferenceStringValue(DefaultPartTemplate);
            if (!File.Exists(selected) || !app.GetUserPreferenceToggle(AlwaysUseDefaultTemplates))
                throw new InvalidOperationException("Cannot establish a valid temporary STEP import template.");
            preferences["selectedPartTemplate"] = selected;
            int importError = 0;
            model = app.LoadFile4(path, "r", app.GetImportFileData(path), ref importError);
            evidence["stepOpen"] = new Hashtable { {"errors", importError}, {"loaded", model != null} };
            if (importError != 0)
                throw new IOException("SolidWorks reported a STEP import error.");
        }
        finally
        {
            if (temporaryTemplate)
                app.SetUserPreferenceStringValue(DefaultPartTemplate, originalTemplate);
            if (!originalToggle)
                app.SetUserPreferenceToggle(AlwaysUseDefaultTemplates, originalToggle);
            preferences["restored"] = app.GetUserPreferenceToggle(AlwaysUseDefaultTemplates) == originalToggle &&
                app.GetUserPreferenceStringValue(DefaultPartTemplate) == originalTemplate;
        }
        if (!(bool)preferences["restored"])
            throw new InvalidOperationException("SolidWorks did not restore its original STEP template preferences.");
    }

    private void MakeShaft(IFeature plane, double[] values)
    {
        double station = 0;
        for (int journal = 0; journal < 3; journal++)
        {
            int value = journal * 2;
            double radius = Meters(values[value] / 2);
            RequireOwnedDocument(null);
            model.ClearSelection2(true);
            if (journal == 0)
                RequireSelection(plane.Select2(false, 0));
            else
                SelectFace(EndFace(station), 0);
            var sketch = SketchCircle("Journal Profile " + (journal + 1), 0, 0, station, radius);
            Extrude(sketch, "Journal " + (journal + 1), Meters(values[value + 1]));
            station += Meters(values[value + 1]);
        }
    }

    private void MakeFlange(IFeature plane, double[] values)
    {
        model.ClearSelection2(true);
        RequireSelection(plane.Select2(false, 0));
        var blank = SketchCircle("Flange Profile", 0, 0, 0, Meters(values[0] / 2));
        Extrude(blank, "Flange Blank", Meters(values[1]));
        double top = Meters(values[1]);
        model.ClearSelection2(true);
        SelectFace(EndFace(top), 0);
        ThroughCut(SketchCircle("Bore Profile", 0, 0, top, Meters(values[2] / 2)), "Center Through Hole");
        model.ClearSelection2(true);
        SelectFace(EndFace(top), 0);
        var seed = ThroughCut(SketchCircle("Bolt Profile", Meters(values[5] / 2), 0, top, Meters(values[3] / 2)), "Bolt Through Hole");
        var outerFaces = Faces().Where(face => {
            var surface = (ISurface)face.GetSurface();
            return surface.IsCylinder() && Math.Abs(((double[])surface.CylinderParams)[6] - Meters(values[0] / 2)) < 1e-8;
        }).ToArray();
        if (outerFaces.Length != 1)
            throw new InvalidOperationException("Cannot identify the flange outside cylinder for the circular pattern.");
        model.ClearSelection2(true);
        SelectFace(outerFaces[0], 1);
        RequireSelection(seed.Select2(true, 4));
        IFeature pattern = model.FeatureManager.FeatureCircularPattern4((int)values[4], 2 * Math.PI, false, "", false, true, false);
        Rename(pattern, "Bolt Circle Pattern");
    }

    private IFeature SketchCircle(string name, double x, double y, double z, double radius)
    {
        model.SketchManager.InsertSketch(true);
        var sketch = model.SketchManager.ActiveSketch;
        if (sketch == null)
            throw new InvalidOperationException("Cannot enter the selected sketch plane.");
        var utility = (IMathUtility)app.GetMathUtility();
        var world = (IMathPoint)utility.CreatePoint(new[] { x, y, z });
        var local = (IMathPoint)world.MultiplyTransform(sketch.ModelToSketchTransform);
        var point = (double[])local.ArrayData;
        var circle = model.SketchManager.CreateCircleByRadius(point[0], point[1], 0, radius);
        if (circle == null)
            throw new InvalidOperationException("Cannot create the circle.");
        model.ClearSelection2(true);
        RequireSelection(((ISketchSegment)circle).Select4(false, null));
        var display = model.AddDiameterDimension2(x + radius * 1.25, y + radius, z) as IDisplayDimension;
        if (display == null)
            throw new InvalidOperationException("Cannot create the driving diameter dimension.");
        Near(Millimeters(display.GetDimension2(0).SystemValue), Millimeters(2 * radius), "sketch diameter");
        model.SketchManager.InsertSketch(true);
        model.ClearSelection2(true);
        var feature = model.Extension.GetLastFeatureAdded() as IFeature;
        if (feature == null || feature.GetTypeName2() != "ProfileFeature")
            throw new InvalidOperationException("Cannot identify the just-created circle sketch.");
        return Rename(feature, name);
    }

    private IFeature Extrude(IFeature sketch, string name, double depth)
    {
        model.ClearSelection2(true);
        RequireSelection(sketch.Select2(false, 0));
        var feature = model.FeatureManager.FeatureExtrusion3(true, false, false, 0, 0, depth, 0,
            false, false, false, false, 0, 0, false, false, false, false, true, true, true, 0, 0, false);
        return Rename(feature, name);
    }

    private IFeature ThroughCut(IFeature sketch, string name)
    {
        model.ClearSelection2(true);
        RequireSelection(sketch.Select2(false, 0));
        // The sketch lies on the top face. A single through-all direction goes into the body.
        var feature = model.FeatureManager.FeatureCut3(true, false, false, 1, 0, 0.01, 0.0,
            false, false, false, false, 0, 0, false, false, false, false, false, true, true,
            false, false, false, 0, 0, false);
        return Rename(feature, name);
    }

    private IDictionary Inspect(string kind, double[] values, bool readFeatures)
    {
        RequireOwnedDocument(null);
        if (!model.ForceRebuild3(false))
            throw new InvalidOperationException("SolidWorks could not rebuild the model.");
        var body = SingleBody();
        int bodyCode = body.Check2();
        if (bodyCode != 0)
            throw new InvalidOperationException("Body.Check2 returned " + bodyCode + ".");
        var mass = model.Extension.CreateMassProperty();
        mass.UseSystemUnits = true;
        double volume = mass.Volume * 1e9;
        double expected = kind == "Shaft" ? Math.PI * (AreaFactor(values[0]) * values[1] +
            AreaFactor(values[2]) * values[3] + AreaFactor(values[4]) * values[5]) :
            Math.PI * (AreaFactor(values[0]) - AreaFactor(values[2]) - values[4] * AreaFactor(values[3])) * values[1];
        if (Double.IsNaN(volume) || Double.IsInfinity(volume) || Math.Abs(volume - expected) > 0.01)
            throw new InvalidOperationException(String.Format(CultureInfo.InvariantCulture, "Unexpected volume {0:R} mm3, expected {1:R} mm3.", volume, expected));

        var cylinders = new List<Cylinder>();
        foreach (IFace2 face in Faces())
        {
            var surface = (ISurface)face.GetSurface();
            if (surface.IsCylinder())
                cylinders.Add(new Cylinder(face, (double[])surface.CylinderParams));
        }
        if (kind == "Shaft")
            CheckShaft(values, cylinders);
        else
            CheckFlange(values, cylinders);
        var rows = new ArrayList();
        foreach (var cylinder in cylinders)
            rows.Add(cylinder.Fields);
        var snapshot = new Hashtable { {"volumeMm3", volume}, {"expectedVolumeMm3", expected}, {"solids", 1},
            {"bodyCheckCode", bodyCode}, {"rebuilt", true}, {"cylinders", rows} };
        if (readFeatures)
            snapshot["features"] = InspectFeatures(kind, values);
        return snapshot;
    }

    private void CheckShaft(double[] values, List<Cylinder> cylinders)
    {
        int count = cylinders.Count;
        if (count != 3)
            throw new InvalidOperationException("Expected three cylindrical journals, measured " + count + ".");
        double start = 0;
        foreach (int journal in Enumerable.Range(0, 3))
        {
            var cylinder = cylinders.OrderBy(item => item.StartMm).ElementAt(journal);
            Near(cylinder.X, 0, "shaft x axis");
            Near(cylinder.Y, 0, "shaft y axis");
            Near(cylinder.Diameter, values[2 * journal], "journal diameter");
            Near(cylinder.StartMm, start, "journal start");
            start += values[2 * journal + 1];
            Near(cylinder.EndMm, start, "journal end");
        }
    }

    private void CheckFlange(double[] values, List<Cylinder> cylinders)
    {
        int count = (int)values[4];
        if (cylinders.Count != count + 2)
            throw new InvalidOperationException("Unexpected flange cylinder count: " + cylinders.Count + ".");
        MatchCylinder(cylinders, values[0], 0, 0, values[1]);
        MatchCylinder(cylinders, values[2], 0, 0, values[1]);
        for (int hole = 0; hole < count; hole++)
        {
            double angle = 2 * Math.PI * hole / count;
            MatchCylinder(cylinders, values[3], values[5] / 2 * Math.Cos(angle), values[5] / 2 * Math.Sin(angle), values[1]);
        }
    }

    private static void MatchCylinder(List<Cylinder> cylinders, double diameter, double x, double y, double thickness)
    {
        var matches = cylinders.Where(item => Math.Abs(item.Diameter - diameter) <= ToleranceMm &&
            Math.Abs(item.X - x) <= ToleranceMm && Math.Abs(item.Y - y) <= ToleranceMm).ToArray();
        if (matches.Length != 1)
            throw new InvalidOperationException(String.Format(CultureInfo.InvariantCulture, "Cannot identify cylinder D{0} at ({1:R}, {2:R}).", diameter, x, y));
        Near(matches[0].StartMm, 0, "flange cylinder start");
        Near(matches[0].EndMm, thickness, "flange cylinder end");
        if (matches[0].CircularEnds != 2)
            throw new InvalidOperationException("The cylindrical face does not meet both end planes in circular boundaries.");
    }

    private IList InspectFeatures(string kind, double[] values)
    {
        string[] expected = kind == "Shaft" ? new[] { "Journal 1", "Journal 2", "Journal 3" } :
            new[] { "Flange Blank", "Center Through Hole", "Bolt Through Hole", "Bolt Circle Pattern" };
        var items = new ArrayList();
        foreach (var name in expected)
        {
            var feature = FindFeature(name, null);
            bool warning;
            int code = feature.GetErrorCode2(out warning);
            if (code != 0)
                throw new InvalidOperationException("Feature " + name + " returned error or warning " + code + ".");
            var dims = new ArrayList();
            for (var display = feature.GetFirstDisplayDimension(); display != null; display = feature.GetNextDisplayDimension(display))
            {
                var dimension = ((IDisplayDimension)display).GetDimension2(0);
                if (dimension != null)
                    dims.Add(new Hashtable { {"name", dimension.FullName}, {"systemValue", dimension.SystemValue} });
            }
            string originalType = feature.GetTypeName();
            var row = new Hashtable { {"name", name}, {"type", feature.GetTypeName2()}, {"originalType", originalType},
                {"errorCode", code}, {"dimensions", dims} };
            if (name == "Bolt Circle Pattern")
            {
                var pattern = feature.GetDefinition() as ICircularPatternFeatureData;
                if (pattern == null || pattern.TotalInstances != (int)values[4] || !pattern.EqualSpacing)
                    throw new InvalidOperationException("The flange pattern does not read back as equal-spaced with the required count.");
                row["operation"] = "circular_pattern";
                row["instanceCount"] = pattern.TotalInstances;
                row["equalSpacing"] = pattern.EqualSpacing;
            }
            else
            {
                bool cut = name == "Center Through Hole" || name == "Bolt Through Hole";
                var extrusion = feature.GetDefinition() as IExtrudeFeatureData2;
                bool knownType = cut ? originalType == "Cut" : originalType == "Boss" || originalType == "Extrusion";
                if (!knownType)
                    throw new InvalidOperationException("Unexpected native feature type for " + name + ": " + originalType + ".");
                if (extrusion != null)
                {
                    row["forwardEndCondition"] = extrusion.GetEndCondition(true);
                    row["reverseEndCondition"] = extrusion.GetEndCondition(false);
                }
                row["operation"] = cut ? "through_cut" : "blind_boss";
            }
            items.Add(row);
        }
        return items;
    }

    private IDimension FirstDriver(IFeature feature)
    {
        var display = feature.GetFirstDisplayDimension() as IDisplayDimension;
        if (display == null)
            throw new InvalidOperationException("Cannot find the editable extrusion dimension.");
        return display.GetDimension2(0);
    }

    private IFace2 EndFace(double station)
    {
        var matches = Faces().Where(face => {
            if (!((ISurface)face.GetSurface()).IsPlane())
                return false;
            var box = (double[])face.GetBox();
            return Math.Abs(box[2] - station) < 1e-8 && Math.Abs(box[5] - station) < 1e-8;
        }).ToArray();
        if (matches.Length != 1)
            throw new InvalidOperationException("Cannot identify the preceding journal end face at " + Millimeters(station) + " mm.");
        return matches[0];
    }

    private IFace2[] Faces()
    {
        var faces = (Array)SingleBody().GetFaces();
        return faces.Cast<IFace2>().ToArray();
    }

    private Array SolidBodies()
    {
        return ((IPartDoc)model).GetBodies2(0, false) as Array ?? new object[0];
    }

    private IBody2 SingleBody()
    {
        var bodies = SolidBodies();
        if (bodies.Length != 1)
            throw new InvalidOperationException("Expected exactly one solid body, found " + bodies.Length + ".");
        return (IBody2)bodies.GetValue(0);
    }

    private void SelectFace(IFace2 face, int mark)
    {
        var data = ((ISelectionMgr)model.SelectionManager).CreateSelectData();
        data.Mark = mark;
        RequireSelection(((IEntity)face).Select4(false, data));
    }

    private IFeature FindFeature(string name, string type)
    {
        for (var candidate = model.FirstFeature() as IFeature; candidate != null; candidate = candidate.GetNextFeature() as IFeature)
            if ((name == null || candidate.Name == name) && (type == null || candidate.GetTypeName2() == type))
                return candidate;
        throw new InvalidOperationException("Feature not found: " + (name ?? type));
    }

    private void Save(string path, string key)
    {
        RequireOwnedDocument(null);
        if (File.Exists(path))
            throw new IOException("Refused to overwrite " + path + ".");
        model.ClearSelection2(true);
        int errors = 0;
        int warnings = 0;
        bool saved = model.Extension.SaveAs(path, 0, Silent, null, ref errors, ref warnings);
        evidence[key] = new Hashtable { {"saved", saved}, {"errors", errors}, {"warnings", warnings}, {"path", path} };
        if (!saved || errors != 0 || warnings != 0 || !File.Exists(path))
            throw new IOException("SolidWorks could not save " + path + " cleanly.");
    }

    private void CloseOwned()
    {
        if (model == null)
            return;
        if (Object.ReferenceEquals(app.ActiveDoc, model))
        {
            if (model.SketchManager.ActiveSketch != null)
                model.SketchManager.InsertSketch(true);
            app.CloseDoc(model.GetTitle());
            model = null;
        }
        else
            evidence["cleanupNeedsReview"] = "Active document changed; this job did not close it.";
    }

    private void RequireOwnedDocument(string path)
    {
        if (model == null || !Object.ReferenceEquals(app.ActiveDoc, model))
            throw new InvalidOperationException("The SolidWorks active document is not the job document.");
        if (path != null && !String.Equals(model.GetPathName(), path, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("The job document path does not match the current task.");
    }

    private static IFeature Rename(IFeature feature, string name)
    {
        if (feature == null)
            throw new InvalidOperationException("SolidWorks could not create " + name + ".");
        feature.Name = name;
        return feature;
    }

    private static void RequireSelection(bool selected)
    {
        if (!selected)
            throw new InvalidOperationException("The required SolidWorks entity could not be selected.");
    }

    private static double AreaFactor(double diameter) { return diameter * diameter / 4; }
    private static double Meters(double millimeters) { return millimeters / 1000; }
    private static double Millimeters(double meters) { return meters * 1000; }

    private static void Near(double actual, double expected, string quantity)
    {
        if (Double.IsNaN(actual) || Double.IsInfinity(actual) || Math.Abs(actual - expected) > ToleranceMm)
            throw new InvalidOperationException(String.Format(CultureInfo.InvariantCulture, "{0}: got {1:R}, expected {2:R}.", quantity, actual, expected));
    }

    private sealed class Cylinder
    {
        public readonly double Diameter;
        public readonly double X;
        public readonly double Y;
        public readonly double StartMm;
        public readonly double EndMm;
        public readonly int CircularEnds;

        public Cylinder(IFace2 face, double[] parameters)
        {
            Near(parameters[3], 0, "cylinder axis x component");
            Near(parameters[4], 0, "cylinder axis y component");
            Near(Math.Abs(parameters[5]), 1, "cylinder axis z component");
            X = Millimeters(parameters[0]);
            Y = Millimeters(parameters[1]);
            Diameter = Millimeters(2 * parameters[6]);
            var edges = ((Array)face.GetEdges()).Cast<IEdge>();
            var ends = new List<double>();
            foreach (var edge in edges)
            {
                var curve = (ICurve)edge.GetCurve();
                if (!curve.IsCircle())
                    continue;
                double station = Millimeters(((double[])curve.CircleParams)[2]);
                if (!ends.Any(existing => Math.Abs(existing - station) <= ToleranceMm))
                    ends.Add(station);
            }
            CircularEnds = ends.Count;
            if (CircularEnds != 2)
                throw new InvalidOperationException("Expected two circular boundaries per cylinder, found " + CircularEnds + ".");
            StartMm = ends.Min();
            EndMm = ends.Max();
        }

        public IDictionary Fields
        {
            get { return new Hashtable { {"xMm", X}, {"yMm", Y}, {"diameterMm", Diameter}, {"startMm", StartMm}, {"endMm", EndMm}, {"circularEnds", CircularEnds} }; }
        }
    }
}
