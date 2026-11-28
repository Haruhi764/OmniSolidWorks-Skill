$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot '..\scripts\V03NativeCylinderPatch.cs'
$cases = Join-Path $PSScriptRoot 'Issue2CylinderCases.cs'
Add-Type -Path $source,$cases -ReferencedAssemblies 'System.Core.dll'
[Issue2CylinderCases]::Run()