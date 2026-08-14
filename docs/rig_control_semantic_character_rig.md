# Semantic Character Rig 再設計

## 1. 本書の目的

本書は、COA Tools 2における既存の**State Rig**と、今後実装する**Character Rig**の境界を整理し、両者を組み合わせられる共通内部構造を定義する。

ここでいうCharacter Rigは、`Arm IK`や`Spine`のような部位別テンプレートだけを指さない。複数のBone、Constraint、Shape Key、Sprite Slot、描画順、任意Propertyを、一つの**意味的動作**として操作する操縦桿を指す。

例:

- 「手を伸ばす」: IK Target、肘方向、肩補正、腕の見かけ奥行き、手のSprite Stateをまとめて評価する。
- 「腕を軸方向へ捻る」: Controlの軸回転を、Bone TwistではなくShape KeyやSlotの組み合わせへ変換する。
- 「見た目の法線方向へ動かす」: 傾けて表示したControlを操作しつつ、実際のArtは平面内に保ち、短縮や重なりをShape Keyで表現する。
- 「紐を揺らす」: Spline IKによる基本形状へSecondary Motionを後段合成する。

本書は目標設計とPhase 7〜8の実装結果を併記する。[Phase 6 キャラクターリグ現行実装資料](rig_control_phase6_current_implementation_inventory.md)は、再設計前の試作を確認するための履歴資料として扱う。

### 1.1 Phase 7〜8実装状況

本設計のPhase 1〜5は`codex/issue-47-rig-design`へ段階的に実装した。

- Phase 1: Frame、Channel、Solver DAG、Output Policy、Presentation Referenceを持つSemantic Rig Schema
- Phase 2: Projected Transformと、任意N次元のRecorded Pose Map
- Phase 3: 3D Mechanism IKと、Art Planeへ投影するPresentation Chain
- Phase 4: 区間指定、前後Blend、Anchor Captureを持つContact / Pin
- Phase 5: NURBS、Hook、Spline IKを使うSpline Chainと、決定論的Bake方式のSecondary Motion
- Presentation Phase: Geometry Nodesで生成する意味別Custom Shapeと、Solverから独立したLive Preview

Blender UIでは、`Projected Transform`、`Kinematic Chain`、`Spline Chain`がそれぞれ独立したSource Chainを持つ。Pose Modeで連結Boneを選択し、各Stageの`Assign Selected Chain`から割り当てる。これにより、同じCharacter Rig内でも腕をIK、髪をSplineとして別Chainへ接続できる。Mapping、Pin、Secondaryは`After UUIDs`で上流Stageを参照し、Component全体の最後のControlへ暗黙接続しない。

Character Rigの絵側出力は、`Recorded Pose Map` Stage内のOutputだけを正規経路とする。旧`RigComponent.bindings`はLegacy Component専用であり、Character Rigでは追加を拒否する。複数の上流Stageを持つPose Mapへ入力次元を追加するときは、その次元が読むSource Stageを明示する。

Recorded Pose Mapは初期実装から3次元以上を扱える。次元数を固定した3D専用実装ではなく、`SemanticChannel`の個数をそのままPose Fieldの次元として使用し、正規化した局所RBFで補間する。したがって、移動、回転、スケール、Solver Featureを必要な数だけ組み合わせられる。

Character RigのCustom Shapeは内部機構から分離したPresentation Layerとして実装済みである。Geometry Nodesの共有GroupへStageごとのSource ObjectからParametersを渡し、評価済みの無面Edge MeshをBone Custom Shapeへ割り当てる。Shapeや寸法を変更してもIK、Pose Map、Spline、Driver、Animation Dataは再構築しない。

初期Blender Adapterの境界も明示しておく。

- Pose Fieldの**入力次元数は任意**であり、3次元以上を同じEvaluatorで扱う。
- Blender上のOutput Adapterは現在scalar単位である。Vector Snapshot自体はSchema/Evaluatorで保持できるが、Bone XYZ等は軸ごとのOutputとして登録する。
- 離散Outputはnearest sampleで扱える。離散**入力次元**は、連続RBFと混同しないため未対応値を明示エラーにする。
- 投影は明示的なArt Planeを標準とする。Screen Plane等の未実装modeを黙って同じ挙動にせず、Compile時に説明付きで拒否する。
- Secondary Motionの初期版は位置Bakeである。回転はSpline tangentが作り、将来Quaternion log空間のspringを追加する。

### 1.2 配布用サンプル

実装済み機構を一つのファイルで比較できるよう、[semantic_character_rig_demo.blend](../samples/semantic_character_rig_demo.blend)を同梱する。推奨起動方法は次のとおり。

```powershell
.\scripts\launch_blender_rig_manual_test.ps1 -OpenSemanticSample
```

この起動方法では開発中のCOA Tools 2を有効化してから、検証用一時フォルダへコピーしたサンプルを開く。手動保存してもリポジトリ内の配布ファイルは上書きされない。通常起動やダブルクリックで先にファイルを開き、Bが動かなかった場合は、`codex/issue-47-rig-design`のアドオンを有効化してからサンプルを開き直す。Recorded Pose MapのDriver関数`coa_pose_field_scalar`はファイル読込前に登録されている必要があり、古いExtension版やアドオン無効状態で一度失敗したDriverは、有効化しただけでは即時復帰しない。

サンプルは四つのArmatureをMulti-Object Pose Modeにした状態で保存している。ビューポートをCamera Viewのまま開き、フレーム`1`、`24`、`48`を切り替えると、次の四例を確認できる。

- State Rig: 2x2 State MatrixとGeometry Nodes Widget
- Character Rig: 4次元Recorded Pose Map、9個のRBF Sample、2D四方向矢印Widget
- Character Rig: 3D Mechanismで解き、平面へ投影する実IK、墓標型IK Handle、楕円Pole
- Character Rig: Spline Chain、球面四方向矢印Widget、Bake済みSecondary Motion

操作時は、Bの左側にある四方向矢印CTRLをクリックし、`G`による画面内移動で`Move X/Y`、`R X X`と`R Z Z`でBone Localの`Turn X/Z`を変更する。この四入力は互いに独立しており、9個のSampleは中央と各軸の正負に対応する。Cは起動時に墓標型CTRLがActiveであり、`G`で動かすとIK Target、楕円CTRLを動かすと曲げ方向を操作できる。手動操作後にフレームを変更すると、フレーム`1`、`24`、`48`のデモ用Keyへ戻る。

ファイル内の`README_SemanticCharacterRig.txt`にも、各例の目的、操作対象、確認ポイントを収録している。再生成する場合は、既存プロジェクトでは実行せず、Blender 5.1以降を`--factory-startup --python scripts/blender_rig_semantic_character_sample.py`で起動する。Scriptは`--factory-startup`がない実行、ファイルを開いた状態、未保存変更がある状態をScene初期化前に拒否する。また、リポジトリ相対で保存先を解決し、個人環境の絶対パスをコードや説明文へ埋め込まない。

## 2. 用語

### 2.1 State Rig

Slider、Dial、Circle、Rectangle、State Matrix等を使い、状態またはパラメーターを連続・離散制御する既存機能を**State Rig**と呼ぶ。

一般的なState Machineが持つイベント、Entry / Exit、時間遷移、状態履歴は持たない。そのため、内部的には`State Field`または`State Control`に近いが、ユーザー向け名称はState Rigへ統一する。

### 2.2 Character Rig

ユーザーが指定した動作意図を、Solver、投影、補間、接触、物理処理等を介して複数出力へ展開するリグをCharacter Rigと呼ぶ。

Character RigのPreset名は部位名を使用できるが、内部構造は部位へ固定しない。例えば`Arm Reach`は、`KINEMATIC_CHAIN + CONTACT_PIN + RECORDED_POSE_MAP`の組み合わせとして表現する。

### 2.3 Semantic Rig

State RigとCharacter Rigに共通する保存、評価、所有、Binding、検証の基盤を**Semantic Rig**と呼ぶ。

Semantic Rigはユーザーが直接選ぶ第三のリグ種類ではない。State RigとCharacter Rigを同じ評価Graphへ載せ、互いの出力を再利用可能にする内部基盤である。

## 3. State RigとCharacter Rigの違い

| 観点 | State Rig | Character Rig |
| --- | --- | --- |
| 操作対象 | 状態・概念・値 | 意味的な動作意図 |
| 例 | 顔向き、口形、表情、衣装状態 | 手を伸ばす、腕を捻る、接地する、紐を揺らす |
| 入力値 | 原則としてそのまま意味を持つ | DecoderやSolverが解釈する |
| 幾何計算 | 原則なし | IK、FK、Spline、投影、接触等を使用可能 |
| 時間依存 | 基本なし | Pin区間、Release、Secondary Motion等で持ち得る |
| 主な出力 | Shape Key、Slot、Property、Constraint Influence | Bone PoseとState Rig出力の複合 |
| 補間 | 1D / 2Dの状態空間が中心 | 最終的に3次元以上のPose Spaceを前提とする |

ユーザー向けには、次の説明を基本とする。

> State Rigは「どの状態をどれだけ混ぜるか」を指定する操縦桿である。  
> Character Rigは「何をしたいか」を指定し、必要な骨格計算と見た目変換をまとめて実行する操縦桿である。

ただし両者は排他的ではない。Character Rigは、Solverの結果から既存State Rigを駆動したり、State Matrixを見た目補正用のPose Mapとして使用したりできる。

## 4. 現行実装と目標の差

### 4.1 現在利用できるState Rig

現行ブランチには次が実装されている。

- 1D Slider、Dial、Circle
- Rectangle Free / Grid
- 任意行列サイズのState Matrix
- Matrixセル単位のMix可否
- Shape Key / Constraint Influence Binding
- Geometry NodesによるState Rig Widget
- Name表示、選択同期、Live Preview

State Matrixは1Dまたは2Dの状態補間として動作する。N次元Pose Map、Solver、接触、時間区間はまだ持たない。

### 4.2 Phase 6以前のLegacy Character Component

現行`RigComponent`には`ROOT`、`FK_CHAIN`、`SPINE_FK`、`LIMB_IK`があり、次の二方式に分かれている。

| 方式 | 現状 | 課題 |
| --- | --- | --- |
| `PARAMETRIC` | 非DeformなFrame / Controlの6軸をShape Key等へ線形Mappingする | `LIMB_IK`でもIKを生成せず、多点・非線形補間を持たない |
| `DIRECT_BONES` | Source Boneを直接操作し、`LIMB_IK`ではBlender IKを生成する | 平面メッシュもBoneとともに3D回転する |

旧サンプルはSource Boneを動かさず、Controlの6軸からShape Keyを駆動するサンプルである。実IKと平面維持を同時に検証するサンプルではない。Phase 7のCharacter RigはこのLegacy経路を暗黙変換せず、後述のSolver Stage DAGとして別に保存・評価する。

### 4.3 継続利用するもの

- `rig_instance_id`、Component UUID、Binding UUIDによる所有管理
- Preflight、競合検出、Transactional Rollback
- 冪等Update、Rename追従、Save / Reload
- Control Orientation
- Shape Key / Constraint Influence Driver
- 既存State Matrixと部分Mix Domain

### 4.4 置き換えるもの

- `component_type`と`deformation_mode`で評価方式全体を二者択一にする構造
- `PARAMETRIC LIMB_IK`のように、名称と実挙動が一致しないComponent
- Control表示軸、入力軸、IK計算軸、Art平面を一つのFrameで兼用する構造

既存Componentを暗黙変換せず、新Schemaへの明示的な移行Operatorを用意する。

## 5. 共通Semantic Rig Pipeline

基本評価経路を次とする。

```text
Viewport Control
    ↓
Input Decoder
    ↓
Semantic Channels
    ↓
Solver Stack
    ↓
Pose Features
    ↓
Recorded Pose Map / State Rig Adapter
    ↓
Output Mixer
    ↓
Bone / Shape Key / Slot / z_value / Constraint / Property
```

### 5.1 Viewport Control

選択、Transform入力、Keyframe、ユーザーへの操作意味の表示を担当する。Widget形状は評価ロジックへ含めない。

### 5.2 Input Decoder

Control Transformを、名前付きのSemantic Channelへ分解する。

例:

```text
local Z translation -> apparent_depth
axis rotation       -> axial_twist
screen translation  -> screen_x / screen_y
effector movement   -> reach_target
```

### 5.3 Solver Stack

IK、FK、投影、接触、Spline、Secondary Motion等を型付きNodeとして順に評価する。単一のComponent種類へ一つのSolverを固定しない。

### 5.4 Pose Features

Solver結果から、見た目制御に適した値を抽出する。

- 関節角
- Swing / Twist
- Reach率
- 画面内方向
- Art Planeからの仮想奥行き
- 接触Weight
- Curveの曲率、伸長率、速度

### 5.5 Output Mixer

複数Nodeが同じ出力へ作用するため、出力ごとに合成規則を明示する。

| 合成規則 | 用途 |
| --- | --- |
| `OVERRIDE` | 最終Bone Pose、離散Slot |
| `ADD` | 補正Bone、Shape Key加算 |
| `MULTIPLY` | Influence、Scale補正 |
| `MAX` / `MIN` | 接触、制限 |
| `NORMALIZED_BLEND` | 複数Pose Sample |

優先順位だけに依存せず、型、Stage、合成規則をSchemaへ保存する。

## 6. 四つのFrame

表示と実評価の混同を避けるため、次を別々に保存する。

### 6.1 Display Frame

Widgetをどこへ、どの向きで表示するかを決める。手のひらや足裏の見た目法線へControlを傾ける用途に使う。

Display Frameを変更しても、入力値、Solver、Artは変化しない。

### 6.2 Input Frame

Control Transformをどの軸のSemantic Channelとして読むかを決める。

Display Frameと一致させることも、画面平面へ投影することもできる。例えば見た目上は斜めの円Controlでも、実LocationはArt Plane内に拘束し、ドラッグ量だけを`apparent_depth`へ変換できる。

### 6.3 Mechanism Frame

IK、FK、Spline等の計算空間を決める。3D計算を許可し、Art Planeに直接拘束されない。

### 6.4 Art Frame / Art Plane

カットアウトメッシュを提示する空間を決める。Mechanism結果をそのまま適用せず、必要な成分だけを投影、変換して渡す。

## 7. Mechanism PoseとPresentation Pose

Character RigではPoseを二層に分離する。

```text
Mechanism Pose
  └─ 非表示MCH Chainで3D IK / FK / Splineを解く

Presentation Pose
  ├─ Art Plane内の位置と画面内回転
  ├─ 平面法線を維持するDEF Pose
  └─ 奥行き、捻り、短縮をShape Key / Slotへ変換
```

IKの標準経路は次とする。

1. MCH Chainで実際のIKを解く。
2. 関節位置、角度、Reach、Swing / TwistをPose Featuresへ抽出する。
3. DEF BoneへはPresetで許可した位置・画面内回転のみを渡す。
4. 面法線方向の回転はArtへ直接渡さず、Recorded Pose Mapへ入力する。
5. Shape Key、Slot、描画順等で見た目を再構成する。

これにより、「ちゃんとIKする」と「平面メッシュを紙の板のように回転させない」を両立する。

## 8. 内部Node種類

### 8.1 `PROJECTED_TRANSFORM`

Controlの移動、回転、ScaleをSemantic Channelへ分解し、必要に応じて別平面へ投影する。

主なMode:

- `SCREEN_TRANSLATE`
- `APPARENT_NORMAL_TRANSLATE`
- `AXIAL_ROTATE`
- `SWING_TWIST`
- `NONLINEAR_SCALE`

見た目法線移動では、Control自体を無限に奥行きへ移動させない。Display Frameの法線をArt Planeへ投影したレール、または画面平面内の代理移動量から仮想的な奥行き値を作る。

### 8.2 `RECORDED_POSE_MAP`

複数入力と複数出力のサンプルを記録し、中間を補間する。State Rigを一般化したPose Space層に相当する。

一つのSampleには次を保存する。

```text
Input Vector
├─ Semantic Channels
├─ Solver Features
└─ Context / Mode Mask

Output Snapshot
├─ Bone Transform群
├─ Shape Key群
├─ Slot / z_value
├─ Constraint Influence
└─ 任意Property
```

### 8.3 `KINEMATIC_CHAIN`

FK、IK、Global Orientation、Bend、Stretch、Joint Limitを扱う。IK/FKは単純な見た目Sliderに固定せず、PinやPose Matchと組み合わせ可能なKinematic Policyとして保存する。

### 8.4 `CONTACT_PIN`

位置、向き、参照Space、Weight、開始・終了区間を持つ。IK/FKから独立し、`KINEMATIC_CHAIN`のTargetまたは評価後Poseへ合成できる。

### 8.5 `SPLINE_CHAIN`

Spine、髪、尾、布、紐、触手等のCurve駆動を扱う。

- FK / Spline IK / B-Bone Adapter
- Root / Tip Pin
- Twist、Roll、Stretch
- Curve Control Point
- ResampleとBone配分

### 8.6 `SECONDARY_MOTION`

Spring、Lag、Overshoot、Damping、重力風Offsetを後段適用する。元のキーPoseを破壊せず、Mute、Bake、再計算できることを必須とする。

## 9. Nodeの複合

上記種類は排他的なComponent種別ではない。特に次を標準的な複合として扱う。

```text
Arm Reach
PROJECTED_TRANSFORM
  -> KINEMATIC_CHAIN
  -> CONTACT_PIN
  -> RECORDED_POSE_MAP
  -> Presentation Outputs

Hair / Rope
SPLINE_CHAIN
  -> SECONDARY_MOTION
  -> CONTACT_PIN (optional)
  -> RECORDED_POSE_MAP (optional corrective)

Body Turn
PROJECTED_TRANSFORM
  -> RECORDED_POSE_MAP
  -> Bone + Shape Key + Slot
```

複合Graphは有向非巡回Graphとし、Compile前に循環を検出する。時間依存Nodeは静的Nodeと別Stageに置き、同一フレーム内のFeedback Loopを禁止する。

PresetはGraphの雛形であり、内部Nodeを隠すことはできるが固定化しない。Advanced UIではNode追加、接続、Mute、順序変更を可能にする余地を残す。

## 10. 多次元Recorded Pose Map

### 10.1 前提

段階的にUIと検証範囲を広げるが、保存SchemaとEvaluatorは最初から**3次元以上**を扱えることを前提にする。1D / 2D専用Schemaを増設して後から変換する方式は採らない。

既存State Matrixは、N次元Pose Mapの2D Adapterとして扱う。

### 10.2 入力の正規化

入力Channelごとに次を保存する。

- 型: Linear、Angle、Boolean、Category
- UnitとDomain
- Scale / Weight
- Clamp / Extrapolation
- Missing値の扱い

角度は境界で不連続にならないよう、必要に応じて`sin` / `cos`へ展開する。位置、角度、Scaleを生値のまま同じ距離計算へ入れない。

### 10.3 補間方式

| 条件 | 方式 |
| --- | --- |
| 1Dで単調な値 | Curve / Hermite |
| 既存2D Grid | State Matrixの双線形・部分Mix |
| 不規則な2D / 3D以上 | 正規化した局所RBF |
| 離散出力 | Nearest / Step / Category Gate |

N次元の標準を**局所RBF**とする。

1. 正規化した入力空間で近傍`k` Sampleを探索する。
2. Compact Support KernelまたはGaussian KernelでWeightを計算する。
3. 正則化項を持つ局所系を解き、疎なSampleでも発散を抑える。
4. Weightを正規化し、連続出力だけを補間する。
5. Sample範囲外ではNearest、Clamp、限定的ExtrapolationをPresetごとに選ぶ。

全Sampleを毎フレーム解き直さず、Sample編集時に係数と近傍IndexをCompileし、評価時はキャッシュを読む。次元数、Sample数、Kernel、正則化値、最大近傍数をValidation結果へ表示する。

### 10.4 離散値とMode

Slot、Space、Kinematic Policy等を連続平均しない。CategoryごとにSample集合を分けるか、連続Weightが閾値を超えたSampleをNearest選択する。

Mode切替前後でPoseが飛ばないよう、出力値の補間ではなくPose Match OffsetとTransition区間を別Nodeで扱う。

### 10.5 Driverと評価

単純な1D / 2Dは既存Driverを継続利用できる。N次元RBF、時間依存処理、複数Bone Snapshotは、長大なDriver式へ展開せず、アドオン管理のEvaluatorとCompile Cacheで評価する。

- 保存データ: Sample、Channel定義、出力参照、Evaluator設定
- 再生成可能データ: 正規化値、近傍Index、RBF係数
- Animation Data: ユーザーがKeyframeしたControl / Semantic Channel

Evaluatorが利用できない場合もファイルを破損させない。最終Presentation PoseをBakeできることをExport条件とする。

## 11. IK、FK、Pinの方針

IK/FKは常設0〜1 Sliderだけを中核にしない。

```text
Kinematic Policy
├─ PARENT_LOCAL
├─ WORLD_EFFECTOR
└─ GLOBAL_ORIENTATION
```

これと独立して次を持つ。

- Pin Position
- Pin Orientation
- Pin Space
- Pin Weight
- Active Frame Range

方式変更時は、現在の評価Poseから新方式のControl値を逆算し、補償Offsetを記録する。OffsetまたはPin Weightを指定区間で減衰させることで、手を固定した状態から自然に離す動きを作る。

Blender内部で複数MCH Chainを使用しても、アニメーターには一組の意味的Controlとして見せる。非アクティブControlは同期し、必要に応じて非表示にする。

## 12. Spline ChainとSecondary Motion

Splineと物理は別Nodeにし、任意順序で組み合わせられるようにする。

標準順序:

```text
Authored Curve / Controls
  -> Spline IK / B-Bone
  -> Pin / Collision Adapter (optional)
  -> Secondary Motion
  -> Corrective Pose Map
  -> Presentation Pose
```

Secondary Motionは必ず次を備える。

- Start Frameと初期状態
- Substep、Damping、Stiffness
- Deterministic evaluation
- Scrub時のCache無効化規則
- Mute / Reset / Bake
- Save / Reload後の再計算

リアルタイム操作時は低品質Preview、Bake時は固定Substepの高品質評価を選べるようにする。

## 13. Custom ShapeとGeometry Nodes

Custom Shapeは内部機構へ依存しない、**差し替え可能なPresentation Layer**として実装する。StageのSolver出力、Driver、KeyframeはWidget Object名やTopologyを参照しない。

### 13.1 生成構造

実装はShape Familyごとに共有Geometry Nodes Groupを一つ持ち、各Control Roleには次の二Objectを所有する。

```text
Stage Presentation
├─ Source Mesh Object
│  └─ Geometry Nodes Modifier + Stage固有Parameters
└─ evaluated edge-only Cache Mesh
   └─ PoseBone.custom_shape
```

Source Objectは編集値を保持し、CacheはCustom Shape表示を安定させる。生成結果は面を持たないEdgeのみの閉じたシルエットであり、Object、Mesh、Artifact RecordはRig Instance / Component / Stage / Roleで所有管理する。再Compileでは同じRoleを再利用し、Shape変更で不要になった所有Objectだけを削除する。

State Rigの`COA_RigWidget_GN`とは別系統とし、Character Rig内でも全Shapeを一つの巨大Groupへ集約しない。これにより、Shape Family単位でVersion管理し、将来Polygon、手足専用形状、状態表示付きWidgetを追加できる。

### 13.2 Shape一覧とParameters

| Shape | 主な用途 | 編集値 |
| --- | --- | --- |
| 1D Double Arrow | 一軸移動 | Width、Bar Width、Arrow Head Length / Width |
| 2D Four-way Arrow | 画面平面移動 | Width / Height、Bar Width、Arrow Head Length / Width |
| Cylindrical 1D Arrow | 見た目軸まわりの一軸操作 | Radius、Arc Angle、矢印寸法、Resolution |
| Spherical 2D Arrow | 立体的な二方向操作 | Radius、Arc Angle、矢印寸法、Resolution |
| Tombstone | 手・足IK等の方向性を持つHandle | Width / Height、Corner Radius、Resolution |
| Ellipse | Pole、汎用回転・移動Handle | Width / Height、Resolution |
| Triangle / Rectangle / Diamond | 意味別の汎用Handle | Width / Height、Corner Radius、Resolution |
| Sector | 角度範囲、扇形操作 | Inner / Outer Radius、Start / Sweep Angle、Resolution |
| Custom Object | 制作者固有の形 | 既存Mesh Object、Wire Width |
| None | Custom Shapeを表示しない | なし |

曲線と3D変形Shapeの`Resolution`は既定`96`、最大`256`とする。特に円筒・球面矢印は旧Prototypeより高い既定解像度で、輪郭の角張りを抑える。`Wire Width`は表示線幅だけを変え、GeometryやSolverには影響しない。Bone ColorはPresentation適用時に上書きしない。

### 13.3 Stageへの割り当て

- `Projected Transform`: Primary Controlへ一つ
- `Kinematic Chain`: IK HandleとPoleへ独立した二設定
- `Spline Chain`: Stage内の全Spline Controlで一設定を共有
- `Recorded Pose Map`、`Contact / Pin`、`Secondary Motion`: 自身ではControlを生成しないため、上流StageのPresentationを利用

Custom Shapeは`Display Frame`用Boneを`custom_shape_transform`として維持する。見た目の向きは変更できるが、Control Boneの入力FrameとArt Plane評価を変更しない。

### 13.4 Blender UIでの設定

1. ArmatureをPose Modeにし、Nパネルの`COA Tools2 > Character Rig`を開く。
2. Componentと対象Stageを選ぶ。生成Control Boneを選択した場合は、そのComponent / Stageへ自動同期する。
3. `Control Presentation`、`IK Handle Presentation`、`Pole Presentation`、または`Spline Controls Presentation`を展開する。
4. `Shape`を選び、表示されたShape固有Parametersを調整する。
5. `Live Preview`が有効なら短いDebounce後に表示だけを自動反映する。無効なら`Apply`を押した時点で反映する。

`Custom Object`はユーザー所有のMeshを直接参照し、COA Tools 2はそのObjectを削除・改変しない。`None`へ変更するとBoneのCustom Shapeを解除し、以前の生成Widgetだけを安全にCleanupする。IKではHandleとPoleを別々に設定できる。

Presentation更新は専用Transactionで実行する。失敗時はCustom Shape割り当て、所有Object、Geometry Nodes Modifierと入力値をRollbackし、IK、Pose Map、Spline、Driver、Animation Dataを再構築しない。

## 14. 保存Schema案

```text
SemanticRigSpec
├─ rig_uuid / version / label
├─ rig_kind: STATE | CHARACTER
├─ controls[]
│  ├─ display_frame
│  ├─ input_frame
│  └─ semantic_channels[]
├─ nodes[]
│  ├─ node_uuid / node_type / stage
│  ├─ inputs[] / outputs[]
│  └─ settings
├─ links[]
├─ output_bindings[]
├─ presentation
└─ ownership
```

Node間接続は名前文字列だけでなく、UUIDと型付きPortで保存する。Bone、Object、Shape Key等の外部参照は既存の名前修復情報を引き継ぐ。

`RECORDED_POSE_MAP`のSampleはRig本体と分離可能なCollectionとし、左右共有、Preset複製、差分更新を可能にする。

## 15. 移行方針

### 15.1 既存State Rig

- そのまま動作させる。
- 既存Slider / Matrixの保存形式を暗黙変換しない。
- Semantic Rigから`STATE_RIG_ADAPTER`経由で値を読み書きできるようにする。
- 新規作成分から、必要に応じてN次元Pose Map Schemaを内部利用する。

### 15.2 現行Character Component

- `PARAMETRIC`は`PROJECTED_TRANSFORM + Output Binding`へ明示変換できる。
- `DIRECT_BONES LIMB_IK`は`KINEMATIC_CHAIN`のSource候補としてAdoptできる。
- Source Bone、Action、未所有Constraintを自動変更しない。
- 変換前に追加、維持、競合、非対応項目をPreflight表示する。
- 旧Componentは読み取り・削除・Bake可能なLegacy Adapterとして当面維持する。

### 15.3 Versioning

Semantic Rig Schema、Node Schema、Pose Map Sample Schemaを別々にVersion管理する。CacheはVersion不一致時に破棄・再Compileし、ユーザーSampleは失わない。

## 16. 実装順

### Phase 1: Semantic Rig共通Schema

- `SemanticRigSpec`、型付きNode / Port / Link
- Display / Input / Mechanism / Art Frame
- Solver StageとOutput Mixer
- Graph循環、型、参照、所有のValidation
- State Rig AdapterとLegacy Component Adapterの境界

Acceptance:

- 保存・再読込でUUID、Frame、Node接続が一致する。
- 異なるNode種類を一つのRigへ複合できる。
- 循環、Port型不一致、未解決参照をCompile前に検出する。
- 既存State RigとCharacter Componentを変更しない。

### Phase 2: Projected Transform + Recorded Pose Map

- Display FrameとInput Frameの分離
- Screen Move、Axial Rotate、Apparent Normal Move
- N次元Channel Schemaと正規化
- 1D / 2D Adapter、局所RBF、離散出力
- Bone、Shape Key、Slot、PropertyのSnapshot記録
- Sample編集時Compile Cache

Acceptance:

- 3入力以上、複数出力のSampleを補間できる。
- 角度境界、疎なSample、重複SampleでNaNや発散が起きない。
- Widgetを傾けてもArtが意図せず奥行き移動しない。
- Sample点では記録値を許容誤差内で再現する。
- State Matrixを2D Adapterとして既存挙動を保ったまま利用できる。

### Phase 3: Mechanism / Presentation分離IK

- MCH IK ChainとPresentation DEF経路
- 関節位置、Swing / Twist、Reach Feature
- 平面投影Policy
- IK結果からRecorded Pose Map / State Rigを駆動
- Kinematic PolicyとPose Match基盤

Acceptance:

- IK Target移動でMCH Chainが実際にIKする。
- Art Plane維持設定では平面メッシュの法線が変化しない。
- 許可した画面内回転と位置はIK結果へ追従する。
- 関節角や仮想奥行きからShape Keyを駆動できる。
- Direct Bone IKの既存Actionを変更しない。

### Phase 4: Pin / Release Transition

- Position / Orientation / Space / Weight Pin
- Active Frame Range
- World、Character、Prop Space
- Switch and Match Offset
- Release TransitionとBake

Acceptance:

- Pin開始・終了フレームでWorld Poseが飛ばない。
- 固定中に親またはPropが動いても指定Spaceを維持する。
- Release区間を変更しても元のControl Keyを破壊しない。
- IK/FK、Recorded Pose Mapと同一Rig内で合成できる。

### Phase 5: Spline Chain + Secondary Motion

- NURBS Curve / Hook / Spline IK Adapter
- 3D MechanismをArt Planeへ戻すProjected Presentation Chain
- Root / Tip Pin、Twist、Stretch
- Spring / Lag / Damping
- 決定論的な位置Secondary Motion Bake
- Spline FeatureからCorrective Pose Mapを駆動

初期実装では、解析解Springを明示的にBakeし、完成したAction / NLAだけを原子的に差し替える。常時HandlerによるLive Physicsは使用しない。B-Bone Adapter、回転Spring、Live Preview Cache / Reset UI、Splineの曲率・短縮量等を直接Semantic Channelへ公開するAdapterは後続実装とする。Spline Controlそのものは通常のPose Map入力として利用できる。

Acceptance:

- 可変Bone数のSpline Chainを冪等生成できる。
- PinとSecondary Motionを任意に有効・無効化できる。
- 同じ初期条件と固定Substepで同じ結果を再現する。
- Scrub、Save / Reload、Bake後に結果が破綻しない。
- Secondary Motionなしの基礎Animationを保持する。

### Presentation Phase: Procedural Custom Shape

Phase 1〜5の内部評価に依存しないPresentation Layerとして実装済み。

- 意味別の共有GN Groupと、Stage / RoleごとのSource Object Parameter
- Flat / Cylindrical / Spherical Arrow、Tombstone、幾何形状、Sector
- 評価済みEdge-only Cache MeshとDisplay Frameへの配置
- IK Handle / Poleの独立設定、Spline Controlsの共有設定
- Custom Object / Noneへの非破壊切替
- Debounce付きLive Previewと手動Apply
- 所有Artifact、Modifier入力、Custom Shape割り当てのRollback

Acceptance:

- Shapeまたは寸法だけの変更でSolver、Driver、Keyframeを再構築しない。
- 同じ設定の再適用でWidget Object、Modifier、Artifact Recordが重複しない。
- 全Procedural Shapeが面を持たないEdge-only Geometryを返す。
- 生成ObjectのRename、Save / Reload、Armature複製後も所有Roleから復旧できる。
- 3D Shapeは既定96、最大256 Segmentで調整できる。
- Custom Objectはユーザー所有のまま保持し、None切替で削除しない。

## 17. 検証方針

### 17.1 Pure Python

- Schema Round TripとVersion移行
- Node Graphの型・循環検査
- N次元正規化、近傍探索、RBF係数
- 離散Modeと連続出力の分離
- Output Mixerの決定性

### 17.2 Blender Headless

- Artifactの冪等生成と所有範囲
- Save / Reload、Undo / Redo
- 3次元以上のPose Map評価
- IK、Pin、Splineの合成
- Art Plane法線維持
- Secondary MotionのCacheとBake
- Procedural WidgetのTopology、冪等性、Shape切替とRollback
- Live Preview / Manual Apply、Custom Object / None
- 既存State Rig / Legacy Componentの非破壊性

### 17.3 DCC実機

- Control選択とKeyframe UX
- 見た目軸と入力方向の一致
- IKからShape Keyへの操作感
- Pin / Releaseの時間編集
- Spline Control数と操作負荷
- 10〜20 Rig、数百Sample時のViewport性能
- GN Widgetを差し替えてもAnimationが変化しないこと

## 18. 完了条件

次を満たした時点で、Semantic Character Rigの内部基盤を完成とみなす。

1. State RigとCharacter Rigを明確に区別しつつ、同じOutput Bindingへ接続できる。
2. Character Rigを部位名ではなく、複合可能なNodeで構成できる。
3. Display、Input、Mechanism、Artの各Frameを独立して変更できる。
4. 3次元以上のRecorded Pose Mapが実用的な性能と安定性で評価できる。
5. 実IKとArt Plane維持を同時に実現できる。
6. Pin、Spline、Secondary Motionを他Nodeと複合できる。
7. 既存State Rig、Action、未所有Artifactを暗黙変更しない。
8. 最終結果をBone / Shape Key / Slot / PropertyへBakeできる。
9. GN Custom Shapeを変更・解除・Custom Objectへ差し替えても内部評価とAnimationが変化しない。

## 19. 今回の決定事項

| 項目 | 判断 |
| --- | --- |
| ユーザー向け名称 | State Rig / Character Rig |
| 共通内部基盤 | Semantic Rig |
| Character Rigの定義 | 複数要素を一つの意味的動作へまとめる操縦桿 |
| 部位専用Componentのみで構成 | 不採用 |
| Node種類の複合 | 採用 |
| 1D / 2D専用の新規補間Schema | 不採用 |
| 最終的な3D以上への対応 | 初期Schemaから採用 |
| N次元標準補間 | 正規化した局所RBF |
| State Matrix | N次元Pose Mapの2D Adapterとして再利用 |
| Mechanism Pose / Presentation Pose分離 | 採用 |
| IK/FK Sliderだけを切替の中核にする | 不採用 |
| PinをIK/FKへ内包 | 不採用。独立Nodeとして合成 |
| SplineとSecondary Motion | 独立Nodeとして合成 |
| GN Custom Shape | 内部機構から独立したPresentation Layerとして採用・実装済み |

## 20. 関連資料

- [2Dリグコントローラー調査・設計案](rig_control_design.md)
- [Rig Graph実装計画](rig_control_graph_implementation_plan.md)
- [Phase 5: Matrix DomainとRig Name表示](rig_control_phase5_matrix_domain.md)
- [Phase 6: Character Posing Rig Components](rig_control_phase6_character_posing.md)
- [Phase 6 キャラクターリグ現行実装資料](rig_control_phase6_current_implementation_inventory.md)
