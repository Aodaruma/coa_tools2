# Phase 6: Character Posing Rig Components 設計案

## 1. 結論

COA Tools 2のキャラクターポージング機能は、既存のState Graphを拡張してすべてを表現するのではなく、次の二つを同じControl基盤上で組み合わせる構成がよい。

1. **State Control**
   - Shape Key、Sprite Slot、描画順、表情、顔向き等の「絵の状態」を連続・離散制御する。
   - 現在のSlider、Dial、Rectangle、State Matrix、Binding、StateDataを使用する。
2. **Pose Rig Component**
   - 既定の`PARAMETRIC`では、3D Control Transformを「絵の状態を選ぶ入力」として管理する。
   - Source / DEF BoneへIKや回転を伝えず、BindingからShape Key等を駆動する。
   - 旧方式が必要な場合だけ`DIRECT_BONES`を明示的に選ぶ。

両者の役割は異なるが、アニメーターからは一つのリグに見えるようにする。

```text
Animator Input
├─ State Control
│  ├─ Face Direction
│  ├─ Mouth Form / Open
│  ├─ Shoulder Corrective
│  └─ Sprite / Z / Shape Key
└─ Pose Rig Component
   ├─ Root / Part / Limb / Spine Control
   ├─ Local Move X/Y/Z
   ├─ Local Rotate X/Y/Z
   └─ Output Bindings
          │
          ▼
     Shape Keys + Art State
```

### 1.1 重要な実装方針

COAの平面メッシュへBlenderの3D回転をそのまま適用すると、絵が紙の板のように傾く。これは本機能の既定動作にしない。

```text
PARAMETRIC（既定）
CTRL Transform ──Driver──> Shape Key / Constraint Influence
Source Bone     ─────────> 変更しない

DIRECT_BONES（互換用）
CTRL Transform ──IK/FK──> Source / DEF Bone
```

`PARAMETRIC`のControlは、見た目基準の局所座標を持つ非Deform Boneである。移動・回転はControl自身にKeyframeするが、Source BoneのPose Matrix、平面メッシュの奥行き座標、Bone Parent Transformは変化させない。各軸へ何を割り当てるかは、リグ外郭を生成した後に`Shape Key & Property Outputs`から追加できる。

既存Schema v1のComponentは互換性のため`DIRECT_BONES`として読み込む。新規Componentだけを`PARAMETRIC`既定とし、旧リグを暗黙変換しない。

最初の実装対象は、既存のIK機能と現行Rig Control基盤を再利用でき、キャラクター全身の操作性へ直結する次の5種類とする。

1. `ROOT`
2. `FK_CHAIN`
3. `LIMB_IK`
4. `IK_FK_MIX`とSnap
5. `SPINE_FK`

肩・顔・口は重要だが、骨格だけで完結させず、上記ComponentとState Controlを合成するプリセットとして第2段階で実装する。

## 2. 本書の対象

本書でいう「ポージングリグ」は、アニメーターがキャラクターの骨格ポーズを作るための操作構造を指す。

- 画面内の移動、回転、拡縮
- 関節のFK操作
- 手足のIK操作
- IK/FK切替とポーズ維持
- 胴体、首、頭の階層操作
- 親空間の切替
- 手足の接地や小道具への固定
- 髪、尾、布等の柔軟なチェーン

次は関連するが、State Controlまたは別Projectの責務とする。

- Shape Key間の補間
- Sprite Slotと描画順
- 顔向き、口形、瞬き等の多状態補間
- 3D Poseから2D Poseを推定するInverse Matching
- 自動Lip Sync、物理演算、モーションキャプチャ

## 3. 現状の資産と不足

### 3.1 再利用できるもの

現行COA Tools 2には、ポージングリグへ転用できる次の資産がある。

- SpriteObject Armatureと通常のPose Bone Animation
- Bone Collection対応を含むBone分類処理
- 既存のIK生成Operator
- 既存のStretch IK生成Operator
- Constraint、Driver付きBoneを最終TransformへBakeするExport処理
- Rig ControlのUUID、所有タグ、Validate / Repair
- Geometry Nodesによる共有Widget生成
- 1D、2D、Dial、State MatrixのControl
- Control選択とUIフォーカスの同期
- Manual UpdateとLive Preview

既存IKは、選択チェーンへIK Targetを作り、2D用に関節軸を制限する最小機能をすでに持つ。一方で、生成物の意味、所有関係、再生成、IK/FK切替、Snap、左右対称生成、Animation保護はComponentとして管理されていない。

### 3.2 現在のState Controlだけでは不足する理由

State Graphは入力値から状態を補間するには適しているが、骨格構造の生成・更新には次の情報が必要になる。

- どのBone Chainを操作するか
- CTRL、MCH、DEFの役割
- ConstraintのTarget、順序、Owner Space
- Rest PoseとConstraint Inverse
- IK Chain LengthとPole/Bend方向
- IK/FK切替時のSnap手順
- 生成BoneやConstraintの所有関係
- 既存Animationを維持した再構築

これらをState PointやBindingへ埋め込むと、State補間と構造Compilerが混ざり、単純な顔Controlでも骨格用設定を意識させることになる。そのため、`RigControl`と`RigComponent`を分離する。

## 4. 他方式から採用する考え方

### 4.1 Blender

BlenderのArmatureは、Bone階層、Constraint、Driver、Pose Actionをネイティブに保存・評価できる。COA Tools 2でも、Runtime Solverを独自実装するより、Blenderの評価結果を利用する方が再生、保存、Undo、Exportとの整合性が高い。

採用する要素:

- IK Constraintによる手足の解法
- Copy TransformsによるMCHからDEFへの伝達
- Child OfによるSpace Switch
- Floorまたは明示的な平面制限による接地
- B-Boneによる滑らかな局所変形
- Spline IKによる長い柔軟チェーン
- Pose Assetによる再利用可能な完成ポーズ
- Bone CollectionによるCTRL / MCH / DEF / UIの表示分離

ConstraintはStack上から下へ評価されるため、Component Compilerが順序を明示し、Validate対象にする。

参考:

- [Blender: Inverse Kinematics Constraint](https://docs.blender.org/manual/en/latest/animation/constraints/tracking/ik_solver.html)
- [Blender: Constraint Stack](https://docs.blender.org/manual/en/latest/animation/constraints/interface/stack.html)
- [Blender: Bendy Bones](https://docs.blender.org/manual/en/latest/animation/armatures/bones/properties/bendy_bones.html)
- [Blender: Pose Library](https://docs.blender.org/manual/en/latest/animation/armatures/posing/editing/pose_library.html)
- [Blender: Bone Collections](https://docs.blender.org/manual/en/latest/animation/armatures/properties/bone_collections.html)

### 4.2 Spine

SpineではConstraintのMixによって、元のBone TransformとIK、Transform、Path等の結果を連続的に合成する。SliderはBoneのTransformをAnimation Frameへ対応付けるUIとして機能する。

COA Tools 2では次を採用する。

- Constraint Influenceを0〜1で制御するIK/FK Mix
- ConstraintなしのPoseとConstraint適用Poseの連続合成
- 1D Sliderをモード値だけでなくMix値にも使用する
- Path Constraint相当を、特殊な曲線操作だけへ限定する

参考:

- [Spine: Constraints](https://esotericsoftware.com/spine-constraints)
- [Spine: Sliders](https://esotericsoftware.com/spine-sliders)
- [Spine: Path Constraints](https://esotericsoftware.com/spine-path-constraints)

### 4.3 Live2D

Live2Dでは、Rotation DeformerとWarp Deformerを階層化し、回転と非線形な絵の変形を分離する。また、X/YのParameterへ複数Keyformを割り当て、顔や身体の向きを表現する。

COA Tools 2では次へ対応させる。

| Live2D | COA Tools 2 |
| --- | --- |
| Rotation Deformer | FK / Parent Bone |
| Warp Deformer | DEF Bone + Shape Key |
| Parameter | Rig Control |
| Keyform | StateData / Shape Key / Slot |
| Deformer hierarchy | CTRL / MCH / DEF + Art hierarchy |

大きな回転を単一Shape Keyの線形補間だけで表現すると、輪郭の縮みや潰れが起きやすい。そのため見かけの3D回転は、正負方向のDirect Bindingまたは複数点のState Matrixへ分割する。画面内を含めSource Boneの回転を使うかは`DIRECT_BONES`を明示的に選んだ場合だけとする。

参考:

- [Live2D: Deformers](https://docs.live2d.com/en/cubism-editor-manual/deformer/)
- [Live2D: Warp Deformer](https://docs.live2d.com/en/cubism-editor-manual/making-and-placement-of-warp-deformer/)
- [Live2D: Keyform Editing in X and Y Directions](https://docs.live2d.com/en/cubism-editor-manual/keyform-xydirection/)

## 5. 共通アーキテクチャ

### 5.1 Boneの役割

```text
SpriteObject Armature
├─ GLOBAL_CTRL
├─ CTRL
│  └─ アニメーターが選択・KeyframeするBone
├─ MCH
│  └─ IK、Space、Blend、Pivot等の計算用Bone
├─ DEF
│  └─ Sprite Meshを実際に変形し、ExportされるBone
└─ UI
   └─ Base、Name、補助表示用の非変形Bone
```

Blender 4.0以降では、対応するBone Collectionを作る。

- `COA Controls`
- `COA Mechanism`
- `COA Deform`
- `COA UI`

一つのBoneは必要に応じて複数Collectionへ所属できるが、Roleは一意にする。Role、Component UUID、Artifact RoleをCustom Propertyへ保存する。

### 5.2 データの責務

| データ | 責務 | 主な生成物 |
| --- | --- | --- |
| `RigControl` | 一つの入力とViewport表示 | Control Bone、Widget、Name |
| `Binding` | 入力値からTarget値への写像 | Driver、Constraint Influence |
| `StateData` | 複数Targetの疎な状態差分 | Shape Key、Property、Bone差分 |
| `RigComponent` | 骨格モジュールとConstraint構造 | CTRL、MCH、Constraint、Property |
| `RigVariant` | 構造そのものの切替 | Component集合、Art構成 |

`RigComponent`は複数の`RigControl`を所有または参照できる。例えばLimb Componentは、IK Target、Bend、IK/FK Sliderの3 Controlを参照できる。

### 5.3 評価方向

```text
Rig Control Transform / Property
        │
        ├─ Bone Constraint / Driver ──> MCH ──> DEF
        │
        └─ Binding / StateData ───────> Shape Key / Slot / Z
```

循環を防ぐため、DEF BoneまたはArt OutputをControl入力へ戻さない。自動補正の入力としてBone Transformを読む場合も、補正結果が同じBoneの解法へ戻らないようValidationする。

### 5.4 見た目基準のControl Frame

キャラクターポージング用Controlはカメラ平面へ固定せず、パーツごとに次の右手系局所座標を持つ。

```text
local X = U = 絵の横方向
local Y = V = 絵の縦方向、またはBoneの長さ方向
local Z = N = 絵の法線、見た目上の奥行き方向
```

例えば手のControl Frameを手のひらと平行に置くと、local Z移動は手のひら法線方向の移動になる。足、肩、頭、胴体も同じ考え方で、見た目に合う局所3軸TransformをDriverやStateDataの入力として利用できる。

Frameの設定方式:

| Mode | 基準 |
| --- | --- |
| `WORLD_VIEW` | Armature X-Zを絵の面、Yを奥行きとする |
| `SOURCE_BONE` | 指定BoneのRest MatrixとRollを使用する |
| `CUSTOM` | SourceまたはWorld FrameへEuler Offsetを加える |

Boneのlocal Yは必ずBoneの長さ方向になるため、local Zを法線として使うにはBone Rollを含む完全なFrameが必要になる。生成Controlでは非表示の`MCH_<component>_FRAME`を作り、Controlの移動軸、Widget表示、Limitの共通基準にする。Source Bone自身を操作するIn-Place FKは`DIRECT_BONES`互換モードに限定する。

参考:

- [Rigify: Limbs](https://docs.blender.org/manual/en/latest/addons/rigging/rigify/rig_types/limbs.html)
- [Cascadeur: Rigging Tools / Custom rotation](https://cascadeur.com/help/rig/rig_mode/rigging_tools)
- [Blender: Bone Roll](https://docs.blender.org/manual/en/latest/animation/armatures/bones/editing/bone_roll.html)

### 5.5 奥行き移動

奥行きはWorld Yへ固定せず、Control Frameのlocal Zとして扱う。

| Mode | 挙動 | 推奨対象 |
| --- | --- | --- |
| `LOCKED` | local Zを0へ固定 | 従来型2D操作 |
| `LIMITED` | `depth_min..depth_max`のSlab内だけ移動 | 手、足、肩、頭、IK Target |
| `FREE` | 3D移動を制限しない | Root、特殊Control |

既定値は`LIMITED`とする。カメラ正面からドラッグして無制限に奥へ移動しないよう、local ZだけをLocal SpaceのLimit Locationで制限し、X/Y移動と3軸回転は許可する。Depth範囲は前後で別値にできる。

`PARAMETRIC`ではlocal Zを実奥行き移動へ伝えず、入力範囲を正規化してShape Key等へBindingする。実座標による奥行き移動は`DIRECT_BONES`と分離し、カメラ方向へ依存するConstraintは使用しない。

## 6. `RigComponent`データモデル

初期SchemaはGeneric Node Graphにせず、型付きPresetを保存する。

```text
RigComponentSpec
├─ schema_version
├─ component_uuid
├─ semantic_id
├─ display_name
├─ component_type
├─ side: CENTER | LEFT | RIGHT
├─ enabled
├─ source_bones[]
├─ control_uuids[]
├─ orientation_mode / reference / offset
├─ depth_mode / depth_min / depth_max
├─ settings
└─ generated_artifacts[]
```

`source_bones`は当面Armature内のBone NameとSemantic Tagを併用する。BlenderのBone参照には安定UUIDがないため、生成BoneにはUUIDを付与し、ユーザーBoneは名前変更時に候補を提示してRepairする。

生成物には次を保存する。

```text
ArtifactRef
├─ artifact_uuid
├─ component_uuid
├─ role
├─ data_type
├─ object_name
├─ bone_name
├─ constraint_name
└─ owned
```

主な`role`:

- `CTRL_BONE`
- `MCH_BONE`
- `DEF_LINK`
- `CONSTRAINT`
- `CUSTOM_PROPERTY`
- `DRIVER`
- `WIDGET_SOURCE`
- `NAME_BONE`
- `TEXT_OBJECT`

既存のRig Control所有タグと同じ原則を使い、所有していないBone、Constraint、Driverは自動削除しない。

## 7. 推奨Component

### 7.1 `ROOT`

キャラクター全体または局所グループの親となるControl。

標準操作:

- 3軸移動
- 3軸回転
- 一様Scale
- 見た目の法線方向だけ任意に奥行き制限

標準構造:

```text
GLOBAL_CTRL
└─ CTRL_root
   └─ DEF_rootまたは既存Root Chain
```

Widget:

- 二重円
- 四方向矢印
- 必要なら中央十字

`GLOBAL_CTRL`は非空間Propertyの保持先として残し、キャラクターを動かすRoot Controlとは分ける。これにより、Root ScaleやTransformの影響を受けずにIK/FK、Space等の値を保持できる。

### 7.2 `FK_CHAIN`

選択した既存DEF Chainを直接回転操作する最小のポージングComponent。

標準操作:

- 各関節の3軸回転
- 必要な関節だけLimit Rotation
- Root Boneのみ任意で移動を許可

Widget:

- 関節を囲む円または円弧
- Bone方向が分かる短い線
- 末端は部位固有形状を選択可能

初期実装ではDEF Chainを複製せず、既存Bone自身をControlとして表示できるモードを用意する。既存AnimationとBone Nameを保ち、生成物と再構築コストを抑えるためである。

次の場合だけ、別CTRL ChainからDEFへCopy Transformsする。

- DEFをAnimatorから完全に隠したい
- Constraint StackをDEFから分離したい
- IK/FKの二重Chainを採用する
- Export用Bone構成を固定したい

### 7.3 `LIMB_IK`

腕または脚の2-Bone Chainを手先・足先から操作する。

標準構造:

```text
upper_DEF
└─ lower_DEF
   └─ end_DEF

CTRL_ik_end
MCH_ik_target
optional CTRL_bend
optional MCH_bend_center
```

標準設定:

- Chain Length: 2
- Stretch: OFF
- FKは全軸回転を許可し、IKの曲げ軸だけをRest Poseまたは明示設定から決定
- End Rotation Follow: 任意
- Bend方向: Rest Poseから決定
- Pole Target: 通常は非表示
- Spatial IKでPoleを表示する場合、レスト時の膝／肘位置に置いた
  `MCH_bend_center`をTargetとする`Limit Distance / On Surface`で軌道を制限する

現行`Set IK` Operatorの処理をComponent Compilerへ移し、次を追加する。

- 所有タグ
- 冪等なUpdate
- 既存ConstraintとのConflict検出
- 左右対称生成
- Bend方向の明示と修復
- IK/FK Mix
- Snap
- Export Bake Test

カットアウトではPoleを常時表示すると操作量が増えるため、標準はRest PoseのBend方向とし、空間的な曲げ方向を明示したい場合だけ小さな菱形Controlを表示する。Pole自身がIK解を決めるため、距離制限のTargetに評価後の膝／肘Boneを直接使わない。IK Chain外の非変形`MCH_bend_center`を使うことで依存循環を避ける。

### 7.4 `IK_FK_MIX`

初期実装は、同じDEF/FK Chainへ置いたIK ConstraintのInfluenceを0〜1で制御する。

```text
ik_fk = 0.0  -> FK Transform
ik_fk = 1.0  -> IK Solve
```

Control:

- 既存1D Slider
- または`GLOBAL_CTRL["arm_l_ik_fk"]`

必須Operator:

- `Snap FK to IK`
- `Snap IK to FK`

Snapは、表示上のPoseを維持したまま操作方式を切り替える。単にInfluenceを変えるだけでは手足が飛ぶため、IK/FK実装と同じPhaseで必ず提供する。

#### 単一Chainを先に採用する理由

3D Character Rigで一般的な`DEF + FK + IK`三重Chainは強力だが、Bone数、Constraint数、生成・修復・Exportのコストが高い。COAの2D Chainでは、FK PoseにIK Influenceを合成する単一Chain方式で大部分の用途を満たせる。

次の実例が確認された時点で、三重Chainを追加する。

- FKとIKを独立に常時保持したい
- 中間Influenceで単一Chainの結果が不安定
- Constraint順序が既存Rigと衝突する
- Bake前後のPose一致を保証できない
- 複雑なStretch、Twist、Spaceを同時使用する

### 7.5 `SPINE_FK`

人型の腰、腹、胸、首を2〜4 BoneのFK Chainとして構成する。

標準構成:

```text
CTRL_cog
└─ hips
   └─ abdomen
      └─ chest
         └─ neck
```

標準操作:

- COGの3軸移動と3軸回転
- 腰、腹、胸の局所3軸回転
- 必要なら胸の小さな3軸移動
- Scaleは既定で禁止

B-Boneは滑らかな胴体変形に有効だが、Segment増加による評価コストとExport差を持つため、初期Presetでは任意設定にする。通常のカットアウトでは2〜3本のDEF BoneとShape Key補正を先に試す。

### 7.6 `CLAVICLE_SHOULDER`

肩は骨格の回転だけでは絵の輪郭を保ちにくいため、Pose ComponentとState Controlを合成する。

```text
CTRL_clavicle
└─ MCH_shoulder
   └─ upper_arm_DEF

upper_arm angle
├─ MCH shoulder offset
├─ shoulder_up/down StateData
├─ shoulder_forward/back Shape Key
└─ arm front/back Art State
```

第1段階:

- 鎖骨の手動回転・移動
- 上腕のFK/IK
- 手動Corrective Slider

第2段階:

- 上腕角度から補正値を自動生成
- 自動値へ手動Overrideを加算
- 腕の前後に応じたSlot / Z制御

Slotと描画順はRender安定性を確認した後に有効化する。

### 7.7 `HEAD_FACE`

頭の画面内回転と、顔が上下左右を向く表現を分離する。

```text
CTRL_head_rotation -> Bone Y Rotation
CTRL_face_direction -> State Matrix X/Y
```

- Head Rotation: 円形Widget、Limit Rotation
- Face Direction: 既存State Matrix
- Eye Direction: CircleまたはRectangle Free
- Blink: 1D Slider

これにより、頭を傾けたまま顔だけ横へ向ける等、Bone PoseとArt Stateを独立にKeyframeできる。

### 7.8 `MOUTH`

口は骨格Componentとして独立させず、State Control Presetを中心にする。

```text
X: Mouth Form  (-1..1)
Y: Mouth Open  ( 0..1)
Optional: Viseme Slot
```

顎Boneが必要なキャラクターでは、Mouth OpenのBinding先へJaw Rotationを追加する。Action ConstraintはTransformへしか作用せずShape Keyを直接駆動できないため、口全体をAction Constraintへまとめない。

参考: [Blender: Action Constraint](https://docs.blender.org/manual/en/latest/animation/constraints/relationship/action.html)

### 7.9 `SPACE_SWITCH`

手、足、頭、小道具等の親空間を切り替える。

候補:

- World
- Root
- Chest
- Head
- Prop

Child Of Constraintを複数置き、Influenceを相互排他的に切り替える。切替時にはInverse Matrixと現在のWorld Transformを計算し、Poseが飛ばない`Switch and Snap`を提供する。

Spaceは離散的な意味を持つため、画面上のSliderよりDropdownまたはButtonが適切である。必要ならPropertyをName Control近傍へ表示する。

### 7.10 `CONTACT`

接地と接触は対象形状によって方式を分ける。

| 用途 | 推奨 |
| --- | --- |
| 水平な床 | Floor Constraintまたは明示的なLimit |
| 画面内の直線Rail | Limit Location / Clamp To |
| 曲線Rail | Curve + Clamp To / Follow Path |
| 不規則なMesh表面 | Shrinkwrap |
| 小道具へ手を固定 | Child Of / Copy Transforms |

通常のIK Targetや2D SliderにはShrinkwrapを使わない。Target MeshのTopologyやProjection方向へUI挙動が依存し、リグ編集時の予測性が下がるためである。

### 7.11 `FLEXIBLE_CHAIN`

髪、尾、布、触手等は、複雑さに応じて段階的に提供する。

1. FK Chain
2. B-Bone + Custom Handle
3. Spline IK
4. 任意でStretch

標準はFKとし、Spline IKは長いChainだけに用いる。自動物理は別機能とし、生成Componentの必須要素にしない。

## 8. Widgetと操作意味

色に依存せず、形だけで意味が分かることを基本とする。現状はCustom Shapeへ色を付けない。将来はSideまたはRole別の任意Themeを追加できる。

| 意味 | Widget | 操作 |
| --- | --- | --- |
| Root | 二重円 + 四方向矢印 | Move / Rotate / Scale |
| COG | 菱形または十字 | Move / Rotate |
| FK Joint | 円または円弧 | Rotate |
| IK Target | 角丸四角、手、足 | Move / Rotate |
| Bend / Pole | 小さな菱形 | Bend Direction |
| IK/FK | 1D Slider | 0..1 Mix |
| Head Rotation | 円 | Rotate |
| Face / Body Direction | State Matrix | X/Y State |
| Foot Roll | 円弧またはDial | Heel / Toe Roll |
| Space | Dropdown / Button | Discrete Switch |
| Name | 下部中央のText | Component識別 |

BaseやName Boneを選択した場合も、対応するRig ComponentとPrimary ControlをUIで選択する。Widget寸法やName Offsetは折りたたみ可能なVisual Settingsへまとめる。

## 9. Constraint方針

### 9.1 基本対応

| Component | 主なConstraint /設定 |
| --- | --- |
| Root / COG | Axis Lock、Limit Location / Rotation / Scale |
| FK | Pose Transform、Limit Rotation |
| Limb IK | IK、PoseBone IK Lock / Limit |
| IK/FK Mix | IK Influence Driver |
| DEF Follow | Copy Transforms |
| Space Switch | Child Of |
| Flat Contact | FloorまたはLimit |
| Surface Contact | Shrinkwrap |
| Curved Slider | Clamp To / Follow Path |
| Flexible Chain | Spline IK |
| Smooth Deform | B-Bone |

### 9.2 Stack順序

標準順序:

```text
CTRL
├─ Space / Parent
└─ 操作範囲Limit

MCH
├─ Space Switch / Child Of
├─ IK / Copy Transforms
└─ 補正Transform

DEF
├─ MCHからのCopy Transforms
└─ 最終的な局所Corrective
```

BlenderのIKは通常のConstraintとは異なる評価を持つため、IKと同一Bone上のConstraintを増やしすぎない。Component Compilerは既存Constraintを検査し、既知の順序へ移動するか、Conflictとしてユーザーへ提示する。

### 9.3 Action Constraint

Action Constraintは、Bone TransformからAction内のObject/Bone Transformを再生する用途に限定する。

- Shape Keyを直接変形しない
- Armature全体のPose Actionを一つのArmature Constraintから安全に再生する用途には向かない
- Action名、対象Bone名、Frame Rangeへの依存が強い

したがって、表情・肩補正・口はBinding / StateData、再利用可能な完成ポーズはBlender Pose Assetを優先する。

## 10. State Controlとの統合

### 10.1 一つのControlから骨格と絵を制御する

Bindingは複数Targetを持てるため、同じControlからBoneとArt Stateを同期できる。

例: Shoulder Lift Slider

```text
Slider Value
├─ clavicle rotation
├─ shoulder MCH offset
├─ shoulder_up Shape Key
└─ sleeve_corrective Shape Key
```

例: Body Direction State Matrix

```text
Matrix X/Y
├─ torso Shape Keys
├─ shoulder width
├─ hip width
├─ face/body Sprite State
└─ arm front/back state
```

### 10.2 `PoseState`、`RigMode`、`RigVariant`

名称を次の意味へ固定する。

| 種類 | 例 | 補間 |
| --- | --- | --- |
| `PoseState` | 顔向き、肩形、口形 | 連続またはMask |
| `RigMode` | IK/FK、Space、Stretch | 連続または離散 |
| `RigVariant` | 腕構造、Art Set、別衣装 | 原則として構造切替 |

IK/FKは見かけ上Poseを変えるが、State MatrixのState Pointではなく`RigMode`である。顔向きは骨格Modeではなく`PoseState`である。この区別をUI Labelと保存Schemaの両方へ反映する。

## 11. UI案

N Panelへ`Pose Rig Components`を追加する。

```text
Pose Rig Components
├─ Add Component
│  ├─ Root / COG
│  ├─ FK Chain
│  ├─ 2D Limb IK
│  ├─ Spine FK
│  └─ Flexible Chain
├─ Components
│  ├─ Arm.L [2D Limb IK]
│  └─ Spine [FK]
├─ Selected Component
│  ├─ Source Bones
│  ├─ Behavior
│  ├─ IK/FK and Snap
│  └─ Visual Settings [collapsed]
├─ Validate
├─ Repair
└─ Rebuild
```

### 11.1 作成操作

- ObjectまたはPose ModeでBoneを選択する。
- `Add Component`から種類を選ぶ。
- 選択順とChainをPreflightで表示する。
- 生成前に、追加・更新・Conflictを要約する。
- 既存AnimationがあるBoneのRename、Reparent、削除は明示確認する。

### 11.2 Live Preview

Live Previewの対象を分ける。

| 変更 | Live Preview |
| --- | --- |
| Widget寸法、Name位置 | ONで即時反映 |
| Constraint Limit、Mix初期値 | ONで反映可能 |
| Bone生成、削除、Reparent | Manual Applyのみ |
| Chain変更、Rig方式変更 | Manual Rebuildのみ |

構造変更をAnimation作業中に自動適用すると、F-Curve PathやPoseが壊れる危険がある。既存のLive Preview Check BoxはVisual / Parameter更新へ使い、Component Topologyは常に手動確定とする。

### 11.3 Binding UIとの関係

Componentの通常操作ではBindingの内部項目を見せない。

- `Target`: 実際に値を書き込むBlender Data
- `Target Name`: UI表示と参照修復に使う識別名
- `Map Domain`: Controlの入力範囲とTarget出力範囲

Component Presetは必要なBindingを自動生成し、Advancedを開いた場合だけ個別編集できるようにする。`Max Domain`のような独立概念は増やさず、入力・出力範囲を一つのMapping UIへ統合する。

## 12. 互換性とExport

### 12.1 既存Project

- Component導入前のArmatureは変更せずに開ける。
- 既存IKを自動的にComponentへ変換しない。
- `Adopt Existing IK`で構造を検査し、所有タグを追加できる。
- 不明なConstraintやDriverは削除しない。
- Source BoneにActionがある場合、生成時にF-Curveを書き換えない。

### 12.2 Export

標準Export対象はDEF BoneとSprite Artとする。

- CTRL、MCH、UIは非Deformかつ非Export
- Constraint / Driverの最終結果をDEFへBake
- IK/FKの中間Mixも最終PoseとしてBake
- B-Bone、Spline IKは対象ExporterごとにBake精度を検証
- Bone Scale、Negative Scale、Shearを極力避ける
- Export後のBone NameとHierarchyをComponent Updateで変えない

DragonBones等でConstraint自体を再現できない場合でも、最終DEF Transformが一致することをAcceptance条件にする。

## 13. コスト、利点、将来性

| 案 | 実装コスト | 操作性 | 既存資産再利用 | 将来性 | 判断 |
| --- | ---: | ---: | ---: | ---: | --- |
| State Graphへ全機能を追加 | 中 | 低 | 中 | 低 | 不採用 |
| Operatorを種類ごとに追加 | 低 | 中 | 高 | 低 | 移行元として利用 |
| 型付きRig Component | 中 | 高 | 高 | 高 | 採用 |
| 初期からGeneric Rig Node Editor | 非常に高 | 中 | 中 | 高 | 延期 |
| 初期から三重IK/FK Chain | 高 | 高 | 中 | 高 | 実例確認後 |
| 単一Chain IK/FK Mix | 中 | 高 | 高 | 中 | MVP採用 |
| 独自IK Solver | 非常に高 | 不明 | 低 | 中 | 不採用 |
| Blender-native Constraint | 低〜中 | 高 | 高 | 高 | 採用 |

型付きComponentは、個別Operatorより初期コストが高いが、Validate、Repair、再生成、左右対称化、Export Testを共通化できる。将来的にComponent数が増えた段階でのみ、Rig Graphへ内部表現を昇格する。

## 14. 実装Phase

### Phase 6A: Component基盤

- `RigComponentSpec`
- PropertyGroup保存
- Artifact Ownership Tag
- Component / Artifact Validation
- `CTRL / MCH / DEF / UI` Bone Collection
- Preflightと冪等Compile
- 既存IKを読む`Adopt Existing IK`

Acceptance:

- 同じ定義を2回CompileしてBone、Constraint、Driver数が増えない。
- 未所有Bone、Constraint、Actionを変更しない。
- Save / Reload後にComponentとArtifactを解決できる。

### Phase 6B: Direct Bone Prototype（互換用）

- `ROOT`
- `FK_CHAIN`
- `LIMB_IK`
- 既存IK OperatorのComponent化
- Root、FK、IK Widget
- Name表示とControl選択同期

Acceptance:

- Control Frameに沿って3軸操作でき、設定したDepth Modeだけが局所法線移動を制限する。
- 腕・脚の2-Bone ChainをIK Targetから安定して操作できる。
- Spatial IKのPoleがレスト膝／肘を中心とする一定半径上を移動し、遠方へ発散しない。
- 現在のFK Poseを維持して追加でき、変換なしに既存FK Actionを上書きしない。

この方式はSchema v1の互換用`DIRECT_BONES`として維持し、新規Componentの既定にはしない。

### Phase 6C: Parametric Pose Output

- 全Component用の独立した非Deform Control / Frame
- `PARAMETRIC`を新規作成時の既定値にする
- Source BoneへConstraint、Custom Shape、Channel Lockを追加しない
- `LOC_X / LOC_Y / LOC_Z`
- `ROT_X / ROT_Y / ROT_Z`
- Shape Key / Constraint Influence Binding
- Driver UUID所有識別、Target Preflight、Rollback、Orphan回収
- 平面維持とSave / Reloadの検証

Acceptance:

- Controlを3D移動・回転してもSource BoneのPose Matrixが変化しない。
- 評価後メッシュの奥行き座標が基準平面から変化しない。
- 指定したShape Keyだけが入力範囲に従って変化する。
- Bindingを後から追加・削除でき、UpdateでDriverが増殖・残留しない。
- 構築後の`PARAMETRIC` / `DIRECT_BONES`変更は直接許可せず、専用変換処理までComponentを作り直す。

### Phase 6D: Direct Bone IK/FK（任意機能）

- Constraint Influenceによる単一Chain Mix
- 1D Slider / Global Property
- `Snap FK to IK`
- `Snap IK to FK`
- Bend方向
- 左右対称生成

Acceptance:

- 両方向のSnapでWorld Poseの差が許容誤差内である。
- 0、0.5、1のMixでNaN、Flip、極端なScaleがない。
- 切替後も既存Actionへ正しくKeyframeできる。

### Phase 6E: 胴体と補正Preset

- `SPINE_FK`
- `CLAVICLE_SHOULDER`
- Head Rotation + Face State Matrix Preset
- Bone Transform Binding
- 自動Corrective + Manual Override

Acceptance:

- Bone PoseとShape Key補正を独立・合成してKeyframeできる。
- Corrective BindingからConstraint解法へ循環しない。

### Phase 6F: Spaceと接触

- Space Switch
- Switch and Snap
- Prop / Chest / World Space
- Floor Contact
- Foot Roll
- 必要箇所だけShrinkwrap

### Phase 6G: 柔軟ChainとPose Library

- FK / B-Bone / Spline IK Preset
- Hair / Tail / Cloth Chain
- Pose Asset作成・適用補助
- 明示的なStretch Toggle

### 14.1 現在の実装範囲

Phase 6A〜6Cとして、次を実装した。

- 新規Componentの既定を`PARAMETRIC`、Schema v1互換を`DIRECT_BONES`として分離
- `ROOT`、`FK_CHAIN`、`SPINE_FK`、`LIMB_IK`すべてに独立した非Deform Controlを生成
- `LIMB_IK`はParametric時にはTarget入力として扱い、Blender IK Constraintを生成しない
- `SOURCE_BONE`、`WORLD_VIEW`、`CUSTOM`による見た目基準の局所座標
- 局所X/Yを絵の面、局所Zを法線・奥行きとして扱う`Plane / Limited Depth / Free 3D`
- ローカル移動3軸・回転3軸からShape Key / Constraint Influenceへの後付けBinding
- Binding UUIDによるDriver所有識別、Target重複Preflight、Rollback、Rename後を含むOrphan回収
- Component、Bone、Driver、Widgetの所有タグと冪等Update
- Direct Bone互換モードのIK、Pole校正、膝／肘中心のPole距離制限、既存Action保護
- Active BoneからComponent UIを選択する同期

次は未実装であり、後続Phaseで扱う。

- IK/FK Mixと双方向Snap
- 既存Limb FK ActionからIK Control Actionへの変換・Bake
- 左右対称生成
- Clavicle / Shoulder、Foot Roll、Space Switch
- Component Transformを入力とする複数点State Matrix
- Sprite Slot、Z、任意Property等の追加Output
- Component用Name Label、Pose Asset、Export Bake

### 14.2 実装サンプル

`scripts/blender_rig_phase6_sample_character.py`は、平面メッシュで構成した簡易キャラクターへ次を適用する。

- Root × 1
- Body Parameter × 1
- Parametric Limb Target × 4
- 正面姿勢と、奥行き移動・3軸回転を含む左右2姿勢
- Frame 1、13、25のAction Key

スクリプトはControlだけにActionを作成し、Source Bone不変、IK / Copy Rotation不在、Shape Key値の変化、評価後メッシュの平面維持を検証する。`%TEMP%\coa_tools2-validation`へ`.blend`と3枚のPNGを出力する。生成物は検証用でありRepositoryへCommitしない。

## 15. 最初のVertical Slice

最初の実コード成果物は、次へ限定する。

> 選択した上腕・前腕・手、または大腿・脛・足のChainから、管理されたParametric Limb Targetを作成する。Source Boneを変更せず、Controlのローカル移動・回転からShape Key等へ後付けBindingできる。同じ定義の再CompileでBone、Driver、Widgetを増殖させず、Save / Reload後も出力を復元できる。

このVertical Sliceは、次を一度に検証できる。

- Component Schema
- 既存IK資産の再利用
- CTRL / MCH / DEFの責務
- Constraint Compiler
- Rig Controlとの統合
- IK/FKのAnimator UX
- Animation保護
- Export Bake

Root、Spine、Shoulderを先に個別実装するより、構造・操作・切替・Bakeの主要課題を早期に露出できる。

## 16. 検証項目

### 16.1 Pure Python

- Component SchemaのRound Trip
- UUID、Semantic ID、SideのValidation
- Artifact Planの冪等性
- Source Bone欠落と名前変更候補
- Component依存関係と循環
- 左右Name Mapping

### 16.2 Blender Headless

- 新規Armatureへ各Componentを生成できる。
- 2回Compileして生成物数が変わらない。
- Source BoneのF-CurveとKeyframeを維持する。
- IK Chain Length、Target、Bend方向が期待値になる。
- IK/FK Snapの前後でWorld Matrixが一致する。
- Constraint Influenceの0、0.5、1を評価できる。
- Save / Reload、Undo / Redo後も所有関係が一致する。
- Component削除時に所有Artifactだけを削除する。
- Armature複製後に別Instanceを誤更新しない。
- Control Boneを非Deform・非Exportにできる。
- 最終DEF PoseのBake前後が一致する。

### 16.3 DCC実機

- Blender 4.5、5.0、5.1
- Pose Modeでの選択性
- FKからIK、IKからFKの切替時にPoseが飛ばない
- 腕、脚、左右、反転Rest Pose
- 10〜20 Componentを持つキャラクターの操作感
- Existing Projectへの非破壊追加
- Action切替、NLA、Save / Reload
- DragonBones / Creature / JSON Export
- Current ProfileとClean Profileの両方

## 17. 今回決めないもの

次は実例と操作テストを得てから決める。

- 単一Chainから三重IK/FK Chainへ移行する条件
- Pole Controlを常時表示するか、Bend Flip Propertyを標準にするか
- B-Boneを人型Spineの標準にするか
- Foot RollのPivot構成
- Pose AssetをCOA専用Browserへ統合するか
- Side / RoleごとのCustom Shape Color
- Generic Rig Node Editor
- 3D Pose Projection / Inverse Solver

## 18. 採用判断

| 項目 | 判断 |
| --- | --- |
| State ControlとPose Rigの分離 | 採用 |
| Control / Widget / Binding基盤の共有 | 採用 |
| 型付き`RigComponent` | 採用 |
| CTRL / MCH / DEF / UI | 採用 |
| Blender-native Constraint | 採用 |
| Root / FK / IK / Spineの初期Preset | 採用 |
| 単一Chain IK/FK Mix + Snap | MVPとして採用 |
| 肩・顔・口の骨格とState合成 | 採用 |
| Shrinkwrapを通常Controlに使用 | 不採用 |
| Action Constraintを表情の中核に使用 | 不採用 |
| 構造変更のLive Preview | 不採用 |
| Pose Asset連携 | 後続採用 |
| 三重IK/FK Chain | 実例確認まで延期 |
| Generic Rig Graph | Component重複が現れるまで延期 |
| 3D Pose Projection | 別Project |

## 19. 参照

- [2Dリグコントローラー調査・設計案](rig_control_design.md)
- [Rig Graph実装計画](rig_control_graph_implementation_plan.md)
- [Phase 5: Matrix DomainとRig Name表示](rig_control_phase5_matrix_domain.md)
- [Blender: Armature Structure](https://docs.blender.org/manual/en/latest/animation/armatures/structure.html)
- [Blender: Inverse Kinematics Constraint](https://docs.blender.org/manual/en/latest/animation/constraints/tracking/ik_solver.html)
- [Blender: Copy Transforms Constraint](https://docs.blender.org/manual/en/latest/animation/constraints/transform/copy_transforms.html)
- [Blender: Constraint Stack](https://docs.blender.org/manual/en/latest/animation/constraints/interface/stack.html)
- [Blender: Bendy Bones](https://docs.blender.org/manual/en/latest/animation/armatures/bones/properties/bendy_bones.html)
- [Blender: Pose Library](https://docs.blender.org/manual/en/latest/animation/armatures/posing/editing/pose_library.html)
- [Spine: Constraints](https://esotericsoftware.com/spine-constraints)
- [Spine: Sliders](https://esotericsoftware.com/spine-sliders)
- [Live2D: Deformers](https://docs.live2d.com/en/cubism-editor-manual/deformer/)
- [Live2D: Keyform Editing in X and Y Directions](https://docs.live2d.com/en/cubism-editor-manual/keyform-xydirection/)
