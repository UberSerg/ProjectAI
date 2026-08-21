<#
.SYNOPSIS
  Restore ProjectAI databases from pg_dump custom-format files.
#>
param(
  [Parameter(Mandatory = $true)][string]$CoreDump,
  [Parameter(Mandatory = $true)][string]$MemoryDump
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path $CoreDump)) { throw "Core dump not found: $CoreDump" }
if (-not (Test-Path $MemoryDump)) { throw "Memory dump not found: $MemoryDump" }

Write-Host "Restoring core..."
docker cp $CoreDump projectai-postgres-core:/tmp/restore_core.dump
docker exec projectai-postgres-core pg_restore -U projectai -d projectai_core --clean --if-exists /tmp/restore_core.dump

Write-Host "Restoring memory..."
docker cp $MemoryDump projectai-postgres-memory:/tmp/restore_memory.dump
docker exec projectai-postgres-memory pg_restore -U projectai -d projectai_memory --clean --if-exists /tmp/restore_memory.dump

Write-Host "Restore completed."
