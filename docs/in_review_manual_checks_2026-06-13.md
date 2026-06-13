# In review項目の手動確認手順 (2026-06-13)

このメモは、GitHub Project `coa_tools2 tasks` で `In review` に入っている issue の手動確認手順をまとめたものです。

## 2026-06-13 時点の確認メモ

- `#6`: 手動確認 OK。close 候補。
- `#18`: operator 自体は存在するが、現状の UI から `Copy Mesh Data` ボタンを見つけられていない。機能未完扱いが妥当。
- `#70`: GIMP 3.2 実機確認で未解決。後述の通り `gimpfu` 依存で読み込みに失敗する。
- `#74`: `setPixelData(..., 0, 0, ...)` の本件は低レベル export では通過した。ただし Krita docker の初期化に別不具合がある。
- `#92`: 手動確認 OK。close 候補。
- `#94`: 依存未導入時の GUI 導線はまだ再確認中。background 実行では別 issue のクラッシュを確認済み。

## 共通の前提

- 想定 Blender: `Blender 5.1.x`
- 推奨サンプル: `samples/sprite_example/test.blend`
- ローカルソースを直接検証する場合は、この repository の最新 `coa_tools2` を使用する

## #6 Automesh from image alpha

目的: Blender 5.1 で `Automesh from Texture` が実行でき、メッシュ生成まで進むことを確認する。

手順:

1. `samples/sprite_example/test.blend` を開く。
2. `body.png` などの sprite mesh を選択する。
3. COA Tools2 の mesh 編集フローに入り、`Automesh from Texture` が使える状態にする。
4. `Automesh from Texture` を実行する。
5. 必要に応じて `Resolution`、`Threshold`、`Margin` を調整して再実行する。

期待結果:

- traceback や致命的エラーが出ない。
- 画像 alpha に基づいて mesh が更新される。
- Blender 5.1 上で operator が完了する。

## #18 Copy mesh / weight / shapekey between sprites

目的: 少なくとも copy 挙動が動作することを確認する。

手順:

1. `samples/sprite_example/test.blend` を開く。
2. `body.png` などの mesh sprite を複製し、転送先を作る。
3. Object Mode で元 sprite を active object にする。
4. 複製した mesh も選択状態にする。
5. `Copy Mesh Data` を実行する。

期待結果:

- operator がエラーなく完了する。
- vertex group が転送先 mesh にコピーされる。
- mesh データの再投影まで進む。

補足:

- これは live-link の確認ではない。
- copy だけ動いて link / sync が未対応なら、issue は open のままにする。
- 2026-06-13 時点では、operator の直接実行は通る一方で、UI から実行する導線が見当たっていない。

## #70 GIMP 3.0.x export

目的: GIMP 3.x で exporter が読み込まれ、少なくとも Python 構文エラーで即死しないことを確認する。

前提:

- GIMP 3.x がインストールされている
- この repository の `GIMP/coatools_exporter.py` を GIMP の plugin path に配置している

手順:

1. `GIMP/coatools_exporter.py` を GIMP 3.x の plugin としてインストールする。
2. `samples/sprite_example/sprite_example.xcf` を GIMP 3.x で開く。
3. COA Tools exporter を実行する。
4. 一時出力フォルダを指定して export する。

期待結果:

- GIMP 3.x 上で exporter が読み込まれる。
- 起動時に Python 構文エラーが出ない。
- JSON と sprite 画像が出力される、または少なくとも export ロジックに進む。

2026-06-13 実機結果:

- GIMP `3.2.4` で確認。
- 旧 README のとおり `plug-ins/coatools_exporter.py` 直下に置くと、`プラグインはサブディレクトリにインストールされている必要があります` でスキップされた。
- `plug-ins/coatools_exporter/coatools_exporter.py` に配置し直すと、今度は `ModuleNotFoundError: No module named 'gimpfu'` で読み込み失敗した。
- つまり、現状の exporter は GIMP 3 系の Python plugin API には未対応。

## #74 Krita export exception

目的: Krita export 時に `setPixelData(..., 0.0, 0.0, ...)` の型エラーが出ないことを確認する。

前提:

- Krita がインストールされている
- `Krita/coa_tools2_exporter` を Krita plugin としてインストールしている

手順:

1. Krita exporter plugin をインストールする。
2. export 可能な layered sample を開く。環境次第では `samples/sprite_example/sprite_example.psd` を使用する。
3. Krita の docker / panel から COA Tools exporter を実行する。
4. 一時出力フォルダを指定して export する。

期待結果:

- `TypeError: setPixelData ... argument 2 has unexpected type 'float'` が出ない。
- export が正常完了するか、少なくとも別の理由で止まる。

2026-06-13 実機結果:

- Krita `5.x` 上で、`exportNode()` を直接呼ぶ低レベル検証では PNG 出力に成功した。
- この経路では `setPixelData(..., 0, 0, ...)` が正常に通っており、本件の float 型エラーは再現しなかった。
- ただし docker の通常初期化では別不具合があり、`COATools2Docker.__init__()` の `super().__init__(self, *args, **kwargs)` で `TypeError: DockWidget(): too many arguments` が発生する。
- この docker 初期化不具合は別 issue `#122` として起票済み。
- そのため、issue `#74` の本件自体はかなり解消済みだが、Krita exporter 全体の実用確認は `#122` を解消してから再確認するのが妥当。

## #92 Edit Weights in Blender 5.0 / 5.1

目的: Blender 5.1 で `Edit Weights` が weight paint workflow に入れることを確認する。

手順:

1. `samples/sprite_example/test.blend` を開く。
2. `body.png` など、armature に bind 済みの mesh sprite を選択する。
3. COA Tools2 panel から `Edit Weights` を押す。

期待結果:

- Blender が Weight Paint mode に切り替わる。
- `Bone.select` や `Bone object has no attribute select` 系の Blender 5.x API エラーが出ない。
- COA Tools2 の weight 編集フローが使える。

## #94 Missing numpy / cv2 guidance for Automesh

目的: 依存未導入時に、生の失敗ではなくガイド付きで案内されることを確認する。

前提:

- `numpy` / `cv2` が COA Tools2 から見えない環境で試す
- または、テスト前に add-on vendor dependency folder を一時退避する

手順:

1. `samples/sprite_example/test.blend` を開く。
2. `body.png` などの sprite mesh を選択する。
3. mesh 編集フローを開く。
4. 依存未導入のまま `Automesh from Texture` を実行する。

期待結果:

- 分かりやすいエラー / ガイドが表示される。
- Preferences と `Install numpy / opencv` 操作へ誘導される。
- uncaught traceback だけで終わらない。

その後、依存導入後の再確認:

1. add-on の dependency installer を実行する。
2. 再度 `Automesh from Texture` を実行する。

期待結果:

- 依存導入後は Automesh が正常に動作する。

2026-06-13 自動確認メモ:

- `dependency_manager.install_dependencies()` による導入後は、Blender 5.1 で `Automesh from Texture` 自体は完了した。
- 一方で、background 実行で dependency installer operator を直接叩くと別 issue のクラッシュを確認している。
- 依存未導入状態での GUI メッセージ導線は、対話環境での再確認がまだ必要。
