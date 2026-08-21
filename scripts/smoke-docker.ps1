$ErrorActionPreference = "Stop"
Write-Host "Validating compose config..."
docker compose config --quiet

Write-Host "Checking health endpoint..."
$health = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/system/health" -TimeoutSec 10
Write-Host ($health | ConvertTo-Json -Depth 5)
if ($health.status -ne "ok") { throw "Health status is not ok" }

Write-Host "Checking frontend..."
$frontend = Invoke-WebRequest -Uri "http://localhost:5173" -UseBasicParsing -TimeoutSec 10
if ($frontend.StatusCode -ne 200) { throw "Frontend not reachable" }

Write-Host "Smoke OK"
