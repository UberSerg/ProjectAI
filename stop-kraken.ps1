#Requires -Version 5.1
<#
.SYNOPSIS
  Stop Kraken containers safely (volumes preserved). Uses `docker compose stop`.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "FAILED: Docker CLI not found."
    exit 1
}
try {
    $null = & docker info 2>$null
    if ($LASTEXITCODE -ne 0) { throw "daemon" }
} catch {
    Write-Host "Docker Desktop is not running."
    exit 1
}

Write-Host "Stopping Kraken (volumes preserved)..."
& docker compose stop
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAILED: docker compose stop"
    exit 1
}
Write-Host "Kraken stopped. Data volumes kept."
Write-Host "Start again with start-kraken.cmd"
exit 0
