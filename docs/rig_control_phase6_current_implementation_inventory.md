# Phase 6 キャラクターリグ現行実装資料

## 1. この資料の目的

この資料は、`codex/issue-47-rig-design` の次の実装を対象に、現在のキャラクターリグが実際に何を生成し、どのように評価されるかを整理したものである。

- `8316386 feat(rig): build 3d posing components`
- `a4d9c1e feat(rig): drive posing through parametric outputs`
- `0ae4a4a test(rig): animate the parametric posing sample`

これは目標仕様ではなく、フィードバックを受けるための**現状確認資料**である。特に、現在の`PARAMETRIC`な`LIMB_IK`は実際にはIKを生成しておらず、今回確認された意図との差を明示する。

## 2. 結論

現在は、次の二方式に分かれている。

| 方式 | Blender IK | Source BoneのPose | 平面メッシュ | 現在の用途 |
| --- | --- | --- | --- | --- |
| `PARAMETRIC` | 生成しない | 変更しない | 面の奥行き方向を維持し、Shape Keyだけ変える | 新規Componentの既定、現行サンプル |
| `DIRECT_BONES` | `LIMB_IK`では生成する | IK/FKで直接変更する | Armature Modifier経由でBoneと一緒に3D回転する | Schema v1互換、Direct Boneテスト |
| 今回確認された要件 | 必要 | IK計算には使用する | 少なくとも意図しない面方向の変更を避ける | **未実装** |

したがって、現状には次の組み合わせがない。

> 手足のControlは実際のIK Targetとして働くが、カットアウトメッシュの面方向は意図せず3D回転させず、必要な見た目変化をShape KeyやStateへ渡す。

## 3. データモデル

### 3.1 `RigComponent`

キャラクターリグ一単位を`RigComponent`として保存する。現在の種類は次の4つ。

| `component_type` | UI表示 | 現在の意味 |
| --- | --- | --- |
| `ROOT` | Root / Body | Root Transform入力、またはDirect Root |
| `FK_CHAIN` | Part Rotation | 単一／複数部位のTransform入力、またはDirect FK |
| `SPINE_FK` | Spine / Body | 胴体用Transform入力、またはDirect FK |
| `LIMB_IK` | Limb Target / IK | Parametric時は単なるTransform入力、Direct時だけ実IK |

主な設定:

- `deformation_mode`
  - `PARAMETRIC`
  - `DIRECT_BONES`
- `source_bones`
- `orientation_mode`
- `orientation_reference`
- `depth_mode`
- `allow_translation`
- `allow_rotation`
- `widget`
- `bindings`
- Direct Limb専用のIK、Pole、Stretch、End Rotation設定

### 3.2 生成物の所有管理

生成したBone、Constraint、Widget Object、Driverは、次のIDでComponentへ紐づけている。

- Armature単位の`rig_instance_id`
- Component単位の`component_uuid`
- 生成物の役割を示す`role`
- Binding単位の`binding_uuid`

未所有のBone、Constraint、DriverをUpdate時に削除しないよう、PreflightとRollbackを設けている。

## 4. Compile経路

`compile_component()`は`deformation_mode`によって処理を分岐する。

```text
RigComponent
    │
    ├─ PARAMETRIC
    │    └─ ensure_parameter_component()
    │         ├─ 非Deform Frame / Control生成
    │         ├─ Source Boneは参照・所有タグのみ
    │         ├─ ControlへDepth Limit
    │         └─ Binding Driver生成
    │
    └─ DIRECT_BONES
         ├─ ROOT / FK_CHAIN / SPINE_FK
         │    └─ Source Boneを直接Control化
         │
         └─ LIMB_IK
              └─ ensure_limb_component()
                   ├─ IK Target生成
                   ├─ IK Constraint生成
                   ├─ Pole生成
                   └─ Source BoneをIKで直接評価
```

構築済みComponentの`PARAMETRIC`と`DIRECT_BONES`の直接切替は、現在は安全のため禁止している。専用の変換Operatorは未実装。

## 5. `PARAMETRIC`の実装

### 5.1 生成Bone

Component種類にかかわらず、基本的に次の2 Boneを生成する。

```text
source_root.parent
└─ MCH_<component>_FRAME
   └─ CTRL_<component>

Source Bone Chain
└─ 既存のまま。ControlからConstraint接続しない。
```

`MCH_FRAME`:

- `use_deform = False`
- 非表示の`COA Mechanism` Bone Collectionへ格納
- Source BoneまたはWorld ViewからControlの局所座標を決める
- 選択不可

`CTRL`:

- `use_deform = False`
- 表示される`COA Controls` Bone Collectionへ格納
- Custom Shapeを設定
- 移動3軸・回転3軸をDriver入力として利用

### 5.2 `PARAMETRIC LIMB_IK`の実態

現在の`PARAMETRIC LIMB_IK`では、次を**生成しない**。

- IK Constraint
- Pole Target
- Copy Rotation
- Source BoneへのCopy Transform
- Source BoneへのCustom Shape
- Source BoneのLocation／Rotation Lock

したがって、`CTRL_Arm_IK`や`CTRL_Leg_IK`を動かしても、手首、足首、肘、膝のBone位置は変化しない。

`LIMB_IK`という名前はComponentの意味を正しく表しておらず、現状は「Limb Parameter Control」に相当する。

### 5.3 Control Transformから出力まで

入力として利用できる値:

- `LOC_X`
- `LOC_Y`
- `LOC_Z`
- `ROT_X`
- `ROT_Y`
- `ROT_Z`

評価経路:

```text
CTRL local Transform
        │
        ├─ Driver Variable
        │
        ├─ Input Min / Maxで正規化
        │
        ├─ Clamp
        │
        └─ Output Min / Maxへ写像
                  │
                  ├─ Shape Key Value
                  └─ Constraint Influence
```

Shape Keyはリグ外郭の生成後に`Shape Key & Property Outputs`から追加できる。

### 5.4 Depth制限

Controlのlocal Zへ`Limit Location`を設定する。

| `depth_mode` | Control local Z |
| --- | --- |
| `LOCKED` | 0へ固定 |
| `LIMITED` | `depth_min`〜`depth_max` |
| `FREE` | 制限なし |

これはControlの入力範囲を制限するもので、Source Boneやメッシュを奥行き移動させるものではない。

## 6. `DIRECT_BONES`の実装

### 6.1 Root／FK／Spine

既存Source Boneへ直接Custom Shapeを割り当てる。

- `ROOT`: 移動・回転を許可
- `FK_CHAIN`／`SPINE_FK`: 基本的に回転を許可
- Source BoneがControlとDeformを兼ねる

この方式では、Source BoneへウェイトされたメッシュはBone Transformに従う。

### 6.2 Direct Limb IK

Directな`LIMB_IK`は実際のBlender IKを生成する。

```text
Source Chain

upper_DEF
└─ lower_DEF  ← IK Constraint Owner
   └─ end_DEF ← 任意のCopy Rotation

Generated Controls

MCH_<limb>_FRAME
└─ CTRL_<limb>              ← IK Target

CTRL_<limb>_BEND            ← Pole Target
MCH_<limb>_BEND_CENTER      ← Pole距離制限の中心
```

IK Constraint:

- Owner: Chain末端の一つ前のBone
- Target: `CTRL_<limb>`
- Chain Length: 既定2
- Stretch: 既定OFF
- Spatial／Planarを選択可能
- End Boneは`COPY_WORLD`、`COPY_LOCAL`、`NONE`を選択可能

### 6.3 Pole

Spatial IKかつ`use_bend_hint = True`の場合:

- `CTRL_<limb>_BEND`
  - IK Pole Target
  - 菱形Custom Shape
- `MCH_<limb>_BEND_CENTER`
  - レスト時の肘／膝位置
  - IK Chain外の非Deform Bone
- Poleの`Limit Distance`
  - Target: `MCH_<limb>_BEND_CENTER`
  - Mode: `On Surface`
  - 一定半径上へPoleを制限

評価後の肘／膝BoneをPole距離制限のTargetにするとIKとの依存循環になるため、現在は独立したMCH Boneを使用する。

### 6.4 Direct IKでメッシュ方向が変わる理由

Direct IKはSource Boneそのものを回転させる。

```text
CTRL IK移動
  → Blender IK
  → upper / lower Source Bone回転
  → Armature Modifier
  → ウェイトされた平面メッシュもBoneと一緒に3D回転
```

現在は、次の分離を行っていない。

- IK計算用Bone
- 位置だけを受け取るBone
- カメラや絵の面に向きを保つDeform Bone
- IK角度を入力にShape Keyを選ぶArt State

そのため、実IKを使う`DIRECT_BONES`ではメッシュ面方向も変化する。

## 7. Control Orientation

### 7.1 `WORLD_VIEW`

Armature空間で次の軸を作る。

- local X = Armature X
- local Y = Armature Z
- local Z = -Armature Y

local X/Yを絵の面、local Zを画面奥行きとして扱う意図だった。

### 7.2 `SOURCE_BONE`

`orientation_reference` BoneのRest Matrixをそのまま`MCH_FRAME`へ使用する。

手のひらや足裏の見た目にControl軸を合わせる目的だったが、Source BoneのRollやRest方向に強く依存する。

### 7.3 `CUSTOM`

Source BoneのRest MatrixへEuler Offsetを加える。

現状では、Controlの見た目基準を調整するための設定であり、メッシュの面方向を固定する機構ではない。

## 8. 現行Custom Shape

Component用WidgetはMesh Objectとしてコード生成している。

| Widget | 現在の形 |
| --- | --- |
| `ROOT` | 立方体ワイヤー＋円 |
| `FK` | XY、XZ、YZの3リング |
| `HAND` | 6頂点の手のひら風輪郭＋法線方向の矢印 |
| `FOOT` | 6頂点の足裏風輪郭＋法線方向の矢印 |
| `SQUARE` | 角を落とした8頂点輪郭＋法線方向の矢印 |
| Pole `DIAMOND` | 菱形＋法線方向の矢印 |

矢印は`_normal_marker()`が追加している。

```text
中心
 │
 └─ 矢印先端
```

これは「Controlのlocal Z／法線方向」を表示する目的で追加したが、今回のフィードバックではIK Custom Shapeには不要である。

また、`HAND`と`FOOT`はRigify Assetを参照して複製したものではなく、単純な独自6頂点輪郭である。Rigifyの手のひら／足IK Shapeを基準にした再設計は未実施。

## 9. 現行サンプルキャラクター

対象:

- `scripts/blender_rig_phase6_sample_character.py`

### 9.1 Component構成

次の6 Componentをすべて`PARAMETRIC`で作成する。

- `Body Root`
- `Body FK`
- `Arm IK.L`
- `Arm IK.R`
- `Leg IK.L`
- `Leg IK.R`

`Arm IK`と`Leg IK`にも実IKは存在しない。

### 9.2 Art構成

各Body Partを平面Meshとして生成し、対応するSource BoneのVertex GroupとArmature Modifierを設定する。

ただしSource Boneは全フレームで変化させないため、Armature Modifierによるポージングは起きない。

### 9.3 自動生成Shape Key

各Art Objectへ次のShape Keyを作る。

| Shape Key | 入力 | 現在の変形 |
| --- | --- | --- |
| `DepthFront` | `LOC_Z +` | X幅を縮め、ZへShear |
| `DepthBack` | `LOC_Z -` | X幅を縮め、逆方向へShear |
| `TiltXPos` | `ROT_X +` | X位置に応じてZをShear |
| `TiltXNeg` | `ROT_X -` | 逆方向へZをShear |
| `TurnYPos` | `ROT_Y +` | X幅を縮め、Zに応じてXをShear |
| `TurnYNeg` | `ROT_Y -` | 逆方向へXをShear |
| `RollZPos` | `ROT_Z +` | Zに応じてXをShear |
| `RollZNeg` | `ROT_Z -` | 逆方向へXをShear |

全Shape Keyは頂点のYを変更しない。そのため、メッシュは同一の平面上に残る。

一方で、X/Z輪郭は圧縮・Shearされるので、**見かけの方向やシルエットは変わる**。

### 9.4 サンプルのテスト内容

フレーム1、13、25で各Parametric ControlへLocation／Rotation Keyframeを打つ。

テストは次を明示的に保証している。

- Source BoneのPose Matrixが全フレームで変化しない
- `hand.L`の位置がフレーム1と13で変化しない
- Art Meshのworld Y座標が全フレームで変化しない
- Shape Key ValueだけがControl Transformに応じて変化する

つまり、このサンプルは「IKポージングのサンプル」ではなく、「6軸State／Shape Key入力のサンプル」である。

## 10. UI

N Panelの`COA Tools2 > Pose Rig Components`へ次を追加した。

- Component一覧
- Component Type
- Artwork Deformation
- Source Bone一覧
- Orientation
- Movement／Depth
- Rotation Axis
- Widget種類・サイズ
- Parametric Output一覧
- Add／Remove Output
- Rebuild Component

Direct Limbの場合だけIK設定を表示する。

- Spatial／Planar
- Bend Hint
- Pole Distance
- End Rotation
- Stretch

Parametric LimbではIK設定を表示しない。これは現行実装がIKを生成しないためである。

## 11. 現在の安全機構

次を実装している。

- 未所有Bone／Constraint／DriverとのConflict検出
- Source Chainの親子順検証
- 既存Direct FK Animationを暗黙にIK変換しない
- Component UUID／Binding UUIDによる所有判定
- 同じTargetへの重複出力防止
- Object、Shape Key、Control Bone Rename後のDriver回収
- 構築失敗時のBone、Constraint、Widget、Driver Rollback
- 冪等Update
- Save／Reload

これらは今後リグ構造を変更する場合も再利用できる。

## 12. 今回確認された要件との差分

### 12.1 IK

要件:

- 手足Controlは実際にIKとして機能する。

現状:

- 新規既定の`PARAMETRIC LIMB_IK`はIKではない。
- 実IKは互換用`DIRECT_BONES`にしかない。

差分:

- 実IKとParametric Art Outputを併用する構成が必要。

### 12.2 メッシュ方向

要件:

- IK操作時にメッシュの面方向が意図せず変わらない。

現状:

- Direct IKではSource Bone回転がメッシュへそのまま伝わる。
- Parametricでは面のY座標は固定されるが、自動Shape KeyがX/Z輪郭を変える。

次の実装前に、少なくとも以下を別々に定義する必要がある。

1. 画面内で腕・脚が関節へ向く回転
2. カメラ方向へ倒れる面法線の回転
3. 手のひら／足裏の見た目切替
4. Shape Keyによる見かけの奥行き表現

### 12.3 IK Widget

要件:

- IK Widgetの矢印は不要。
- Rigifyの手のひらIK、足IK Shapeを参考にする。

現状:

- `HAND`、`FOOT`、`SQUARE`、Poleへ法線矢印を追加している。
- Hand／FootはRigify準拠ではなく独自の単純輪郭。

差分:

- `_normal_marker()`をIK Widgetから除外する。
- Rigifyの手／足Control Shapeを調査し、輪郭と原点・軸方向を再設計する。

### 12.4 Component名称

現状の`LIMB_IK`はモードによって意味が変わる。

- Parametric: Limb Parameter
- Direct: Limb IK

UIとデータ定義が挙動を正確に表していない。今後の設計では、Component TypeとArtwork Deformationを直交させるか、IK SolverとArt Deformerを別設定として扱う必要がある。

## 13. 次の修正で決める必要がある境界

次のフィードバックでは、特に以下を具体化すると実装経路を一意にできる。

### 13.1 IK結果をどこまでBoneへ反映するか

- 上腕／前腕、腿／脛の画面内回転は許可するか
- Source Boneを直接IKで解くか
- MCH IK Chainを別途作り、Source／DEFへ一部だけ反映するか
- 手首／足首位置だけを追従させるか

### 13.2 「メッシュ方向を変えない」の対象

- 平面の法線だけをカメラへ固定する
- 画面内回転も含めて完全に固定する
- 手のひら／足裏だけ固定する
- 腕・脚は画面内で関節方向へ回すが、奥行き方向へは倒さない

### 13.3 Shape Keyとの関係

- IK Bone角度から自動でState／Shape Keyを選ぶ
- IK TargetのTransformからShape Keyを選ぶ
- 両方を入力にする
- Shape Keyは補正だけに限定する

### 13.4 IK／FK

- IKのみ
- FKのみ
- IK/FK切替
- IK/FK切替時のSnap

## 14. 関連ファイル

| ファイル | 役割 |
| --- | --- |
| `coa_tools2/rig_control/component_schema.py` | Component定義 |
| `coa_tools2/rig_control/blender/properties.py` | Blender保存Property |
| `coa_tools2/rig_control/blender/component_compiler.py` | Compile分岐とRollback |
| `coa_tools2/rig_control/blender/component_artifacts.py` | Bone、Constraint、Widget生成 |
| `coa_tools2/rig_control/blender/component_outputs.py` | Parametric Binding／Driver |
| `coa_tools2/rig_control/blender/component_ui.py` | N Panel UI |
| `scripts/blender_rig_phase6b_posing_test.py` | Direct Bone IKテスト |
| `scripts/blender_rig_phase6c_parametric_test.py` | Parametric出力テスト |
| `scripts/blender_rig_phase6_sample_character.py` | 現行サンプル |

## 15. 現行実装から再利用できる部分

要件に合わないのは主に、IKとArt Deformationを二者択一にした構造である。次は継続利用できる。

- Component Definition
- 生成物の所有タグ
- Preflight
- Transactional Rollback
- Control Orientation
- Binding UUID
- Shape Key／Constraint Influence Driver
- Pole Angle校正
- Poleの距離制限
- Save／Reload
- テスト用の平面維持検査

次の実装では、これらを残しつつ、`LIMB_IK`のSolver経路とArt Deformation経路を分離して再構成する必要がある。
