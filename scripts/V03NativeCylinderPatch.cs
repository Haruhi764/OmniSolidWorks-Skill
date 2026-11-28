using System;
using System.Collections.Generic;
using System.Linq;

public sealed class V03CylinderPatch
{
    public const double AngularTolerance = 1e-5;
    private const double Period = 2 * Math.PI;
    public readonly double X, Y, Radius, Low, High, Start, Sweep;
    public readonly bool Rectangular;

    public V03CylinderPatch(double x, double y, double radius, double z1, double z2,
        double start, double sweep, double area)
    {
        X = x; Y = y; Radius = radius; Low = Math.Min(z1, z2); High = Math.Max(z1, z2);
        Start = (start % Period + Period) % Period;
        Sweep = sweep;
        double expectedArea = radius * sweep * (High - Low);
        // UV bounds also enclose arbitrary trims. The face must fill that cylindrical rectangle.
        Rectangular = radius > 0 && High > Low && sweep > AngularTolerance &&
            sweep <= Period + AngularTolerance && Math.Abs(expectedArea - area) <= Math.Max(1e-9, expectedArea * 1e-5);
    }

    public bool Matches(double x, double y, double diameter, double lo, double hi, double tolerance)
    {
        return Rectangular && Math.Abs(X - x) <= tolerance && Math.Abs(Y - y) <= tolerance &&
            Math.Abs(2 * Radius - diameter) <= tolerance && Math.Abs(Low - lo) <= tolerance && Math.Abs(High - hi) <= tolerance;
    }

    public static bool IsComplete(V03CylinderPatch[] patches, Func<int, int, bool> sharedSeam)
    {
        if (patches.Length == 0 || patches.Any(patch => !patch.Rectangular) ||
            Math.Abs(patches.Sum(patch => patch.Sweep) - Period) > AngularTolerance)
            return false;

        // Each patch must lie on the same analytical cylinder, independent of the job's dimensional tolerance.
        const double seamToleranceMm = 1e-5;
        var first = patches[0];
        if (patches.Any(patch => !patch.Matches(first.X, first.Y, 2 * first.Radius, first.Low, first.High, seamToleranceMm)))
            return false;

        var intervals = new List<Tuple<double, double>>();
        foreach (var patch in patches)
        {
            double end = patch.Start + patch.Sweep;
            intervals.Add(Tuple.Create(patch.Start, Math.Min(end, Period)));
            if (end > Period) intervals.Add(Tuple.Create(0.0, end - Period));
        }
        double covered = 0;
        foreach (var span in intervals.OrderBy(span => span.Item1))
        {
            if (Math.Abs(span.Item1 - covered) > AngularTolerance) return false;
            covered = Math.Max(covered, span.Item2);
        }
        if (Math.Abs(covered - Period) > AngularTolerance) return false;

        // A geometric match alone cannot join independently trimmed faces.
        var pending = new Queue<int>();
        var visited = new HashSet<int> { 0 };
        pending.Enqueue(0);
        while (pending.Count != 0)
        {
            int index = pending.Dequeue();
            for (int next = 0; next < patches.Length; next++)
                if (!visited.Contains(next) && sharedSeam(index, next))
                {
                    visited.Add(next);
                    pending.Enqueue(next);
                }
        }
        return visited.Count == patches.Length;
    }
}