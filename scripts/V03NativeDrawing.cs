using System.Diagnostics;
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using SolidWorks.Interop.sldworks;

public sealed partial class V03Native
{
    private sealed class SheetPlan
    {
        public readonly Dictionary<string, string> Names = new Dictionary<string, string>();
        public readonly Dictionary<string, double> Scales = new Dictionary<string, double>();
        public string ModelPath;
        public string TemplatePath;
        public bool IsAssembly;
        public bool Exploded;
        public bool Bom;
        public bool AssemblySection;
        public bool CenterMarks;
        public double[] Envelope;
        public string Title;
        public string DrawingNumber;
        public double Width;
        public double Height;
        public double Scale;
        public int ComponentCount;
        public bool CheckBalloonBounds;
        public IDictionary Incremental;
    }

    private void BuildDrawing(IDictionary job)
    {
        var options = Items(job["features"]).Cast<IDictionary>().Single();
        var dependencies = Items(job["dependencies"]).Cast<IDictionary>().ToArray();
        var validation = Child(job, "validation");
        string name = Text(Child(job, "outputs"), "name");
        var plan = new SheetPlan {
            IsAssembly = Path.GetExtension(Text(dependencies[0], "path")).Equals(".sldasm", StringComparison.OrdinalIgnoreCase),
            Exploded = (bool)options["exploded"], Bom = (bool)options["bom"], CenterMarks = (bool)options["center_marks"],
            AssemblySection = (bool)options["section"] && (bool)options["bom"],
            Title = options["title"] as string, DrawingNumber = options["drawing_number"] as string
        };
        plan.CheckBalloonBounds = Number(job, "schema_version") == 2;
        plan.Incremental = job["incremental_drawing"] as IDictionary;
        if (plan.Incremental == null && options.Contains("witness_dimensions"))
            plan.Incremental = new Hashtable { {"witnesses", options["witness_dimensions"]} };
        plan.ComponentCount = plan.IsAssembly ? (int)Number(validation, "component_count") : 0;
        evidence["stage"] = "open_drawing_reference";
        var referenceRoot = Path.Combine(output, "references");
        var expectedReferences = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var nestedModules = job["drawing_modules"] == null ? new string[0] :
            Items(job["drawing_modules"]).Cast<string>().ToArray();
        string partsFolder = nestedModules.Length == 0 ? Path.Combine(referenceRoot, "references") :
            Path.Combine(referenceRoot, "references", "references");
        foreach (var row in dependencies.Skip(1))
        {
            var reference = Path.Combine(partsFolder, Text(row, "id") + ".SLDPRT");
            Open(reference, Part, true, "sourceOpen:" + Text(row, "id"));
            expectedReferences.Add(reference);
        }

        foreach (string id in nestedModules)
        {
            RequireFileId(id);
            var module = Path.Combine(referenceRoot, "references", id + ".SLDASM");
            Open(module, Assembly, true, "sourceOpen:" + id, 32);
            expectedReferences.Add(module);
        }
        plan.ModelPath = Path.Combine(referenceRoot, Text(dependencies[0], "id") + (plan.IsAssembly ? ".SLDASM" : ".SLDPRT"));
        var source = Open(plan.ModelPath, plan.IsAssembly ? Assembly : Part, true, "drawingSource", plan.IsAssembly ? 32 : 0);
        if (plan.IsAssembly)
        {
            if (plan.Incremental != null)
            {
                model = source;
                Activate(source);
                Rebuild();
            }
            var components = Items(((IAssemblyDoc)source).GetComponents(nestedModules.Length == 0)).Cast<IComponent2>().ToArray();
            if (components.Length != plan.ComponentCount + nestedModules.Length || components.Any(item => item.GetModelDoc2() == null) ||
                !expectedReferences.SetEquals(components.Select(item => item.GetPathName())))
                throw new InvalidOperationException("The drawing assembly did not resolve exclusively to the staged references.");
            if (plan.Exploded && ((IAssemblyDoc)source).GetExplodedViewCount() != 1)
                throw new InvalidOperationException("An exploded drawing requires a single verified native exploded assembly view.");
        }
        var orientations = Items(source.GetModelViewNames()).Cast<string>().ToArray();
        if (orientations.Length < 8)
            throw new InvalidOperationException("SolidWorks did not return its standard model orientations.");
        double[] envelope = Vector(plan.IsAssembly ? ((IAssemblyDoc)source).GetBox(0) : ((IPartDoc)source).GetPartBox(true));
        plan.Envelope = envelope;
        double span = Enumerable.Range(0, 3).Max(index => Mm(envelope[index + 3] - envelope[index]));
        if (span <= 0) throw new InvalidOperationException("The referenced model envelope is empty.");
        string paper = Text(options, "paper");
        if (paper == "auto" && job.Contains("limits") && (dependencies.Length > 10 || plan.ComponentCount > 20))
            paper = "a0";
        plan.TemplatePath = DrawingTemplate(paper, span, plan.Bom || (bool)options["section"] || (bool)options["detail"]);

        evidence["stage"] = "create_drawing_sheet";
        model = NewModel(Drawing, plan.TemplatePath);
        var drawing = (IDrawingDoc)model;
        ConfigureSheet(drawing, (ISheet)drawing.GetCurrentSheet(), plan, span);
        var views = CreateMainViews(drawing, plan, orientations);
        if (plan.Incremental != null)
        {
            LayoutNativeViews(plan, views);
            AddNativeWitnessDimensions(drawing, views, Items(plan.Incremental["witnesses"]).Cast<IDictionary>(), plan.AssemblySection);
            LabelExplodedScale(drawing, plan, views["Isometric"]);
        }
        if (plan.CheckBalloonBounds && plan.Bom)
        {
            evidence["stage"] = "save_layout_checkpoint";
            Save(Path.Combine(output, name + "_layout.SLDDRW"), "layoutCheckpointSave");
        }
        evidence["stage"] = "drawing_annotations";
        if (!plan.IsAssembly)
        {
            ImportDimensions(drawing, views, plan);
            if (plan.Incremental != null) HideSupersededWitnesses(views);
        }
        AddDrawingDetails(drawing, plan, views, options);
        ReconcileTitleBlock(drawing, plan);
        var sheet = (ISheet)drawing.GetCurrentSheet();
        if (!sheet.SetScale(plan.Scale >= 1 ? plan.Scale : 1, plan.Scale >= 1 ? 1 : Math.Round(1 / plan.Scale), false, false))
            throw new InvalidOperationException("Could not restore the chosen scale after automatic view insertion.");
        foreach (var entry in views)
        {
            if (entry.Key == "Top" || entry.Key == "Left" || entry.Key == "Section") entry.Value.UseParentScale = true;
            else { entry.Value.UseSheetScale = 0; entry.Value.ScaleDecimal = plan.Scales[entry.Key]; }
        }
        if (job.Contains("limits"))
        {
            // SolidWorks 2014 document toggles for axes, temporary axes, origins and sketches.
            foreach (int reference in new[] { 4, 7, 6, 196 })
                if (model.GetUserPreferenceToggle(reference) && !model.SetUserPreferenceToggle(reference, false))
                    throw new InvalidOperationException("Could not hide drawing reference geometry: " + reference);
        }
        RebuildDrawing();
        if (Number(job, "schema_version") == 2 && plan.Bom)
            PlaceExplodedBalloons(plan, views["Isometric"]);
        if (plan.Incremental != null && plan.Bom)
            BalanceNativeBalloons(plan, views["Isometric"], views["Left"]);
        evidence["stage"] = "validate_drawing";
        evidence["drawing"] = ReadDrawing(drawing, plan, validation);

        var path = Path.Combine(output, name + ".SLDDRW");
        evidence["stage"] = "save_drawing";
        Save(path, "nativeSave");
        evidence["stage"] = "export_drawing";
        var pdf = (IExportPdfData)app.GetExportFileData(1);
        if (pdf != null)
        {
            pdf.ViewPdfAfterSaving = false;
            evidence["explicitPdfSheet"] = pdf.SetSheets(3, new[] { ((ISheet)drawing.GetCurrentSheet()).GetName() });
        }
        Save(Path.Combine(output, name + ".PDF"), "pdfSave", pdf);
        Save(Path.Combine(output, name + ".DWG"), "dwgSave");
        Save(Path.Combine(output, name + ".DXF"), "dxfSave");
        CloseOwnedDocuments();
        if (app.GetDocumentCount() != 0) throw new InvalidOperationException("The drawing and its sources remained open before validation.");
        evidence["stage"] = "reopen_drawing";
        model = Open(path, Drawing, true, "nativeOpen");
        Activate(model);
        evidence["stage"] = "read_reopened_drawing";
        evidence["reopenedDrawing"] = ReadDrawing((IDrawingDoc)model, plan, validation);
        CloseModel(model);
    }

    private string DrawingTemplate(string paper, double modelSpan, bool extra)
    {
        if (paper == "a2")
        {
            string a2 = Path.Combine(Path.GetDirectoryName(template), "gb_a2.drwdot");
            if (!File.Exists(a2)) throw new IOException("The installed GB A2 template is missing.");
            return a2;
        }
        if (paper == "a1")
        {
            string large = Path.Combine(Path.GetDirectoryName(template), "gb_a1.drwdot");
            if (!File.Exists(large)) throw new IOException("The installed GB A1 template is missing.");
            return large;
        }
        if (paper == "a0")
        {
            string large = Path.Combine(Path.GetDirectoryName(template), "gb_a0.drwdot");
            if (!File.Exists(large)) throw new IOException("The installed GB A0 template is missing.");
            return large;
        }
        if (paper == "a3" || (paper == "auto" && (modelSpan > 160 || extra)))
        {
            string a3 = Path.Combine(Path.GetDirectoryName(template), "gb_a3.drwdot");
            if (!File.Exists(a3)) throw new IOException("The matching SolidWorks GB A3 template is missing.");
            return a3;
        }
        return template;
    }

    private void ConfigureSheet(IDrawingDoc drawing, ISheet sheet, SheetPlan plan, double span)
    {
        var props = Vector(sheet.GetProperties());
        double width = 0, height = 0;
        int paper = sheet.GetSize(ref width, ref height);
        if (props.Length < 7 || width < M(200) || height < M(190) || width <= height)
            throw new InvalidOperationException("The drawing requires a landscape engineering template.");
        double allowed = Mm(Math.Min(width * 0.195, height * 0.26)) / (span * (plan.Exploded ? 1.65 : 1.15));
        double ratio = new[] { 2.0, 1.0, 0.5, 0.2, 0.1, 0.05 }.FirstOrDefault(value => value <= allowed);
        if (ratio <= 0) throw new InvalidOperationException("The model is too large for the selected layout.");
        double denominator = ratio < 1 ? Math.Round(1 / ratio) : 1;
        double numerator = ratio < 1 ? 1 : ratio;
        string data = Path.GetDirectoryName(Path.GetDirectoryName(plan.TemplatePath));
        string format = Path.Combine(data, "lang", "chinese-simplified", "sheetformat", Path.GetFileNameWithoutExtension(plan.TemplatePath).Equals("gb_a0", StringComparison.OrdinalIgnoreCase)
            ? "a0 - gb.slddrt" : (paper == 8 ? "a3 - gb.slddrt" : "a4 - gb.slddrt"));
        if (Path.GetFileNameWithoutExtension(plan.TemplatePath).Equals("gb_a1", StringComparison.OrdinalIgnoreCase))
            format = Path.Combine(Path.GetDirectoryName(format), "a1 - gb.slddrt");
        if (Path.GetFileNameWithoutExtension(plan.TemplatePath).Equals("gb_a2", StringComparison.OrdinalIgnoreCase))
            format = Path.Combine(Path.GetDirectoryName(format), "a2 - gb.slddrt");
        if (!File.Exists(format))
        {
            string installation = Path.GetDirectoryName(Process.GetProcessById(app.GetProcessID()).MainModule.FileName);
            format = Path.Combine(installation, "lang", "chinese-simplified", "sheetformat", Path.GetFileName(format));
        }
        evidence["resolvedSheetFormat"] = Path.GetFileName(format);
        if (!File.Exists(format) || !Track("SetupSheet5", () => drawing.SetupSheet5(sheet.GetName(), paper, 12,
            numerator, denominator, true, format, width, height, "", false)))
            throw new InvalidOperationException("Could not load the installed GB sheet format.");
        sheet = (ISheet)drawing.GetCurrentSheet();
        if (!File.Exists(sheet.GetTemplateName())) sheet.SetTemplateName(format);
        double[] readback = Vector(sheet.GetProperties());
        evidence["initialSheetProperties"] = readback;
        evidence["initialSheetFormat"] = sheet.GetTemplateName();
        if (readback[4] == 0 || !Close(readback[2] / readback[3], ratio) ||
            !String.Equals(Path.GetFileName(sheet.GetTemplateName()), Path.GetFileName(format), StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Could not read back the requested first-angle scale and GB format.");
        plan.Width = width;
        plan.Height = height;
        plan.Scale = ratio;
        if (model.Extension.GetUserPreferenceInteger(13, 0) != 7 &&
            !model.Extension.SetUserPreferenceInteger(13, 0, 7))
            throw new InvalidOperationException("The drawing document could not use the GB detailing standard.");
        evidence["drawingTemplate"] = plan.TemplatePath;
    }

    private void RebuildDrawing()
    {
        RequireActive(model);
        rebuilds++;
        if (!Track("EditRebuild3", () => model.EditRebuild3()))
            throw new InvalidOperationException("The native drawing rebuild did not complete.");
    }

    private Dictionary<string, IView> CreateMainViews(IDrawingDoc drawing, SheetPlan plan, string[] orientations)
    {
        evidence["stage"] = "create_drawing_views";
        var views = new Dictionary<string, IView>();
        var front = Track("CreateDrawViewFromModelView3", () => drawing.CreateDrawViewFromModelView3(
            plan.ModelPath, orientations[1], plan.Width * 0.24, plan.Height * 0.71, 0));
        RegisterView(plan, views, "Front", front, plan.Scale);
        SelectView(drawing, front);
        var top = Track("CreateUnfoldedViewAt3", () => drawing.CreateUnfoldedViewAt3(plan.Width * 0.24, plan.Height * 0.36, 0, false));
        RegisterView(plan, views, "Top", top, plan.Scale);
        SelectView(drawing, front);
        var left = Track("CreateUnfoldedViewAt3", () => drawing.CreateUnfoldedViewAt3(plan.Width * 0.51, plan.Height * 0.71, 0, false));
        RegisterView(plan, views, "Left", left, plan.Scale);
        model.ClearSelection2(true);
        var isoOrientation = plan.Incremental != null && plan.Incremental.Contains("model_view")
            ? Text(plan.Incremental, "model_view") : orientations[7];
        if (!orientations.Contains(isoOrientation)) throw new InvalidOperationException("The named drawing model view is missing.");
        var iso = Track("CreateDrawViewFromModelView3", () => drawing.CreateDrawViewFromModelView3(
            plan.ModelPath, isoOrientation, plan.Width * 0.80, plan.Height * 0.71, 0));
        RegisterView(plan, views, "Isometric", iso, plan.Scale);
        if (plan.Exploded && (!Track("ShowExploded", () => iso.ShowExploded(true)) || !iso.IsExploded()))
            throw new InvalidOperationException("The isometric view did not display the native assembly explosion.");
        return views;
    }

    private static void RegisterView(SheetPlan plan, Dictionary<string, IView> views, string role, IView view, double scale)
    {
        if (view == null || String.IsNullOrEmpty(view.GetName2())) throw new InvalidOperationException("SolidWorks did not place " + role);
        views.Add(role, view);
        plan.Names.Add(role, view.GetName2());
        plan.Scales.Add(role, scale);
    }

    private void SelectView(IDrawingDoc drawing, IView view)
    {
        model.ClearSelection2(true);
        string name = view.GetName2();
        Selected(model.Extension.SelectByID2(name, "DRAWINGVIEW", 0, 0, 0, false, 0, null, 0));
        if (!drawing.ActivateView(name)) throw new InvalidOperationException("Unable to activate drawing view " + name);
    }

    private void ImportDimensions(IDrawingDoc drawing, Dictionary<string, IView> views, SheetPlan plan)
    {
        SelectView(drawing, views["Front"]);
        Track("InsertModelAnnotations3", () => drawing.InsertModelAnnotations3(0, 32768 | 524288, false, false, false, false));
        model.ClearSelection2(true);
        var thicknesses = new List<double>();
        foreach (var view in views.Values) ReadDimensions(view, thicknesses);
        double thickness = Mm(plan.Envelope[5] - plan.Envelope[2]);
        if (!thicknesses.Any(value => Math.Abs(value - thickness) < 0.005))
            AddThicknessDimension(drawing, views["Top"], thickness);
    }

    private void AddDrawingDetails(IDrawingDoc drawing, SheetPlan plan, Dictionary<string, IView> views, IDictionary options)
    {
        if (plan.CenterMarks) AddCenterMarks(drawing, views["Front"]);
        if ((bool)options["section"]) AddSectionView(drawing, plan, views);
        if ((bool)options["detail"]) AddDetailView(drawing, plan, views);
        if (plan.Bom) AddBillOfMaterials(drawing, plan, views["Isometric"]);
        model.ClearSelection2(true);
        drawing.EditSheet();
    }

    private IDictionary ReadDrawing(IDrawingDoc drawing, SheetPlan plan, IDictionary validation)
    {
        RequireActive(model);
        if (Items(Track("GetSheetNames", () => drawing.GetSheetNames())).Count() != 1) throw new InvalidOperationException("Expected one native drawing sheet.");
        var sheet = (ISheet)Track("GetCurrentSheet", () => drawing.GetCurrentSheet());
        var props = Vector(sheet.GetProperties());
        evidence["observedSheetProperties"] = props;
        if (props[4] == 0 || !Close(props[2] / props[3], plan.Scale))
            throw new InvalidOperationException("Drawing sheet projection or scale changed.");
        var all = Track("ReadDrawingViewMap", () => ReadViewMap(drawing));
        if (all.Count != plan.Names.Count) throw new InvalidOperationException("Unexpected native view count.");
        var rows = new ArrayList();
        var dimensionValues = new List<double>();
        var extents = new List<double[]>();
        IView main = all[plan.Names["Front"]];
        foreach (var entry in plan.Names)
        {
            IView view = all[entry.Value];
            evidence["lastDrawingView"] = entry.Key;
            var outline = Vector(view.GetOutline());
            if (outline.Length != 4 || outline[0] < M(5) || outline[1] < M(15) ||
                outline[2] > plan.Width - M(5) || outline[3] > plan.Height - M(5) || outline[2] <= outline[0] || outline[3] <= outline[1])
                throw new InvalidOperationException("View escapes the usable sheet area: " + entry.Key);
            if (extents.Any(other => Math.Min(outline[2], other[2]) - Math.Max(outline[0], other[0]) > M(1) &&
                Math.Min(outline[3], other[3]) - Math.Max(outline[1], other[1]) > M(1)))
                throw new InvalidOperationException("Native view extents overlap: " + entry.Key);
            extents.Add(outline);
            if (!String.Equals(Track("GetReferencedModelName", () => view.GetReferencedModelName()), plan.ModelPath, StringComparison.OrdinalIgnoreCase) ||
                Track("ReferencedDocument", () => view.ReferencedDocument) == null)
                throw new InvalidOperationException("The view is detached from its staged native model: " + entry.Key);
            Near(view.ScaleDecimal, plan.Scales[entry.Key], 1e-6, "drawing view scale");
            bool projected = entry.Key == "Top" || entry.Key == "Left";
            var parent = view.GetBaseView() as IView;
            if (projected && (parent == null || parent.GetName2() != main.GetName2()))
                throw new InvalidOperationException("A projected view lost its parent.");
            if (projected) VerifyProjection(main, view, entry.Key);
            if (entry.Key == "Section" && (view.Type != 2 || view.GetSection() == null || parent == null || parent.GetName2() != main.GetName2()))
                throw new InvalidOperationException("The section view lost its native cutting definition.");
            if (entry.Key == "Detail" && (view.Type != 3 || view.GetDetail() == null || parent == null || parent.GetName2() != main.GetName2()))
                throw new InvalidOperationException("The detail view lost its native boundary definition.");
            if (entry.Key == "Isometric" && view.IsExploded() != plan.Exploded)
                throw new InvalidOperationException("The drawing explosion state did not persist.");
            var dimensions = ReadDimensions(view, dimensionValues);
            rows.Add(new Hashtable { {"role", entry.Key}, {"name", entry.Value}, {"type", view.Type}, {"scale", view.ScaleDecimal},
                {"orientation", view.GetOrientationName()}, {"boundsMm", outline.Select(Mm).ToArray()}, {"dimensions", dimensions},
                {"base", parent == null ? null : parent.GetName2()}, {"exploded", view.IsExploded()}, {"centerMarks", CountCenterMarks(view)} });
        }
        evidence["observedDrawingDimensionsMm"] = dimensionValues;
        foreach (double target in Vector(validation["dimensions_mm"]))
            if (!dimensionValues.Any(actual => Math.Abs(actual - target) < 0.005))
                throw new InvalidOperationException("The drawing omitted or changed required dimension " + target + " mm.");
        if (plan.CenterMarks && CountCenterMarks(main) == 0)
            throw new InvalidOperationException("The native hole center marks were lost.");
        var result = new Hashtable { {"sheet", sheet.GetName()}, {"sheetFormat", sheet.GetTemplateName()}, {"firstAngle", true},
            {"sheetMm", new[] { Mm(plan.Width), Mm(plan.Height) }}, {"scale", plan.Scale}, {"views", rows}, {"dimensionsMm", dimensionValues} };
        int standard = model.Extension.GetUserPreferenceInteger(13, 0);
        if (standard != 7) throw new InvalidOperationException("The GB detailing standard did not persist.");
        result["detailStandard"] = standard;
        if (plan.Bom) result["bom"] = ReadBillOfMaterials(drawing, all[plan.Names["Isometric"]], plan);
        return result;
    }

    private static Dictionary<string, IView> ReadViewMap(IDrawingDoc drawing)
    {
        var all = new Dictionary<string, IView>();
        var root = drawing.GetFirstView() as IView;
        if (root == null) throw new InvalidOperationException("The sheet has no view tree.");
        for (var view = root.GetNextView() as IView; view != null; view = view.GetNextView() as IView)
            all.Add(view.GetName2(), view);
        return all;
    }

    private static void VerifyProjection(IView front, IView projected, string direction)
    {
        double[] main = Vector(front.Position), side = Vector(projected.Position);
        double[] parentTransform = Vector(front.ModelToViewTransform.ArrayData), projection = Vector(projected.ModelToViewTransform.ArrayData);
        double dot = parentTransform[2] * projection[2] + parentTransform[5] * projection[5] + parentTransform[8] * projection[8];
        if (Math.Abs(dot) > 1e-5 || (direction == "Top" ? Math.Abs(main[0] - side[0]) > M(0.1) || side[1] >= main[1]
            : Math.Abs(main[1] - side[1]) > M(0.1) || side[0] <= main[0]))
            throw new InvalidOperationException("The first-angle projection geometry is incorrect: " + direction);
    }

    private static IList ReadDimensions(IView view, List<double> values)
    {
        var rows = new ArrayList();
        for (var display = view.GetFirstDisplayDimension5() as IDisplayDimension; display != null; display = display.GetNext5() as IDisplayDimension)
        {
            var dim = display.GetDimension2(0);
            if (dim == null) continue;
            var annotation = display.GetAnnotation() as IAnnotation;
            if (annotation != null && annotation.Visible == 3) continue;
            double actual = Math.Abs(Mm(dim.SystemValue));
            values.Add(actual);
            int toleranceType = dim.GetToleranceType();
            var row = new Hashtable { {"name", dim.FullName}, {"valueMm", actual}, {"dimensionType", display.Type2}, {"toleranceType", toleranceType} };
            if (toleranceType != 0 && dim.Tolerance != null)
                row["toleranceMm"] = new[] { Mm(dim.Tolerance.GetMinValue()), Mm(dim.Tolerance.GetMaxValue()) };
            rows.Add(row);
        }
        return rows;
    }
}
