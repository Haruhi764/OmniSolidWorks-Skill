using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using SolidWorks.Interop.sldworks;

public static class V03NativeHost
{
    [DllImport("ole32.dll")]
    private static extern int CreateBindCtx(uint reserved, out IBindCtx context);

    public static ISldWorks Attach(int revision, int targetPid)
    {
        if (targetPid == 0)
            return (ISldWorks)Marshal.GetActiveObject("SldWorks.Application." + revision);
        string identity = "SolidWorks_PID_" + targetPid;
        IBindCtx context = null;
        IRunningObjectTable table = null;
        IEnumMoniker cursor = null;
        try
        {
            Marshal.ThrowExceptionForHR(CreateBindCtx(0, out context));
            context.GetRunningObjectTable(out table);
            table.EnumRunning(out cursor);
            var row = new IMoniker[1];
            while (cursor.Next(1, row, IntPtr.Zero) == 0)
            {
                var moniker = row[0];
                try
                {
                    string name;
                    try { moniker.GetDisplayName(context, null, out name); }
                    catch (UnauthorizedAccessException) { continue; }
                    catch (COMException) { continue; }
                    if (!String.Equals(name.TrimStart('!'), identity, StringComparison.OrdinalIgnoreCase)) continue;
                    object value;
                    table.GetObject(moniker, out value);
                    var app = value as ISldWorks;
                    if (app != null && app.GetProcessID() == targetPid &&
                        app.RevisionNumber().StartsWith(revision + ".", StringComparison.Ordinal))
                        return app;
                    if (value != null && Marshal.IsComObject(value)) Marshal.ReleaseComObject(value);
                    throw new InvalidOperationException("The ROT entry did not identify the requested SolidWorks process.");
                }
                finally
                {
                    row[0] = null;
                    Marshal.ReleaseComObject(moniker);
                }
            }
        }
        finally
        {
            if (cursor != null) Marshal.ReleaseComObject(cursor);
            if (table != null) Marshal.ReleaseComObject(table);
            if (context != null) Marshal.ReleaseComObject(context);
        }

        // Legacy hosts can register only the version-specific active object.
        var legacy = (ISldWorks)Marshal.GetActiveObject("SldWorks.Application." + revision);
        if (legacy.GetProcessID() == targetPid) return legacy;
        Marshal.ReleaseComObject(legacy);
        throw new InvalidOperationException("The requested SolidWorks process has no matching accessible ROT entry.");
    }

    public static void ExitEmptyOwnedHost(int revision, int pid, long startUtcTicks, string executable)
    {
        using (var process = Process.GetProcessById(pid))
            if (process.StartTime.ToUniversalTime().Ticks != startUtcTicks ||
                !String.Equals(process.MainModule.FileName, executable, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("The owned SolidWorks process identity changed.");
        var app = Attach(revision, pid);
        if (app.GetProcessID() != pid || app.GetDocumentCount() != 0)
            throw new InvalidOperationException("The owned SolidWorks process is not empty.");
        app.ExitApp();
    }

    public static string[] Probe(int revision, int targetPid)
    {
        var app = Attach(revision, targetPid);
        try
        {
            return new[] { app.RevisionNumber(), app.GetProcessID().ToString(), app.GetDocumentCount().ToString(),
                app.GetCurrentLanguage() };
        }
        finally { Marshal.ReleaseComObject(app); }
    }
}
