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

## Codex Issue Fix Workflow

このリポジトリで GitHub issue を並列修正する場合は、以下を基本手順にする。

- 先に GitHub issues と Project `coa_tools2 tasks` を確認し、重要度・衝突リスク・検証容易性で作業順を決める。
- issue ごとに 1 worktree / 1 branch を割り当てる。
- branch は通常 `develop` 起点で `codex/issue-<番号>-<短い説明>` を作る。`master` 向けは release / hotfix だけにする。
- 古い issue branch がある場合も、そのまま作業せず、現在の `develop` 起点 branch から必要な差分だけ参照する。
- subagent を使う場合は、担当 worktree、対象 issue、編集してよい範囲、検証条件、コミット方針を明示する。
- subagent には「他 agent も同時に作業しているため、別 worktree や他者の変更を戻さない」と必ず伝える。
- 現在の subagent tool で `gpt-4.5` を指定できない場合は model override を省略し、`reasoning_effort` を `high` または `xhigh` にする。
- DCC 実機検証（Blender / Krita / GIMP）は main agent が直列で行う。GUI やユーザー設定を同時に触る検証は subagent に並列実行させない。
- PR はユーザーが明示した場合を除き draft にせず、通常の ready for review として作成する。
- PR title / body は英語で書く。内部メモやユーザー向け報告は日本語でよい。
- GitHub PR body は `--body-file` を使い、PowerShell で `\n` がリテラル化しないようにする。
- 完全に修正できた issue は `Fixes #...`、部分修正や関連確認は `Refs #...` を使う。
- PR 作成後は、対応 issue と PR の Project Status を `In review` にする。
- Krita / GIMP のユーザー plugin フォルダを検証で触る場合は、必ず事前バックアップし、検証後に元へ戻す。
