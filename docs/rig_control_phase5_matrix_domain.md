# Phase 5: Matrix DomainとRig Name表示

## 1. 目的

`2D Rectangle Grid`と`2D State Matrix`を別種の見た目として増やすのではなく、次の一つの到達領域として扱う。

- `columns × rows`: State Point数
- `(columns - 1) × (rows - 1)`: 4点で囲まれたCell数
- Cellごとの`mix_enabled`: Cell内部を自由移動・4点Mixできるか

この定義により、同じState Matrixで次を表現できる。

| Cell Mask | 表示・操作 |
| --- | --- |
| 全Cell `false` | Grid Railのみ。2×2なら従来のno-mix Rectangle Grid |
| 全Cell `true` | 全面自由移動。従来のFULL State Matrix |
| true / false混在 | 指定Cellだけ自由移動するPartial Mix Matrix |

2×3で下Cellだけ`true`にすると、下4点の区間は自由なBilinear Mix、上4点の区間はRail上の2状態補間になる。

## 2. 永続データ

`RigControl.state_cells`へ、State Pointとは独立してCellを保存する。

```text
StateCell
  cell_uuid
  control_uuid
  column
  row
  mix_enabled
```

Shape Key未割当でも外郭と操作領域を先に作れるよう、Cell MaskはBindingやState PointのTargetを参照しない。

`state_mix_policy`は正本ではなくMaskの要約・Presetとする。

- `FULL`: 全Cell有効
- `NO_MIX`: 全Cell無効
- `PARTIAL`: 有効・無効が混在

Resize時は同じ`(column, row)`のUUIDと`mix_enabled`を維持する。旧State MatrixにCellがない場合は、既存挙動を守るため全Cell有効としてRepair時に補完する。旧Rectangle GridはStateDataを暗黙生成せず、従来Controlとして維持する。

## 3. Constraint

採用構成はControlごとに次の2個だけとする。

1. `Limit Location`: 外側の矩形と面外軸を制限
2. `Shrinkwrap / Nearest Surface`: Matrix Domainへ投影

Matrix Domainのhidden Meshは、次を一つのTargetに含める。

- 全Grid中心線を表す、制御平面に垂直なカーテン面
- `mix_enabled=true`のCellを表す、制御平面上の面

垂直面を使うことで、細い平面帯の端ではなくGrid中心線へ正確に投影できる。許可Cell内では同一平面のCell面までの距離が0なので位置を変えず、禁止Cell内では最寄りのRail中心線へ移動する。

Follow PathとClamp Toは単一Curve上の1次元位置には適するが、分岐Gridと2次元面の和集合を一つのConstraintで表せないため採用しない。

既存のHat Basis Driver式は変更しない。自由Cell内部では4点のBilinear Weight、Rail上では片方の軸がState座標に一致するため2点Weight、交点では1点Weightになる。

## 4. Geometry Nodes Widget

共有`COA_RigWidget_Matrix_GN`へ次を入力する。

- Width / Height
- Columns / Rows
- Node Radius / Bar Width
- 各Control固有の有効Cell Solid Mesh

任意長のBool配列をModifier Socketへ展開しない。Widget Source Objectの入力Geometryへ有効CellだけをSolidとして保存し、共有Node Groupで以下を合成する。

```text
全Grid Bar
  + 全State Point Circle
  + 有効Cell Solid
  -> Exact Union
  -> Top Boundary
  -> 面なしMesh Edge
```

これにより、有効Cellの内側Pathだけが消え、無効CellのRail輪郭は残る。同一のCell Maskから表示とConstraint Targetを生成するため、見た目と到達領域がずれない。

## 5. UI

State Matrixの`Continuous States`内へ次を表示する。

- `Full`: 全Cellを一括有効化
- `Grid Only`: 全Cellを一括無効化
- Cell Grid Button: 各4点区間を個別切替

Cell Buttonは上段から表示するが、保存順は下段からのrow-majorとする。Button操作時にWidget、Domain Target、Constraintを即時再Compileする。

Add Rigの`State Matrix`では作成時に`Full`または`Grid Only`を選べる。従来の`Grid Rails`は後方互換の通常2D Controlとして残し、State Matrix側では任意行列のno-mixを同じMatrix Domainで作成できる。

## 6. Rig Name

各Controlに次の管理対象Artifactを生成する。

- `NAME_<semantic_id>`: `GLOBAL_CTRL`配下の非Deform Name Bone
- `TXT_<semantic_id>`: Name BoneへBone ParentしたFONT Object

TextはControlの下部中央へ配置し、Renderには含めない。`label`、`show_name`、`name_size`、`name_offset`をUpdate Rig ControlとRepairで同期する。

配置基準はControl種別ごとの表示下端とする。

- Horizontal Slider: Node下端
- Vertical Slider: Rail長の下端
- Rectangle / Matrix: Height下端 + Node半径
- Circle / Dial: Radius下端

Name BoneとTextにも`control_uuid`とArtifact Roleを保存し、Validationで欠損・親子関係・表示文字列を確認する。

## 7. 既知の操作特性

ShrinkwrapにはLimit Locationの`Affect Transform`に相当するRaw Transform補正がない。禁止Cell内部でBoneを大きくドラッグした場合、保存されたLocationと評価後の見た目が一時的に異なることがある。また禁止Cellの等距離線では最寄Railが切り替わる。

標準ConstraintでMatrix Domainを一般化する初期実装として許容し、触感上の問題が大きい場合は、将来の専用Gizmoで直前Railを保持するHysteresisを検討する。

## 8. 検証条件

- 2×2 `NO_MIX`: Cell内部入力がRail中心へ投影され、非0 Weightが最大2
- 2×3 `PARTIAL`: 下Cell内部は4点Mix、上Cell内部はRail上2点Mix
- `FULL`: 全Cell内部で入力位置を維持
- Widgetの有効Cell内側Pathだけが消える
- 全State PointにNode Circleがある
- Resizeで重なるCell Maskを維持
- Update / Repairを繰り返してBone、Text、Widget、Targetが増殖しない
- Save / Reload後にCell Mask、Driver、Name Textを維持
- Blender 4.5 / 5.0 / 5.1で同じ結果になる

## 9. 参考

- [Blender: Shrinkwrap Constraint](https://docs.blender.org/manual/en/5.0/animation/constraints/relationship/shrinkwrap.html)
- [Blender: Follow Path Constraint](https://docs.blender.org/manual/en/5.0/animation/constraints/relationship/follow_path.html)
- [Blender: Constraint Stack](https://docs.blender.org/manual/en/latest/animation/constraints/interface/stack.html)
