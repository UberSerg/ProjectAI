# Publish review artifacts to branch `review-artifacts`
#
# Usage (from repo root):
#   pwsh scripts/review-artifacts/publish.ps1 -PrNumber 59 -Slug dark-dashboard -SourceDir .tmp/kraken-personal-v1/screenshots
#
# Copies files from -SourceDir into review-artifacts/pr-<N>-<slug>/ on branch
# review-artifacts, commits, and pushes. Does not modify the current feature branch tip permanently
# (returns to the previous branch afterwards).

param(
  [Parameter(Mandatory = $true)][int]$PrNumber,
  [Parameter(Mandatory = $true)][string]$Slug,
  [Parameter(Mandatory = $true)][string]$SourceDir,
  [string]$FeatureCommit = "",
  [string]$FeatureTitle = "",
  [switch]$SkipPush
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $repoRoot

if (-not (Test-Path $SourceDir)) {
  throw "SourceDir not found: $SourceDir"
}

$prevBranch = (git branch --show-current).Trim()
$stashNeeded = $false
if ((git status --porcelain) ) {
  git stash push -u -m "review-artifacts-publish-temp"
  $stashNeeded = $true
}

try {
  git fetch origin main 2>$null
  $hasRemote = $false
  git show-ref --verify --quiet refs/remotes/origin/review-artifacts
  if ($LASTEXITCODE -eq 0) { $hasRemote = $true }

  if ($hasRemote) {
    git checkout -B review-artifacts origin/review-artifacts
  } else {
    git show-ref --verify --quiet refs/heads/review-artifacts
    if ($LASTEXITCODE -eq 0) {
      git checkout review-artifacts
    } else {
      git checkout -B review-artifacts origin/main
    }
  }

  $destRel = "review-artifacts/pr-$PrNumber-$Slug"
  $dest = Join-Path $repoRoot $destRel
  New-Item -ItemType Directory -Force -Path $dest | Out-Null

  Get-ChildItem $SourceDir -File | ForEach-Object {
    Copy-Item $_.FullName (Join-Path $dest $_.Name) -Force
  }

  if (-not $FeatureCommit) {
    $FeatureCommit = (git rev-parse origin/feature/kraken-personal-v1-dark-dashboard 2>$null)
    if (-not $FeatureCommit) { $FeatureCommit = "(see feature PR)" }
  }
  if (-not $FeatureTitle) { $FeatureTitle = "PR #$PrNumber" }

  $rows = Get-ChildItem $dest -File | Where-Object { $_.Name -ne "README.md" } | Sort-Object Name | ForEach-Object {
    "| ``$($_.Name)`` | (see Notes) |"
  }
  $readme = @"
# Review artifacts — PR #$PrNumber

## Feature
$FeatureTitle

## Commit
``$FeatureCommit``

## Artifacts

| File | What it shows |
|---|---|
$($rows -join "`n")

## Notes
Visual review pack for PR #$PrNumber. Prefer numbered filenames; update this table if labels are vague.
"@
  Set-Content -Path (Join-Path $dest "README.md") -Value $readme -Encoding utf8

  git add -- $destRel
  $pending = git status --porcelain -- $destRel
  if (-not $pending) {
    Write-Host "No changes to publish."
  } else {
    git commit -m "chore(review-artifacts): publish PR #$PrNumber $Slug"
    if (-not $SkipPush) {
      git push -u origin review-artifacts
    }
    Write-Host "Published: $destRel"
    Write-Host "Commit: $(git rev-parse --short HEAD)"
  }
}
finally {
  git checkout $prevBranch
  if ($stashNeeded) {
    git stash pop
  }
}
