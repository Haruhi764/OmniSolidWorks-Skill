param(
    [Parameter(Mandatory)][int]$RevisionMajor,
    [Parameter(Mandatory)][string]$InstallDirectory,
    [Parameter(Mandatory)][string]$Directory
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$pia = Join-Path $InstallDirectory 'SolidWorks.Interop.sldworks.dll'
$exe = (Get-Item -LiteralPath (Join-Path $InstallDirectory 'SLDWORKS.exe')).FullName
$files = @(Get-ChildItem -LiteralPath $Directory -Recurse -File |
    Where-Object Extension -in '.SLDPRT','.SLDASM','.SLDDRW')
if ($files.Count -eq 0 -or $files.Count -gt 1000) { throw 'Expected 1 to 1000 native input files.' }
if (@($files | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) {
    throw 'Reference list contains a reparse point.'
}
[void][Reflection.Assembly]::LoadFrom($pia)
Add-Type -ReferencedAssemblies $pia -TypeDefinition @"
using System;
using System.Collections;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;

public static class SwFileVersions
{
    public static Hashtable Read(int major, string executable, string[] files)
    {
        var app = (ISldWorks)Marshal.GetActiveObject("SldWorks.Application." + major);
        int pid = app.GetProcessID();
        string revision = app.RevisionNumber();
        using (var process = Process.GetProcessById(pid))
            if (!revision.StartsWith(major + ".") ||
                !String.Equals(process.MainModule.FileName, executable, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Unexpected SolidWorks revision or executable.");
        var rows = new ArrayList();
        int before = app.GetDocumentCount();
        foreach (string path in files)
        {
            var row = new Hashtable { {"name", Path.GetFileName(path)}, {"type", Path.GetExtension(path)} };
            try { row["history"] = app.VersionHistory(path); }
            catch (COMException error) { row["hresult"] = "0x" + error.ErrorCode.ToString("X8"); }
            rows.Add(row);
        }
        return new Hashtable { {"revision", revision}, {"pid", pid}, {"files", rows},
            {"documentsBefore", before}, {"documentsAfter", app.GetDocumentCount()} };
    }
}
"@
[SwFileVersions]::Read($RevisionMajor, $exe, [string[]]$files.FullName) |
    ConvertTo-Json -Depth 8
