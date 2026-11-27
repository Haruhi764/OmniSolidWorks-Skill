param([int]$RevisionMajor,[string]$InstallDirectory,[string]$Template,[string]$RunDirectory,[int]$TargetPid)
$ErrorActionPreference='Stop'
$project=(Split-Path -Parent $PSScriptRoot)
if((Get-Location).ProviderPath -ne $project){throw 'Wrong workspace'}
$root=Join-Path $project 'outputs\v0.5\gear'
$run=(Get-Item -LiteralPath $RunDirectory).FullName
if((Split-Path -Parent $run) -ne $root -or (Split-Path -Leaf $run) -notmatch '\Arun-[a-f0-9]{12}\z'){throw 'Invalid job path'}
foreach($d in @($project,(Join-Path $project 'outputs'),(Join-Path $project 'outputs\v0.5'),$root,$run)){
 if((Get-Item -LiteralPath $d -Force).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Redirected job path'}
}
$pia=Join-Path $InstallDirectory 'SolidWorks.Interop.sldworks.dll'
$exe=(Get-Item -LiteralPath (Join-Path $InstallDirectory 'SLDWORKS.exe')).FullName
$report=[ordered]@{status='FAIL';stage='compile';transport='SolidWorks installed PIA';utc=[DateTimeOffset]::UtcNow.ToString('o')}
$timer=[Diagnostics.Stopwatch]::StartNew()
$mutex=[Threading.Mutex]::new($false,'Local\SolidWorksMechanicalNativePartJob')
$owned=$false
try {
 $owned=$mutex.WaitOne(0)
 if(!$owned){throw 'Another CAD operation is active'}
 if([Threading.Thread]::CurrentThread.GetApartmentState() -ne 'STA'){throw 'STA required'}
 [void][Reflection.Assembly]::LoadFrom($pia)
 $sources=@(Get-ChildItem -LiteralPath $PSScriptRoot -File -Filter 'V03Native*.cs' | Select-Object -ExpandProperty FullName)
 Add-Type -Path $sources -ReferencedAssemblies $pia,'System.Core.dll','System.Web.Extensions.dll'
 [V03Native]::RunGear($RevisionMajor,$exe,$Template,$run,(Join-Path $run 'job.json'),$TargetPid,$report)
 $report.status='PASS'
} catch {
 $err=$_.Exception.GetBaseException()
 $report.error=$err.Message
 $report.hresult='0x{0:X8}' -f $err.HResult
 if($report.stage -eq 'attach'){$report.status='BLOCKED'}
} finally {
 if($owned){$mutex.ReleaseMutex()}
 $mutex.Dispose()
 $report.nativeSeconds=[Math]::Round($timer.Elapsed.TotalSeconds,3)
 $out=[IO.File]::Open((Join-Path $run 'native.json'),[IO.FileMode]::CreateNew)
 try {
  $buffer=[Text.UTF8Encoding]::new($false).GetBytes(($report | ConvertTo-Json -Depth 28))
  $out.Write($buffer,0,$buffer.Length)
 } finally {$out.Dispose()}
}
if($report.status -ne 'PASS'){exit 1}

