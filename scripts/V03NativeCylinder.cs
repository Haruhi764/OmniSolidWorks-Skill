using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using SolidWorks.Interop.sldworks;

public sealed partial class V03Native
{
    private ArrayList VerifyCylinders(IBody2 body, object expected)
    {
        var patches = new List<KeyValuePair<IFace2, V03CylinderPatch>>();
        foreach (IFace2 face in Items(body.GetFaces()).Cast<IFace2>())
        {
            var surface = (ISurface)face.GetSurface();
            if (!surface.IsCylinder()) continue;
            var axis = Vector(surface.CylinderParams);
            if (Math.Abs(axis[3]) > 1e-6 || Math.Abs(axis[4]) > 1e-6 || Math.Abs(axis[5]) < .999999)
                continue;
            double x = Mm(axis[0] - axis[2] * axis[3] / axis[5]);
            double y = Mm(axis[1] - axis[2] * axis[4] / axis[5]);
            double radius = Mm(axis[6]);
            double[] uv = Vector(face.GetUVBounds());
            double sweep = uv[1] - uv[0];
            double[] first = Vector(surface.Evaluate(uv[0], uv[2], 0, 0));
            double[] second = Vector(surface.Evaluate(uv[0] + sweep / 4, uv[2], 0, 0));
            double[] edge = Vector(surface.Evaluate(uv[0], uv[3], 0, 0));
            double start = Math.Atan2(Mm(first[1]) - y, Mm(first[0]) - x);
            double sample = Math.Atan2(Mm(second[1]) - y, Mm(second[0]) - x);
            double turn = Math.Atan2(Math.Sin(sample - start), Math.Cos(sample - start));
            if (Math.Abs(Math.Abs(turn) - sweep / 4) > V03CylinderPatch.AngularTolerance)
                continue;
            if (turn < 0) start -= sweep;
            var patch = new V03CylinderPatch(x, y, radius, Mm(first[2]), Mm(edge[2]), start, sweep, face.GetArea() * 1e6);
            if (patch.Rectangular) patches.Add(new KeyValuePair<IFace2, V03CylinderPatch>(face, patch));
        }

        var results = new ArrayList();
        foreach (IDictionary target in Items(expected))
        {
            double[] center = Vector(target["center"]), ends = Vector(target["z"]);
            double diameter = Number(target, "diameter");
            var matches = patches.Where(row => row.Value.Matches(center[0], center[1], diameter, ends[0], ends[1], DimensionTolerance)).ToArray();
            var cylinders = matches.Select(row => row.Value).ToArray();
            if (!V03CylinderPatch.IsComplete(cylinders, (a, b) => ShareCylinderSeam(matches[a].Key, matches[b].Key)))
                throw new InvalidOperationException("Did not find one continuous full circular boundary at " +
                    center[0] + ", " + center[1] + " (matching cylindrical faces: " + matches.Length + ").");
            var actual = cylinders[0];
            results.Add(new Hashtable { {"center", new[] { actual.X, actual.Y }}, {"diameter", 2 * actual.Radius},
                {"z", new[] { actual.Low, actual.High }}, {"faceCount", cylinders.Length},
                {"coverageRadians", cylinders.Sum(patch => patch.Sweep)} });
        }
        return results;
    }

    private static bool ShareCylinderSeam(IFace2 source, IFace2 other)
    {
        foreach (IEdge edge in Items(source.GetEdges()).Cast<IEdge>())
        {
            foreach (IFace2 neighbor in Items(edge.GetTwoAdjacentFaces2()).OfType<IFace2>())
                if (!source.IsSame(neighbor) && other.IsSame(neighbor)) return true;
        }
        return false;
    }
}