[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $BundlePath,
    [Parameter(Mandatory)][string] $ReviewPath,
    [Parameter(Mandatory)][string] $OutputDirectory
)

$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'Invoke-Runner.ps1') -BundlePath $BundlePath -ReviewPath $ReviewPath -OutputDirectory $OutputDirectory
