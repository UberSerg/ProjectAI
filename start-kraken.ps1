#Requires -Version 5.1
<#
.SYNOPSIS
  Start the full Kraken (ProjectAI) Docker Compose stack and wait until READY.

.PARAMETER Build
  Force image rebuild before up.

.PARAMETER OpenBrowser
  Open the frontend URL after success.

.PARAMETER TimeoutSec
  Max seconds to wait for healthy stack (default 300).
#>
[CmdletBinding()]
param(
    [switch]$Build,
    [switch]$OpenBrowser,
    [int]$TimeoutSec = 300
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Test-Path (Join-Path $Root "docker-compose.yml"))) {
    Write-Error "docker-compose.yml not found next to this script: $Root"
    exit 2
}
Set-Location $Root

function Write-Step([string]$Label, [string]$State) {
    $pad = $Label.PadRight(22, ".")
    Write-Host ("[{0}] {1} {2}" -f $script:StepNum, $pad, $State)
    $script:StepNum++
}

function Test-DockerDaemon {
    try {
        $null = & docker info 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Get-ComposePsJson {
    $raw = & docker compose ps --format json 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($raw)) { return @() }
    # Compose may emit NDJSON (one object per line) or a JSON array
    $text = $raw.Trim()
    if ($text.StartsWith("[")) {
        return @( $text | ConvertFrom-Json )
    }
    $items = @()
    foreach ($line in ($raw -split "`n")) {
        $line = $line.Trim()
        if ($line) { $items += ($line | ConvertFrom-Json) }
    }
    return $items
}

function Get-ServiceState([string]$Name) {
    $rows = Get-ComposePsJson | Where-Object { $_.Service -eq $Name -or $_.Name -like "*$Name*" }
    if (-not $rows) { return @{ state = "missing"; health = "n/a"; status = "missing" } }
    $r = $rows | Select-Object -First 1
    $health = if ($r.Health) { $r.Health } elseif ($r.State -match "\((\w+)\)") { $Matches[1] } else { "n/a" }
    return @{
        state  = [string]$r.State
        health = [string]$health
        status = [string]$r.Status
        name   = [string]$r.Name
    }
}

function Show-FailLogs([string[]]$Services) {
    foreach ($svc in $Services) {
        Write-Host ""
        Write-Host "---- logs: $svc (tail 40) ----"
        & docker compose logs --tail 40 $svc 2>&1 | ForEach-Object { Write-Host $_ }
    }
}

function Wait-HttpOk([string]$Url, [int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300) { return $true }
        } catch { }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Restart-IfUnhealthy([string]$Service) {
    $s = Get-ServiceState $Service
    $bad = ($s.health -match "unhealthy") -or ($s.state -match "exited|dead|restarting")
    if ($bad) {
        Write-Host "  recovering $Service (state=$($s.state) health=$($s.health))..."
        & docker compose restart $Service | Out-Null
        return $true
    }
    return $false
}

# --- main ---
$script:StepNum = 1
$startedAt = Get-Date

Write-Host "Kraken START"
Write-Host "Repo: $Root"
Write-Host ""

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "FAILED: Docker CLI not found. Install Docker Desktop."
    exit 1
}
if (-not (Test-DockerDaemon)) {
    Write-Host "Docker Desktop is not running. Start Docker Desktop and run Start Kraken again."
    Write-Host "Docker Desktop не запущен. Запустите Docker Desktop и повторите Start Kraken."
    exit 1
}
Write-Step "Docker" "OK"

if (-not (Test-Path (Join-Path $Root ".env"))) {
    Write-Host "FAILED: .env missing. Create it from .env.example."
    Write-Host "Отсутствует .env. Создайте его из .env.example."
    exit 1
}
Write-Step ".env" "OK"

$verLine = (& docker compose version 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAILED: 'docker compose' unavailable. Need Docker Compose V2."
    exit 1
}

Write-Host "Compose up..."
$upArgs = @("compose", "up", "-d", "--wait", "--wait-timeout", ([string]$TimeoutSec))
if ($Build) { $upArgs = @("compose", "up", "-d", "--build", "--wait", "--wait-timeout", ([string]$TimeoutSec)) }
& docker @upArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Kraken START FAILED (compose up --wait)"
    & docker compose ps
    Show-FailLogs @("postgres-core", "postgres-memory", "redis", "backend", "worker", "scheduler", "frontend")
    exit 1
}

# Bounded recovery if a dependency came up but app stayed unhealthy
$recovered = $false
foreach ($svc in @("backend", "worker", "frontend")) {
    if (Restart-IfUnhealthy $svc) { $recovered = $true }
}
if ($recovered) {
    & docker compose up -d --wait --wait-timeout ([Math]::Min(120, $TimeoutSec)) | Out-Null
}

$required = @(
    @{ name = "postgres-core"; label = "PostgreSQL Core" },
    @{ name = "postgres-memory"; label = "PostgreSQL Memory" },
    @{ name = "redis"; label = "Redis" },
    @{ name = "backend"; label = "Backend" },
    @{ name = "frontend"; label = "Frontend" }
)
$important = @(
    @{ name = "worker"; label = "Worker" },
    @{ name = "scheduler"; label = "Scheduler" }
)

$failed = @()
foreach ($svc in $required) {
    $st = Get-ServiceState $svc.name
    $ok = ($st.state -match "running") -and ($st.health -match "healthy|n/a" -or $svc.name -eq "scheduler")
    # postgres/redis/backend/frontend must be healthy
    if ($svc.name -ne "scheduler") {
        $ok = ($st.health -eq "healthy") -or ($st.status -match "\(healthy\)")
    }
    if ($ok) {
        Write-Step $svc.label "HEALTHY"
    } else {
        Write-Step $svc.label ("FAIL state=$($st.state) health=$($st.health)")
        $failed += $svc.name
    }
}
foreach ($svc in $important) {
    $st = Get-ServiceState $svc.name
    $running = ($st.state -match "running") -or ($st.status -match "Up")
    if ($running) {
        Write-Step $svc.label ("RUNNING" + $(if ($st.health -and $st.health -ne "n/a") { " ($($st.health))" } else { "" }))
    } else {
        Write-Step $svc.label ("DEGRADED state=$($st.state)")
        # worker/scheduler degraded → still fail READY for operational Kraken
        $failed += $svc.name
    }
}

$readyUrl = "http://localhost:8000/api/v1/system/health/ready"
$uiUrl = "http://localhost:5173"
$apiOk = Wait-HttpOk $readyUrl 60
$uiOk = Wait-HttpOk $uiUrl 60
if (-not $apiOk) { $failed += "backend-http" }
if (-not $uiOk) { $failed += "frontend-http" }

$elapsed = [int]((Get-Date) - $startedAt).TotalSeconds

if ($failed.Count -gt 0) {
    Write-Host ""
    Write-Host "Kraken START FAILED"
    Write-Host ("Services: " + ($failed -join ", "))
    & docker compose ps
    Show-FailLogs ($failed | Select-Object -Unique)
    exit 1
}

Write-Host ""
Write-Host "Kraken READY ($elapsed s)"
Write-Host "Kraken готов."
Write-Host "UI:  $uiUrl"
Write-Host "API: http://localhost:8000"
Write-Host "Docs: http://localhost:8000/docs"
Write-Host "Ready: $readyUrl"

# Persist timing for acceptance artifacts when folder exists
$art = Join-Path $Root ".tmp\docker-startup-reliability-v1"
if (Test-Path (Split-Path $art -Parent)) {
    New-Item -ItemType Directory -Force -Path $art | Out-Null
    @{
        started_at = $startedAt.ToString("o")
        elapsed_sec = $elapsed
        build = [bool]$Build
        status = "READY"
    } | ConvertTo-Json | Set-Content -Path (Join-Path $art "startup-time.json") -Encoding utf8
}

if ($OpenBrowser) {
    Start-Process $uiUrl
}

exit 0
