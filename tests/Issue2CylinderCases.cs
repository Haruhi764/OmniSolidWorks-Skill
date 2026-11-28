using System;
using System.Linq;

public static class Issue2CylinderCases
{
    private static V03CylinderPatch Patch(double start, double sweep, double radius = 20,
        double low = 0, double high = 30, double x = 0, double areaFactor = 1)
    {
        return new V03CylinderPatch(x, 0, radius, low, high, start, sweep,
            radius * (high - low) * sweep * areaFactor);
    }

    private static void Check(string name, bool expected, bool seam, params V03CylinderPatch[] patches)
    {
        var matching = patches.Where(patch => patch.Matches(0, 0, 40, 0, 30, .003)).ToArray();
        if (V03CylinderPatch.IsComplete(matching, (a, b) => seam) != expected)
            throw new InvalidOperationException("Cylinder case failed: " + name);
        Console.WriteLine("PASS " + name);
    }

    public static void Run()
    {
        double half = Math.PI;
        var first = Patch(-.4, half);
        var second = Patch(half - .4, half);
        Check("single full face crossing the angular origin", true, false, Patch(.7, 2 * half));
        Check("two complementary faces with shared seam", true, true, first, second);
        Check("three complementary faces with shared seams", true, true,
            Patch(0, half / 2), Patch(half / 2, half / 2), Patch(half, half));
        Check("complementary faces without shared topology", false, false, first, second);
        Check("duplicate half faces with angular gap", false, true, first, first);
        Check("missing face", false, false, first);
        Check("missing cylinder", false, false);
        Check("wrong radius", false, false, Patch(.7, 2 * half, 19.99));
        Check("wrong axis center", false, true, first, Patch(half - .4, half, x: .01));
        Check("coaxial fragments at independent axial locations", false, true, first, Patch(half - .4, half, low: 30, high: 60));
        Check("stepped cylinder", false, true, first, Patch(half - .4, half, radius: 21));
        Check("mismatched radius within job tolerance", false, true, first, Patch(half - .4, half, radius: 20.0005));
        Check("trim missing surface inside UV bounds", false, true, first, Patch(half - .4, half, areaFactor: .95));
        Check("duplicate full cylinders", false, true, Patch(0, 2 * half), Patch(0, 2 * half));
        Check("independent full cylinder outside requested axial range", true, false,
            Patch(0, 2 * half), Patch(0, 2 * half, low: 35, high: 65));
    }
}