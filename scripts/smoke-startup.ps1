#Requires -Version 5.1
<#
.SYNOPSIS
  Bounded acceptance for Docker Startup Reliability V1.
  Scenarios: all-stopped start, partial-stack recovery, repeated start.
#>
[CmdletBinding()]
param(
    [int]$TimeoutSec = 300
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
# script lives in scripts/ — repo root is parent
if (Test-Path (Join-Path $Root "docker-compose.yml")) {
    # ok
} else {
    $Root = Split-Path -Parent $MyInvocation.MyCommand.Path
    if (-not (Test-Path (Join-Path $Root "docker-compose.yml"))) {
        $Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
    }
}
# Prefer locating from this file: scripts/smoke-startup.ps1 → repo root
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$Art = Join-Path $Root ".tmp\docker-startup-reliability-v1"
New-Item -ItemType Directory -Force -Path $Art | Out-Null

function Invoke-Start {
    & (Join-Path $Root "start-kraken.ps1") -TimeoutSec $TimeoutSec
    if ($LASTEXITCODE -ne 0) { throw "start-kraken failed with $LASTEXITCODE" }
}

function Save-Out([string]$Name, [scriptblock]$Block) {
    $path = Join-Path $Art $Name
    $text = & $Block | Out-String
    Set-Content -Path $path -Value $text -Encoding utf8
    return $text
}

Write-Host "=== Acceptance A: all stopped ==="
& docker compose stop | Out-Null
Start-Sleep -Seconds 3
$beforeA = & docker compose ps -a --format "table {{.Name}}\t{{.Status}}" | Out-String
Set-Content (Join-Path $Art "before-all-stopped.txt") $beforeA -Encoding utf8
$t0 = Get-Date
Invoke-Start
$elapsedA = [int]((Get-Date) - $t0).TotalSeconds
Save-Out "startup-all-stopped.txt" { & (Join-Path $Root "status-kraken.ps1") }

Write-Host "=== Acceptance G: repeated start ==="
$t1 = Get-Date
Invoke-Start
$elapsedG = [int]((Get-Date) - $t1).TotalSeconds
Save-Out "startup-repeated.txt" { & (Join-Path $Root "status-kraken.ps1") }

Write-Host "=== Acceptance B: partial stack (reproduce incident) ==="
& docker compose stop postgres-core postgres-memory redis frontend | Out-Null
Start-Sleep -Seconds 5
# leave backend/worker/scheduler as-is (may become unhealthy / restarting)
$beforeB = & docker compose ps -a --format "table {{.Name}}\t{{.Status}}" | Out-String
Set-Content (Join-Path $Art "before-partial-stack.txt") $beforeB -Encoding utf8
$t2 = Get-Date
Invoke-Start
$elapsedB = [int]((Get-Date) - $t2).TotalSeconds
Save-Out "startup-partial-stack.txt" { & (Join-Path $Root "status-kraken.ps1") }
Save-Out "status-ready.txt" { & (Join-Path $Root "status-kraken.ps1") }

& docker compose config | Out-File (Join-Path $Art "compose-config.txt") -Encoding utf8

# Persistence probe (counts only)
$persist = & docker compose exec -T backend python -c @"
from app.infrastructure.db.session import core_session
from sqlalchemy import text
with core_session() as s:
    instruments = s.execute(text('select count(*) from market.instruments')).scalar()
    portfolios = s.execute(text('select count(*) from portfolio.manual_portfolios')).scalar()
    print(f'instruments={instruments}')
    print(f'manual_portfolios={portfolios}')
"@ 2>&1 | Out-String
Set-Content (Join-Path $Art "persistence-counts.txt") $persist -Encoding utf8

$matrix = @{
    postgres_core = "required"
    postgres_memory = "required"
    redis = "required"
    backend = "required"
    frontend = "required"
    worker = "operational"
    scheduler = "operational"
    restart_policy = "unless-stopped"
    backend_healthcheck = "/api/v1/system/health/ready"
    compose_project = "projectai"
    root_cause = "explicitly stopped containers stay stopped; unless-stopped does not revive them; launcher runs compose up --wait"
}
$matrix | ConvertTo-Json | Set-Content (Join-Path $Art "health-matrix.json") -Encoding utf8

@{
    acceptance_a_all_stopped_sec = $elapsedA
    acceptance_b_partial_sec = $elapsedB
    acceptance_g_repeated_sec = $elapsedG
} | ConvertTo-Json | Set-Content (Join-Path $Art "startup-time.json") -Encoding utf8

Write-Host "Acceptance OK"
Write-Host "Artifacts: $Art"
exit 0
