# Graph State Rig / Lip Sync preset 設計

## 目的

Graph State Rig は、既存の State Rig を「等間隔の LINEAR / Matrix」から、任意位置に置いた名前付き状態へ拡張するものです。アニメーターが Pose Bone の2Dハンドルを直接動かす操作は変えず、音声解析や専用 Shape Key の作成を前提にしません。

既存機能は非破壊で維持します。

- `LINEAR_1D`: 等間隔の1次元状態
- `MATRIX_2D`: 任意列・行の双線形補間とセルごとの Mix Domain
- `GRAPH_2D`: 任意の名前・位置・fallback edge を持つ状態

`Setup Rig States` の LINEAR / Matrix 自動生成、既存の binding、State Point UUID、Shape Key driver は従来どおり利用できます。

## データモデル

Graph State は、Control ごとに次を保持します。

- `graph_interpolation`: `NAMED_GRAPH` / `MAP_2D` / `HYBRID`
- `graph_radius`: 近傍補間の影響半径
- `lip_sync_preset`: プリセット由来を示すメタデータ
- `graph_custom_object`: 生成baseを置き換える任意の Custom Shape object

各 State Point は次を保持します。

- 永続 UUID と表示名
- Control 内の正規化2D座標 `(0..1, 0..1)`
- 表示shapeと任意の custom object 参照
- 明示的な fallback State UUID
- Shape Key 名候補
- phoneme alias
- 従来と同じ target object / Shape Key / intentional empty / enabled

名前やObject名ではなく UUID で接続するため、ユーザーによるボーン・Objectのrename後も driver の識別子は変化しません。保存・再読込時も同じ定義を使って再評価します。

## 補間

### 2D Mouth Map (`MAP_2D`)

全enabled pointに対する距離ベースのweightを正規化します。Point座標上では必ず one-hot になり、それ以外では連続値になります。`graph_radius` は近い状態をどの程度強く選ぶかを調整します。

### Named Graph (`NAMED_GRAPH`)

明示した fallback edgeへqueryを射影し、edge端点間を連続補間します。fallbackが未設定の孤立点は、編集途中でも操作不能にならないよう、決定的な最近傍edgeを補います。Viewport handleは生成railへShrinkwrapされます。

### Hybrid

Named point付近では2D Map、離れた領域ではfallback edgeを優先します。口形の局所mixと、定義外領域での安全な遷移を一つのControlで併用する用途です。Handleは矩形内を自由に操作できます。

## Driver runtime

Graph全体の数式を各Blender driver expressionへ展開すると、Point数に比例して式が長大になります。そのためdriverは次の短い呼出だけを保存します。

```text
coa_graph_state_weight(rig_uuid, control_uuid, state_uuid, state_x, state_y)
```

runtimeは永続UUIDから現在のRNA定義を解決し、pure PythonのGraph evaluatorを呼びます。Blenderのdriver namespaceへAddon登録時と`load_post`で再登録するため、保存再読込後も手動操作できます。無効・欠損データはdriver評価を停止させず `0.0` にfallbackします。

## Geometry Nodes presentation

Graph baseはState Rigと同じ、面を持たないエッジ主体のトーンです。

- point座標とfallback edgeをControl固有のsource meshへ格納
- Pointごとの `CIRCLE` / `TRIANGLE` / `SQUARE` / `DIAMOND` をmesh attributeへ格納
- `CUSTOM_OBJECT` は元objectを変更せず、評価済みローカルXY edgeをnode半径へ正規化してPoint overlayとして格納
- 共有 `COA_RigWidget_Graph_GN` がattributeを読み、rail幅とnode半径からoutlineを生成
- 既定backendではproduction GN sourceを評価し、Custom Shape用mesh cacheを作成
- Live Modifierを選んだ場合はsourceを直接Custom Shapeに使用

これにより、共有Node GroupをPoint数ごとに複製せず、Controlごとの差はsource geometryとパラメーターだけになります。ユーザー指定の `graph_custom_object` は生成baseを置き換えますが、Addon管理外objectの可視状態やdataは変更しません。

## Lip Sync preset

`Add Lip Sync State Rig` はGraph State Controlと未割当target slotを生成します。音声ファイルの解析、Shape Keyの追加・rename、既存キーの上書きは行いません。`Match Existing Shape Keys` を明示した場合だけ、候補名に一致する既存Shape Keyを割り当てます。

未割当slotは構造エラーではなく `state.unassigned_point` warningです。候補名を保ったまま手動操作・保存でき、必要な口形だけを後からAssignできます。

| Profile | 生成する名前付き状態 |
|---|---|
| `MINIMAL` | REST, A_E, I, U_O |
| `JP_VOWELS` | REST, A, I, U, E, O |
| `JP_VOWELS_MBP` | REST, A, I, U, E, O, MBP |
| `STANDARD_2D` | REST, MBP, ETC, E, AI, O, U |
| `STANDARD_2D` optional | 上記 + FV, L, WQ |
| `ADVANCED_PHONEME` | Standard + FV, L, WQ とphoneme alias |

Advancedのalias解決では、既知phonemeを対応visemeへ、未知tokenを `ETC` へfallbackします。これは将来、外部の音素タイミングを受けるための名前変換であり、手動ハンドルを置き換えるものではありません。

## 基本ワークフロー

1. `Add State Rig > 2D Rectangle > State Graph`、または `Add Lip Sync State Rig` を実行する。
2. State名・正規化位置・fallbackを編集する。
3. 必要なStateだけ、既存MeshのShape Keyへ `Assign` する。
4. `MAP_2D` / `NAMED_GRAPH` / `HYBRID` とradiusを選ぶ。
5. Pose ModeでTipを直接動かし、必要に応じてkeyframeを打つ。

Live Previewが有効なら定義変更を自動再構築し、無効なら `Rebuild Now` まで現在のartifactを維持します。

## 検証範囲

`scripts/blender_rig_phase10_graph_lipsync_test.py` は次を一つのclean Blender sessionで確認します。

- 任意位置・名前・fallbackを持つGraphの生成
- 実Pose handle移動による近傍weight変化
- fallback変更によるweight変化
- production Graph GN sourceと評価済みCustom Shape cache
- 全Lip profileとStandard optionalの生成件数
- Shape Keyを自動生成しないこと
- 音声なしの手動操作
- compact driver expressionとnamespace
- `.blend` 保存・再読込後の位置、fallback、候補名、driver、widget
