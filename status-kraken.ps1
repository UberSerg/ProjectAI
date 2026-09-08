#Requires -Version 5.1
<#
.SYNOPSIS
  Show Kraken Docker / health status.

.PARAMETER Json
  Emit machine-readable JSON.
#>
[CmdletBinding()]
param(
    [switch]$Json
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Test-DockerDaemon {
    try {
        $null = & docker info 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Get-ComposePsJson {
    $raw = & docker compose ps -a --format json 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($raw)) { return @() }
    $text = $raw.Trim()
    if ($text.StartsWith("[")) { return @( $text | ConvertFrom-Json ) }
    $items = @()
    foreach ($line in ($raw -split "`n")) {
        $line = $line.Trim()
        if ($line) { $items += ($line | ConvertFrom-Json) }
    }
    return $items
}

function Probe-Url([string]$Url) {
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
        return @{ ok = $true; code = [int]$r.StatusCode }
    } catch {
        return @{ ok = $false; code = 0; error = $_.Exception.Message }
    }
}

$dockerOk = (Get-Command docker -ErrorAction SilentlyContinue) -and (Test-DockerDaemon)
$rows = if ($dockerOk) { Get-ComposePsJson } else { @() }

$services = @("postgres-core", "postgres-memory", "redis", "backend", "worker", "scheduler", "frontend")
$matrix = @{}
foreach ($name in $services) {
    $r = $rows | Where-Object { $_.Service -eq $name } | Select-Object -First 1
    if (-not $r) {
        $matrix[$name] = @{ state = "missing"; health = "n/a"; status = "missing" }
    } else {
        $matrix[$name] = @{
            state  = [string]$r.State
            health = if ($r.Health) { [string]$r.Health } else { "n/a" }
            status = [string]$r.Status
        }
    }
}

$ready = Probe-Url "http://localhost:8000/api/v1/system/health/ready"
$health = Probe-Url "http://localhost:8000/api/v1/system/health"
$ui = Probe-Url "http://localhost:5173"

$payload = [ordered]@{
    docker = $dockerOk
    services = $matrix
    backend_ready_http = $ready
    backend_health_http = $health
    frontend_http = $ui
    urls = @{
        ui = "http://localhost:5173"
        api = "http://localhost:8000"
        docs = "http://localhost:8000/docs"
        ready = "http://localhost:8000/api/v1/system/health/ready"
    }
}

if ($Json) {
    $payload | ConvertTo-Json -Depth 6
    exit 0
}

Write-Host "Kraken status"
Write-Host ("Docker................... {0}" -f $(if ($dockerOk) { "OK" } else { "NOT RUNNING" }))
foreach ($name in $services) {
    $m = $matrix[$name]
    $line = "{0} {1}" -f $m.state, $m.health
    if ($m.status -match "healthy") { $line = "healthy" }
    elseif ($m.state -match "running" -and $name -eq "scheduler") { $line = "running" }
    elseif ($m.health -eq "healthy") { $line = "healthy" }
    elseif ($m.state -match "running") { $line = "running ($($m.health))" }
    Write-Host ("{0} {1}" -f ($name.PadRight(24, "."), $line))
}
Write-Host ("Backend ready HTTP....... {0}" -f $(if ($ready.ok) { "OK $($ready.code)" } else { "FAIL" }))
Write-Host ("Frontend HTTP............ {0}" -f $(if ($ui.ok) { "OK $($ui.code)" } else { "FAIL" }))
Write-Host ""
Write-Host "UI:  http://localhost:5173"
Write-Host "API: http://localhost:8000"

$requiredHealthy = @(
    ($matrix["postgres-core"].health -eq "healthy"),
    ($matrix["postgres-memory"].health -eq "healthy"),
    ($matrix["redis"].health -eq "healthy"),
    ($matrix["backend"].health -eq "healthy"),
    ($matrix["frontend"].health -eq "healthy"),
    $ready.ok,
    $ui.ok
)
if ($dockerOk -and ($requiredHealthy -notcontains $false)) {
    Write-Host "Overall: READY"
    exit 0
}
Write-Host "Overall: NOT READY"
exit 1
