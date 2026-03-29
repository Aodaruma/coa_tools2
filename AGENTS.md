# Release and Branch Playbook

This repository uses two long-lived branches:
- `master`: stable branch for release-ready code
- `develop`: integration branch for ongoing work

## Pull Request Rules

- PRs into `master` must come from one of:
  - `develop`
  - `hotfix-*`
  - `codex/hotfix-*`
- For urgent production fixes, use `hotfix-*` (or `codex/hotfix-*`) and merge to `master` first.
- After hotfix merge to `master`, sync `master` back into `develop`.

## Tag Rules

- Stable release tag (from `master`): `vX.Y.Z`
  - Example: `v2.2.0`
- Prerelease tag (from `develop`): `vX.Y.Z-bN`
  - Example: `v2.1.3-b1`

## Automated Release Workflow

Workflow file:
- `.github/workflows/create-release-from-tags.yml`

Behavior:
- On tag push `v*`, validate format and source branch.
- Build zip assets for:
  - `GIMP`
  - `Krita`
  - `coa_tools2`
  - `Photoshop`
  - `Godot`
- Create GitHub release draft:
  - `vX.Y.Z` => stable draft release
  - `vX.Y.Z-bN` => draft prerelease

## Manual Fallback (if automation fails)

1. Check workflow logs and fix root cause if needed.
2. If release is urgent, create release manually from the same tag.
3. Upload the same five zip assets listed above.
4. Keep title/notes consistent with tag type (stable vs prerelease).

## Branch Cleanup Policy

- Delete remote branches only when they are clearly merged into `master` or `develop`.
- Do not delete branches that still contain unique commits.
- Keep active work branches until the owner confirms cleanup.
