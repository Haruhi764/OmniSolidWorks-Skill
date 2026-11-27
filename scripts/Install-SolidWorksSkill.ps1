param(
    [Parameter(Mandatory)][string]$Destination,
    [string]$Python = 'python',
    [switch]$Smoke
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not [Environment]::Is64BitProcess) {
    throw 'Run the installer in a 64-bit PowerShell session on Windows.'
}
if ([string]::IsNullOrWhiteSpace($Destination)) { throw 'Supply a new local destination with -Destination.' }
$destinationPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Destination)
if ($destinationPath -notmatch '^[A-Za-z]:\\[^\\]') {
    throw 'Choose a directory on a local Windows drive.'
}
foreach ($segment in $destinationPath.Substring(3).Split('\')) {
    if ($segment.EndsWith('.') -or $segment.EndsWith(' ') -or $segment.Contains(':') -or
        $segment -match '^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:[.]|$)') {
        throw 'The destination contains a reserved Windows path segment.'
    }
}
if ((Test-Path -LiteralPath $destinationPath) -or
    $destinationPath.StartsWith($root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Choose a new destination outside the extracted release folder.'
}
function Assert-LocalPath([string]$Path) {
    for ($current = $Path; $current; $current = [IO.Path]::GetDirectoryName($current)) {
        $item = Get-Item -LiteralPath $current -Force -ErrorAction SilentlyContinue
        if ($item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "A managed path contains a reparse point: $current"
        }
    }
}
Assert-LocalPath $destinationPath
$manifestPath = Join-Path $root 'RELEASE_MANIFEST.json'
Assert-LocalPath $manifestPath
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.schema -ne 1 -or -not $manifest.release -or -not $manifest.files.Count) {
    throw 'The release manifest is missing or invalid.'
}
$pythonCommand = Get-Command -Name $Python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $pythonCommand) { throw 'Python was not found. Set -Python to the full path of a Windows x64 Python 3.12+ executable.' }
$pythonExe = $pythonCommand.Source
$windowsPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
if (-not (Test-Path -LiteralPath $windowsPowerShell -PathType Leaf)) { throw 'Windows PowerShell 5.1 is missing from System32.' }
& $pythonExe -B -c 'import sys, winreg; sys.exit(0 if sys.version_info >= (3, 12) and sys.maxsize > 2**32 else 1)'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12+ for Windows x64 is required.' }
$seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($row in $manifest.files) {
    $relative = [string]$row.path
    if ($relative -notmatch '^(?:[A-Za-z0-9_-][A-Za-z0-9_.-]*/)*[A-Za-z0-9_-][A-Za-z0-9_.-]*$' -or
        -not $seen.Add($relative) -or $row.sha256 -notmatch '^[a-fA-F0-9]{64}$') {
        throw 'Invalid or duplicate relative path in the release manifest.'
    }
    foreach ($segment in $relative.Split('/')) {
        if ($segment.EndsWith('.') -or $segment -match '^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:[.]|$)') {
            throw 'Reserved Windows path segment in the release manifest.'
        }
    }
    $source = Join-Path $root $relative
    Assert-LocalPath $source
    if ((Get-Item -LiteralPath $source).Length -ne $row.bytes -or
        (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $row.sha256) {
        throw "Release file differs from the manifest: $relative"
    }
}
foreach ($required in 'SKILL.md','scripts/v03_jobs.py','examples/v09_install_smoke.json') {
    if (-not $seen.Contains($required)) { throw "Missing required release member: $required" }
}
$hostInfo = $null
if ($Smoke) {
    $lines = & $pythonExe -B (Join-Path $root 'scripts/v03_jobs.py') --preflight
    $probeCode = $LASTEXITCODE
    try { $hostInfo = ($lines -join [Environment]::NewLine) | ConvertFrom-Json } catch {
        throw 'The release preflight did not return JSON. From the extracted folder run python -B scripts/v03_jobs.py --preflight.'
    }
    if ($probeCode -ne 0 -or $hostInfo.status -ne 'PASS') {
        throw ("Preflight failed [{0}] {1} {2}" -f $hostInfo.stage, $hostInfo.error, $hostInfo.hint)
    }
}
try { [void][IO.Directory]::CreateDirectory($destinationPath) } catch {
    throw ("Cannot create installation directory '{0}'. Choose a writable location. {1}" -f $destinationPath, $_.Exception.Message)
}
foreach ($row in $manifest.files) {
    $target = Join-Path $destinationPath $row.path
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))
    [IO.File]::Copy((Join-Path $root $row.path), $target, $false)
    if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $row.sha256) {
        throw "Installed file differs from the manifest: $($row.path)"
    }
}
[IO.File]::Copy($manifestPath, (Join-Path $destinationPath 'RELEASE_MANIFEST.json'), $false)
if (-not $Smoke) {
    [ordered]@{status='PASS'; release=$manifest.release; verifiedFiles=$manifest.files.Count; smoke='not_requested'} |
        ConvertTo-Json -Compress
    return
}
$previousTarget = $env:SOLIDWORKS_TARGET_PID
Push-Location -LiteralPath $destinationPath
try {
    $env:SOLIDWORKS_TARGET_PID = [string]$hostInfo.pid
    $hostJson = & $pythonExe -B scripts/v03_jobs.py
    if ($LASTEXITCODE -ne 0) { throw 'The installed COM probe failed.' }
    $installedHost = $hostJson | ConvertFrom-Json
    if ($installedHost.status -ne 'PASS' -or $installedHost.documents -ne 0 -or $installedHost.pid -ne $hostInfo.pid) {
        throw 'The preflight SolidWorks session changed during installation. Recheck the selected PID and close open documents before using -Smoke.'
    }
    $smokeJson = & $pythonExe -B scripts/v03_jobs.py examples/v09_install_smoke.json
    if ($LASTEXITCODE -ne 0) { $smokeJson; throw 'The installed native smoke test failed. See the installed outputs folder.' }
    $smokeRows = ($smokeJson -join [Environment]::NewLine) | ConvertFrom-Json
    if ($smokeRows.Count -ne 1) { throw 'Expected one native smoke result.' }
    $smokeResult = $smokeRows[0]
    if ($smokeResult.status -ne 'PASS' -or $smokeResult.cache_hit -or $smokeResult.revision -ne $hostInfo.revision) {
        throw 'The installed native smoke result did not match the connected host.'
    }
    [ordered]@{status='PASS'; release=$manifest.release; verifiedFiles=$manifest.files.Count;
        revision=$hostInfo.revision; pid=$hostInfo.pid; smoke=$smokeResult} | ConvertTo-Json -Depth 9
} finally {
    $env:SOLIDWORKS_TARGET_PID = $previousTarget
    Pop-Location
}
