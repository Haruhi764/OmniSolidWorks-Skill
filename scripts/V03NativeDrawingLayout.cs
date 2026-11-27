using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.IO;
using SolidWorks.Interop.sldworks;

public sealed partial class V03Native
{
    private void LayoutNativeViews(SheetPlan plan, Dictionary<string,IView> views)
    {
        evidence["stage"] = "fit_drawing_views";
        var roles = new[] { "Front", "Top", "Left" };
        var original = roles.ToDictionary(role => role, role => Vector(views[role].GetOutline()));
        double scaleLimit = double.PositiveInfinity;
        foreach (string role in roles)
        {
            var box = original[role];
            double zoneWidth = plan.Width * (role == "Left" ? .205 : .294);
            double zoneHeight = plan.Height * (role == "Top" ? .30 : .37);
            scaleLimit = Math.Min(scaleLimit, views[role].ScaleDecimal *
                Math.Min(zoneWidth / (box[2] - box[0]), zoneHeight / (box[3] - box[1])));
        }
        double scale = new[] { 2.0, 1.0, .5, .2, .1, .05 }.FirstOrDefault(value => value <= scaleLimit);
        if (scale <= 0) throw new InvalidOperationException("Orthographic views do not fit the reserved zones.");
        plan.Scale = scale;
        foreach (string role in roles)
        {
            if (role == "Front")
            {
                views[role].UseSheetScale = 0;
                views[role].ScaleDecimal = scale;
            }
            else views[role].UseParentScale = true;
            plan.Scales[role] = scale;
            views[role].Position = new[] { plan.Width * (role == "Left" ? .425 : .191),
                plan.Height * (role == "Top" ? .33 : .73) };
        }
        var iso = views["Isometric"];
        var originalIso = Vector(iso.GetOutline());
        double isoLimit = iso.ScaleDecimal * Math.Min(plan.Width * .30 / (originalIso[2] - originalIso[0]),
            plan.Height * .40 / (originalIso[3] - originalIso[1]));
        double isoScale = new[] { 1.0, .5, .2, .1, .05 }.FirstOrDefault(value => value <= isoLimit);
        if (isoScale <= 0) throw new InvalidOperationException("Exploded drawing view does not fit.");
        iso.UseSheetScale = 0;
        iso.ScaleDecimal = isoScale;
        iso.Position = new[] { plan.Width * .735, plan.Height * .72 };
        plan.Scales["Isometric"] = isoScale;
        evidence["chosenDrawingScales"] = plan.Scales;
        RebuildDrawing();
    }

    private void AddNativeWitnessDimensions(IDrawingDoc drawing, Dictionary<string,IView> views,
        IEnumerable<IDictionary> witnesses, bool extraSectionClearance)
    {
        var observed = new ArrayList();
        evidence["nativeWitnessDimensions"] = observed;
        foreach (var witness in witnesses)
        {
            string role = Text(witness, "view");
            string[] partIds = witness.Contains("parts") ? Items(witness["parts"]).Cast<string>().ToArray()
                : new[] { Text(witness, "part") };
            int axis = (int)Number(witness, "model_axis");
            double target = Number(witness, "mm");
            evidence["stage"] = "drawing_dimension:" + role + ":" + axis;
            IView view = views[role];
            SelectView(drawing, view);
            var utility = (IMathUtility)app.GetMathUtility();
            var modelToView = view.ModelToViewTransform;
            double scale = view.ScaleDecimal;
            var components = (view.GetVisibleComponents() as Array ?? new object[0]).OfType<IComponent2>().ToArray();
            var candidates = components.Where(item => IsWitnessComponent(item, partIds)).ToArray();
            string sourceId = Path.GetFileNameWithoutExtension(view.GetReferencedModelName());
            if (view.ReferencedDocument is IPartDoc && partIds.Contains(sourceId, StringComparer.OrdinalIgnoreCase))
                candidates = new IComponent2[] { null };
            if (candidates.Length == 0)
            {
                var referenced = view.ReferencedDocument as IAssemblyDoc;
                var native = referenced == null ? null : referenced.GetComponents(false) as Array;
                if (native != null)
                    candidates = native.OfType<IComponent2>().Where(item => IsWitnessComponent(item, partIds)).ToArray();
            }
            var matches = new List<Tuple<IEdge, bool, double>>();
            var vertices = new List<Tuple<IVertex, double[]>>();
            int edgeCount = 0;
            foreach (var component in candidates)
            {
                var edges = view.GetVisibleEntities2((Component2)component, 1) as Array ?? new object[0];
                foreach (var edge in edges.OfType<IEdge>())
                {
                    edgeCount++;
                    var curve = edge.GetCurve() as ICurve;
                    var start = edge.GetStartVertex() as IVertex;
                    var end = edge.GetEndVertex() as IVertex;
                    if (curve == null || !curve.IsLine() || start == null || end == null) continue;
                    double[] a = Vector(start.GetPoint()), b = Vector(end.GetPoint());
                    double[] p = DrawingPoint(utility, modelToView, a);
                    double[] q = DrawingPoint(utility, modelToView, b);
                    vertices.Add(Tuple.Create(start, p));
                    vertices.Add(Tuple.Create(end, q));
                    bool horizontal;
                    if (Math.Abs(Mm(Math.Abs(a[axis] - b[axis])) - target) <= .005 &&
                        DimensionProjection(p, q, scale, target, out horizontal))
                        matches.Add(Tuple.Create(edge, horizontal, WitnessMargin(p, q, horizontal)));
                }
            }

            object first = null, second = null;
            bool alongX = true;
            var best = matches.OrderBy(row => row.Item3).FirstOrDefault();
            if (best != null)
            {
                first = best.Item1;
                alongX = best.Item2;
            }
            else if (vertices.Count > 1 && candidates.Length == 1)
            {
                // A split or occluded straight edge can leave two visible extrema on the same component.
                var direction = new double[3];
                direction[axis] = 1;
                var vector = DrawingPoint(utility, modelToView, direction);
                var zero = DrawingPoint(utility, modelToView, new double[3]);
                int screenAxis = Math.Abs(vector[0] - zero[0]) > Math.Abs(vector[1] - zero[1]) ? 0 : 1;
                var ordered = vertices.OrderBy(v => v.Item2[screenAxis]).ToArray();
                var low = ordered.First();
                var high = ordered.Last();
                if (DimensionProjection(low.Item2, high.Item2, scale, target, out alongX) && alongX == (screenAxis == 0))
                {
                    first = low.Item1;
                    second = high.Item1;
                }
            }
            var rowEvidence = new Hashtable { {"role", role}, {"requestedMm", target}, {"edgesScanned", edgeCount},
                {"visibleComponents", components.Length}, {"matchedComponents", candidates.Select(item => item == null ? sourceId : item.Name2).ToArray()},
                {"visibleNames", components.Take(50).Select(item => item.Name2).ToArray()} };
            observed.Add(rowEvidence);
            if (first == null)
            {
                rowEvidence["status"] = "missing_witness";
                if (witness["required"] is bool && (bool)witness["required"])
                    throw new InvalidOperationException("Required projected dimension witness is missing in " + role + ".");
                continue;
            }

            model.ClearSelection2(true);
            Selected(Track("SelectDrawingWitness", () => view.SelectEntity(first, false)));
            if (second != null) Selected(Track("SelectDrawingWitness", () => view.SelectEntity(second, true)));
            double[] box = Vector(view.GetOutline());
            var display = Track("AddWitnessDimension", () => alongX
                ? model.AddHorizontalDimension2((box[0] + box[2]) / 2, box[1] - M(6), 0)
                : model.AddVerticalDimension2(box[2] + M(extraSectionClearance ? 15 : 5), (box[1] + box[3]) / 2, 0)) as IDisplayDimension;
            if (display == null) throw new InvalidOperationException("SolidWorks did not create a witness dimension.");
            var dimension = display.GetDimension2(0);
            if (dimension == null) throw new InvalidOperationException("SolidWorks returned no native dimension.");
            double actual = Math.Abs(Mm(dimension.SystemValue));
            Near(actual, target, .005, "drawing witness dimension");
            rowEvidence["status"] = "associated";
            rowEvidence["mm"] = actual;
            rowEvidence["name"] = dimension.FullName;
            rowEvidence["screenAxis"] = alongX ? "horizontal" : "vertical";
            rowEvidence["method"] = second == null ? "visible_edge" : "visible_vertices";
            model.ClearSelection2(true);
        }
    }

    private void HideSupersededWitnesses(Dictionary<string,IView> views)
    {
        var checkedRows = (IList)evidence["nativeWitnessDimensions"];
        foreach (IDictionary row in checkedRows)
        {
            if (Text(row, "status") != "associated") continue;
            var view = views[Text(row, "role")];
            int fitType = Text(row, "screenAxis") == "horizontal" ? 11 : 12;
            var wanted = Text(row, "name");
            var matching = new List<string>();
            IAnnotation redundant = null;
            for (var display = view.GetFirstDisplayDimension5() as IDisplayDimension; display != null;
                display = display.GetNext5() as IDisplayDimension)
            {
                var dim = display.GetDimension2(0);
                if (dim == null) continue;
                if (dim.FullName == wanted) redundant = display.GetAnnotation() as IAnnotation;
                else if (display.Type2 == fitType && Math.Abs(Mm(dim.SystemValue) - Number(row, "mm")) <= .005)
                    matching.Add(dim.FullName);
            }
            if (matching.Count != 1 || redundant == null) continue;
            redundant.Visible = 3;
            row["visibleReplacement"] = matching[0];
        }
    }

    private static bool IsWitnessComponent(IComponent2 item, string[] partIds)
    {
        string file = Path.GetFileNameWithoutExtension(item.GetPathName());
        if (partIds.Contains(file, StringComparer.OrdinalIgnoreCase)) return true;
        string instance = (item.Name2 ?? "").Split('/').Last().Split('@')[0];
        int dash = instance.LastIndexOf('-');
        int occurrence;
        return dash > 0 && Int32.TryParse(instance.Substring(dash + 1), out occurrence) &&
            partIds.Contains(instance.Substring(0, dash), StringComparer.OrdinalIgnoreCase);
    }

    private static double[] DrawingPoint(IMathUtility utility, MathTransform transform, double[] point)
    {
        var modelPoint = (IMathPoint)utility.CreatePoint(point);
        return Vector(((IMathPoint)modelPoint.MultiplyTransform(transform)).ArrayData);
    }

    private static bool DimensionProjection(double[] a, double[] b, double scale, double target, out bool horizontal)
    {
        double x = Mm(Math.Abs(a[0] - b[0])) / scale;
        double y = Mm(Math.Abs(a[1] - b[1])) / scale;
        horizontal = x > y;
        return Math.Abs(Math.Max(x, y) - target) <= .005;
    }

    private static double WitnessMargin(double[] a, double[] b, bool horizontal)
    {
        return horizontal ? (a[1] + b[1]) / 2 : -(a[0] + b[0]) / 2;
    }

    private void ClearUnconfirmedWeight(IView sheetView, SheetPlan plan)
    {
        var notes = new List<INote>();
        for (var note = sheetView.GetFirstNote() as INote; note != null; note = note.GetNext() as INote)
            notes.Add(note);
        var matches = notes.Where(note => {
            string linked = (note.PropertyLinkedText ?? "").ToUpperInvariant();
            return linked.Contains("SW-MASS") || linked.Contains("SW-质量") || linked.Contains("SW-重量") || linked == "$PRPSHEET:\"质量\"" || linked == "$PRPSHEET:\"重量\"";
        }).ToArray();

        if (matches.Length == 0 && Path.GetFileName(plan.TemplatePath).Equals("gb_a3.drwdot", StringComparison.OrdinalIgnoreCase)
            && Math.Abs(Mm(plan.Width) - 420) < .05 && Math.Abs(Mm(plan.Height) - 297) < .05)
        {
            // The 2014 installed GB A3 format stores an unlabelled value note
            // below the permanent weight caption. Read the two rows of this cell.
            var cell = notes.Select(note => Tuple.Create(note, Vector(((IAnnotation)note.GetAnnotation()).GetPosition())))
                .Where(row => Mm(row.Item2[0]) > 339 && Mm(row.Item2[0]) < 355 &&
                    Mm(row.Item2[1]) > 23 && Mm(row.Item2[1]) < 43).ToArray();
            evidence["weightCellNotes"] = cell.Select(row => new Hashtable {
                {"text", row.Item1.GetText()}, {"link", row.Item1.PropertyLinkedText}, {"positionMm", row.Item2.Select(Mm).ToArray()}
            }).ToArray();
            if (cell.Length != 0)
            {
                double baseline = cell.Min(row => row.Item2[1]);
                var upper = cell.Where(row => row.Item2[1] - baseline >= M(5)).ToArray();
                if (upper.Any(row => (row.Item1.GetText() ?? "").Contains("重量")))
                    matches = cell.Where(row => row.Item2[1] - baseline < M(1))
                        .Select(row => row.Item1).ToArray();
            }
        }

        evidence["weightFieldMatches"] = matches.Length;
        if (matches.Length == 0)
        {
            evidence["weightField"] = "unidentified_template_field";
            return;
        }
        var positions = matches.Select(note => Vector(((IAnnotation)note.GetAnnotation()).GetPosition())).ToArray();
        if (positions.Any(point => Math.Abs(point[0] - positions[0][0]) >= M(1) ||
            Math.Abs(point[1] - positions[0][1]) >= M(1)))
            throw new InvalidOperationException("The GB sheet contains weight fields in different cells.");
        foreach (var field in matches)
        {
            field.PropertyLinkedText = "-";
            if (!field.SetText("-") || (field.GetText() ?? "").Trim() != "-")
                throw new InvalidOperationException("The GB sheet weight field could not be cleared.");
            ((IAnnotation)field.GetAnnotation()).Visible = 3;
        }
        evidence["weightField"] = "cleared_unconfirmed_model_mass";
    }

    private void LabelExplodedScale(IDrawingDoc drawing, SheetPlan plan, IView view)
    {
        double scale = plan.Scales["Isometric"];
        if (Math.Abs(scale - plan.Scale) < 1e-8) return;
        model.ClearSelection2(true);
        drawing.ActivateView("");
        string label = scale <= 1 ? "1:" + Math.Round(1 / scale) : Math.Round(scale) + ":1";
        var note = Track("InsertViewScaleNote", () => model.InsertNote(label)) as INote;
        var annotation = note == null ? null : note.GetAnnotation() as IAnnotation;
        double[] bounds = Vector(view.GetOutline());
        if (annotation == null || !annotation.SetPosition((bounds[0] + bounds[2]) / 2, bounds[1] - M(5), 0))
            throw new InvalidOperationException("Could not label the exploded view scale.");
        evidence["explodedScaleNote"] = label;
    }
}

