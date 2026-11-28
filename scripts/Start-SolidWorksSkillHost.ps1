param(
    [ValidateRange(5,90)][int]$TimeoutSeconds = 45,
    [string]$Python = 'python',
    [switch]$StartIfMissing
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$pythonCommand = Get-Command -Name $Python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $pythonCommand) { throw 'Python was not found. Set -Python to a Windows x64 Python 3.12+ executable.' }
$pythonExe = $pythonCommand.Source
$pythonVersion = & $pythonExe -B -c 'import sys; print(sys.version.split()[0]); sys.exit(0 if sys.version_info >= (3, 12) and sys.maxsize > 2**32 else 1)'
if ($LASTEXITCODE -ne 0) { throw "Detected Python $pythonVersion. Install Windows x64 Python 3.12+ and pass its executable path via -Python." }
Push-Location -LiteralPath $root
try {
    $record = @"
import json, sys
sys.path.insert(0, "scripts")
from v03_jobs import configuration, configured_pid, windows_powershell
try:
    revision, install, _ = configuration()
    windows_powershell()
    print(json.dumps({"major": revision, "path": str(install / "SLDWORKS.exe"), "target": configured_pid()}))
except (OSError, ValueError) as exc:
    print(str(exc), file=sys.stderr)
    sys.exit(1)
"@ | & $pythonExe -B -
    if ($LASTEXITCODE -ne 0) { throw 'Could not locate the configured SolidWorks installation.' }
    $config = $record | ConvertFrom-Json
    $exe = (Get-Item -LiteralPath $config.path).FullName
    if ([Diagnostics.FileVersionInfo]::GetVersionInfo($exe).FileMajorPart -ne $config.major) {
        throw 'Configured SolidWorks executable and COM major do not agree.'
    }
    $existing = @(Get-Process -Name SLDWORKS -ErrorAction SilentlyContinue)
    if ($config.target -gt 0) {
        $existing = @($existing | Where-Object Id -eq $config.target)
        if ($existing.Count -ne 1) { throw 'SOLIDWORKS_TARGET_PID does not match a running SolidWorks process.' }
    }
    $started = $null
    if ($existing.Count -eq 0 -and $StartIfMissing) {
        $started = (Start-Process -FilePath $exe -WorkingDirectory (Split-Path $exe) -WindowStyle Hidden -PassThru).Id
    } elseif ($existing.Count -ne 1 -or $existing[0].Path -ne $exe) {
        throw 'Open the configured SolidWorks release. If multiple sessions are open, select one using SOLIDWORKS_TARGET_PID.'
    }
    $probe = @"
import json, sys, time
sys.path.insert(0, "scripts")
from v03_jobs import configuration, host_command, run_host
revision, install, _ = configuration()
limit, expected = map(int, sys.argv[1:])
deadline = time.monotonic() + limit
host = {"status": "BLOCKED", "error": "COM startup timeout"}
while time.monotonic() < deadline:
    try:
        raw = run_host(host_command("Invoke-V03Probe.ps1", revision, install, expected),
                       timeout=min(5, max(.1, deadline - time.monotonic())))
        if raw.returncode == 0:
            host = json.loads(raw.stdout.decode("utf-8-sig"))
    except TimeoutError:
        pass
    if host.get("status") == "PASS":
        if host["pid"] != expected or host["documents"]:
            host.update(status="BLOCKED", error="Unexpected process or open SolidWorks documents")
        print(json.dumps(host))
        sys.exit(host["status"] != "PASS")
    time.sleep(min(1, max(0, deadline - time.monotonic())))
host.update(status="BLOCKED", reason="startup_timeout")
print(json.dumps(host))
sys.exit(1)
"@
    $expected = if ($null -ne $started) { $started } else { $existing[0].Id }
    $result = $probe | & $pythonExe -B - $TimeoutSeconds $expected
    $code = $LASTEXITCODE
    $result
    if ($code -ne 0) { exit $code }
} finally { Pop-Location }
