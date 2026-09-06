# Phase 9: Animation Controls and State Graphs

## 1. 目的

Phase 9では、Semantic Character Rigの内部自由度を増やしつつ、アニメーターが日常的に触る操作数を抑える。

- FK/IKと接触維持は、キーフレーム可能な2操作へ集約する。
- 音声解析を必須とせず、State Rigから口形を直接操作できる。
- Pose Mapのvector値を、1つの意味的OutputとしてBlenderへ出力する。
- B-BoneをBezier Curveに近いポイント／ハンドル操作へ置き換える。

Screen Plane入力はArt Plane標準構成の必須機能ではないため、本Phaseの必須範囲から外す。

## 2. FK / IK / Contact Pin

通常UIでアニメーターへ公開するパラメーターは次の2つだけとする。

```text
Mode        = FK | IK
Contact Pin = OFF | ON
```

どちらもアニメーション可能な離散プロパティで、Keyframeの補間はConstantとする。滑らかな見た目は離散値そのものを補間せず、切替Operatorが内部のPose Match／補償カーブを生成して実現する。

### 2.1 Mode切替

- FKからIK: 現在のFK評価姿勢からIK TargetとPoleを配置してからIKへ切り替える。
- IKからFK: 現在のIK評価姿勢をFK Controlへ書き戻してからFKへ切り替える。
- Pose Matchは通常の独立パラメーターにせず、Mode切替の原子的処理に含める。

### 2.2 Contact Pin

- ON: 現在のEffector姿勢へIK Target、Orientation、PoleをPose Matchし、Anchorを記録する。
- ON中: 公開ModeがFKでも内部的にIKを有効化し、FK/IK切替と独立して接触を維持する。
- Position onlyでは手首位置のみを固定し、Art Planeの面方向を変えずにFK終端回転を許可する。Orientationを有効にした場合は終端回転も固定する。
- OFF: 既存のFK ControlとFK Animation Curveを書き換えず、現在のContact weightから既定Transition区間で0へ戻す。
- 途中反転は現在の評価weightから再開し、同一フレームの姿勢を連続に保つ。既存の将来切替にTransitionが到達する場合は、キーを破壊せず操作を拒否する。

Pin Space、Orientation固定、Transition Frames、Pole policyはSetup/Advanced設定とし、通常のアニメーションUIへ常時表示しない。

### 2.3 Standalone FK

`CHAIN_FK`はIKの子機能ではなく、Semantic DAGに追加できる独立Solver stageとする。各FK ControlにGeometry NodesのPresentationを割り当て、Pose Mapやその他の後段Stageへ入力できる。接触を維持する自動ContactはIK solverを必要とするため、`CHAIN_IK`の公開ModeをFKにして使う。

## 3. Graph State Rig

既存のLINEAR/MATRIX State Rigに、任意配置の名前付きPointを扱うGRAPH modeを追加する。

```text
Graph Point
├─ UUID / Label
├─ 2D position
├─ Point shape / Custom object
├─ Output binding candidate
└─ Fallback point UUID
```

GraphはMatrixの行列インデックスを前提にしない。近傍Pointと明示Fallback Edgeを使い、アニメーターがControlを直接移動して状態を選択・混合できる。既存LINEAR/MATRIXの保存形式、双線形補間、Rail Domainは維持する。

## 4. Lip Sync Presets

音声解析は入力Adapterの一つにすぎず、Rig自体は手動操作だけで完結させる。Preset GeneratorはGraph Point、ラベル、fallback、未割当Output slotとShape Key名候補を生成する。専用Shape Keyの存在は要求しない。

| Profile | Required states | Optional states |
|---|---|---|
| Minimal | REST, A_E, I, U_O | - |
| JP Vowels | REST, A, I, U, E, O | - |
| JP Vowels + MBP | REST, A, I, U, E, O, MBP | - |
| Standard 2D | REST, MBP, ETC, E, AI, O, U | FV, L, WQ |
| Advanced Phoneme | 選択ProfileのViseme | IPA等のalias mapping |

Fallbackは `exact phoneme -> authored viseme family -> base viseme -> REST` の順で解決する。Advanced modeでも音素ごとの専用絵を必須にしない。

生成形式は次を選択可能にする。

- Named Graph: 離散的な口形選択と短いcross-fade。
- 2D Mouth Map: Mouth FormとMouth Openによる連続操作。
- Hybrid: Named VisemeへOpen/Formを重ねる。

## 5. Vector Output Adapter

Pose Fieldの1つのvector snapshotを、Blenderの複数FCurveへ展開する。

```text
Semantic Output Vec3
├─ FCurve target[0]
├─ FCurve target[1]
└─ FCurve target[2]
```

定義・sample・所有UUID・rollbackは1つのOutputとして扱い、Blender Driver評価時だけcomponent indexへ分解する。初期対応はBone Location、Euler Rotation、array Custom Propertyの2～4要素。Shape Key、Constraint Influence、Slot、Z Value、discrete outputはscalarのままとする。

## 6. B-Bone Bezier Rig

通常UIはB-Boneのraw propertyではなくBezier操作へ置き換える。

```text
Start point (circle) --- handle (triangle)
              |
         optional mid point
              |
End point   (circle) --- handle (triangle)
```

- Point widgetは円。
- Handle widgetは三角形。
- Handle位置・距離からcustom handleとeasein/easeoutを導出する。
- Handle回転からrollin/rolloutを導出する。
- Scale連動はAdvancedで有効化する。
- Secondary MotionはUser HandleとB-Bone custom handleの間へ合成する。

Spline Rigとは排他的なComponent種類にせず、Semantic DAG上の別Solver stageとして扱う。

## 7. 非目標

- 音声認識エンジンの同梱。
- 音素ごとの口形作成の強制。
- FK/IKの常設blend slider。
- Screen PlaneをArt Planeとして黙って代用すること。
- B-Bone raw RNA propertyを通常UIへすべて露出すること。

## 8. 操作用サンプル

現在の操作導線は [Rig: Animate / Setup](rig_control_animation_workspace.md) を参照。

4機能をまとめた `samples/semantic_animation_controls_demo.blend` を用意している。
開発版Addonを隔離profileへ読み込んでからサンプルを開くには、repository rootで次を実行する。

```powershell
.\scripts\launch_blender_rig_manual_test.ps1 -OpenAnimationControlsSample
```

サンプル内の `README_AnimationControls.txt` に、各区画の操作対象とframe例を記載している。
