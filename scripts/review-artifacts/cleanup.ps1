# Cleanup review artifacts for a merged/closed PR from branch `review-artifacts`
#
# Usage:
#   pwsh scripts/review-artifacts/cleanup.ps1 -PrNumber 59
#
# Only run after: PR merged or finally closed AND required CI green AND no open review.

param(
  [Parameter(Mandatory = $true)][int]$PrNumber,
  [string]$Slug = "",
  [switch]$SkipPush
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $repoRoot

$prevBranch = (git branch --show-current).Trim()
$stashNeeded = $false
if ((git status --porcelain)) {
  git stash push -u -m "review-artifacts-cleanup-temp"
  $stashNeeded = $true
}

try {
  git fetch origin review-artifacts
  git checkout -B review-artifacts origin/review-artifacts

  $matches = Get-ChildItem "review-artifacts" -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "pr-$PrNumber-*" -or ($Slug -and $_.Name -eq "pr-$PrNumber-$Slug") }

  if (-not $matches) {
    Write-Host "No artifact directories for PR #$PrNumber"
  } else {
    foreach ($d in $matches) {
      git rm -r -- $d.FullName.Substring($repoRoot.Length + 1).Replace("\", "/")
    }
    git commit -m "chore(review-artifacts): clean PR #$PrNumber"
    if (-not $SkipPush) {
      git push origin review-artifacts
    }
    Write-Host "Cleaned PR #$PrNumber artifacts. Commit: $(git rev-parse --short HEAD)"
  }
}
finally {
  git checkout $prevBranch
  if ($stashNeeded) {
    git stash pop
  }
}
