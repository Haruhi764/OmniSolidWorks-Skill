param([int]$RevisionMajor, [string]$InstallDirectory, [int]$TargetPid = 0)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$stage = 'powershell'
try {
    if ($PSVersionTable.PSEdition -ne 'Desktop' -or $PSVersionTable.PSVersion -lt [version]'5.1' -or
        -not [Environment]::Is64BitProcess -or
        [Threading.Thread]::CurrentThread.GetApartmentState() -ne 'STA') {
        throw 'Use 64-bit Windows PowerShell 5.1 in STA mode for the SolidWorks COM bridge.'
    }
    $stage = 'installation'
    $pia = Join-Path $InstallDirectory 'SolidWorks.Interop.sldworks.dll'
    $exe = (Get-Item -LiteralPath (Join-Path $InstallDirectory 'SLDWORKS.exe')).FullName
    if ([Diagnostics.FileVersionInfo]::GetVersionInfo($exe).FileMajorPart -ne $RevisionMajor) {
        throw 'Executable major does not match SOLIDWORKS_REVISION_MAJOR. Verify SOLIDWORKS_INSTALL_DIR.'
    }
    $stage = 'pia'
    if (-not (Test-Path -LiteralPath $pia -PathType Leaf)) { throw 'SolidWorks PIA is missing from the configured installation directory.' }
    [void][Reflection.Assembly]::LoadFrom($pia)
    Add-Type -Path (Join-Path $PSScriptRoot 'V03NativeHost.cs') -ReferencedAssemblies $pia
    $stage = 'com_attachment'
    $data = [V03NativeHost]::Probe($RevisionMajor, $TargetPid)
    $hostProcess = Get-Process -Id ([int]$data[1])
    if ($hostProcess.Path -ne $exe -or $data[0] -notmatch "^$RevisionMajor\.") { throw 'COM target identity differs from the configured release.' }
    [ordered]@{ status='PASS'; revision=$data[0]; pid=[int]$data[1]; documents=[int]$data[2]; language=$data[3] } | ConvertTo-Json -Compress
} catch {
    $cause = $_.Exception.GetBaseException()
    $hint = if ($stage -eq 'com_attachment') {
        'Open the configured SolidWorks release in the current Windows session. If several sessions are open, set SOLIDWORKS_TARGET_PID to the intended PID.'
    } else { $null }
    [ordered]@{ status='BLOCKED'; stage=$stage; hint=$hint; hresult=('0x{0:X8}' -f $cause.HResult); error=$cause.Message } | ConvertTo-Json -Compress
}
