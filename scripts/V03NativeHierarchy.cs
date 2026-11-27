using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using SolidWorks.Interop.sldworks;

public sealed partial class V03Native
{
    private void BuildHierarchy(IDictionary job)
    {
        var validation = Child(job, "validation");
        var operations = Items(job["features"]).Cast<IDictionary>().ToArray();
        var children = Items(job["child_parts"]).Cast<string>().ToArray();
        var modules = job["module_files"] == null ? new[] { Text(job, "subassembly") } :
            Items(job["module_files"]).Cast<string>().ToArray();
        string referenceDirectory = Path.Combine(output, "references");
        var modulePaths = modules.Select(id => {
            RequireFileId(id);
            return Path.Combine(referenceDirectory, id + ".SLDASM");
        }).ToArray();
        var childPaths = children.Select(id => Path.Combine(referenceDirectory, "references", id + ".SLDPRT")).ToArray();
        foreach (string path in childPaths) Open(path, Part, true, "child:" + Path.GetFileName(path));
        var dependencies = modules.Zip(modulePaths, (id, path) => new { id, path })
            .ToDictionary(item => item.id, item => item.path);
        var childSteps = new Dictionary<string, int>();
        foreach (var item in dependencies)
        {
            model = Open(item.Value, Assembly, true, "subassemblyOpen:" + item.Key, 32);
            Activate(model);
            Rebuild();
            var config = (IConfiguration)model.ConfigurationManager.ActiveConfiguration;
            int stepCount = config.GetNumberOfExplodeSteps();
            if (stepCount < 1) throw new InvalidOperationException("Missing saved explosion in " + item.Key);
            childSteps.Add(item.Key, stepCount);
        }
        evidence["sourceChildExplodeSteps"] = childSteps.Values.First();
        evidence["sourceChildStepCounts"] = childSteps;
        if (job["module_files"] != null)
            foreach (var partPath in childPaths) dependencies.Add(Path.GetFileNameWithoutExtension(partPath), partPath);
        var components = new Dictionary<string, IComponent2>();
        var names = new Dictionary<string, string>();
        InsertAssembly(true, operations.Where(row => Text(row, "operation") == "component").ToArray(),
            dependencies, components, names);
        var assembly = (IAssemblyDoc)model;
        foreach (var mate in operations.Where(row => Text(row, "operation") == "mate"))
            AddSubassemblyPlaneMate(assembly, components, mate);
        Rebuild();
        evidence["assembly"] = ReadAssembly(job, names, dependencies);
        var steps = operations.Where(row => Text(row, "operation") == "explode").ToArray();
        string pathName = Path.Combine(output, Text(Child(job, "outputs"), "name") + ".SLDASM");
        string anchor = Text(job, "anchor");
        string datum = Text(job, "datum_part");
        if (job["module_files"] == null)
            components.Add("StationDatum", Items(components[anchor].GetChildren()).OfType<IComponent2>()
                .Single(c => Path.GetFileNameWithoutExtension(c.GetPathName()) == datum));

        var explosionNames = new Dictionary<string, string>(names);
        var target = job["cross_level"] as IDictionary;
        if (target != null)
        {
            var nestedPad = Items(components[Text(target, "parent")].GetChildren()).OfType<IComponent2>()
                .Single(c => c.Name2.Split('/').Last() == Text(target, "leaf"));
            string alias = Text(target, "alias");
            components.Add(alias, nestedPad);
            explosionNames.Add(alias, nestedPad.Name2);
            var usedNames = new HashSet<string>(explosionNames.Values, StringComparer.Ordinal);
            int index = 0;
            foreach (var occurrence in Items(assembly.GetComponents(false)).OfType<IComponent2>())
                if (usedNames.Add(occurrence.Name2))
                    explosionNames.Add("ObservedLeaf" + (++index), occurrence.Name2);
            evidence["crossLevelDirectInstance"] = nestedPad.Name2;
            evidence["crossLevelObservedOccurrences"] = explosionNames.Count;
        }
        Save(Path.Combine(output, "HierarchyCollapsed.SLDASM"), "preExplodeSave");
        CreateExplosion(assembly, components, steps);
        evidence["explosion"] = ReadExplosion(assembly, explosionNames, steps, validation);
        evidence["stage"] = "save_hierarchy";
        Save(pathName, "nativeSave");
        CloseOwnedDocuments();
        model = Open(pathName, Assembly, true, "nativeOpen", 32);
        Activate(model);
        Rebuild();
        evidence["reopenedAssembly"] = ReadAssembly(job, names, dependencies);
        var tree = ReadAssemblyTree();
        evidence["assemblyTree"] = tree;
        var expectedReferences = new HashSet<string>(childPaths.Concat(modulePaths), StringComparer.OrdinalIgnoreCase);
        int expectedModules = job["module_files"] == null ? names.Count : modules.Length;
        if (!expectedReferences.SetEquals((string[])tree["references"]) ||
            ((IList)tree["missing"]).Count != 0 || ((IList)tree["unresolved"]).Count != 0 ||
            (int)tree["maxDepth"] != 2 || (int)tree["partInstances"] != (int)Number(validation, "leaf_count") ||
            (int)tree["subassemblyInstances"] != expectedModules)
            throw new InvalidOperationException("Nested instance count or staged references do not match.");
        assembly = (IAssemblyDoc)model;
        evidence["reopenedExplosion"] = ReadExplosion(assembly, explosionNames, steps, validation);
        evidence["moduleBoxesMm"] = ComponentBoxes(assembly, names);
        NativeInterference(assembly);
        double scale = NativeExplosionPreview(assembly, "Exploded.bmp", null, 0);
        NativeExplosionPreview(assembly, "Collapsed.bmp", null, scale, false);
        CloseModel(model);
    }

    private void AddSubassemblyPlaneMate(IAssemblyDoc assembly, Dictionary<string, IComponent2> components, IDictionary operation)
    {
        evidence["stage"] = "top_level_plane_mate";
        model.ClearSelection2(true);
        var pair = Items(operation["components"]).Cast<string>().ToArray();
        for (int index = 0; index < pair.Length; index++)
        {
            var plane = components[pair[index]].FirstFeature() as IFeature;
            while (plane != null && plane.GetTypeName2() != "RefPlane")
                plane = plane.GetNextFeature() as IFeature;
            if (plane == null) throw new InvalidOperationException("Missing contextual assembly plane.");
            Selected(plane.Select2(index != 0, 1));
        }
        int error;
        int type = MateType(Text(operation, "kind"));
        double distance = type == 5 ? M(Number(operation, "distance_mm")) : 0;
        var mate = assembly.AddMate4(type, 2, false, distance, distance, distance, 0, 0, 0, 0, 0, false, false, out error);
        evidence["topLevelMateStatus"] = error;
        if (mate == null || error != 1)
            throw new InvalidOperationException("Native subassembly plane mate failed: " + error);
        NameFeature((IFeature)mate, Text(operation, "id"));
        model.ClearSelection2(true);
    }
}
