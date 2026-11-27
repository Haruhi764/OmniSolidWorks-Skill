param(
    [Parameter(Mandatory=$true)][string]$InstallDirectory,
    [Parameter(Mandatory=$true)][string]$PartTemplate,
    [Parameter(Mandatory=$true)][int]$RevisionMajor,
    [Parameter(Mandatory=$true)][string]$OutputRoot
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if ([Threading.Thread]::CurrentThread.GetApartmentState() -ne 'STA') {
    throw 'Run this diagnostic in Windows PowerShell with -Sta.'
}

$interop = Join-Path $InstallDirectory 'SolidWorks.Interop.sldworks.dll'
$executable = Join-Path $InstallDirectory 'SLDWORKS.exe'
$runFolder = Join-Path $OutputRoot ('native-smoke-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8))
[void](New-Item -ItemType Directory -Path $runFolder)
$evidence = [ordered]@{
    startedAt = [DateTimeOffset]::Now.ToString('o')
    transport = 'Windows PowerShell STA / installed SolidWorks PIA'
    expectedRevisionMajor = $RevisionMajor
    targetExecutable = [IO.Path]::GetFullPath($executable)
    completed = $false
}

$source = @'
using System;
using System.Collections;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;

public static class NativeSmoke
{
    private const string FeatureName = "Cylinder Extrusion";

    public static void Run(int major, string executable, string fallbackTemplate, string output, IDictionary evidence)
    {
        string progId = "SldWorks.Application." + major;
        evidence["progId"] = progId;
        evidence["stage"] = "bind_instance";
        Process[] processes = Process.GetProcessesByName("SLDWORKS");
        if (processes.Length != 1)
            throw new InvalidOperationException("The diagnostic requires one running SolidWorks process.");
        int pid = processes[0].Id;
        if (!String.Equals(processes[0].MainModule.FileName, executable, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("The running SolidWorks process does not match the requested installation.");
        var app = (ISldWorks)Marshal.GetActiveObject(progId);
        string revision = app.RevisionNumber();
        evidence["revision"] = revision;
        evidence["pid"] = app.GetProcessID();
        if (app.GetProcessID() != pid || !revision.StartsWith(major + ".", StringComparison.Ordinal))
            throw new InvalidOperationException("The attached COM instance did not match the requested process and release.");

        string defaultPart = app.GetUserPreferenceStringValue(8);
        evidence["defaultTemplates"] = new Hashtable {
            {"part", defaultPart}, {"assembly", app.GetUserPreferenceStringValue(9)}, {"drawing", app.GetUserPreferenceStringValue(10)}
        };
        string template = File.Exists(defaultPart) ? defaultPart : fallbackTemplate;
        evidence["partTemplate"] = template;
        if (!File.Exists(template) || !String.Equals(Path.GetExtension(template), ".prtdot", StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("A readable part template is required.");
        int initialCount = app.GetDocumentCount();
        evidence["documentCountBefore"] = initialCount;
        string outputFile = Path.Combine(output, "Cylinder.SLDPRT");
        string ownedTitle = null;
        try
        {
            evidence["stage"] = "create_part";
            var model = (IModelDoc2)app.NewDocument(template, 0, 0.0, 0.0);
            if (model == null)
                throw new InvalidOperationException("NewDocument returned null. Check the license and part template.");
            ownedTitle = model.GetTitle();
            RequireActive(app, model, null);
            var existingBodies = ((IPartDoc)model).GetBodies2(0, false) as Array;
            if (model.GetType() != 1 || (existingBodies != null && existingBodies.Length != 0))
                throw new InvalidOperationException("The new document is not an empty part.");
            evidence["documentUnits"] = model.GetUnits();
            evidence["stage"] = "build_cylinder";
            if (!FindFeature(model, "RefPlane", null).Select2(false, 0))
                throw new InvalidOperationException("The sketch plane could not be selected.");
            model.SketchManager.InsertSketch(true);
            if (model.SketchManager.ActiveSketch == null || model.SketchManager.CreateCircleByRadius(0, 0, 0, 0.010) == null)
                throw new InvalidOperationException("The cylinder sketch could not be created.");
            model.SketchManager.InsertSketch(true);
            model.ClearSelection2(true);
            if (!FindFeature(model, "ProfileFeature", null).Select2(false, 0))
                throw new InvalidOperationException("The cylinder sketch could not be selected.");
            IFeature feature = model.FeatureManager.FeatureExtrusion3(
                true, false, false, 0, 0, 0.010, 0.0, false, false, false, false, 0.0, 0.0,
                false, false, false, false, true, true, true, 0, 0.0, false);
            if (feature == null)
                throw new InvalidOperationException("FeatureExtrusion3 returned null.");
            feature.Name = FeatureName;
            evidence["beforeSave"] = Measure(model);

            evidence["stage"] = "save_part";
            RequireActive(app, model, null);
            model.ClearSelection2(true);
            int saveErrors = 0;
            int saveWarnings = 0;
            if (File.Exists(outputFile))
                throw new IOException("The target file already exists.");
            bool saved = model.Extension.SaveAs(outputFile, 0, 1, null, ref saveErrors, ref saveWarnings);
            evidence["save"] = new Hashtable { {"ok", saved}, {"errors", saveErrors}, {"warnings", saveWarnings} };
            ownedTitle = model.GetTitle();
            if (!saved || saveErrors != 0 || saveWarnings != 0 || !File.Exists(outputFile))
                throw new IOException("SolidWorks did not return a clean native save.");
            RequireActive(app, model, outputFile);
            evidence["outputFile"] = outputFile;

            evidence["stage"] = "close_before_reopen";
            app.CloseDoc(ownedTitle);
            ownedTitle = null;
            if (app.GetOpenDocumentByName(outputFile) != null || app.GetDocumentCount() != initialCount)
                throw new InvalidOperationException("The saved test part did not close.");
            evidence["closedBeforeReopen"] = true;

            evidence["stage"] = "reopen_and_measure";
            int openErrors = 0;
            int openWarnings = 0;
            var reopened = (IModelDoc2)app.OpenDoc6(outputFile, 1, 3, "", ref openErrors, ref openWarnings);
            evidence["open"] = new Hashtable { {"loaded", reopened != null}, {"errors", openErrors}, {"warnings", openWarnings} };
            if (reopened != null)
                ownedTitle = reopened.GetTitle();
            if (reopened == null || openErrors != 0 || openWarnings != 0)
                throw new IOException("SolidWorks did not return a clean native reopen.");
            RequireActive(app, reopened, outputFile);
            evidence["afterReopen"] = Measure(reopened);
        }
        finally
        {
            if (ownedTitle != null)
                app.CloseDoc(ownedTitle);
            evidence["documentCountAfter"] = app.GetDocumentCount();
        }
        if (app.GetOpenDocumentByName(outputFile) != null || app.GetDocumentCount() != initialCount)
            throw new InvalidOperationException("The diagnostic did not restore the original document count.");
        evidence["stage"] = "complete";
    }

    private static void RequireActive(ISldWorks app, IModelDoc2 model, string path)
    {
        if (!Object.ReferenceEquals(app.ActiveDoc, model))
            throw new InvalidOperationException("The job document is not active.");
        if (path != null && !String.Equals(model.GetPathName(), path, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("The active document has an unexpected path.");
    }

    private static IFeature FindFeature(IModelDoc2 model, string type, string name)
    {
        for (var candidate = model.FirstFeature() as IFeature; candidate != null; candidate = candidate.GetNextFeature() as IFeature)
            if ((type == null || candidate.GetTypeName2() == type) && (name == null || candidate.Name == name))
                return candidate;
        throw new InvalidOperationException("Required feature missing: " + (name ?? type));
    }

    private static IDictionary Measure(IModelDoc2 model)
    {
        if (!model.ForceRebuild3(false))
            throw new InvalidOperationException("ForceRebuild3 failed.");
        var feature = FindFeature(model, null, FeatureName);
        bool warning;
        int featureCode = feature.GetErrorCode2(out warning);
        var bodies = ((IPartDoc)model).GetBodies2(0, false) as Array;
        if (featureCode != 0 || bodies == null || bodies.Length != 1)
            throw new InvalidOperationException("Feature error or unexpected solid body count.");
        var body = (IBody2)bodies.GetValue(0);
        int bodyCode = body.Check2();
        var mass = model.Extension.CreateMassProperty();
        mass.UseSystemUnits = true;
        double measured = mass.Volume * 1e9;
        double expected = Math.PI * 10.0 * 10.0 * 10.0;
        if (bodyCode != 0 || Double.IsNaN(measured) || Math.Abs(measured - expected) > 1e-5)
            throw new InvalidOperationException("Body integrity or independently computed cylinder volume failed. Body check: " + bodyCode + ", volume: " + measured);
        return new Hashtable {
            {"bodyCount", bodies.Length}, {"bodyCheckCode", bodyCode}, {"featureType", feature.GetTypeName2()},
            {"featureErrorCode", featureCode}, {"volumeMm3", measured}, {"expectedVolumeMm3", expected}, {"rebuild", true}
        };
    }
}
'@

try {
    [void][Reflection.Assembly]::LoadFrom($interop)
    Add-Type -TypeDefinition $source -ReferencedAssemblies $interop
    [NativeSmoke]::Run($RevisionMajor, $evidence.targetExecutable, [IO.Path]::GetFullPath($PartTemplate), $runFolder, $evidence)
    $evidence.sha256 = (Get-FileHash -LiteralPath $evidence.outputFile -Algorithm SHA256).Hash.ToLowerInvariant()
    $evidence.fileBytes = (Get-Item -LiteralPath $evidence.outputFile).Length
    $evidence.completed = $true
} catch {
    $failure = $_.Exception.GetBaseException()
    $evidence.hresult = '0x{0:X8}' -f $failure.HResult
    $evidence.error = $failure.Message
} finally {
    $reportPath = Join-Path $runFolder 'report.json'
    $evidence | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding UTF8
    Write-Output $reportPath
    Get-Content -LiteralPath $reportPath
}

if (-not $evidence.completed) { exit 1 }
