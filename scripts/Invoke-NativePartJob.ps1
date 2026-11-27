param(
    [Parameter(Mandatory=$true)][string]$InstallDirectory,
    [Parameter(Mandatory=$true)][string]$PartTemplate,
    [Parameter(Mandatory=$true)][int]$RevisionMajor,
    [Parameter(Mandatory=$true)][string]$OutputRoot,
    [Parameter(Mandatory=$true)][string]$Specification,
    [Parameter(Mandatory=$true)][ValidateSet('Shaft','Flange')][string]$Kind
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if ([Threading.Thread]::CurrentThread.GetApartmentState() -ne 'STA') {
    throw 'Run this diagnostic in Windows PowerShell with -Sta.'
}

$inputData = Get-Content -Raw -LiteralPath $Specification | ConvertFrom-Json
if ($inputData.schema_version -ne 1 -or $inputData.unit -ne 'mm') {
    throw 'Expected a version 1 specification in millimeters.'
}

if ($Kind -eq 'Shaft') {
    $segments = $inputData.shaft.segments
    if (@($segments).Count -ne 3) { throw 'The shaft requires three segments.' }
    $values = [double[]]@(foreach ($segment in $segments) { $segment.diameter; $segment.length })
    if ($values[0] -eq $values[2] -or $values[2] -eq $values[4]) {
        throw 'Adjacent shaft segments must have distinct diameters.'
    }
} else {
    $flange = $inputData.flange
    $values = [double[]]@($flange.outer_diameter, $flange.thickness, $flange.bore_diameter, $flange.bolt_diameter, $flange.bolt_count, $flange.pitch_circle_diameter)
    $outer, $thickness, $bore, $bolt, $count, $pitch = $values
    if ($count -lt 2 -or $count -gt 100 -or $count -ne [Math]::Floor($count) -or
        $pitch + $bolt -ge $outer -or $pitch - $bolt -le $bore -or
        $pitch * [Math]::Sin([Math]::PI / $count) -le $bolt) {
        throw 'Flange holes must be integer in count, lie within the blank, and remain mutually separated.'
    }
}
foreach ($value in $values) {
    if ([Double]::IsNaN($value) -or [Double]::IsInfinity($value) -or $value -le 0) {
        throw 'All part dimensions and counts must be finite and positive.'
    }
}

$template = (Get-Item -LiteralPath $PartTemplate).FullName
if ([IO.Path]::GetExtension($template) -ne '.prtdot') { throw 'A native part template is required.' }
$interop = Join-Path $InstallDirectory 'SolidWorks.Interop.sldworks.dll'
$executable = (Get-Item -LiteralPath (Join-Path $InstallDirectory 'SLDWORKS.exe')).FullName
if ([Diagnostics.FileVersionInfo]::GetVersionInfo($executable).FileMajorPart -ne $RevisionMajor) {
    throw 'The configured SolidWorks executable does not match the requested release.'
}

$folderName = $Kind.ToLowerInvariant() + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)
$runFolder = Join-Path $OutputRoot $folderName
[void](New-Item -ItemType Directory -Path $runFolder)
$report = [ordered]@{
    schemaVersion = 1
    startedAt = [DateTimeOffset]::Now.ToString('o')
    backend = 'Windows PowerShell STA / installed SolidWorks PIA'
    kind = $Kind
    inputs = $inputData.($Kind.ToLowerInvariant())
    completed = $false
}
$jobMutex = [Threading.Mutex]::new($false, 'Local\SolidWorksMechanicalNativePartJob')
$ownsMutex = $false

try {
    try {
        $ownsMutex = $jobMutex.WaitOne(0)
    } catch [Threading.AbandonedMutexException] {
        $ownsMutex = $true
        throw 'A previous COM job exited unexpectedly. Verify the SolidWorks session before retrying.'
    }
    if (-not $ownsMutex) { throw 'Another SolidWorks Mechanical job is in progress.' }
    [void][Reflection.Assembly]::LoadFrom($interop)
    Add-Type -Path (Join-Path $PSScriptRoot 'NativePartJob.cs') -ReferencedAssemblies $interop,'System.Core.dll'
    [NativePartJob]::Run($RevisionMajor, $executable, $template, $runFolder, $Kind, $values, $report)
    $report.artifacts = @(Get-ChildItem -LiteralPath $runFolder -File | ForEach-Object {
        $fileStream = [IO.File]::OpenRead($_.FullName)
        $sha256 = [Security.Cryptography.SHA256]::Create()
        try { $digest = [BitConverter]::ToString($sha256.ComputeHash($fileStream)).Replace('-', '').ToLowerInvariant() }
        finally { $sha256.Dispose(); $fileStream.Dispose() }
        @{ name = $_.Name; bytes = $_.Length; sha256 = $digest }
    })
    $report.completed = $true
} catch {
    $rootError = $_.Exception.GetBaseException()
    $report.hresult = '0x{0:X8}' -f $rootError.HResult
    $report.error = $rootError.Message
} finally {
    if ($ownsMutex) { $jobMutex.ReleaseMutex() }
    $jobMutex.Dispose()
    $reportPath = Join-Path $runFolder 'report.json'
    $report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $reportPath -Encoding UTF8
    Write-Output $reportPath
    [pscustomobject]@{ stage = $report.stage; completed = $report.completed; error = $report.error; hresult = $report.hresult } | ConvertTo-Json -Compress
}

if (-not $report.completed) { exit 1 }
