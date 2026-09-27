# Review artifacts — PR #61

## Feature
Kraken V1.0 release — versioning, About UI, CHANGELOG

## Commit
`abbb671` (merged release infra) + follow-up human changelog PR #62

## Artifacts

| File | What it shows |
|---|---|
| `01-version-sidebar.png` | USER mode sidebar with `Kraken V1.0` entry and role switch |
| `02-about-user.png` | USER About / version history view (no build SHA internals) |
| `03-about-owner.png` | OWNER About with Version / tag / commit / build time |

## Notes
- Live runtime mounts release worktree (not dirty `E:\!AI\ProjectAI`)
- Backend/frontend version `1.0.0`, commit metadata `abbb671…`
- Presentation USER/OWNER is not IAM

## Cleanup
Remove this directory after review + successful `v1.0.0` release (see `.cursor/rules/40-review-artifacts.mdc`).
