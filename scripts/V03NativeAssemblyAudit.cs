using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using SolidWorks.Interop.sldworks;

public sealed partial class V03Native
{
    private IDictionary ReadAssemblyTree()
    {
        var configuration = (IConfiguration)model.ConfigurationManager.ActiveConfiguration;
        var root = configuration.GetRootComponent3(false);
        if (root == null) throw new InvalidOperationException("Could not read the active assembly root.");
        var rows = new List<Hashtable>();
        var missing = new List<string>();
        var unresolved = new List<string>();
        var references = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var partFiles = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var pending = new Stack<Tuple<IComponent2, string, int>>();
        QueueChildren(root, null, 1, pending);
        int partInstances = 0, assemblyInstances = 0, maxDepth = 0;
        while (pending.Count > 0)
        {
            var entry = pending.Pop();
            if (entry.Item3 > 128 || rows.Count >= 50000)
                throw new InvalidOperationException("Assembly traversal exceeded the bounded readback size.");
            var component = entry.Item1;
            string instance = component.Name2;
            string path = component.GetPathName() ?? "";
            bool suppressed = component.IsSuppressed();
            bool virtualPart = component.IsVirtual;
            var loaded = suppressed ? null : component.GetModelDoc2() as IModelDoc2;
            string extension = Path.GetExtension(path).ToLowerInvariant();
            int kind = loaded != null ? loaded.GetType() :
                extension == ".sldprt" ? Part : extension == ".sldasm" ? Assembly : 0;
            bool pathPresent = virtualPart || File.Exists(path);
            if (!suppressed && !pathPresent) missing.Add(instance);
            if (!suppressed && loaded == null) unresolved.Add(instance);
            if (path.Length != 0 && !virtualPart) references.Add(path);
            if (kind == Part)
            {
                partInstances++;
                if (path.Length != 0 && !virtualPart) partFiles.Add(path);
            }
            if (kind == Assembly) assemblyInstances++;
            maxDepth = Math.Max(maxDepth, entry.Item3);
            rows.Add(new Hashtable { {"instance", instance}, {"parent", entry.Item2}, {"depth", entry.Item3},
                {"path", path}, {"type", kind}, {"configuration", component.ReferencedConfiguration},
                {"suppressed", suppressed}, {"suppressionCode", component.GetSuppression()},
                {"resolved", loaded != null}, {"exists", pathPresent}, {"virtual", virtualPart},
                {"fixed", !suppressed && component.IsFixed()},
                {"constraintCode", loaded == null ? (object)null : component.GetConstrainedStatus()},
                {"toolboxPartType", loaded == null || kind != Part ? (object)null : loaded.Extension.ToolboxPartType} });
            if (!suppressed) QueueChildren(component, instance, entry.Item3 + 1, pending);
        }
        return new Hashtable { {"configuration", configuration.Name}, {"instances", rows}, {"partInstances", partInstances},
            {"subassemblyInstances", assemblyInstances}, {"independentPartFiles", partFiles.Count},
            {"references", references.OrderBy(path => path, StringComparer.OrdinalIgnoreCase).ToArray()},
            {"unresolved", unresolved}, {"missing", missing}, {"maxDepth", maxDepth},
            {"rebuildState", model.Extension.NeedsRebuild2} };
    }

    private static void QueueChildren(IComponent2 component, string parent, int depth,
        Stack<Tuple<IComponent2, string, int>> pending)
    {
        var children = component.GetChildren() as Array;
        if (children == null) return;
        foreach (var child in children.Cast<IComponent2>().OrderByDescending(value => value.Name2, StringComparer.Ordinal))
            pending.Push(Tuple.Create(child, parent, depth));
    }

    private void ReviewSavedAssembly(Dictionary<string, string> names, bool exploded)
    {
        evidence["stage"] = "read_reopened_assembly_tree";
        var tree = ReadAssemblyTree();
        evidence["assemblyTree"] = tree;
        if (((List<string>)tree["missing"]).Count != 0 || ((List<string>)tree["unresolved"]).Count != 0)
            throw new InvalidOperationException("A required component reference did not resolve.");
        var assembly = (IAssemblyDoc)model;
        NativeInterference(assembly);
        if (!exploded) return;
        evidence["componentBoxesMm"] = ComponentBoxes(assembly, names);
        double scale = NativeExplosionPreview(assembly, "Exploded.bmp", null, 0);
        NativeExplosionPreview(assembly, "Collapsed.bmp", null, scale, false);
    }
}
