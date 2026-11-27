using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using SolidWorks.Interop.sldworks;

public sealed partial class V03Native
{
    private void AddCenterMarks(IDrawingDoc drawing, IView front)
    {
        evidence["stage"] = "drawing_center_marks";
        SelectView(drawing, front);
        var edges = front.GetVisibleEntities2(null, 1) as Array;
        if (edges == null) throw new InvalidOperationException("No visible native edges for hole center marks.");
        var centers = new List<double[]>();
        int existing = CountCenterMarks(front);
        foreach (IEdge edge in edges)
        {
            var geometry = (ICurve)edge.GetCurve();
            if (!geometry.IsCircle()) continue;
            var p = Vector(geometry.CircleParams);
            if (Math.Abs(Math.Abs(p[5]) - 1) > 1e-5 || centers.Any(item =>
                Math.Abs(item[0] - p[0]) < 1e-6 && Math.Abs(item[1] - p[1]) < 1e-6)) continue;
            centers.Add(p);
            if (existing > 0) continue;
            model.ClearSelection2(true);
            SelectData selection = Selection(0);
            selection.View = (View)front;
            Selected(((IEntity)edge).Select4(false, selection));
            if (Track("InsertCenterMark3", () => drawing.InsertCenterMark3(2, false, false)) == null)
                throw new InvalidOperationException("SolidWorks refused a native hole center mark.");
        }
        evidence["centerMarkLocationsMm"] = centers.Select(point => new[] { Mm(point[0]), Mm(point[1]) }).ToArray();
        if (centers.Count == 0 || CountCenterMarks(front) < centers.Count)
            throw new InvalidOperationException("Hole center mark count could not be verified.");
    }

    private static int CountCenterMarks(IView view)
    {
        int count = 0;
        for (var mark = view.GetFirstCenterMark() as ICenterMark; mark != null; mark = mark.GetNext() as ICenterMark)
            count++;
        return count;
    }

    private void ReconcileTitleBlock(IDrawingDoc drawing, SheetPlan plan)
    {
        evidence["stage"] = "drawing_title_block";
        int addressed = 0;
        bool hasTitle = String.IsNullOrEmpty(plan.Title);
        model.ClearSelection2(true);
        Track("EditTemplate", () => drawing.EditTemplate());
        try
        {
            var root = (IView)drawing.GetFirstView();
            for (var note = root.GetFirstNote() as INote; note != null; note = note.GetNext() as INote)
            {
                string text = (note.GetText() ?? "").Trim().Trim('"', '“', '”');
                string linked = note.PropertyLinkedText ?? "";
                string replace;
                if (text == "图样名称") { replace = plan.Title; hasTitle = true; }
                else if (text == "图样代号") replace = plan.DrawingNumber;
                else if (text.Contains("<未指定>") || linked.IndexOf("SW-Mass", StringComparison.OrdinalIgnoreCase) >= 0)
                    replace = null;
                else continue;
                if (String.IsNullOrEmpty(replace))
                    ((IAnnotation)note.GetAnnotation()).Visible = 3;
                else if (!note.SetText(replace))
                    throw new InvalidOperationException("SolidWorks did not apply the confirmed title block text.");
                addressed++;
            }
            ClearUnconfirmedWeight(root, plan);
        }
        finally { drawing.EditSheet(); }
        evidence["titleNotesAddressed"] = addressed;
        if (!hasTitle) throw new InvalidOperationException("The GB sheet format has no recognised title field.");
    }

    private void AddThicknessDimension(IDrawingDoc drawing, IView view, double thickness)
    {
        SelectView(drawing, view);
        var visible = view.GetVisibleEntities2(null, 1) as Array;
        if (visible == null) throw new InvalidOperationException("The projected view has no editable thickness edges.");
        IEdge selected = null;
        double targetX = Double.NegativeInfinity;
        double targetY = 0;
        foreach (IEdge edge in visible)
        {
            var first = edge.GetStartVertex() as IVertex;
            var last = edge.GetEndVertex() as IVertex;
            if (first == null || last == null || !((ICurve)edge.GetCurve()).IsLine()) continue;
            double[] a = Vector(first.GetPoint()), b = Vector(last.GetPoint());
            if (!Close(Mm(a[0] - b[0]), 0) || !Close(Mm(a[1] - b[1]), 0) ||
                Math.Abs(Math.Abs(Mm(a[2] - b[2])) - thickness) > 0.005) continue;
            var utility = (IMathUtility)app.GetMathUtility();
            var midpoint = (IMathPoint)utility.CreatePoint(a.Zip(b, (x, y) => (x + y) / 2).ToArray());
            var sheet = Vector(((IMathPoint)midpoint.MultiplyTransform(view.ModelToViewTransform)).ArrayData);
            if (sheet[0] <= targetX) continue;
            selected = edge;
            targetX = sheet[0];
            targetY = sheet[1];
        }
        if (selected == null) throw new InvalidOperationException("No unambiguous projected thickness edge was found.");
        model.ClearSelection2(true);
        SelectData data = Selection(0);
        data.View = (View)view;
        Selected(((IEntity)selected).Select4(false, data));
        var dimension = Track("AddDrawingThicknessDimension", () => model.AddVerticalDimension2(targetX + M(9), targetY, 0)) as IDisplayDimension;
        if (dimension == null) throw new InvalidOperationException("SolidWorks did not insert the native thickness dimension.");
        Near(Math.Abs(Mm(dimension.GetDimension2(0).SystemValue)), thickness, 0.005, "projected thickness");
        model.ClearSelection2(true);
    }

    private void AddSectionView(IDrawingDoc drawing, SheetPlan plan, Dictionary<string, IView> views)
    {
        evidence["stage"] = "drawing_section";
        var front = views["Front"];
        SelectView(drawing, front);
        model.ClearSelection2(true);
        var ext = plan.Envelope;
        double midY = (ext[1] + ext[4]) / 2;
        var line = Track("CreateSectionCutLine", () => model.SketchManager.CreateLine(ext[0] - M(8), midY, 0, ext[3] + M(8), midY, 0));
        if (line == null) throw new InvalidOperationException("Cannot create the native section cutting line.");
        var section = Track("CreateSectionViewAt4", () => drawing.CreateSectionViewAt4(plan.Width * 0.51, plan.Height * 0.36, 0, "A", 1, null));
        RegisterView(plan, views, "Section", section, plan.Scale);
    }

    private void AddDetailView(IDrawingDoc drawing, SheetPlan plan, Dictionary<string, IView> views)
    {
        evidence["stage"] = "drawing_detail";
        var front = views["Front"];
        SelectView(drawing, front);
        model.ClearSelection2(true);
        var ext = plan.Envelope;
        double radius = Math.Min(ext[3] - ext[0], ext[4] - ext[1]) * 0.39;
        var boundary = Track("CreateDetailCircle", () => model.SketchManager.CreateCircleByRadius(
            (ext[0] + ext[3]) / 2, (ext[1] + ext[4]) / 2, 0, radius));
        if (boundary == null) throw new InvalidOperationException("Cannot create the native detail boundary.");
        double scale = plan.Scale * 2;
        var detail = Track("CreateDetailViewAt3", () => drawing.CreateDetailViewAt3(plan.Width * 0.80, plan.Height * 0.39,
            0, 0, scale, 1, "B", 1, false)) as IView;
        RegisterView(plan, views, "Detail", detail, scale);
    }

    private void AddBillOfMaterials(IDrawingDoc drawing, SheetPlan plan, IView iso)
    {
        evidence["stage"] = "drawing_bom_balloon";
        string executable = Process.GetProcessById(app.GetProcessID()).MainModule.FileName;
        string file = Path.Combine(Path.GetDirectoryName(executable), "lang", "chinese-simplified", "bom-standard.sldbomtbt");
        if (!File.Exists(file)) throw new IOException("The local SolidWorks BOM template is missing.");
        model.ClearSelection2(true);
        var table = Track("InsertBomTable4", () => iso.InsertBomTable4(false, plan.Width * 0.54, plan.Height * 0.42,
            1, 1, iso.ReferencedConfiguration, file, false, 0, false));
        if (table == null) throw new InvalidOperationException("SolidWorks did not create a native parts-only BOM.");
        if (plan.Incremental != null)
        {
            IAnnotation annotation = ((ITableAnnotation)table).GetAnnotation() as IAnnotation;
            if (annotation == null || !annotation.SetPosition(plan.Width * (plan.AssemblySection ? .685 : .44), plan.Height * .43, 0))
                throw new InvalidOperationException("Could not place the native BOM in its reserved zone.");
        }

        SelectView(drawing, iso);
        var options = drawing.CreateAutoBalloonOptions();
        if (options == null) throw new InvalidOperationException("Native balloon options are unavailable.");
        options.Layout = 5;
        options.IgnoreMultiple = true;
        if (plan.CheckBalloonBounds) options.InsertMagneticLine = false;
        options.Style = 1;
        options.UpperTextContent = 1;
        var inserted = Track("AutoBalloon5", () => drawing.AutoBalloon5(options)) as Array;
        if (inserted == null || inserted.Length == 0) throw new InvalidOperationException("Native component balloons were not inserted.");
    }

    private void PlaceExplodedBalloons(SheetPlan plan, IView view)
    {
        evidence["stage"] = "place_balloons_inside_sheet";
        var annotations = Items(view.GetAnnotations()).OfType<IAnnotation>().Where(annotation => {
            var note = annotation.GetSpecificAnnotation() as INote;
            return note != null && note.IsBomBalloon();
        }).OrderByDescending(annotation => Vector(annotation.GetPosition())[1]).ToList();
        var box = Vector(view.GetOutline());
        double center = (box[1] + box[3]) / 2;
        double gap = Math.Min(M(16), plan.Height * .36 / Math.Max(1, annotations.Count - 1));
        if (gap < M(8)) throw new InvalidOperationException("Too many balloons for this sheet. Use the larger drawing format.");
        double halfStack = gap * (annotations.Count - 1) / 2;
        center = Math.Min(plan.Height - M(14) - halfStack, Math.Max(plan.Height * 0.49 + halfStack, center));
        double x = plan.Width - M(19);
        for (int index = 0; index < annotations.Count; index++)
        {
            var annotation = annotations[index];
            var before = Vector(annotation.GetPosition());
            double y = center + halfStack - gap * index;
            if (!Track("SetBalloonPosition", () => annotation.SetPosition(x, y, before[2])))
                throw new InvalidOperationException("The native BOM balloon could not be repositioned.");
        }
    }

    private IDictionary ReadBillOfMaterials(IDrawingDoc drawing, IView iso, SheetPlan plan)
    {
        var root = drawing.GetFirstView() as IView;
        var tables = new List<IBomTableAnnotation>();
        foreach (var view in new[] { root, iso })
        {
            var values = view.GetTableAnnotations() as Array;
            if (values != null) foreach (var value in values)
            {
                var row = value as IBomTableAnnotation;
                if (row != null && !tables.Any(item => Object.ReferenceEquals(item, row))) tables.Add(row);
            }
        }
        if (tables.Count != 1) throw new InvalidOperationException("Expected one linked native BOM table.");
        var bom = tables[0];
        var data = (ITableAnnotation)bom;
        var rows = new ArrayList();
        var instances = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var items = new HashSet<string>(StringComparer.Ordinal);
        for (int index = 0; index < data.RowCount; index++)
        {
            var components = bom.GetComponents2(index, iso.ReferencedConfiguration) as Array;
            if (components == null || components.Length == 0) continue;
            string[] names = components.Cast<IComponent2>().Select(item => item.Name2).ToArray();
            foreach (var component in names)
                if (!instances.Add(component)) throw new InvalidOperationException("Duplicate BOM component: " + component);
            string itemNumber, partNumber;
            int quantity = bom.GetComponentsCount2(index, iso.ReferencedConfiguration, out itemNumber, out partNumber);
            if (quantity != names.Length || String.IsNullOrWhiteSpace(itemNumber) || !items.Add(itemNumber.Trim()))
                throw new InvalidOperationException("BOM quantities or item numbering did not reconcile.");
            string[] cells = Enumerable.Range(0, data.ColumnCount).Select(col => data.get_DisplayedText(index, col)).ToArray();
            rows.Add(new Hashtable { {"cells", cells}, {"names", names}, {"quantity", quantity},
                {"item", itemNumber.Trim()}, {"part", partNumber} });
        }
        var balloons = new ArrayList();
        var annotations = iso.GetAnnotations() as Array;
        if (annotations != null) foreach (IAnnotation annotation in annotations)
        {
            var note = annotation.GetSpecificAnnotation() as INote;
            if (note == null || !note.IsBomBalloon()) continue;
            int leaders = annotation.GetLeaderCount();
            if (leaders == 0) throw new InvalidOperationException("A native item balloon lost its leader.");
            var location = Vector(annotation.GetPosition());
            if (plan.CheckBalloonBounds && (location[0] < M(12) || location[0] > plan.Width - M(12) ||
                location[1] < M(14) || location[1] > plan.Height - M(12)))
                throw new InvalidOperationException("A BOM balloon lies outside the safe sheet margin.");
            balloons.Add(new Hashtable { {"item", note.GetText()}, {"leaders", leaders},
                {"positionMm", location.Select(Mm).ToArray()} });
        }
        var shown = new HashSet<string>(balloons.Cast<IDictionary>().Select(balloon => Text(balloon,"item").Trim()));
        if (instances.Count != plan.ComponentCount || rows.Count < 1 || !shown.SetEquals(items))
            throw new InvalidOperationException("BOM component or balloon readback is incomplete: " + instances.Count + "/" + balloons.Count);
        return new Hashtable { {"rows", rows}, {"componentCount", instances.Count}, {"balloons", balloons} };
    }
}
