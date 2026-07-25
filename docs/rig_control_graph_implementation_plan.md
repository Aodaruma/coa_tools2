# COA Tools 2: Rig Control / Rig Graph 統合設計・実装方針

更新日: 2026-07-25

## 1. この文書の目的

本書は、次の3案を比較し、COA Tools 2の実コードへ段階的に落とすための統合方針を定める。

- 既存の[2Dリグコントローラー調査・設計案](rig_control_design.md)
- 共有案A: `coa_tools2_rig_graph_design.md`
- 共有案B: `coa_tools2_rig_graph_implementation_spec.md`

既存案はViewportで操作する2Dコントローラーを中心にしている。共有案A/Bは、それらを再利用可能な宣言データから生成・再生成するRig Graph Compilerを中心にしている。両者は競合案ではなく、前者がユーザーに見える操作層、後者がその構築と保守を担う上位層である。

本書の結論は、汎用Rig Graphを先に完成させるのではなく、1D Sliderの縦切り実装でBlender固有の制約を検証し、その実装から汎用化できる境界を抽出する、というものである。

### 1.1 実装状況

Phase 0〜3に加え、Phase 4AとしてShape Keyを対象にした連続StateDataを実装済みである。

- リグの外郭だけを先に作り、後から各State PointへShape Keyを割り当てられる。
- 1Dは2点以上、2D Matrixは任意の`columns × rows`を保存する。
- `2×2`、`3×2`、`2×4`のUI PresetとCustom Resizeを持つ。
- Add Rigでは`2D Rectangle`のModeとしてFree、Grid Rails、State Matrixを選ぶ。
- 各State Shape Keyへ区分線形基底またはBilinear Weight Driverを生成する。
- State PointのAssign、明示的なEmpty、Snap、Validate、Repairに対応する。
- 行列拡張時は既存座標の割当を維持し、縮小で失われる割当を一覧Previewして確認を要求する。
- Matrix専用の共有`COA_RigWidget_Matrix_GN`から、外枠と任意数の状態点を生成する。
- Save/Reload後もState Point割当とDriver評価を維持する。

`FULL` Mixではセル内部を連続補間するため、Matrix Baseに内部Railを描かず、Control Boneを矩形内部で自由移動させる。通常の`Rectangle Grid`は内部Railを描き、Rail上だけを動く別Presetとして維持する。内部Railと部分的な遷移を組み合わせる`MASKED` Mix、Triangle State、複数Bone/Propertyを束ねる汎用Pose StateはPhase 4B以降とする。

## 2. 結論

推奨する最終構造は、次の4層である。

1. **Animator Interface**: Bone TransformまたはCustom Propertyとして公開される、安定した操作点
2. **Rig Definition**: `ControlSpec`、`BindingSpec`、将来の`PoseStateSpec`から成る宣言データ
3. **Planner / Compiler**: 検証、正規化、生成計画、Blenderデータへの適用、修復
4. **Blender Artifacts**: Bone、Constraint、Driver、Widget Mesh、Propertyなどの実行物

ただし、実装順は下層から汎用的に作るのではなく、次の順とする。

1. Geometry Nodesで円と矩形バーを合成するWidget基盤と、1D Slider BoneからShape Keyを制御する最小機能を実装する。
2. 同じ機能を再生成・修復できる最小Schema、所有タグ、検証器を整える。
3. 2D、Dial、複数Binding、任意列×行の2D State Matrixへ広げる。
4. 実例が蓄積した時点で、必要な範囲だけを型付きRig Graphへ一般化する。

これにより、共有案の長期的な保守性を採り入れながら、Issue [#47](https://github.com/Aodaruma/coa_tools2/issues/47)のユーザー価値を早期に検証できる。

### 2.1 採用する原則

- 公開Controlと生成物を分離する。
- Controlには不変のUUIDとSemantic IDを持たせる。
- 再生成可能なデータと、Animatorが作るAnimationを分離する。
- 生成物には所有者、役割、Schema/Compiler Versionを記録する。
- Compileは同じ入力に対して冪等にする。
- 通常再生時の評価はBlender標準のDriver、Constraint、F-Curveに任せる。
- Pythonのframe handlerや任意コードを通常評価経路へ入れない。
- 公開ControlだけをKeyableにし、内部値は派生値とする。
- 離散的なRig Mode、連続的なPose State、構造的なRig Variantを分ける。
- CoreとBlender依存部の境界は初期から設けるが、Coreを目的化しない。
- Widgetは共有Geometry Node Groupと型付きParameterから生成し、Preset間で同じPrimitiveを再利用する。

### 2.2 初期には採用しないもの

- 汎用Node Editor
- 任意Python Nodeや任意Driver Namespace Function
- すべてのRigを表現する巨大なNode Registry
- 3Dから2DへのProjection / Inverse Solver
- Category Theory上の一般性をコード要件にすること
- Slot Indexを直接Driver制御する標準Binding

これらを否定するものではない。初期のIssue #47を越える研究・製品スコープであり、基礎の安定後に個別の採否を判断する。

## 3. 3案の比較

| 観点 | 既存Control設計 | 共有案A: Rig Graph設計 | 共有案B: Compiler仕様 |
| --- | --- | --- | --- |
| 主な目的 | 2D Animator向け操作体験 | Rig構築の宣言化・再利用・逆問題への発展 | 汎用Compilerを実装可能なSchemaへ具体化 |
| 主役 | Slider Bone、Widget、Binding、StateData | Typed Graph、Public Control、Component | Node/Port/Connection、JSON、Pipeline |
| ユーザー価値の出る地点 | 最初のSlider生成時 | Compilerで複数Rigを生成できた時 | Storage/Core/Compilerが揃った時 |
| 初期実装可能性 | 高い | 概念単位では高いが全体は研究規模 | 個々は可能だがMVP範囲が広い |
| COA Tools 2との適合 | 現行Bone、Action、Exporterへ直接接続できる | 長期構造に適合する | 現行の登録・テスト構造に対して大きい |
| UX | Viewport中心で明快 | 最終的にはPreset/UIが必要 | JSON/Inspector先行では一般ユーザーに遠い |
| 保守性 | 小規模では良いが、手続き的生成だけでは伸びにくい | Stable ID、再Compile、Migrationに強い | Ownership/Diff/Validationが具体的で強い |
| 主なリスク | 機能追加ごとの分岐増加 | 抽象化先行、Schemaの早期固定 | 最初の可視成果までの距離、実装面積 |
| 将来性 | Rig Graphの実行Backendになれる | 最終アーキテクチャ候補 | 段階導入すれば実用的な設計資産になる |

### 3.1 既存Control設計の強み

- Issue #47の1D、2D、円、回転Sliderへ直接対応する。
- 現行のPose Bone Transform keyingとCustom Shape作成を再利用できる。
- DriverやConstraintが実際に保存、複製、Render、Exportできるかを早期に検証できる。
- AnimatorにJSONやNode Graphを意識させずに価値を提供できる。

弱点は、各Presetを個別Operatorとして増やすだけでは、再生成、Migration、複数Binding、共有Componentの管理が難しくなる点である。

### 3.2 Rig Graph設計の強み

- Rig定義を生成物から分離し、再現可能にできる。
- Semantic IDを公開ABIとして扱える。
- Shape Key、Constraint、Alpha、Zなど異種Targetを一つのControlへ束ねられる。
- Characterごとの差分をPreset、Component、Variantとして管理できる。
- 将来のValidation、Migration、Dry Run、Diff、Projectionへ拡張しやすい。

弱点は、Blender上で成立する最小例より先に汎用型、Graph rewrite、Transaction、Node Registryを設計すると、実利用から得られる制約をSchemaへ反映できない点である。

### 3.3 Compiler仕様の強みと修正点

共有案Bの次の部分は、初期実装にも採用価値が高い。

- Pure CoreとBlender Backendの分離
- Validation Issueの構造化
- PlanningとApplyの分離
- Artifact Ownership Tag
- Idempotent Recompile
- Migration Version
- Public ControlのみをKeyableにする方針
- Pure Python TestとBlender Headless Testの併用

一方、次の点は初期MVPでは修正する。

- `Pure Graph Core`単体を最初の製品実装にしない。1D Sliderの縦切りでCoreの必要形を決める。
- Float Controlを一律Custom Propertyにしない。空間的ControlはBone Transformを正本とする。
- `coa.slot_index`をMVP Bindingから外す。
- Canonical JSON Textを初期から唯一の正本にはしない。
- Full Transaction、Generic Diff、SCC Cycle処理は、最小Compileで必要な範囲から増やす。
- Projectionは別Epicとし、Issue #47のAcceptance Criteriaへ含めない。
- WidgetはStatic Mesh固定ではなく、Geometry Nodesによるパラメトリック生成をMVPへ含める。
- 2D State Gridは2×2固定ではなく、任意`columns × rows`の連続Matrixとして実装する。

## 4. 重要な設計判断

### 4.1 「Rigの定義」と「Animationの値」は別の正本である

Source of Truthという語を一つにまとめると、設計が混乱する。次の2種類を分ける。

| 種類 | v1の正本 | 内容 |
| --- | --- | --- |
| Rig Definition | SpriteObject上のPropertyGroup | Control種別、範囲、Binding、Target、Widget、Version |
| Animation | Bone TransformまたはCustom PropertyのF-Curve | Animatorが打ったKeyframeと補間 |

Driver、Constraint、Widget Meshは生成物であり、Rig Definitionから修復できる。一方、AnimationをJSON定義から毎回生成し直してはならない。

共有案のJSONは、深い任意Graphの保存、差分確認、Migrationには有利である。しかし初期の固定Schemaでは次のコストがある。

- BlenderのPointer、Undo、UI、Library Overrideとの二重管理
- Text Datablockの削除、複製、リンク時の所有関係
- JSONとPropertyGroup View Model間の同期
- AnimatorのF-Curveとは別の正本が増えることによる混乱

したがってv1はPropertyGroupをRig Definitionの正本とし、Pureな`to_dict` / `from_dict`を用意する。JSONはImport、Export、Debug、将来のGraph Asset交換形式とする。任意Graphが必要になった段階で、Text DatablockをCanonical Sourceへ昇格するかを技術スパイクで再評価する。

### 4.2 空間Controlと非空間Controlを分ける

公開値をすべてCustom Propertyへ寄せると、2Dリグの直接操作性が落ちる。逆に、すべてをBone Transformへ寄せると、EnumやModeの表現が不自然になる。

| Control | 推奨Host | 例 |
| --- | --- | --- |
| 1D / 2D Slider | Pose Bone local location | 表情、視線、口形状 |
| Dial / Arc | Pose Bone local location（円弧Rail上の評価位置から角度へ変換） | 回転、捻り、連続Parameter |
| Direct Transform | Pose Bone transform | IK Target、Body Control |
| Toggle / Enum / Rig Mode | `GLOBAL_CTRL`等のPose Bone Custom Property | IK/FK、Space、表示Mode |
| 非空間Scalar | Pose Bone Custom Property | 数値として扱う方が自然な設定 |

一つの意味値にBone TransformとCustom Propertyの両方を正本として持たせない。UIは正本を表示し、必要ならDriverで一方向に派生させる。

Graph側では両方を`PublicControl`として抽象化し、`host_kind`で区別する。これによりAnimator UXを損なわず、上位Graphから同じBinding APIを利用できる。

### 4.3 Stable IDとBlenderの名前依存を併用する

UUIDだけではF-CurveのData Pathを保護できない。Bone AnimationはBone名を含むため、公開Bone名はAnimation ABIでもある。

- `control_uuid`: 管理用の不変ID
- `semantic_id`: `face.smile`、`eyes.aim`等の意味的ID
- `display_name`: UI表示名。変更可能
- `host_name`: Bone/Property名。Keyableになった後は原則固定

v1では公開`host_name`の直接Renameを許可しない。将来Renameを提供する場合は、F-Curve、Driver Variable、Constraint Targetを一括で書き換える専用Operatorと検証が必要である。

Rig複製時は、Artifactの識別を単一UUIDではなく次の組で行う。

```text
(rig_instance_id, control_uuid, artifact_role)
```

Character Rigを複製した場合、Semantic IDとControl UUIDはTemplate上の同一性として保持できるが、`rig_instance_id`は新規にする。Compilerは常に対象SpriteObject配下へ探索範囲を限定し、別Characterの同一Controlを誤更新しない。

### 4.4 Stateの用語を分離する

3案では`State`が異なる意味で使われているため、コード上は次の用語を用いる。

| 用語 | 意味 | 例 |
| --- | --- | --- |
| `PoseState` / `StateData` | 連続補間される姿勢・Property差分 | 口形、表情、顔向き |
| `RigMode` | Rig構造は同じまま切り替える離散状態 | IK/FK、Space、表示Mode |
| `RigVariant` | 生成構造またはAsset構成そのものの差 | 腕本数、衣装構成、Atlas構成 |

Issue [#66](https://github.com/Aodaruma/coa_tools2/issues/66)は`PoseState`に相当する。Slotの置換ではなく、連続補間可能な値を中心にする。Rig Graph上のModeやVariantと同じCollectionへ混在させない。

### 4.5 Driverと評価経路

初期実装では次を標準とする。

- Bone Transformは`TRANSFORMS` Driver Variableで読む。
- 1Dは線形範囲変換とClampを基本にする。
- 2DはX/Yを独立に読み、Target Adapter側で必要なWeightへ変換する。
- 1DとFree 2DのConstraintはControl Boneの移動範囲を制限し、Grid 2DとDialは表示と同形状の非表示Rail MeshへShrinkwrapする。
- Driver Expressionは単純式に限定する。
- 任意Python、frame handler、Driver Namespace Functionを必須にしない。
- 離散値はConstant補間または専用Operatorで扱う。

複雑なState補間は、Driver Expressionを巨大化させる前に、中間Property、Shape Key、Constraint構成、Geometry Nodes等のBlender-nativeな評価方法を比較する。

### 4.6 Control、Display、Mechanism Boneを分ける

Sliderの枠とHandleを一つの移動Boneへ割り当てると、操作時に枠まで動いてしまう。Boneの役割を次のように分ける。

```text
GLOBAL_CTRLまたは部位Anchor
├── DISP_<semantic_id>     # Rail、枠、目盛。非Keyable、非Deform
├── CTRL_<semantic_id>     # Handle。Animatorが操作・Keyframe化
└── MCH_<semantic_id>_*    # 必要な場合だけ生成。非表示、非Deform
```

- `CTRL`のlocal Transformだけを公開値にする。
- `DISP`は操作範囲を示すGeometry Nodes Base Widgetを持ち、`CTRL`と同じAnchorに固定する。
- `MCH`は複雑なConstraintやSpace変換に必要な場合だけ使う。
- Widget Mesh Objectは専用Collectionへ隠し、Bone Custom Shapeとしてだけ表示する。
- Control、Display、Mechanismの全Boneで`use_deform = False`とする。

この役割分離はPresentationを差し替えてもAnimation ABIを維持するため、将来のGraph Compilerでも保持する。

## 5. 推奨データモデル

v1では一般Graphより狭い、ControlとBindingの二部モデルを用いる。これは将来Graphへ移行可能な最小IRでもある。

### 5.1 ControlSpec

```python
@dataclass(frozen=True)
class ControlSpec:
    schema_version: int
    control_uuid: str
    semantic_id: str
    display_name: str
    control_type: ControlType
    host_kind: ControlHostKind
    host_name: str
    axis: ControlAxis
    value_min: tuple[float, float]
    value_max: tuple[float, float]
    default_value: tuple[float, float]
    widget_type: WidgetType
    widget_spec_id: str
    matrix_spec_id: str | None
```

実際の保存は`Object.coa_tools2.rig_controls`のPropertyGroupとし、Compiler入口でPureな`ControlSpec`へ変換する。BlenderオブジェクトをPure Coreへ渡さない。

### 5.2 BindingSpec

```python
@dataclass(frozen=True)
class BindingSpec:
    schema_version: int
    binding_uuid: str
    control_uuid: str
    source_channel: SourceChannel
    target_kind: TargetKind
    target_ref: TargetRef
    input_min: float
    input_max: float
    output_min: float
    output_max: float
    interpolation: Interpolation
    clamp: bool
    enabled: bool
```

`target_ref`は任意Data Path文字列をユーザーへ直接入力させず、Target Adapterごとの型付き参照にする。

初期Target Adapterは次に限定する。

1. `SHAPE_KEY_VALUE`
2. `CONSTRAINT_INFLUENCE`
3. 必要性を確認後に`COA_ALPHA`
4. 安定性確認後に`COA_Z_VALUE`

`COA_SLOT_INDEX`はIssue [#62](https://github.com/Aodaruma/coa_tools2/issues/62)がCloseされ、Driver付きRenderの回帰試験を満たすまで標準Targetへ含めない。

2026-07-18時点で#62はOpenで、Project Statusは`In review`である。現行コードに評価値のClampやRender時処理の改善が見えても、Issueの再現条件を満たすDCC回帰試験が完了するまではGateを維持する。

### 5.3 WidgetSpec

Widgetの見た目をControlの意味値から独立させ、同じControlへ別Designを適用できるようにする。

```python
@dataclass(frozen=True)
class WidgetSpec:
    schema_version: int
    widget_uuid: str
    layout_kind: WidgetLayoutKind
    width: float
    height: float
    tip_radius: float
    node_radius: float
    bar_width: float
    stroke_radius: float  # 旧Tube輪郭互換と非表示Rail Targetの微小幅用
    columns: int
    rows: int
    orientation: float
    arc_start: float
    arc_end: float
    show_state_nodes: bool
    show_grid_lines: bool
```

Geometry Nodesの基本Primitiveは円`CIRCLE`と、任意Pathから内外Offsetして作る`RAIL`に限定する。`tip_radius`の既定値は`node_radius × 2`とする。参考デザインを次の合成へ正規化する。

| Widget | 円 | Rail Path |
| --- | --- | --- |
| 1D Slider | Tip、両端 | Rail |
| Dial | Tip、Ringまたは状態点 | 必要な目盛 |
| 2D Slider | Tip、四隅 | 四辺 |
| State Matrix `FULL` | Tip、各状態点 | 外枠のみ。内部は連続補間領域 |
| Triangle / Polygon | Tip、各頂点 | 回転させた各辺 |

Control BoneにはTip Widget、Display BoneにはBase Widgetを割り当てる。Source ObjectはSlider、Radial、Rectangle等の同一形態内でNode Groupを共有するが、Modifier InputとArtifact Roleは個別に持つ。全形式を一つの巨大Groupで切り替えない。

### 5.4 MatrixStateSpec

```python
@dataclass(frozen=True)
class MatrixStateSpec:
    schema_version: int
    matrix_uuid: str
    columns: int
    rows: int
    x_positions: tuple[float, ...]
    y_positions: tuple[float, ...]
    state_ids: tuple[str, ...]  # row-major, length == columns * rows
    interpolation: MatrixInterpolation
    mix_policy: MatrixMixPolicy
    clamp: bool
```

`columns`と`rows`は各2以上とし、2×2、3×2、2×4等を許可する。初期Interpolationは`BILINEAR`、Mix Policyは全セルを連続補間する`FULL`に限定する。参考デザインの「mixなし」「一部mix」は、辺・セルのMaskを明示する`MASKED`として後続実装する。

列・行の座標は初期値を等間隔にするが、不均等配置もSchema上は許可する。行列サイズの変更で既存Stateが失われる場合は、Compile前にDiffを提示して確認を要求する。

### 5.5 ArtifactTag

生成物には最低限、次を記録する。

```text
coa_rig_managed = true
coa_rig_instance_id = <uuid>
coa_rig_control_uuid = <uuid>
coa_rig_binding_uuid = <uuid or empty>
coa_rig_artifact_role = <control_bone|limit|driver|widget|frame|...>
coa_rig_schema_version = <int>
coa_rig_compiler_version = <string>
```

Blender型によってCustom Propertyを付けにくい場合は、親IDにArtifact Registryを保持し、Data Pathと役割を記録する。名前だけで所有権を判断しない。

### 5.6 将来のRig Graphへの写像

| v1 | 将来のRig Graph |
| --- | --- |
| `ControlSpec` | `PublicControl` + Control Node |
| `BindingSpec` | Connection + Output/Adapter Node |
| `WidgetType` | ControlのPresentation Metadata |
| `WidgetSpec` | Presentation Component / Widget Node群 |
| `MatrixStateSpec` | 2D Basis / State Component |
| `PoseStateSpec` | State Component / Pose Node群 |
| Artifact Tag | Compiler Ownership / Artifact Map |

この写像を守れば、v1は捨て実装にならない。Graph導入時もAnimatorのBone名、Semantic ID、F-Curveを維持できる。

## 6. Compilerの最小構造

### 6.1 推奨モジュール

```text
coa_tools2/
└── rig_control/
    ├── __init__.py
    ├── schema.py           # Enum、dataclass。bpy禁止
    ├── validation.py       # Pure validation
    ├── planning.py         # ArtifactPlan。bpy禁止
    ├── serialization.py    # dict/JSON、Migration
    └── blender/
        ├── storage.py      # PropertyGroupとの変換
        ├── artifacts.py    # Tag、探索、所有権
        ├── widgets.py      # Geometry Node Group、Modifier Input、評価Mesh Cache
        ├── drivers.py      # Driver/Constraint Adapter
        ├── compiler.py     # Planの適用・修復
        ├── operators.py
        └── ui.py
```

現行の`properties.py`と`__init__.py`へ全実装を追加せず、登録入口だけを接続する。別Addonにはせず、内部Package境界を設ける。

### 6.2 最小Pipeline

```text
PropertyGroup
    -> load as ControlSpec / BindingSpec
    -> validate
    -> build ArtifactPlan
    -> preflight conflict check
    -> apply create/update/reuse
    -> verify invariants
    -> report result
```

初期から完全なDatabase Transactionを模倣する必要はない。OperatorをUndo対応にし、Apply前のPreflight、作成物の記録、失敗時の限定Cleanupを実装する。複数Rigを横断する大規模Compileが必要になった時点でTransaction層を拡張する。

### 6.3 冪等性とConflict Policy

同じDefinitionで2回Compileした結果が、次を満たすことを冪等性とする。

- Control Bone、Widget、Constraint、Driverが増殖しない。
- AnimatorのF-Curveを変更しない。
- 未管理のBone、Driver、Constraintを変更・削除しない。
- 管理対象の設定差分だけを更新する。
- Targetが見つからない場合は破壊せずErrorを返す。

v1の差分種別は`CREATE`、`UPDATE_OWNED`、`KEEP`、`CONFLICT`で十分である。`REPLACE`と`DELETE_OWNED`は、所有権とAnimation保護の試験が揃ってから追加する。

## 7. Viewport UX

一般ユーザーはGraphやJSONを編集せず、次の手順でControlを作成できるようにする。

1. SpriteObjectまたは対象Armatureを選ぶ。
2. `Add Rig Control`から1D、2D、Dial等のPresetを選ぶ。
3. TargetとしてObject、Shape KeyまたはConstraintを選ぶ。
4. 入出力範囲と向きを設定する。
5. Previewを確認して作成する。
6. 問題があれば`Validate`または`Repair`を実行する。

初期UIに必要なものは次である。

- Control一覧
- Binding一覧
- Target picker
- Range / Axis / Clamp
- Validate結果
- `Create`、`Update`、`Repair`
- 管理対象であることの表示

JSON Editor、Node Editor、Graph Inspectorは上級機能とする。共有案のGraphは内部構造として価値があるが、それをユーザー操作の前提にしない。

### 7.1 GLOBAL_CTRL

`GLOBAL_CTRL`はCharacterのSpriteObject Armature内に一つ置き、次を集約する。

- Rig ModeとSpace切替
- 非空間Scalar / Enum
- Character全体に作用する公開Property
- Control表示や補助設定

顔や部位を直接操作するSliderまで全て`GLOBAL_CTRL`のCustom Propertyへ集めず、空間Controlは部位近くのBoneとして配置する。これによりViewport上の視線移動とPanel往復を減らせる。

### 7.2 Widget

WidgetはGeometry Nodesによるパラメトリック生成を必須とする。`Tip`、`Slider`、`Radial（Circle / Dial）`、`Rectangle（Free / Grid）`の形態別共有Node Groupへ`WidgetSpec`を入力し、中心Path、Offset Rail、円Nodeを合成して面なしMesh Edgeを出力する。

- 1D: 円Tip、両端円、Rail Bar
- 2D Free: 円Tip、四隅円、外側境界のみ。内側Pathを削除して枠内を自由移動
- 2D Grid: 円Tip、任意列×行のGrid Bar。表示Rail上だけを移動
- Circle: 円Tip、外側円周のみ。内側Pathを削除して円内を自由移動
- Dial: 円Tip、設定角度範囲の内外Offset Arc Railと端点Node。表示Rail上だけを移動
- Matrix FULL: 円Tip、外枠、任意列×行のState Point。内部は自由移動
- Triangle/Polygon: 円Tip、頂点円、回転Bar

主要UI Parameterは、幅、高さ、向き、Tip半径、状態点半径、Bar幅、Dial範囲、Snap数、列数、行数、Grid表示である。Tip半径の既定値は状態点半径の2倍とする。Preset選択後も調整でき、Control Animationを変更せずにWidgetだけを再Compileできるようにする。

初期実装ではBaseとHandleへ固有色を付けず、Bone Colorは`DEFAULT`とする。将来必要になった場合は、Control種別またはDisplay/Control等の役割単位で選択可能なThemeをPresentation設定として追加し、GeometryやDriver定義から分離する。

BlenderのCustom Bone ShapeはMesh Objectを前提とするため、実装は二つのBackendを持つ。

1. `LIVE_MODIFIER`: GN Modifier付きMeshを直接Custom Shapeへ使う。
2. `EVALUATED_MESH_CACHE`: Depsgraphで評価したGN出力をCustom Shape用Meshへ同期する。

Phase 0で対応Blender Versionごとに直接評価を試験し、安定する場合は`LIVE_MODIFIER`、それ以外はCacheを使う。Cache方式でも形状の正本と生成処理はGNであり、UI Parameter変更時に再評価する。BaseはDefinition変更時だけ更新し、毎Frame動くTipはControl Bone Transformに任せる。

### 7.3 2D State Matrix UX

Matrix Control作成時は、`Columns`と`Rows`を指定し、Viewport PreviewでGridを確認する。最低2×2、上限は初期実装で性能試験から決める。

- 各Grid PointにPose StateまたはShape Keyを割り当てる。
- 未割当PointはValidation Warningとし、明示的な空Stateも許可する。
- Handleを各PointへSnapしてStateを登録・更新できる。
- 通常操作ではセル内を連続補間する。
- 列・行追加時は既存Stateを保持し、新しいPointだけ未割当にする。
- 列・行削除時は失われるStateを一覧表示し、確認なしに削除しない。

列方向の区分線形基底を`bx_i(u)`、行方向を`by_j(v)`とすると、各State Weightは次になる。

```text
w_ij(u, v) = bx_i(u) * by_j(v)
sum(w_ij) = 1
result = sum(w_ij * state_ij)
```

これはセル内Bilinear補間と等価で、セル境界でも連続する。Shape Key Matrixでは各State Shape Keyの`value`へ対応Weight Driverを生成する。汎用Pose Stateでは同じWeightをBinding展開に使う。

## 8. 現行コードへの適合性

### 8.1 利用できる既存経路

- `operators/draw_bone_shape.py`と`operators/edit_mesh.py`にCustom Shape作成・割当の経路がある。
- `operators/animation_handling.py`はPose Boneのlocation、rotation、scaleをActionへKeyframe化できる。
- `operators/exporter/export_dragonbones.py`はDriver Target Boneを検出し、非Deform Controlを除去しつつDeform結果をBakeする設計を持つ。
- `ObjectProperties`にはShape Key周辺、Alpha、Z、Slot、Animation Collection等の既存接続先がある。

したがって、1D Slider BoneとShape Key Driverの組み合わせは現行構造に最も近く、最初の縦切りとして実装可能性が高い。

### 8.2 先に解決・明文化する課題

- `coa_tools2/blender_manifest.toml`はBlender 4.2以上、`bl_info`はBlender 5.0以上を示している。Action APIはBlender 4.4前後で分岐しているため、対応Versionを統一する。
- 現在の通常Unit TestはDependency/Updater中心で、RigのBlender Headless Testを新設する必要がある。
- Alpha、Z、SlotにはUpdate Callbackやdepsgraph handlerが関係する。Shape KeyとConstraintより後に段階導入する。
- 公開BoneのRenameとArmature複製時のID Policyを実装前に固定する。
- ExporterごとにControl BoneとDriver結果の扱いが同じとは限らないため、DragonBones以外も個別に検証する。
- Geometry Nodes Modifierの出力がCustom Shape描画へ直接反映されるかを、宣言対応Versionごとに確認する。反映されない場合は評価Mesh Cacheを使う。
- Node Group Interface SocketのIdentifierを名前だけで解決せず、Version差を吸収するAdapterを用意する。

## 9. 実装コストと将来性

相対コストを次のように定義する。

- **S**: 一つの限定機能・既存構造内
- **M**: 複数ModuleとBlender統合試験が必要
- **L**: 保存、Migration、UI、Compilerを横断
- **XL**: 研究要素または独立Product規模

| 機能 | コスト | 不確実性 | ユーザー貢献 | 判断 |
| --- | --- | --- | --- | --- |
| GN Widget基盤 + 1D Slider + Shape Key | M〜L | 中 | 非常に高い | 最優先 |
| Stable ID / Ownership / Repair | M | 中 | 直接は中、長期は非常に高い | 1Dと同時に最小導入 |
| 2D Rectangle / Dial | M | 中 | 高い | 1D後 |
| 任意サイズ2D State Matrix | L | 中〜高 | 非常に高い | StateDataの主機能 |
| 複数Binding | M | 中 | 高い | 初期基盤の次 |
| Alpha / Z Adapter | M | 中〜高 | 中〜高 | Render試験後 |
| Slot Index Adapter | M | 高 | 中 | #62解決後 |
| Pose State / StateData | L | 高 | 非常に高い | #66と連携 |
| Idempotent Generic Diff | L | 中〜高 | 長期で高い | 必要範囲から拡張 |
| Canonical JSON Graph + Migration | L | 中 | 制作者/開発者に高い | Graph導入Gate後 |
| Typed Node Registry / Component | L | 中〜高 | 大量Rigで高い | 3種以上の実例後 |
| Node Editor | XL | 高 | 上級者には高い | 十分なNode語彙確立後 |
| Geometry Nodes Widget | M〜L | 中〜高 | 高い | 必須基盤 |
| Matrix `MASKED` Mix | L | 高 | 中〜高 | FULL補間後 |
| 3D -> 2D Projection / Inverse Solver | XL | 非常に高い | 成功すれば高い | 別Epic |

汎用Graphを最初に実装する場合、ユーザー貢献が見える前にL相当の領域を複数同時に進めることになる。縦切り方式では、M相当の成果から得た制約を後続設計へ還元できる。

## 10. 段階的な実装計画

### Phase 0: ADRと技術スパイク

- 本書と既存調査書を設計判断の基準にする。
- 対応Blender Versionを統一する。
- 1D ControlのBone階層、local axis、Constraint、Driver式を手動Rigで検証する。
- 円と矩形バーを合成する共有Geometry Node Groupを作り、`LIVE_MODIFIER`と`EVALUATED_MESH_CACHE`を比較する。
- Widget Parameter変更、Node Group共有、Save/Reload、Undo、複製、10/50/100個時の性能を測定する。
- PropertyGroupとText JSONについて、Undo、複製、Save/Reload、Library Link/Overrideを比較する。
- 公開Bone名とUUIDの複製Policyを確定する。

成果はコード量ではなく、縦切り実装のAcceptance Fixtureとなる`.blend`またはHeadless Test仕様である。

### Phase 1: 1D Vertical Slice

- SpriteObject Armature内に1D SliderのDisplay BoneとControl Boneを作る。
- Display Boneへ両端円+Rail、Control Boneへ円TipのGeometry Nodes Widgetを割り当てる。
- `WidgetSpec`からGN Modifier Inputを設定し、Backendに応じて評価Mesh Cacheを更新する。
- Control Boneへlocal spaceのLimit Locationを設定する。
- Shape Key値へ単純なDriverを接続する。
- 最小`ControlSpec` / `BindingSpec`を導入する。
- `rig_instance_id`、Control UUID、Artifact Roleを付与する。
- 同じOperatorの再実行でArtifactが増殖しないようにする。
- Control BoneのTransformを既存Animation CollectionへKeyframe化する。

このPhaseでは汎用Graph、StateData、Slot、Projectionを実装しない。

### Phase 2: Binding / Validation / Repair

- 複数Bindingを許可する。
- Shape KeyとConstraint Influence Adapterを正式化する。
- Pure ValidationとArtifactPlanを分離する。
- Missing Target、Ownership Conflict、Duplicate IDを構造化して報告する。
- `Validate`、`Update`、`Repair` UIを追加する。
- JSON Import/ExportをDebug/交換用途として追加する。

### Phase 3: Control Presets

- 2D Rectangle
- 2D Circle
- Dial / Arc
- Triangle/Barycentric Controlの技術スパイク
- IK/FK、Space Switch用Rig Mode Property
- すべてのPresetを円+矩形バーの共有GN Widgetへ統一

No-pop Space Switchは専用Operatorとし、切替前後のWorld Transform一致を試験する。

### Phase 4: Pose State / StateData

#### Phase 4A: Shape Key State（実装済み）

- Issue #66へ接続可能なStateData Schema
- 1D Stateと任意列×行の2D State Matrix
- 2×2、3×2、2×4 PresetとBilinear Weight Driver
- Matrix Pointの割当、明示的Empty、Snap
- 行列追加時の割当維持と、削除Preview・確認
- Slot置換と連続Stateのデータ分離
- GN Matrix Base + Control Bone Cursor
- `FULL` Mix

#### Phase 4B: Pose State拡張（未実装）

- 複数Bone、Shape Key、COA Property差分を束ねる疎なPose State
- Triangle / Barycentric State
- Matrix `MASKED` Mixと部分遷移境界
- 不均等な列・行座標
- 複製、Export Bakeを含むGate Cの残り

#### Phase 4Aの基本操作

1. 1Dは`1D Slider`をBindingなしで作り、`Continuous States > Set Up State Grid`を開く。
2. MatrixはAdd Rigの`2D Rectangle`で`State Matrix` Modeを選び、列数・行数を指定する。
3. 既存のFree/Grid RectangleをMatrixへ変える場合も`Set Up State Grid`を使える。
4. 一覧でState Pointを選択し、`Assign`からMeshとShape Keyを割り当てる。
5. Shape Keyを割り当てない意図的な基準状態は`Empty`にする。
6. `Snap`でHandleを選択中のState Pointへ移動し、位置と割当を確認する。

リグ作成時にShape Keyが揃っている必要はない。State Point一覧は後から編集でき、`Update Rig Control`と`Repair Rig`は現在のStateDataからWidgetとDriverを再生成する。

Rectangle系はAdd Rig上で一つにまとめるが、内部評価は分離する。`Grid Rails`は全格子交点へ円Nodeを置き、内部Rail上だけを移動する。`State Matrix`の`FULL` Mixは外枠と状態点を表示し、セル内部を自由移動してBilinear補間する。

### Phase 5: Rig Graph導入判断

次の条件を満たした場合に、`ControlSpec` / `BindingSpec`を型付きRig Graphへ昇格する。

- 1D、2D、Dialの少なくとも3種類が実運用されている。
- 一つのControlから異種Targetへの複数Bindingが必要になっている。
- Character間で共有したいComponentが2種類以上ある。
- 手続き的Preset追加に重複が現れている。
- Save/Reload、Migration、Repairの要求が実例で明確になっている。

この時点で、Node、Port、Connection、Registry、Cycle Validation、Canonical JSONの必要範囲を決める。既存のPublic Control ABIとAnimationは維持する。

### Phase 6: Character Posing Rig Components

State Graphとは別に、Root、FK、IK、IK/FK切替、Spine等の骨格ポージング構造を、型付き`RigComponent`として導入する。`RigControl`、Widget、Binding、所有タグは共有するが、骨格構造をState Pointへ埋め込まない。

最初のVertical Sliceは、選択した2-Bone Chainから管理された2D Limb IKを生成し、単一ChainのIK/FK Mix、両方向Snap、Validate / Repair、Export Bakeまでを成立させる。

詳細は[Phase 6: Character Posing Rig Components 設計案](rig_control_phase6_character_posing.md)を参照する。

### Phase 7以降: 別Epic

- Rig Variant / Atlas構成
- Generic Node Editor
- 3D Pose Projection
- Inverse Matching / Solver
- 別AddonまたはLibraryへのCore抽出

これらはRig Control基盤を再利用するが、Issue #47の完了条件には含めない。

## 11. PR分割案

| PR | 内容 | ユーザーに見える成果 |
| --- | --- | --- |
| 1 | ADR、Version方針、最小Fixture | 設計と検証条件の固定 |
| 2 | GN Widget基盤 + 1D Slider + Shape Key縦切り | デザイン調整可能なViewport Slider |
| 3 | Schema、Ownership、Validate/Repair | 壊れにくい再生成 |
| 4 | 複数Binding + Constraint Adapter | 一つのControlで複数挙動を同期 |
| 5 | 2D + Dial Preset | 表情、視線、回転操作の拡張 |
| 6 | 任意サイズState Matrix | 2×2、3×2、2×4等の連続状態補間 |
| 7 | StateData汎用化 | Pose間の連続補間 |
| 8 | Rig Graph採否ADR | 実例に基づく一般化判断 |

Pure Graph CoreだけのPRを先に置かない。Pure Moduleは各縦切りPRに必要なSchema、Validation、Planningとして追加し、Blender上のAcceptance Testと対にする。

## 12. 検証戦略

### 12.1 Pure Python Test

- Schemaのserialize/deserialize round trip
- Migration
- Duplicate UUID / Semantic ID
- 範囲、軸、型、Target参照のValidation
- 同一入力から同一ArtifactPlanが得られること
- 未知Schema/Target Typeを安全に拒否すること
- 2×2、3×2、2×4 Matrixの頂点、辺、セル中央で期待Weightになること
- Matrix内の全位置でWeight合計が許容誤差内で1になること
- 不均等な列・行座標でもセル境界が連続すること

### 12.2 Blender Headless Test

- 新規SpriteObjectへ1D Controlを生成できる。
- 2回CompileしてBone、Widget、Constraint、Driver数が変わらない。
- Shape KeyがControlの最小・中央・最大で期待値になる。
- Control Bone TransformへKeyframeが入り、Action切替後も残る。
- Save/Reload後にUUIDとBindingが解決する。
- Controlを含むRig複製後、別Instanceを誤更新しない。
- Undo/Redoで生成前後が整合する。
- 未管理Artifactを上書きまたは削除しない。
- Target欠落時にCrashせずValidation Errorになる。
- 非Deform Controlを含んでもExport Bake結果が一致する。
- Widget Parameter変更でGN出力または評価Mesh Cacheが更新される。
- Node Groupを共有する複数WidgetのParameterが相互に混線しない。
- Node Group欠落時にValidateで検出し、Repairで復元できる。
- Matrixの各Grid Pointで対応StateだけがWeight 1になる。

### 12.3 DCC実機検証

- Viewport上の選択性、Drag方向、Snap、視認性
- Pose ModeとCOA Tools 2独自Edit操作の競合
- Render Animation中の安定性
- 複数Characterを同一Sceneへ置いた場合の分離
- Blender 4.2/5.xのうち正式対応としたVersionでの挙動
- DragonBones / Creature / JSON Exportの各経路
- 1D、Dial、2D、2×2、3×2、2×4が参考デザインと同じPrimitive構成で視認・選択できること
- 10、50、100 Control時のGN Widget更新とViewport操作感

## 13. Go / No-Go Gate

### Gate A: 1D基盤

次をすべて満たせば2DとDialへ進む。

- Save/Reload、Undo/Redo、複製でデータ破損しない。
- 2回Compileで生成物が増殖しない。
- Animation F-Curveが再Compileで維持される。
- Shape Key Driver付きRenderが安定する。
- Export BakeがControlなしの期待結果と一致する。
- 円半径、Bar幅、長さ、向きを変えてWidgetが更新される。
- Save/Reload後もNode Group、Modifier Input、Cache Backendが復元される。

### Gate B: COA Property Binding

Alpha/Z/Slotへ進む条件は、Update Callbackとdepsgraph handlerを含むRender回帰試験があることである。特にSlotはIssue #62のCloseだけでなく、Driver付きRenderを対象Versionで再現試験する。

### Gate C: State Matrix

2×2、3×2、2×4の全Fixtureで、State PointのWeightが1、セル内Weight合計が1、セル境界が連続し、Save/Reload後も割当が維持されることを条件とする。まずShape Key Matrixを成立させ、その後に複数Targetを持つPose Stateへ広げる。

### Gate D: Generic Rig Graph

Phase 5の実利用条件が満たされず、Presetだけで重複が少ない間は、Generic Graphを実装しない。逆に、複数Component、複数Target、Migration要求が反復するなら、共有案A/BのGraph Coreへ昇格する。

### Gate E: Projection

Forward Rigの意味的Controlが安定し、評価関数をBlenderなしでも再現できる範囲が明確になるまで、Inverse Solverを開始しない。Projectionは独立した性能・品質指標を持つ別Projectとして扱う。

## 14. 採用判断一覧

| 提案要素 | 判断 | 理由 |
| --- | --- | --- |
| Custom Shape Slider Bone | 採用 | 最も直接的なAnimator UX |
| `GLOBAL_CTRL` | 採用 | Rig Modeと非空間Controlの集約に有効 |
| Control / Widget / Binding分離 | 採用 | 再利用、表示差替え、複数Targetに必要 |
| Stable UUID / Semantic ID | 採用 | 再Compileと公開ABIに必要 |
| Artifact Ownership Tag | 採用 | User Data保護に必要 |
| Idempotent Compile | 採用 | Preset生成でも早期から価値が高い |
| Pure Core / Blender Backend境界 | 採用 | Testと将来抽出に有効 |
| Blender-native runtime | 採用 | 再生性能、保存、Exportに適合 |
| Rig DefinitionとArtifactの分離 | 採用 | RepairとMigrationの基礎 |
| PropertyGroupをView Modelだけにする | 変更採用 | v1は固定Schemaの正本。Graph段階で再評価 |
| Text Datablock JSONをCanonicalにする | 延期 | 任意Graphが必要になるまで同期コストが勝る |
| Public ControlをCustom Propertyへ統一 | 不採用 | 空間ControlのViewport UXを損なう |
| Typed DAG / Node Registry | 延期 | 実例から必要な型とNodeを抽出する |
| Full Diff / Transaction | 段階採用 | Preflightと所有物Updateから開始 |
| Rig State / Rig Variant分離 | 採用 | ただしPoseState/RigMode/RigVariantへ改称 |
| Generic Node Editor | 延期 | Preset UIの方が初期ユーザー価値が高い |
| Driver Namespace Function | 原則延期 | Portableで単純なDriverを優先 |
| Slot Index Binding | 保留 | #62がOpenでRender Crash履歴がある |
| Geometry Nodes動的Widget | 採用・必須 | 円+矩形バーの共有生成基盤として全Presetで使う |
| 任意列×行の2D State Matrix | 採用 | Live2D型の多状態連続補間に直接貢献する |
| Matrix `FULL` Bilinear Mix | 採用 | Blender-native Driverへ分解しやすく連続性を保証できる |
| Matrix Cell Mask Mix | 採用 | Cell単位でGrid Railと自由なBilinear Mixを同一Domainに統合 |
| Name Bone + Text Layer | 採用 | 各Controlの意味をViewport上で識別し、下部中央へ追従表示する |
| 3D -> 2D Projection | 別Epic | 不確実性と評価指標がIssue #47と異なる |
| 初期から別Addon化 | 不採用 | 現行COA Adapterと密接。内部境界だけ設ける |

## 15. 最初に実装する成果物

最初のコード成果物は、次の一つに限定する。

> SpriteObject Armatureに、固定されたRail表示Boneと、local XまたはYだけを移動できるHandle Control Boneを生成する。Railは両端円+矩形バー、Handleは円Tipとして共有Geometry Node Groupから生成し、そのTransform Channel Driverで一つのShape Key値を0〜1へ制御する。Control、Widget、Binding、所有タグを保存し、同じ定義の再Compileで生成物を増殖させず、既存ActionのControl Keyframeを保持する。

この成果物には、小さくても次を含める。

- `ControlSpec` / `BindingSpec`
- PropertyGroup保存
- Target Validation
- Artifact Tag
- Create / Update / Conflictの最小Plan
- 1D Widget生成
- `WidgetSpec`と共有Geometry Node Group
- `LIVE_MODIFIER`または評価Mesh Cache
- Limit Location
- Transform Channel Driver
- Action、Save/Reload、Undo、Render、Exportの試験

ここまでで、既存Control設計の操作性、参考デザインのパラメトリック生成、共有案A/Bの再現性を同時に検証できる。成功後は、同じGN Widget基盤を2D、Dial、任意サイズState Matrixへ広げ、実際に触った感触を各Presetの寸法、Snap、Mix Policyへ反映する。実例が一般化を要求した時点でRig Graph Compilerへ昇格する。

## 16. 参照

- [2Dリグコントローラー調査・設計案](rig_control_design.md)
- [Phase 5: Matrix DomainとRig Name表示](rig_control_phase5_matrix_domain.md)
- [Phase 6: Character Posing Rig Components 設計案](rig_control_phase6_character_posing.md)
- [Issue #47: Add Sliders for Shapekeys and Advanced 2D Rigging Features](https://github.com/Aodaruma/coa_tools2/issues/47)
- [Issue #62: Slot index causes Blender to crash during rendering](https://github.com/Aodaruma/coa_tools2/issues/62)
- [Issue #66: StateData for smooth transition animation](https://github.com/Aodaruma/coa_tools2/issues/66)
- [Blender: Bone Custom Shape](https://docs.blender.org/manual/en/latest/animation/armatures/bones/properties/display.html)
- [Blender: Geometry Nodes Modifier](https://docs.blender.org/manual/en/latest/modeling/modifiers/generate/geometry_nodes.html)
- [Blender Python API: Object.to_mesh / evaluated_geometry](https://docs.blender.org/api/current/bpy.types.Object.html)
