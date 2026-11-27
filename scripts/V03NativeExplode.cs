using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;

public sealed partial class V03Native
{
    private void CreateExplosion(IAssemblyDoc assembly, Dictionary<string, IComponent2> components, IDictionary[] steps,
        bool replaceExisting = false)
    {
        RequireActive(model);
        model.ClearSelection2(true);
        if (replaceExisting)
        {
            var existingName = Items(assembly.GetExplodedViewNames()).Cast<string>().Single();
            SetExploded(assembly, false, existingName);
        }
        else if (!Track("CreateExplodedView", () => assembly.CreateExplodedView()))
            throw new InvalidOperationException("SolidWorks did not create a native exploded view in the new assembly.");
        var config = model.ConfigurationManager.ActiveConfiguration as IConfiguration;
        if (config == null) throw new InvalidOperationException("Missing active assembly configuration.");
        int originalCount = config.GetNumberOfExplodeSteps();
        int startIndex = originalCount > 0 && ReadStep(config, 0) == null ? 1 : 0;
        var originalSteps = new List<string>();
        for (int index = 0; index < originalCount; index++)
        {
            var initial = ReadStep(config, index + startIndex);
            if (initial == null || String.IsNullOrEmpty(initial.Name))
                throw new InvalidOperationException("Could not identify an automatically generated explode step.");
            originalSteps.Add(initial.Name);
        }
        evidence["autoExplodeSteps"] = originalSteps;
        var replacements = new List<KeyValuePair<string, IExplodeStep>>();
        foreach (var operation in steps)
        {
            string id = Text(operation, "id");
            evidence["stage"] = "explode_step:" + id;
            model.ClearSelection2(true);
            var axisComponent = components[Text(operation, "axis_component")];
            string[] keys = MovingKeys(operation);
            string direction = Text(operation, "direction");
            int axisIndex = "xyz".IndexOf(direction[1]);
            double sign;
            object axisEntity;
            if (operation.Contains("axis_diameter"))
            {
                var face = (IFace2)ComponentCylinder(axisComponent, Number(operation, "axis_diameter"));
                sign = Vector(((ISurface)face.GetSurface()).CylinderParams)[5];
                axisEntity = face;
            }
            else
            {
                var edge = FindDirectionEdge(axisComponent, axisIndex);
                sign = Vector(((ICurve)edge.GetCurve()).LineParams)[axisIndex + 3];
                axisEntity = edge;
            }
            SelectEntity(axisEntity, false, 1);
            foreach (string key in keys)
                Selected(components[key].Select4(true, Selection(2), false));
            bool reverse = (sign < 0) != (direction[0] == '-');
            var step = Track("AddExplodeStep", () => config.AddExplodeStep(M(Number(operation, "distance_mm")), reverse, false, false)) as IExplodeStep;
            if (step == null || step.GetNumOfComponents() != keys.Length)
                throw new InvalidOperationException("SolidWorks did not create the specified native explode step " + id);
            step.Name = replaceExisting ? id + " Revision" : id;
            if (replaceExisting) replacements.Add(new KeyValuePair<string, IExplodeStep>(id, step));
        }
        foreach (var name in originalSteps)
            if (!Track("DeleteExplodeStep", () => config.DeleteExplodeStep(name)))
                throw new InvalidOperationException("Could not remove a default step from the new job-owned view.");
        foreach (var replacement in replacements) replacement.Value.Name = replacement.Key;
        model.ClearSelection2(true);
    }

    private IDictionary ReadExplosion(IAssemblyDoc assembly, Dictionary<string, string> names, IDictionary[] expected, IDictionary validation)
    {
        int count = Track("GetExplodedViewCount", () => assembly.GetExplodedViewCount());
        var viewNames = Track("GetExplodedViewNames", () => assembly.GetExplodedViewNames()) as Array;
        if (count != 1 || viewNames == null || viewNames.Length != 1)
            throw new InvalidOperationException("Expected exactly one persisted native exploded view.");
        string name = (string)viewNames.GetValue(0);
        SetExploded(assembly, false, name);
        var baseline = ComponentTransforms(assembly, names, false);
        var collapsed = ComponentPositions(assembly, names);
        var boxes = validation.Contains("clearance_check") && (bool)validation["clearance_check"]
            ? ComponentBoxes(assembly, names) : null;
        SetExploded(assembly, true, name);
        var expanded = ComponentPositions(assembly, names);
        bool recursive = names.Values.Any(value => value.Contains("/"));
        var expandedTransforms = recursive ? ComponentTransforms(assembly, names, true) : null;
        var config = model.ConfigurationManager.ActiveConfiguration as IConfiguration;
        int actualCount = config == null ? -1 : config.GetNumberOfExplodeSteps();
        evidence["observedExplodeStepCount"] = actualCount;
        if (actualCount != expected.Length)
            throw new InvalidOperationException("Native exploded view step count " + actualCount + ", expected " + expected.Length + ".");

        var rows = new ArrayList();
        int firstIndex = ReadStep(config, 0) == null ? 1 : 0;
        for (int index = 0; index < expected.Length; index++)
        {
            var operation = expected[index];
            var step = ReadStep(config, index + firstIndex);
            string[] keys = MovingKeys(operation);
            if (step == null || step.GetNumOfComponents() != keys.Length || step.Name != Text(operation, "id"))
                throw new InvalidOperationException("A native explode step could not be verified.");
            int offset = ReadStepComponent(step, 0) == null ? 1 : 0;
            string[] instances = Enumerable.Range(offset, keys.Length).Select(indexOfComponent => ReadStepComponent(step, indexOfComponent)).ToArray();
            if (!new HashSet<string>(instances).SetEquals(keys.Select(key => names[key])))
                throw new InvalidOperationException("Explode step contains unexpected instances.");
            var row = new Hashtable { {"name", step.Name}, {"components", keys}, {"nativeInstances", instances},
                {"direction", Text(operation, "direction")}, {"requestedDistanceMm", Number(operation, "distance_mm")} };
            if (keys.Length == 1) { row["component"] = keys[0]; row["nativeInstance"] = instances[0]; }
            rows.Add(row);
        }
        var deltas = new Hashtable();
        evidence["observedExplodeDisplacements"] = deltas;
        foreach (var key in names.Keys)
        {
            var target = new double[3];
            foreach (var row in expected.Where(row => MovingKeys(row).Any(moved =>
                moved == key || names[key].StartsWith(names[moved] + "/", StringComparison.Ordinal))))
            {
                string direction = Text(row, "direction");
                target["xyz".IndexOf(direction[1])] += Number(row, "distance_mm") * (direction[0] == '-' ? -1 : 1);
            }
            var delta = expanded[key].Zip(collapsed[key], (a, b) => a - b).ToArray();
            deltas[key] = delta;
            for (int axis = 0; axis < 3; axis++)
                Near(delta[axis], target[axis], 0.01, key + " explosion axis " + axis);
        }
        SetExploded(assembly, false, name);
        var recovered = ComponentPositions(assembly, names);
        foreach (var key in names.Keys)
            for (int axis = 0; axis < 3; axis++) Near(recovered[key][axis], collapsed[key][axis], 0.01, key + " collapse position");
        var restored = ComponentTransforms(assembly, names, false);
        foreach (string key in names.Keys)
            for (int i = 0; i < baseline[key].Length; i++)
                Near(restored[key][i], baseline[key][i], 1e-7, key + " restored native transform");
        var result = new Hashtable { {"verified", true}, {"name", name}, {"steps", rows}, {"deltaMm", deltas},
            {"expandedChecked", true}, {"collapsedChecked", true}, {"restoredTransforms", true} };
        if (recursive)
        {
            foreach (var key in names.Keys)
                for (int axis = 0; axis < 9; axis++)
                    Near(expandedTransforms[key][axis], baseline[key][axis], 1e-7, key + " expanded native rotation");
            result["nativeTransforms"] = new Hashtable { {"folded", baseline}, {"expanded", expandedTransforms}, {"restored", restored} };
        }
        if (boxes != null) result["clearance"] = CheckClearance(boxes, deltas);
        return result;
    }

    private static string[] MovingKeys(IDictionary operation)
    {
        return operation.Contains("components") ? Items(operation["components"]).Cast<string>().ToArray()
            : new[] { Text(operation, "component") };
    }

    private static IEdge FindDirectionEdge(IComponent2 component, int axis)
    {
        foreach (var face in ComponentFaces(component))
            foreach (var edge in Items(face.GetEdges()).OfType<IEdge>())
            {
                var curve = (ICurve)edge.GetCurve();
                if (!curve.IsLine()) continue;
                var line = Vector(curve.LineParams);
                if (Math.Abs(Math.Abs(line[axis + 3]) - 1) < 1e-7) return edge;
            }
        throw new InvalidOperationException("No unambiguous principal straight edge on " + component.Name2);
    }

    private static Dictionary<string, double[]> ComponentTransforms(IAssemblyDoc assembly,
        Dictionary<string, string> names, bool presentation)
    {
        var instances = Items(assembly.GetComponents(!names.Values.Any(value => value.Contains("/")))).Cast<IComponent2>().ToDictionary(component => component.Name2);
        return names.ToDictionary(row => row.Key, row => Vector(instances[row.Value].GetTotalTransform(presentation).ArrayData));
    }

    private static Dictionary<string, double[]> ComponentBoxes(IAssemblyDoc assembly, Dictionary<string, string> names)
    {
        var instances = Items(assembly.GetComponents(true)).Cast<IComponent2>().ToDictionary(component => component.Name2);
        return names.ToDictionary(row => row.Key, row => Vector(instances[row.Value].GetBox(false, false)).Select(Mm).ToArray());
    }

    private IDictionary CheckClearance(Dictionary<string, double[]> boxes, IDictionary deltas)
    {
        var keys = boxes.Keys.ToArray();
        var overlapping = new List<string>();
        int count = 0;
        for (int i = 0; i < keys.Length - 1; i++)
            for (int j = i + 1; j < keys.Length; j++)
            {
                count++;
                var a = boxes[keys[i]];
                var b = boxes[keys[j]];
                var da = (double[])deltas[keys[i]];
                var db = (double[])deltas[keys[j]];
                if (Enumerable.Range(0,3).All(k => Math.Min(a[k+3]+da[k],b[k+3]+db[k]) -
                    Math.Max(a[k]+da[k],b[k]+db[k]) > 0.2))
                    overlapping.Add(keys[i] + " / " + keys[j]);
            }
        var result = new Hashtable { {"test", "final translated native bounding boxes"}, {"pairs", count},
            {"potentialOverlap", overlapping} };
        evidence["clearanceObserved"] = result;
        if (overlapping.Count > 0)
            throw new InvalidOperationException("Potential overlap in final exploded state: " + String.Join(", ", overlapping));
        return result;
    }

    private void SetExploded(IAssemblyDoc assembly, bool show, string name)
    {
        RequireActive(model);
        if (model.IsExploded() != show)
        {
            if (!Track("ShowExploded2", () => assembly.ShowExploded2(show, name)) || model.IsExploded() != show)
                throw new InvalidOperationException("SolidWorks did not switch the named exploded view state.");
        }
    }

    private Dictionary<string, double[]> ComponentPositions(IAssemblyDoc assembly, Dictionary<string, string> names)
    {
        var instances = Items(assembly.GetComponents(!names.Values.Any(value => value.Contains("/")))).Cast<IComponent2>().ToDictionary(component => component.Name2);
        return names.ToDictionary(item => item.Key, item => Translation(instances[item.Value].GetTotalTransform(true)));
    }

    private static IExplodeStep ReadStep(IConfiguration config, int index)
    {
        try { return config.GetExplodeStep(index) as IExplodeStep; }
        catch (COMException) { return null; }
    }

    private static string ReadStepComponent(IExplodeStep step, int index)
    {
        try
        {
            var component = step.GetComponent(index) as IComponent2;
            return component == null ? null : component.Name2;
        }
        catch (COMException) { return null; }
    }
}
