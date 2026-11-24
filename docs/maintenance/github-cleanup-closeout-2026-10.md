# Kraken GitHub cleanup — closeout (28 October 2026)

Status: cleanup complete for verified obsolete remote branches; local worktrees with uncommitted or unmerged content intentionally preserved.

## Confirmed remote snapshot before this closeout

- Repository: UberSerg/ProjectAI
- Default branch: `main`
- Main HEAD: `76877439351559e25d7ed35f2cdecedd25c1bb97`
- Remote branches after two cleanup waves: **8**, down from **68**
- **60 remote branches removed** from merged PRs after exact SHA/PR verification and backup checks
- Remote branches deliberately preserved: `main`, `review-artifacts`, `feature/brain-foundation-v2`, `feature/dataset-v4-research-foundation-v1`, `feature/dividend-pit-calendar-historical-universe-v3`, `feature/fundamental-provider-coverage-v1-1`, `feature/kraken-personal-v1-dark-dashboard`, `feature/shadow-catchup-role-views-v1`
- Remote cleanup did not mutate `main` or `E:\hds-live-store`

## Local cleanup reported by Cursor (not independently inspected from GitHub)

- Worktrees: 108 → 62 (46 clean completed worktrees removed without force)
- Local branches: 148 → 64 (84 removed after ancestry/squash-merge and bundle verification)
- Dirty/active worktrees, including project checkout and agent worktrees, preserved
- Backup: `E:\repo-backups\ProjectAI-pre-cleanup.bundle`
- SHA manifest: `E:\repo-backups\ProjectAI-pre-cleanup-manifest.json`
- Original detailed report remains uncommitted locally at `docs/maintenance/github-branch-cleanup-report.md`, in a checkout containing unrelated changes. **Do not overwrite it**; reconcile separately if it is ever committed.

## Legacy PR disposition

- **#31**: closed as superseded without merging. Existing FNS GIR BO path and historical FNS adapter are in current main; authenticated e-disclosure gateway needs a new scoped PR if ever required.
- **#58**: preserved, not merged. Broad old diff conflicts with newer Dataset and Historical Engine. Only potentially useful delta is MOEX ISS session-calendar support for dividend entitlement / `last_eligible_trading_date`. Reimplement in a new focused PR from current main; test the 2024-01-03..05 sessions against a real dated exchange-session source and the current workday fallback. Preserve honest unknown/coverage states. Do not modify Dataset V3/V4 or Historical Engine in this cleanup.

## GitHub configuration still requiring an admin action

At the time of inspection, `delete_branch_on_merge = false`.

Enable: **Settings → General → Pull Requests → Automatically delete head branches**.

Also consider a branch ruleset for `main` prohibiting force pushes and deletions, and requiring PR plus relevant passing CI checks. Test permissions and workflow impact before enabling enforcement.

## Completion criteria

This cleanup is complete when this documentation PR is merged and branch auto-deletion is enabled. Do not delete preserved dirty worktrees or #58 just for a lower branch count.

Historical data live outside git; the repo cleanup does not migrate or back up those datasets.
