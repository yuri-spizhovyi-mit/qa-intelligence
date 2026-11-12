[CmdletBinding()]
param([Parameter(Mandatory)][string] $OutputDirectory)

$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'Invoke-Runner.ps1') -Preflight -OutputDirectory $OutputDirectory
