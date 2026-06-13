# Codex で複数 issue を並列対応する運用メモ (2026-06-13)

このメモは、`coa_tools2` で複数の issue を Codex と worktree で安全に並列処理するための実務向けメモです。

## 結論

この repo では、次の運用が一番事故が少ないです。

1. GitHub Project `coa_tools2 tasks` を単一の進捗ソースにする
2. issue ごとに branch / worktree を 1 つ切る
3. 1 worktree につき 1 本命 agent を置く
4. subagent は「探索」「調査」「限定的な補助実装」にだけ使う
5. `master` 直編集は避け、通常修正は `develop` 起点で進める

同じ checkout で複数 issue を同時に触る運用は、差分混線とレビュー負荷が高いので避けた方がよいです。

## 背景

OpenAI の Codex 公式 docs では、subagents は並列タスク向け、`AGENTS.md` は永続的な作業ルール向け、worktrees は並列コード変更を分離する手段として案内されています。  
また Git 公式 docs でも、`git worktree` は同一 repository で複数 branch を同時 checkout するための標準機能です。

この repo では Blender / Krita / GIMP / Photoshop など対象が分かれているため、issue ごとに検証環境や変更箇所が分かれやすく、worktree 分離と相性がいいです。

## この repo での推奨ルール

### 1. Project を起点にする

修正前に、対象 issue が Project にあり、status が適切か確認します。

- `Backlog`: 未着手
- `Ready`: すぐ着手してよい
- `Pending`: blocker 待ち
- `In progress`: 実装中
- `In review`: 実装済みまたは部分修正済みで、手動確認待ち
- `Done`: close 済み

実装 agent には「まず project を見て、自分の issue の status を更新する」ことを必須にするのがよいです。

### 2. 通常修正は `develop` 起点

この repo のブランチ方針では、

- `master`: 安定版
- `develop`: 統合ブランチ

です。  
したがって、通常の機能修正や通常バグ修正は `develop` 起点に寄せるのが自然です。

例外:

- リリース済み不具合を急いで直すときは `codex/hotfix-*`

## 推奨ディレクトリ構成

親ディレクトリに worktree 用フォルダを切ります。

```powershell
mkdir ..\wt -Force
```

例:

```text
..\wt\issue-122-krita-docker
..\wt\issue-70-gimp3
..\wt\issue-94-automesh-deps
```

## 推奨ブランチ命名

通常修正:

```text
codex/issue-122-krita-docker
codex/issue-70-gimp3
codex/issue-94-automesh-deps
```

緊急 hotfix:

```text
codex/hotfix-<short-name>
```

## 実際の開始手順

### 方式 A: Git worktree + Codex CLI / Codex App

`develop` から issue ごとの worktree を作る例です。

```powershell
git fetch origin
git worktree add ..\wt\issue-122-krita-docker -b codex/issue-122-krita-docker origin/develop
git worktree add ..\wt\issue-70-gimp3 -b codex/issue-70-gimp3 origin/develop
git worktree add ..\wt\issue-94-automesh-deps -b codex/issue-94-automesh-deps origin/develop
```

その後、各 worktree で別々に Codex を起動します。

```powershell
codex --cd ..\wt\issue-122-krita-docker
codex --cd ..\wt\issue-70-gimp3
codex --cd ..\wt\issue-94-automesh-deps
```

Codex App を使う場合も、project として各 worktree を開けば同じ考え方で運用できます。

### 方式 B: Codex App の built-in Worktree

Codex App の公式 docs では、worktree は「同じ project で複数の独立タスクを干渉なく走らせる」ための機能として案内されています。  
App 側で Worktree thread を作る方法は、手作業で `git worktree add` しなくて済むので楽です。

ただしこの repo では Blender / GIMP / Krita のローカル検証が入るため、初回は setup の見通しが立ちやすい手動 worktree の方が管理しやすいです。

## subagent の使い分け

subagent は便利ですが、書き込みを広げすぎると逆に壊れます。  
この repo では次の使い分けを推奨します。

### 良い使い方

- `explorer`:
  - issue の再現条件調査
  - 関連ファイルの洗い出し
  - upstream / commit / PR の追跡
- `worker`:
  - 明確にファイル範囲が分かれている補助修正
  - テスト追加
  - docs 更新

### 避けたい使い方

- 同じ worktree で複数 worker に同じファイル群を触らせる
- Blender operator 本体と UI 本体を別 agent が同時編集する
- 1 issue の主修正を 2 agent 以上で並列に書かせる

## この repo 向けの役割分担

### 1 issue = 1 本命 agent

本命 agent は次を担当します。

- 再現
- 実装
- ローカル検証
- issue / project 更新
- 最終 diff 整理

### 補助 agent

必要なら 1 〜 2 個まで。

例:

- `#122` Krita docker:
  - 本命: exporter 実装修正
  - 補助: Krita API 変更点調査
- `#70` GIMP 3:
  - 本命: GIMP 3 対応実装
  - 補助: GIMP 3 Python plugin API 調査
- `#94` dependency guidance:
  - 本命: UI 導線修正
  - 補助: Blender background / modal クラッシュ原因調査

## AGENTS.md の使い方

OpenAI 公式 docs では、Codex は作業前に `AGENTS.md` を読み、root から現在ディレクトリまでの instructions を順に積み上げます。  
この repo ではすでに root の `AGENTS.md` があるため、通常はそれで十分です。

必要なら、worktree 内で issue 専用の補助メモを別 markdown として置き、prompt から明示参照するのが安全です。  
issue ごとに一時的な作業ルールを root `AGENTS.md` に増やし続ける運用は、ノイズが増えやすいので勧めません。

## local environment / setup script

Codex App の公式 docs では、worktree は別ディレクトリで動くため、依存や build 生成物が足りず、そのために setup script を自動実行できるとされています。

この repo では特に次が候補です。

- Blender 検証用 user scripts の準備
- Python 依存の初期導入
- サンプルファイルのコピー
- 共有テストコマンド

たとえば `.codex` 配下で共有したいのは次のようなものです。

- `Blender 5.1 で addon を current source から読む準備`
- `validation_work/` の初期化
- `pytest` や lint 相当の共通 action

ただし、まだこの repo は DCC アプリ依存の手順が多いので、最初から自動化しすぎず、まずは docs 化してから script 化するのがよいです。

## 実運用フロー

### 着手前

1. issue を選ぶ
2. project status を `In progress` にする
3. `develop` 起点で worktree を作る
4. worktree で Codex を起動する
5. prompt で issue 番号、目的、禁止事項を書く

### 実装中

1. 再現手順を docs または issue comment に残す
2. 修正
3. ローカル検証
4. 必要なら subagent で補助調査
5. 途中で project を更新

### 実装後

1. issue に確認手順をコメント
2. project を `In review`
3. 人手確認
4. OK なら close
5. project を `Done`

## prompt テンプレート

### 本命 agent 用

```text
Issue #122 を対応してください。
作業対象はこの worktree 配下だけです。
まず GitHub Project `coa_tools2 tasks` を確認し、この issue の status を `In progress` にしてください。
再現、修正、ローカル検証、issue への結果コメントまで実施してください。
他の issue の変更は混ぜないでください。
```

### explorer 用

```text
Issue #70 の GIMP 3 対応について、現行コードで GIMP 2 系依存になっている箇所を洗い出してください。
編集は不要です。関連ファイル、API 差分、移植方針だけ報告してください。
```

### 補助 worker 用

```text
Issue #94 の補助作業です。
担当は docs と確認手順の整理だけです。
実装本体には触れず、変更ファイルは docs 配下のみに限定してください。
```

## どの issue から並列化しやすいか

並列化しやすい順に挙げると次です。

1. `#122` Krita exporter docker 初期化
2. `#70` GIMP 3 exporter
3. `#94` dependency guidance
4. `#18` copy/link mesh data

理由:

- `#122` と `#70` は対象アプリが別で、ファイル範囲がほぼ衝突しない
- `#94` は Blender add-on 側だが、主に dependency / UI 導線
- `#18` は UI と operator 仕様が絡むため、少し設計判断が必要

## 今は避けた方がよい並列化

- `#18` と別の Blender UI 大改修 issue を同時に走らせる
- 同じ `coa_tools2/operators/` 配下を複数 issue で同時多発に触る
- issue 未分解の大きい改善を 1 本の worktree に詰め込む

## 参考リンク

- OpenAI Codex Subagents  
  https://developers.openai.com/codex/subagents
- OpenAI AGENTS.md  
  https://developers.openai.com/codex/guides/agents-md
- OpenAI Codex App Worktrees  
  https://developers.openai.com/codex/app/worktrees
- OpenAI Codex App Local Environments  
  https://developers.openai.com/codex/app/local-environments
- OpenAI Codex Best Practices  
  https://developers.openai.com/codex/learn/best-practices
- Git worktree 公式  
  https://git-scm.com/docs/git-worktree
