#Requires -Version 5.1
<#
.SYNOPSIS
  Restart Kraken: stop then start (volumes preserved).

.PARAMETER Build
  Rebuild images on start.
#>
[CmdletBinding()]
param(
    [switch]$Build,
    [switch]$OpenBrowser
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $Root "stop-kraken.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$startArgs = @()
if ($Build) { $startArgs += "-Build" }
if ($OpenBrowser) { $startArgs += "-OpenBrowser" }
& (Join-Path $Root "start-kraken.ps1") @startArgs
exit $LASTEXITCODE
