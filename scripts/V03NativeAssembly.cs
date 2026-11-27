using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using SolidWorks.Interop.sldworks;

public sealed partial class V03Native
{
    private IDictionary incrementalCheckpointNames;

    private void BuildAssembly(IDictionary job)
    {
        if (job["hierarchy"] is bool && (bool)job["hierarchy"])
        {
            BuildHierarchy(job);
            return;
        }
        if (job["route_probe"] is IDictionary)
        {
            ProbeRouteSketch(job);
            return;
        }
        bool extended = Number(job, "schema_version") == 2;
        var dependencies = new Dictionary<string, string>();
        evidence["stage"] = "load_part_references";
        foreach (IDictionary row in Items(job["dependencies"]))
        {
            string key = Text(row, "id");
            string path = Path.Combine(output, "references", key + ".SLDPRT");
            Open(path, Part, true, "sourceOpen:" + key);
            dependencies.Add(key, path);
        }

        var operations = Items(job["features"]).Cast<IDictionary>().ToArray();
        var incremental = job["incremental"] as IDictionary;
        if (incremental != null) incrementalCheckpointNames = job["checkpoint_names"] as IDictionary;
        var comps = new Dictionary<string, IComponent2>();
        var inserted = new Dictionary<string, string>();
        string checkpoint = Path.Combine(output, "checkpoint.SLDASM");
        if (extended && File.Exists(checkpoint))
            ResumeAssembly(checkpoint, operations, dependencies, comps, inserted);
        else
            InsertAssembly(extended, operations, dependencies, comps, inserted);
        var assembly = (IAssemblyDoc)model;

        string name = Text(Child(job, "outputs"), "name");
        string pathName = Path.Combine(output, name + ".SLDASM");
        evidence["stage"] = "validate_assembly";
        if (!File.Exists(checkpoint)) Rebuild();
        evidence["assembly"] = ReadAssembly(job, inserted, dependencies);
        var before = extended ? ComponentTransforms(assembly, inserted, false) : null;
        var explode = operations.Where(item => Text(item, "operation") == "explode").ToArray();
        if (incremental != null && incremental.Contains("capture_only"))
        {
            CaptureExplosion(assembly, inserted, explode, Child(job, "validation"));
            CloseModel(model);
            return;
        }
        double comparisonScale = 0;
        if (incremental != null && incremental.Contains("prior_explosion"))
        {
            var old = Items(incremental["prior_explosion"]).Cast<IDictionary>().ToArray();
            evidence["priorExplosion"] = ReadExplosion(assembly, inserted, old, Child(job, "validation"));
            comparisonScale = NativeExplosionPreview(assembly, "BeforeExploded.bmp", null, 0);
        }
        if (explode.Length > 0)
        {
            evidence["stage"] = "build_native_explosion";
            if (!File.Exists(checkpoint))
                Save(Path.Combine(output, name + "_base.SLDASM"), "preExplodeSave");
            if (comparisonScale > 0 && incremental.Contains("replace_steps"))
                CreateExplosion(assembly, comps, explode, true);
            else if (comparisonScale == 0)
                CreateExplosion(assembly, comps, explode);
            evidence["stage"] = "verify_native_explosion";
            evidence["explosion"] = ReadExplosion(assembly, inserted, explode, Child(job, "validation"));
        }
        evidence["stage"] = "save_assembly";
        if (comparisonScale > 0)
        {
            SetPreviewCamera((IModelView)model.ActiveView, Vector(incremental["camera"]));
            model.NameView("Service Exploded");
        }
        Save(pathName, "nativeSave");
        CloseOwnedDocuments();
        evidence["stage"] = "reopen_assembly";
        model = Open(pathName, Assembly, true, "nativeOpen", 32);
        Activate(model);
        Rebuild();
        evidence["reopenedAssembly"] = ReadAssembly(job, inserted, dependencies);
        if (before != null)
        {
            var after = ComponentTransforms((IAssemblyDoc)model, inserted, false);
            foreach (string key in before.Keys)
                for (int i = 0; i < before[key].Length; i++)
                    Near(after[key][i], before[key][i], 1e-7, key + " saved collapsed transform");
            evidence["assembledBaselinePreserved"] = true;
        }
        if (explode.Length > 0)
        {
            evidence["stage"] = "reopened_native_explosion";
            evidence["reopenedExplosion"] = ReadExplosion((IAssemblyDoc)model, inserted, explode, Child(job, "validation"));
        }
        if (comparisonScale > 0)
        {
            var reopened = (IAssemblyDoc)model;
            if (!Items(model.GetModelViewNames()).Cast<string>().Contains("Service Exploded"))
                throw new InvalidOperationException("The saved service view is missing.");
            evidence["serviceViewPersisted"] = true;
            NativeInterference(reopened);
            NativeExplosionPreview(reopened, "AfterExploded.bmp", Vector(incremental["camera"]), comparisonScale);
        }
        if (job["review_assembly"] is bool && (bool)job["review_assembly"])
            ReviewSavedAssembly(inserted, explode.Length > 0);
        CloseModel(model);
    }

    private void ResumeAssembly(string checkpoint, IDictionary[] operations, Dictionary<string, string> dependencies,
        Dictionary<string, IComponent2> comps, Dictionary<string, string> inserted)
    {
        evidence["stage"] = "open_staged_checkpoint";
        model = Open(checkpoint, Assembly, false, "checkpointOpen", 32);
        Activate(model);
        var assembly = (IAssemblyDoc)model;
        // SolidWorks 2014 may return NeedsRegen for a relocated assembly.
        // Refresh the staged reference graph before enumerating components.
        evidence["stage"] = "rebuild_staged_checkpoint";
        Rebuild();
        evidence["stage"] = "bind_staged_checkpoint";
        var entries = Items(Track("CheckpointGetComponents", () => assembly.GetComponents(true))).Cast<IComponent2>().ToList();
        foreach (var row in operations.Where(item => Text(item, "operation") == "component"))
        {
            string key = Text(row, "id");
            string path = dependencies[Text(row, "dependency")];
            var matches = entries.Where(c => String.Equals(c.GetPathName(), path, StringComparison.OrdinalIgnoreCase)).ToArray();
            if (incrementalCheckpointNames != null)
                matches = matches.Where(c => c.Name2 == Text(incrementalCheckpointNames, key)).ToArray();
            if (matches.Length != 1)
                throw new InvalidOperationException("Cannot identify a unique staged checkpoint component: " + key);
            comps.Add(key, matches[0]);
            inserted.Add(key, matches[0].Name2);
        }
        evidence["checkpointReused"] = true;
    }

    private void InsertAssembly(bool extended, IDictionary[] operations, Dictionary<string, string> dependencies,
        Dictionary<string, IComponent2> comps, Dictionary<string, string> inserted)
    {
        evidence["stage"] = "new_assembly";
        model = NewModel(Assembly);
        var assembly = (IAssemblyDoc)model;
        foreach (var row in operations.Where(item => Text(item, "operation") == "component"))
        {
            string id = Text(row, "id");
            evidence["stage"] = "component:" + id;
            string path = dependencies[Text(row, "dependency")];
            var location = Vector(row["location"]);
            Activate(model);
            var component = Track("AddComponent5", () => assembly.AddComponent5(path, 0, "", false, "",
                M(location[0]), M(location[1]), M(location[2]))) as IComponent2;
            if (component == null || !String.Equals(component.GetPathName(), path, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("SolidWorks did not bind the staged component " + id);
            if (comps.Count == 0 && !component.IsFixed())
            {
                model.ClearSelection2(true);
                Selected(component.Select4(false, null, false));
                Track("FixComponent", () => assembly.FixComponent());
                if (!component.IsFixed()) throw new InvalidOperationException("The assembly base could not be fixed.");
            }
            if (comps.Count > 0 && component.IsFixed())
            {
                model.ClearSelection2(true);
                Selected(component.Select4(false, null, false));
                Track("UnfixComponent", () => assembly.UnfixComponent());
                if (component.IsFixed()) throw new InvalidOperationException("The inserted component could not be floated: " + id);
            }
            if (extended && comps.Count > 0)
            {
                var math = (IMathUtility)app.GetMathUtility();
                var origin = Translation(comps.Values.First().Transform2);
                var absolute = location.Zip(origin, (offset, basis) => M(offset + basis)).ToArray();
                var transform = (MathTransform)math.CreateTransform(new[] {1d,0,0,0,1,0,0,0,1,
                    absolute[0],absolute[1],absolute[2],1,0,0,0});
                component.Transform2 = transform;
                if (row.Contains("fixed") && (bool)row["fixed"])
                {
                    model.ClearSelection2(true);
                    Selected(component.Select4(false, null, false));
                    assembly.FixComponent();
                    if (!component.IsFixed()) throw new InvalidOperationException("Component fixing failed: " + id);
                }
            }
            comps.Add(id, component);
            inserted.Add(id, component.Name2);
            evidence["inserted:" + id] = new Hashtable { {"name", component.Name2}, {"fixed", component.IsFixed()},
                {"locationMm", Translation(component.Transform2)} };
        }
        // Set the axial constraint before aligning free cylinder axes. SolidWorks
        // 2014 can reject a second planar mate when the first mate flipped an axis.
        foreach (var row in operations.Where(item => Text(item, "operation") == "mate")
            .OrderBy(item => Text(item, "kind") == "concentric"))
            AddMate(assembly, comps, row);
    }

    private void AddMate(IAssemblyDoc assembly, Dictionary<string, IComponent2> components, IDictionary operation)
    {
        string name = Text(operation, "id");
        evidence["stage"] = "mate:" + name;
        RequireActive(model);
        model.ClearSelection2(true);
        var keys = Items(operation["components"]).Cast<string>().ToArray();
        var first = components[keys[0]];
        var second = components[keys[1]];
        string kind = Text(operation, "kind");
        int type = MateType(kind);
        if (type == 1)
        {
            double[] sizes = Vector(operation["diameters"]);
            SelectEntity(ComponentCylinder(first, sizes[0]), false, 1);
            SelectEntity(ComponentCylinder(second, sizes[1]), true, 1);
        }
        else
        {
            SelectEntity(ComponentSeat(first), false, 1);
            SelectEntity(ComponentSeat(second), true, 1);
        }
        int error;
        double distance = type == 5 ? M(Number(operation, "distance_mm")) : 0;
        calls.Add("AddMate4");
        var mate = assembly.AddMate4(type, 2, type == 5, distance, distance, distance, 0, 0, 0, 0, 0, false, false, out error);
        if (mate == null || error != 1)
            throw new InvalidOperationException("SolidWorks rejected " + name + " mate, status " + error);
        NameFeature((IFeature)mate, name);
        model.ClearSelection2(true);
        evidence["mateCall:" + name] = new Hashtable { {"status", error}, {"type", type}, {"distanceMm", Mm(distance)},
            {"firstLocationMm", Translation(first.Transform2)}, {"secondLocationMm", Translation(second.Transform2)} };
    }

    private static int MateType(string kind)
    {
        if (kind == "coincident") return 0;
        if (kind == "concentric") return 1;
        if (kind == "distance") return 5;
        throw new InvalidOperationException("Invalid mate type");
    }

    private static object ComponentCylinder(IComponent2 component, double diameter)
    {
        var candidates = ComponentFaces(component).Where(face => {
            var surface = (ISurface)face.GetSurface();
            if (!surface.IsCylinder()) return false;
            var cylinder = Vector(surface.CylinderParams);
            return Close(Mm(2 * cylinder[6]), diameter) && Close(Mm(cylinder[0]), 0) && Close(Mm(cylinder[1]), 0) &&
                Math.Abs(Math.Abs(cylinder[5]) - 1) < 1e-6;
        }).ToArray();
        if (candidates.Length != 1)
            throw new InvalidOperationException("Ambiguous concentric mate cylinder on " + component.Name2);
        return candidates[0];
    }

    private static IFace2 ComponentSeat(IComponent2 component)
    {
        var candidates = ComponentFaces(component).Where(face => {
            if (!((ISurface)face.GetSurface()).IsPlane()) return false;
            var box = Vector(face.GetBox());
            return Math.Abs(box[2]) < 1e-8 && Math.Abs(box[5]) < 1e-8;
        }).ToArray();
        if (candidates.Length != 1)
            throw new InvalidOperationException("Mate component needs one unambiguous planar seat at its model origin: " + component.Name2);
        return candidates[0];
    }

    private static IEnumerable<IFace2> ComponentFaces(IComponent2 component)
    {
        object info;
        var bodies = component.GetBodies3(0, out info) as Array;
        if (bodies == null || bodies.Length != 1)
            throw new InvalidOperationException("Mate component does not have one resolved solid.");
        return Items(((IBody2)bodies.GetValue(0)).GetFaces()).Cast<IFace2>();
    }

    private IDictionary ReadAssembly(IDictionary job, Dictionary<string, string> names, Dictionary<string, string> dependencies)
    {
        RequireActive(model);
        var assembly = (IAssemblyDoc)model;
        var found = Track("GetComponents", () => assembly.GetComponents(true)) as Array;
        if (found == null || found.Length != names.Count)
            throw new InvalidOperationException("Top-level component count differs from the job.");
        var byName = found.Cast<IComponent2>().ToDictionary(component => component.Name2, StringComparer.OrdinalIgnoreCase);
        var componentRows = new ArrayList();
        var rows = Items(job["features"]).Cast<IDictionary>().ToArray();
        var expected = Child(Child(job, "validation"), "relative_positions");
        var componentPlans = rows.Where(item => Text(item, "operation") == "component").ToArray();
        var origin = Translation(byName[names[Text(componentPlans[0], "id")]].Transform2);
        foreach (var plan in componentPlans)
        {
            string id = Text(plan, "id");
            var component = byName[names[id]];
            string path = component.GetPathName();
            if (!String.Equals(path, dependencies[Text(plan, "dependency")], StringComparison.OrdinalIgnoreCase) || component.GetModelDoc2() == null)
                throw new InvalidOperationException("The reopened assembly component reference is unresolved: " + id);
            var coordinates = Translation(component.Transform2);
            var relative = coordinates.Zip(origin, (a, b) => a - b).ToArray();
            double[] position = Vector(expected[id]);
            for (int axis = 0; axis < 3; axis++) Near(relative[axis], position[axis], 0.01, id + " relative position");
            componentRows.Add(new Hashtable { {"id", id}, {"instance", component.Name2}, {"path", path},
                {"relativeMm", relative}, {"fixed", component.IsFixed()} });
        }

        var group = Features().FirstOrDefault(feature => feature.GetTypeName2() == "MateGroup");
        if (group == null) throw new InvalidOperationException("No native MateGroup in the assembly.");
        var mates = new Dictionary<string, IFeature>();
        for (var item = group.GetFirstSubFeature() as IFeature; item != null; item = item.GetNextSubFeature() as IFeature)
            if (item.GetSpecificFeature2() is IMate2) mates.Add(item.Name, item);
        if (mates.Count != (int)Number(Child(job, "validation"), "mate_count"))
            throw new InvalidOperationException("Unexpected count of native mates.");
        var mateRows = new ArrayList();
        foreach (var plan in rows.Where(item => Text(item, "operation") == "mate"))
        {
            string id = Text(plan, "id");
            var feature = mates[id];
            var mate = feature.GetSpecificFeature2() as IMate2;
            bool warning;
            int errors = feature.GetErrorCode2(out warning);
            if (mate.Type != MateType(Text(plan, "kind")) || mate.GetMateEntityCount() != 2 || errors != 0)
                throw new InvalidOperationException("Native mate readback is incomplete or unhealthy: " + id);
            var refs = new[] { mate.MateEntity(0).ReferenceComponent.Name2, mate.MateEntity(1).ReferenceComponent.Name2 };
            if (!new HashSet<string>(refs).SetEquals(Items(plan["components"]).Cast<string>().Select(key => names[key])))
                throw new InvalidOperationException("Native mate references differ from the job: " + id);
            mateRows.Add(new Hashtable { {"id", id}, {"type", mate.Type}, {"error", errors}, {"references", refs} });
        }
        return new Hashtable { {"verified", true}, {"components", componentRows}, {"mates", mateRows} };
    }

    private static double[] Translation(MathTransform transform)
    {
        if (transform == null) throw new InvalidOperationException("The component transform is missing.");
        return Vector(transform.ArrayData).Skip(9).Take(3).Select(Mm).ToArray();
    }
}
