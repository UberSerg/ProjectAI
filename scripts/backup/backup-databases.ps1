<#
.SYNOPSIS
  Backup ProjectAI core and memory PostgreSQL databases.
#>
param(
  [string]$OutputDir = (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "backups")
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

Write-Host "Backing up core DB..."
docker exec projectai-postgres-core pg_dump -U projectai -d projectai_core -Fc -f /tmp/core.dump
docker cp "projectai-postgres-core:/tmp/core.dump" (Join-Path $OutputDir "core_$stamp.dump")

Write-Host "Backing up memory DB..."
docker exec projectai-postgres-memory pg_dump -U projectai -d projectai_memory -Fc -f /tmp/memory.dump
docker cp "projectai-postgres-memory:/tmp/memory.dump" (Join-Path $OutputDir "memory_$stamp.dump")

Write-Host "Backups written to $OutputDir"
Get-ChildItem $OutputDir | Sort-Object LastWriteTime -Descending | Select-Object -First 6
