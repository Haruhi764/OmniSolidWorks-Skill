using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using SolidWorks.Interop.sldworks;

public sealed partial class V03Native
{
    private sealed class BalloonPlacement
    {
        public IAnnotation Annotation;
        public double[] Anchor;
        public double[] Head;
    }

    private void BalanceNativeBalloons(SheetPlan plan, IView iso, IView side)
    {
        evidence["stage"] = "balance_native_balloon_leaders";
        var box = Vector(iso.GetOutline());
        var sideBox = Vector(side.GetOutline());
        var balloons = new List<BalloonPlacement>();
        foreach (var annotation in Items(iso.GetAnnotations()).OfType<IAnnotation>())
        {
            var note = annotation.GetSpecificAnnotation() as INote;
            if (note == null || !note.IsBomBalloon()) continue;
            double[] head = Vector(annotation.GetPosition());
            var raw = annotation.GetLeaderPointsAtIndex(0) as Array;
            if (raw == null || raw.Length < 6 || raw.Length % 3 != 0)
            {
                evidence["balloonOptimization"] = "native_leader_points_unavailable";
                return;
            }
            double[] points = Vector(raw);
            var anchor = Enumerable.Range(0, points.Length / 3).Select(i => new[] {points[3*i], points[3*i+1]})
                .Where(p => p[0] >= box[0] - M(3) && p[0] <= box[2] + M(3) &&
                            p[1] >= box[1] - M(3) && p[1] <= box[3] + M(3))
                .OrderByDescending(p => SquareDistance(p, head)).FirstOrDefault();
            if (anchor == null)
            {
                evidence["balloonOptimization"] = "native_anchor_outside_view";
                return;
            }
            balloons.Add(new BalloonPlacement {Annotation = annotation, Head = head, Anchor = anchor});
        }
        if (balloons.Count < 2) return;
        balloons = balloons.OrderBy(b => b.Anchor[0]).ThenByDescending(b => b.Anchor[1]).ToList();
        double[] originalX = balloons.Select(row => row.Head[0]).ToArray();
        double[] originalY = balloons.Select(row => row.Head[1]).ToArray();
        double[][] anchors = balloons.Select(row => row.Anchor).ToArray();
        int initial = CountLeaderCrossings(anchors, originalX, originalY);
        evidence["baselineLeaderCrossings"] = initial;
        double left = Math.Max(sideBox[2] + M(10), box[0] - M(17));
        double right = Math.Min(plan.Width - M(15), box[2] + M(22));
        double bottom = Math.Max(plan.Height * .47, box[1] - M(20));
        double top = Math.Min(plan.Height - M(17), box[3] + M(20));
        if (left > box[0] - M(6) || right < box[2] + M(6))
        {
            evidence["balloonOptimization"] = "reserved_lanes_too_narrow";
            return;
        }
        int chosenCrossings = int.MaxValue, chosenSplit = 0;
        double bestLength = double.PositiveInfinity;
        double[] chosenX = null, chosenY = null;
        int minSplit = Math.Max(1, balloons.Count / 4);
        for (int split = minSplit; split <= balloons.Count - minSplit; split++)
        {
            var x = new double[balloons.Count];
            var y = new double[balloons.Count];
            if (!BuildLane(anchors, x, y, 0, split, left, bottom, top) ||
                !BuildLane(anchors, x, y, split, balloons.Count, right, bottom, top)) continue;
            int crossings = CountLeaderCrossings(anchors, x, y);
            double length = Enumerable.Range(0, x.Length).Sum(i =>
                Math.Sqrt(SquareDistance(anchors[i], new[] { x[i], y[i] })));
            if (crossings > chosenCrossings || (crossings == chosenCrossings && length >= bestLength)) continue;
            chosenCrossings = crossings;
            bestLength = length;
            chosenX = x;
            chosenY = y;
            chosenSplit = split;
        }
        if (chosenX == null || chosenCrossings > initial)
        {
            evidence["balloonOptimization"] = "no_safe_bilateral_layout";
            return;
        }
        for (int i = 0; i < balloons.Count; i++)
            if (!Track("RepositionNativeBalloon", () => balloons[i].Annotation.SetPosition(chosenX[i], chosenY[i], balloons[i].Head[2])))
                throw new InvalidOperationException("A native balloon did not move to its reserved lane.");
        double[][] actual = balloons.Select(row => Vector(row.Annotation.GetPosition())).ToArray();
        int after = CountLeaderCrossings(anchors, actual.Select(p => p[0]).ToArray(),
            actual.Select(p => p[1]).ToArray());
        if (after > initial)
            throw new InvalidOperationException("Native readback shows additional leader crossings.");
        evidence["candidateLeaderCrossings"] = after;
        evidence["balloonLanes"] = new[] { chosenSplit, balloons.Count - chosenSplit };
        evidence["balloonOptimization"] = "bilateral_native_anchor_chords";
    }

    private static bool BuildLane(double[][] anchors, double[] x, double[] y, int begin, int end,
        double position, double bottom, double top)
    {
        var order = Enumerable.Range(begin, end - begin).OrderByDescending(i => anchors[i][1]).ToArray();
        double interval = Math.Min(.016, (top - bottom) / Math.Max(1, order.Length - 1));
        if (interval < .008) return false;
        double center = (top + bottom) / 2;
        for (int i = 0; i < order.Length; i++)
        {
            x[order[i]] = position;
            y[order[i]] = center + interval * ((order.Length - 1) / 2.0 - i);
        }
        return true;
    }

    private static double SquareDistance(double[] a, double[] b)
    {
        return Math.Pow(a[0] - b[0], 2) + Math.Pow(a[1] - b[1], 2);
    }

    public static int CountLeaderCrossings(double[][] anchors, double[] x, double[] y)
    {
        int crossings = 0;
        for (int first = 0; first < anchors.Length; first++)
            for (int second = first + 1; second < anchors.Length; second++)
            {
                var a = anchors[first];
                var b = new[] { x[first], y[first] };
                var c = anchors[second];
                var d = new[] { x[second], y[second] };
                if (StrictOppositeSides(a, b, c, d) && StrictOppositeSides(c, d, a, b)) crossings++;
            }
        return crossings;
    }

    private static bool StrictOppositeSides(double[] a, double[] b, double[] c, double[] d)
    {
        double first = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
        double second = (b[0] - a[0]) * (d[1] - a[1]) - (b[1] - a[1]) * (d[0] - a[0]);
        return first > 1e-10 && second < -1e-10 || first < -1e-10 && second > 1e-10;
    }
}

