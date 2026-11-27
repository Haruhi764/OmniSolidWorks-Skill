param(
    [int]$RevisionMajor,
    [string]$InstallDirectory,
    [string]$Template,
    [string]$RunDirectory,
    [int]$TargetPid = 0
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$outputRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\outputs')).TrimEnd('\') + '\'
$run = (Get-Item -LiteralPath $RunDirectory).FullName
if (-not $run.StartsWith($outputRoot, [StringComparison]::OrdinalIgnoreCase) -or
    $run.Substring($outputRoot.Length) -notmatch '^(?:v0\.(?:3|4(?:\.1)?)\\jobs\\[A-Za-z][A-Za-z0-9_-]*\\run-[a-z0-9-]+|incremental\\run-[a-z0-9-]+\\[a-z0-9-]+\\partial\\attempt-[0-9]+)$') {
    throw 'Run directory is outside the versioned job roots.'
}
$request = Join-Path $run 'normalized.json'
$jobFile = Get-Item -LiteralPath $request -Force
if ($jobFile.PSIsContainer -or $jobFile.Length -gt 4MB -or
    ($jobFile.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Invalid normalized job file.' }
for ($ancestor = $run; $ancestor; $ancestor = [IO.Path]::GetDirectoryName($ancestor)) {
    if ((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'Redirected native job path.'
    }
}
$destination = Join-Path $run 'native.json'
if (Test-Path -LiteralPath $destination) { throw 'This run already has native evidence.' }
$pia = Join-Path $InstallDirectory 'SolidWorks.Interop.sldworks.dll'
$exe = (Get-Item -LiteralPath (Join-Path $InstallDirectory 'SLDWORKS.exe')).FullName
$report = [ordered]@{status='FAIL'; stage='compile'; transport='SolidWorks installed PIA'; utc=[DateTimeOffset]::UtcNow.ToString('o')}
$clock = [Diagnostics.Stopwatch]::StartNew()
$mutex = [Threading.Mutex]::new($false, 'Local\SolidWorksMechanicalNativePartJob')
$owned = $false
try {
    try { $owned = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] {
        $owned = $true
        throw 'A prior native command ended unexpectedly. Check the SolidWorks session before retrying.'
    }
    if (-not $owned) { throw 'Another project CAD operation is active.' }
    if ([Threading.Thread]::CurrentThread.GetApartmentState() -ne 'STA') { throw 'The PIA bridge requires Windows PowerShell STA.' }
    [void][Reflection.Assembly]::LoadFrom($pia)
    $sources = @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter 'V03Native*.cs' -File | Select-Object -ExpandProperty FullName)
    Add-Type -Path $sources -ReferencedAssemblies $pia,'System.Core.dll','System.Web.Extensions.dll'
    if ([Diagnostics.FileVersionInfo]::GetVersionInfo($exe).FileMajorPart -ne $RevisionMajor) { throw 'Executable release mismatch.' }
    if ($TargetPid -gt 0) {
        $report.streamProgress = $true
        [V03Native]::Run($RevisionMajor, $exe, $Template, $run, $request, $report, $TargetPid)
    } else {
        [V03Native]::Run($RevisionMajor, $exe, $Template, $run, $request, $report)
    }
    $report.status = 'PASS'
} catch {
    $failure = $_.Exception.GetBaseException()
    $report.error = $failure.Message
    $report.hresult = '0x{0:X8}' -f $failure.HResult
    if ($report.stage -eq 'attach') { $report.status = 'BLOCKED' }
} finally {
    $report.nativeSeconds = [Math]::Round($clock.Elapsed.TotalSeconds, 3)
    if ($owned) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
    $json = $report | ConvertTo-Json -Depth 30
    $buffer = [Text.UTF8Encoding]::new($false).GetBytes($json)
    $tempEvidence = $destination + '.writing'
    $file = [IO.File]::Open($tempEvidence, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    try { $file.Write($buffer, 0, $buffer.Length); $file.Flush($true) } finally { $file.Dispose() }
    [IO.File]::Move($tempEvidence, $destination)
    [ordered]@{status=$report.status; stage=$report.stage; error=$report.error} | ConvertTo-Json -Compress
}
if ($report.status -ne 'PASS') { exit 1 }
