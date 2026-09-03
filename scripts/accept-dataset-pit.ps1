# Dataset/PIT V0 acceptance watchdog.
# Timeout + stale detection + non-zero exit. No infinite poll.
param(
    [Parameter(Mandatory = $true)]
    [string] $DateFrom,
    [string] $DateTo = "",
    [int[]] $InstrumentIds = @(),
    [int] $TimeoutSec = 180,
    [int] $StaleSec = 45,
    [int] $PollSec = 3,
    [string] $BaseUrl = "http://localhost:8000"
)

$ErrorActionPreference = "Stop"
$deadline = (Get-Date).AddSeconds($TimeoutSec)
$body = @{
    date_from = $DateFrom
    dataset_spec_code = "pit_daily_core"
    dataset_spec_version = 1
}
if ($DateTo) { $body.date_to = $DateTo }
if ($InstrumentIds.Count -gt 0) { $body.instrument_ids = $InstrumentIds }

Write-Host "POST $BaseUrl/api/v1/learning/datasets/build"
$start = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/learning/datasets/build" `
    -ContentType "application/json" -Body ($body | ConvertTo-Json -Compress) -TimeoutSec 30
$workflowId = $start.workflow_id
if (-not $workflowId) { throw "No workflow_id from DatasetBuild" }
Write-Host "workflow_id=$workflowId"

$lastHeartbeat = Get-Date
$lastMeta = ""
while ((Get-Date) -lt $deadline) {
    $wf = Invoke-RestMethod -Uri "$BaseUrl/api/v1/workflows/$workflowId" -TimeoutSec 15
    $status = [string]$wf.status
    $meta = ($wf.meta | ConvertTo-Json -Compress)
    Write-Host ("[{0:HH:mm:ss}] status={1} meta={2}" -f (Get-Date), $status, $meta)
    if ($meta -ne $lastMeta) {
        $lastHeartbeat = Get-Date
        $lastMeta = $meta
    }
    if ($status -in @("SUCCESS", "WARNING", "success", "warning")) {
        $runs = Invoke-RestMethod -Uri "$BaseUrl/api/v1/learning/datasets/runs?limit=5" -TimeoutSec 15
        $run = $runs | Where-Object { $_.workflow_id -eq ([string]$workflowId) } | Select-Object -First 1
        if (-not $run) { $run = $runs | Select-Object -First 1 }
        Write-Host "ACCEPT OK run_id=$($run.id) samples=$($run.samples_total) hash=$($run.dataset_hash) pit=$($run.pit_status)"
        if ($run.pit_status -ne "PASS") { throw "PIT status is $($run.pit_status)" }
        if (-not $run.dataset_hash) { throw "Missing dataset hash" }
        if ([int]$run.samples_total -le 0) { throw "No samples materialized" }
        $summary = Invoke-RestMethod -Uri "$BaseUrl/api/v1/learning/datasets/runs/$($run.id)/summary" -TimeoutSec 15
        Write-Host ($summary | ConvertTo-Json -Depth 6)
        exit 0
    }
    if ($status -in @("ERROR", "error")) {
        $diag = Invoke-RestMethod -Uri "$BaseUrl/api/v1/system/diagnostics/text" -TimeoutSec 20
        Write-Host $diag
        throw "DatasetBuild failed: $($wf.error)"
    }
    $age = ((Get-Date) - $lastHeartbeat).TotalSeconds
    if ($age -gt $StaleSec) {
        throw "Watchdog stale: no workflow meta progress for ${StaleSec}s (status=$status)"
    }
    Start-Sleep -Seconds $PollSec
}

try {
    $diag = Invoke-RestMethod -Uri "$BaseUrl/api/v1/system/diagnostics/text" -TimeoutSec 20
    Write-Host $diag
} catch {
    Write-Host "diagnostics unavailable"
}
throw "DatasetBuild timed out after ${TimeoutSec}s (workflow_id=$workflowId)"
