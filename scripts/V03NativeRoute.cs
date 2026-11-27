using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;

public sealed partial class V03Native
{
    private void ProbeRouteSketch(IDictionary job)
    {
        foreach (IDictionary row in Items(job["dependencies"]))
        {
            string key = Text(row, "id");
            Open(Path.Combine(output, "references", key + ".SLDPRT"), Part, true, "source:" + key);
        }
        model = Open(Path.Combine(output, "checkpoint.SLDASM"), Assembly, false, "routeCheckpoint", 32);
        Activate(model);
        Rebuild();
        var route = Child(job, "route_probe");
        var assembly = (IAssemblyDoc)model;
        string saved = Path.Combine(output, Text(Child(job, "outputs"), "name") + ".SLDASM");
        Save(saved, "routeBaseSave");
        if (route["auto_explode"] is bool && (bool)route["auto_explode"])
        {
            evidence["stage"] = "route_auto_create_explosion";
            if (assembly.GetExplodedViewCount() != 0 || !Track("AutoExplode", () => assembly.AutoExplode()))
                throw new InvalidOperationException("The official AutoExplode-style control did not create a configuration view.");
            evidence["createdByAutoExplode"] = true;
        }
        var names = Items(assembly.GetExplodedViewNames()).Cast<string>().ToArray();
        if (names.Length != 1 || ((IConfiguration)model.ConfigurationManager.ActiveConfiguration).GetNumberOfExplodeSteps() < 1)
            throw new InvalidOperationException("The route sketch requires one verified existing native exploded view.");
        string explodeName = names[0];
        var components = Items(assembly.GetComponents(true)).OfType<IComponent2>().ToArray();
        var first = components.Single(c => Path.GetFileNameWithoutExtension(c.GetPathName()) == Text(route, "first"));
        var second = components.Single(c => Path.GetFileNameWithoutExtension(c.GetPathName()) == Text(route, "second"));
        var prior = ReadRouteProfiles();
        SetExploded(assembly, true, explodeName);
        if (!Track("EditRebuild3Exploded", () => model.EditRebuild3()))
            throw new InvalidOperationException("Could not rebuild the expanded view before route selection.");
        model.ViewZoomtofit2();
        model.ClearSelection2(true);
        evidence["stage"] = "route_sketch_enter";
        bool entered = Track("InsertExplodeLineSketch", () => model.SketchManager.InsertExplodeLineSketch());
        var sketch = model.GetActiveSketch2() as ISketch;
        evidence["nativeExplodeLineSketchCreated"] = entered;
        evidence["routeExplodedBeforeInsert"] = model.IsExploded();
        evidence["routeActiveSketchType"] = sketch == null ? null : sketch.GetType().FullName;
        if (!entered || sketch == null || !sketch.Is3D() || !model.IsExploded())
            throw new InvalidOperationException("No active native explode-line sketch in expanded view.");

        string source = route["source"] as string ?? "body";
        string kind = route["witness"] as string ?? ((route["circular_edges"] is bool && (bool)route["circular_edges"]) ? "edges" : "faces");
        string packing = route["packing"] as string ?? "typed";
        byte[] routeIdentity = null;
        var inputs = new ArrayList();
        evidence["routeInputEntities"] = inputs;
        try
        {
            evidence["stage"] = "route_select_" + source;
            object a = RouteEndpoint(first, Number(route, "diameter"), kind == "edges", true, source, inputs);
            object b = RouteEndpoint(second, Number(route, "diameter"), kind != "faces", false, source, inputs);
            Array entities = PackRouteEntities(a, b, kind, packing);
            bool along = route["along"] is bool && (bool)route["along"];
            Array reverse = packing == "variant" ? (Array)new object[] { false, false } : new bool[2];
            Array alternate = packing == "variant" ? (Array)new object[] { false, false } : new bool[2];
            Array xyz = packing == "variant" ? (Array)new object[] { along, false } : new[] { along, false };
            evidence["routeArrays"] = new Hashtable { {"entities", entities.GetType().FullName},
                {"reverse", reverse}, {"alternatePath", alternate}, {"alongXYZ", xyz},
                {"flagType", xyz.GetType().FullName}, {"packing", packing} };
            evidence["stage"] = "route_insert";
            bool inserted = Track("InsertRouteLine", () => sketch.InsertRouteLine(entities, reverse, alternate, xyz));
            evidence["nativeRouteLineCreated"] = inserted;
            int segments = RouteSegmentCount(sketch);
            evidence["routeSegments"] = segments;
            if (!inserted || segments == 0)
                throw new InvalidOperationException("InsertRouteLine returned " + inserted + " with " + segments + " native segments.");
            var segment = ((Array)sketch.GetSketchSegments()).GetValue(0);
            try { routeIdentity = model.Extension.GetPersistReference3(segment) as byte[]; }
            catch (COMException ex) { evidence["routePersistIdHresult"] = "0x" + ex.HResult.ToString("X8"); }
            evidence["routePersistReferenceLength"] = routeIdentity == null ? 0 : routeIdentity.Length;

        }
        catch (Exception ex)
        {
            evidence["routeFailureStage"] = evidence["stage"];
            evidence["routeFailureHresult"] = "0x" + ex.HResult.ToString("X8");
            throw;
        }
        finally
        {
            model.ClearSelection2(true);
            if (model.GetActiveSketch2() != null)
            {
                evidence["stage"] = "route_sketch_exit";
                if (route["exit_with_3d"] is bool && (bool)route["exit_with_3d"])
                {
                    Track("Finish3DSketch", () => model.SketchManager.Insert3DSketch(true));
                    evidence["routeExitMethod"] = "Insert3DSketch";
                }
                else
                    evidence["routeToggleReturned"] = Track("ExitExplodeLineSketch",
                        () => model.SketchManager.InsertExplodeLineSketch());
            }
            evidence["routeSketchExited"] = model.GetActiveSketch2() == null;
        }
        if (!(bool)evidence["routeSketchExited"])
            throw new InvalidOperationException("The explode-line sketch edit session remained active.");

        evidence["stage"] = "route_feature_read";
        var created = ReadRouteProfiles().Where(row => !prior.ContainsKey(row.Key) && row.Value.Item2 > 0)
            .ToDictionary(row => row.Key, row => row.Value);
        evidence["routeProfilesAfterExit"] = ReadRouteProfiles().Select(row =>
            row.Key + ":" + row.Value.Item1 + ":" + row.Value.Item2).ToArray();
        evidence["routeFeatureInventory"] = RouteFeatures().Select(f => f.Name + ":" + f.GetTypeName2()).ToArray();
        evidence["stage"] = "route_native_save";
        model.SetSaveFlag();
        evidence["routeDirtyBeforeSave"] = model.GetSaveFlag();
        int savedErrors = 0, savedWarnings = 0;
        bool committed = Track("RouteSave3", () => model.Save3(Silent, ref savedErrors, ref savedWarnings));
        evidence["nativeSave"] = new Hashtable { {"path", saved}, {"ok", committed}, {"errors", savedErrors},
            {"warnings", savedWarnings}, {"expanded", model.IsExploded()} };
        if (!committed || savedErrors != 0 || savedWarnings != 0 || model.GetSaveFlag())
            throw new IOException("The native exploded configuration could not be saved in place.");
        CloseOwnedDocuments();
        model = Open(saved, Assembly, false, "nativeOpen", 32);
        Activate(model);
        evidence["routeExpandedImmediatelyAfterOpen"] = model.IsExploded();
        SetExploded((IAssemblyDoc)model, true, explodeName);
        evidence["routeProfilesBeforeRebuild"] = ReadRouteProfiles().Select(row =>
            row.Key + ":" + row.Value.Item1 + ":" + row.Value.Item2).ToArray();
        Rebuild();
        var persisted = ReadRouteProfiles();
        evidence["routeProfilesAfterReopen"] = persisted.Select(row =>
            row.Key + ":" + row.Value.Item1 + ":" + row.Value.Item2).ToArray();
        int persistStatus = -1;
        var reopenedSegment = routeIdentity == null ? null :
            model.Extension.GetObjectByPersistReference3(routeIdentity, out persistStatus) as ISketchSegment;
        evidence["routePersistReferenceStatus"] = persistStatus;
        evidence["routePersistSegmentResolved"] = reopenedSegment != null;
        if (created.Count == 0)
            created = persisted.Where(row => !prior.ContainsKey(row.Key) && row.Value.Item2 > 0)
                .ToDictionary(row => row.Key, row => row.Value);
        if (created.Count != 1)
            throw new InvalidOperationException("Expected exactly one new persisted native explode-line feature.");
        var profile = created.Single();
        if (!persisted.ContainsKey(profile.Key) || !persisted[profile.Key].Equals(profile.Value))
            throw new InvalidOperationException("The native route sketch did not persist after reopen.");
        var feature = RouteFeatures().Single(f => f.Name == profile.Key && f.GetTypeName2() == profile.Value.Item1);
        evidence["nativeRouteSketch"] = new Hashtable { {"name", profile.Key},
            {"type", profile.Value.Item1}, {"segments", profile.Value.Item2} };
        model.ClearSelection2(true);
        Selected(feature.Select2(false, 0));
        evidence["stage"] = "route_edit_readback";
        Track("EditNativeRouteSketch", () => model.EditSketch());
        var reopenedSketch = model.GetActiveSketch2() as ISketch;
        bool editable = reopenedSketch != null && RouteSegmentCount(reopenedSketch) == profile.Value.Item2;
        if (reopenedSketch != null)
            Track("ExitReopenedExplodeLineSketch", () => model.SketchManager.InsertExplodeLineSketch());
        if (!editable || model.GetActiveSketch2() != null)
            throw new InvalidOperationException("Could not edit and exit the saved native route sketch.");
        evidence["routeEditable"] = true;
        evidence["reopenedAssembly"] = new Hashtable { {"verified", true}, {"nativeRouteSketch", evidence["nativeRouteSketch"]} };
        SetExploded((IAssemblyDoc)model, false, explodeName);
        evidence["routeFoldedAfterReopen"] = !model.IsExploded();
        CloseModel(model);
    }

    private object RouteEndpoint(IComponent2 component, double diameter, bool edge, bool high, string source, IList evidenceRows)
    {
        var local = PartCylinder(component, diameter);
        object partEntity = edge ? (object)RouteEndEdge(local, high) : local;
        object picked;
        string selection = source;
        if (source == "body")
        {
            var face = (IFace2)ComponentCylinder(component, diameter);
            picked = edge ? (object)RouteEndEdge(face, high) : face;
        }
        else if (source == "corresponding")
            picked = Track("GetCorrespondingEntity", () => component.GetCorrespondingEntity(partEntity));
        else if (source == "selection")
            picked = RouteSelectionWitness(component, local, edge, high, out selection);
        else
            throw new InvalidDataException("Unsupported explode-line entity source.");
        var entity = picked as IEntity;
        var actual = entity == null ? null : entity.GetComponent() as IComponent2;
        var row = new Hashtable { {"source", source}, {"selection", selection},
            {"expectedInstance", component.Name2}, {"partName", Path.GetFileName(component.GetPathName())},
            {"expectedKind", edge ? "circular_edge" : "cylindrical_face"},
            {"asEdge", picked is IEdge}, {"asFace", picked is IFace2},
            {"comType", picked == null ? null : picked.GetType().FullName},
            {"reportedInstance", actual == null ? null : actual.Name2},
            {"contextMatches", actual != null && actual.Name2 == component.Name2} };
        evidenceRows.Add(row);
        if (picked == null || (edge ? !(picked is IEdge) : !(picked is IFace2)))
            throw new InvalidOperationException("Could not resolve the requested route entity kind.");
        return picked;
    }

    private object RouteSelectionWitness(IComponent2 component, IFace2 local, bool edge, bool high, out string selection)
    {
        var circle = (ICurve)RouteEndEdge(local, high).GetCurve();
        var v = Vector(circle.CircleParams);
        double z = edge ? v[2] : (v[2] + Vector(((ICurve)RouteEndEdge(local, !high).GetCurve()).CircleParams)[2]) / 2;
        var xform = component.GetTotalTransform(true);
        var utility = (IMathUtility)app.GetMathUtility();
        var selected = (ISelectionMgr)model.SelectionManager;
        for (int quarter = 0; quarter < 4; quarter++)
        {
            var point = (IMathPoint)utility.CreatePoint(new[] {v[0] + v[6]*Math.Cos(quarter*Math.PI/2),
                v[1] + v[6]*Math.Sin(quarter*Math.PI/2), z});
            var p = Vector(((IMathPoint)point.MultiplyTransform(xform)).ArrayData);
            model.ClearSelection2(true);
            if (!Track("RouteSelectByID2", () => model.Extension.SelectByID2("", edge ? "EDGE" : "FACE",
                    p[0], p[1], p[2], false, 0, null, 0))) continue;
            var owner = selected.GetSelectedObjectsComponent4(1, -1) as IComponent2;
            var item = Track("RouteGetSelectedObject6", () => selected.GetSelectedObject6(1, -1));
            model.ClearSelection2(true);
            if (owner != null && owner.Name2 == component.Name2 &&
                (edge ? item is IEdge && ((ICurve)((IEdge)item).GetCurve()).IsCircle() :
                        item is IFace2 && ((ISurface)((IFace2)item).GetSurface()).IsCylinder()))
            {
                selection = "SelectByID2/GetSelectedObject6";
                return item;
            }
        }

        model.ClearSelection2(true);
        object localEntity = edge ? (object)RouteEndEdge(local, high) : local;
        var contextual = component.GetCorrespondingEntity(localEntity) as IEntity;
        if (contextual == null || !Track("RouteEntitySelect4", () => contextual.Select4(false, null)))
        {
            selection = "SelectByID2_failed";
            return null;
        }
        var trackedOwner = selected.GetSelectedObjectsComponent4(1, -1) as IComponent2;
        var result = Track("RouteGetSelectedObject6", () => selected.GetSelectedObject6(1, -1));
        model.ClearSelection2(true);
        selection = "Select4/GetSelectedObject6";
        return trackedOwner != null && trackedOwner.Name2 == component.Name2 ? result : null;
    }

    private static IFace2 PartCylinder(IComponent2 component, double diameter)
    {
        var part = component.GetModelDoc2() as IPartDoc;
        return Items(part.GetBodies2(0, false)).OfType<IBody2>()
            .SelectMany(body => Items(body.GetFaces()).OfType<IFace2>()).Single(face => {
                var surface = (ISurface)face.GetSurface();
                if (!surface.IsCylinder()) return false;
                var values = Vector(surface.CylinderParams);
                return Close(Mm(values[6] * 2), diameter) && Close(Mm(values[0]), 0) && Close(Mm(values[1]), 0);
            });
    }

    private static Array PackRouteEntities(object a, object b, string kind, string packing)
    {
        if (packing == "dispatch") return new DispatchWrapper[] { new DispatchWrapper(a), new DispatchWrapper(b) };
        if (packing == "variant" || kind == "mixed") return new object[] { a, b };
        if (kind == "edges") return new Edge[] { (Edge)a, (Edge)b };
        return new Face2[] { (Face2)a, (Face2)b };
    }

    private static IEdge RouteEndEdge(IFace2 face, bool high)
    {
        return Items(face.GetEdges()).OfType<IEdge>()
            .Where(edge => ((ICurve)edge.GetCurve()).IsCircle())
            .OrderBy(edge => Vector(((ICurve)edge.GetCurve()).CircleParams)[2] * (high ? -1 : 1)).First();
    }

    private static int RouteSegmentCount(ISketch sketch)
    {
        var rows = sketch.GetSketchSegments() as Array;
        return rows == null ? 0 : rows.Length;
    }

    private IEnumerable<IFeature> RouteFeatures()
    {
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var stack = new Stack<IFeature>(Features().Reverse());
        var all = model.FeatureManager.GetFeatures(false) as Array;
        if (all != null)
            foreach (var feature in all.OfType<IFeature>()) stack.Push(feature);
        var assembly = (IAssemblyDoc)model;
        foreach (string name in new[] { "3DExplode1", "3D爆炸1", "3D爆炸线1", "3D Explode1" })
        {
            var candidate = assembly.FeatureByName(name) as IFeature;
            if (candidate != null) stack.Push(candidate);
        }

        while (stack.Count != 0)
        {
            var feature = stack.Pop();
            if (!seen.Add(feature.GetTypeName2() + "/" + feature.Name)) continue;
            yield return feature;
            for (var sub = feature.GetFirstSubFeature() as IFeature; sub != null; sub = sub.GetNextSubFeature() as IFeature)
                stack.Push(sub);
        }
    }

    private Dictionary<string, Tuple<string,int>> ReadRouteProfiles()
    {
        var result = new Dictionary<string, Tuple<string,int>>();
        foreach (var feature in RouteFeatures())
        {
            string type = feature.GetTypeName2();
            var sketch = feature.GetSpecificFeature2() as ISketch;
            if (sketch != null && sketch.Is3D())
                result[feature.Name] = Tuple.Create(type, RouteSegmentCount(sketch));
        }
        return result;
    }
}
