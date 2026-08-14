# B-Bone Bezier Character Rig

## 目的

`B-Bone Bezier` は、1 本の変形用 B-Bone を「始点・終点・接線ハンドル・任意の中点」という意味的な操作へまとめる Character Rig stage です。Blender の B-Bone 設定をアニメーターへ直接並べず、操作ボーンと Geometry Nodes 製カスタムシェイプから間接制御します。

State Rig のスライダーや Matrix が「状態・パラメーター」を選ぶのに対し、この stage はキャラクターの胴体、髪、尻尾、布などの連続した曲がりを直接ポージングするためのものです。

## 内部構造

```text
Start / End point CTRL
        │
        ├─ Copy Location / Stretch To ──> source deform B-Bone
        │
Handle Out / Handle In CTRL
        │
        ├─ hidden effective handles ────> custom B-Bone handles
        ├─ local Y rotation Driver ─────> Roll In / Out
        │
optional Mid CTRL ── weighted pull ─────┘
```

- source はちょうど 1 本の既存変形ボーンです。
- 始点と終点は B-Bone の位置と長さを制御します。
- `Handle Out` と `Handle In` は hidden mechanism bone を介して B-Bone の custom handle を制御します。
- tangent handle の移動と scale は Blender の native custom-handle 評価へ渡され、接線と ease／endpoint scale をポーズごとに調整できます。回転については Blender 5.1 の custom handle orientation に依存せず、`Handle Out / In` の local Y 回転を所有管理 Driver が `Roll In / Out` へ加算します。
- `Midpoint Control` を有効にすると、両方の effective handle を中点へ指定量だけ引き寄せられます。
- 元の B-Bone RNA 値と custom handle は記録され、stage を無効化・削除したときに復元されます。

この中間層により、後段の Secondary Motion は authored handle を書き換えず、effective handle の入力先だけを SIM output へ差し替えられます。

## 作成手順

1. Pose Mode で B-Bone にしたい変形ボーンを 1 本選択します。
2. Character Rig component の Stage 一覧で `Add Semantic Stage` を押します。
3. `B-Bone Bezier` を選びます。
4. 必要なら `Assign Selected Chain` で source を再指定します。この stage では選択数は 1 本だけです。
5. `Apply Changes` で構築します。

初回構築時の production presentation は次の設定です。

| 対象 | 既定 Shape | 意味 |
|---|---|---|
| Start / End / Mid | `ELLIPSE`（同じ縦横寸法） | 曲線上の位置 |
| Handle Out / In | `TRIANGLE` | 接線方向を作るハンドル |

いずれも既存の production Geometry Nodes widget library を使用します。presentation は solver から独立しているため、Shape や寸法だけを更新しても B-Bone mechanism は再生成されません。

## UI 設定

Stage を選ぶと次の 2 グループが表示されます。

- `Point Controls Presentation`: Start / End / optional Mid 共通
- `Tangent Handles Presentation`: Handle Out / Handle In 共通

各グループでは Shape、形状パラメーター、`Live Preview`、`Apply` を利用できます。`NONE` は custom shape を付けず、`CUSTOM_OBJECT` は既存 Mesh object をそのまま使います。

通常表示では次だけを調整します。

- `Midpoint Control`
- `Midpoint Pull`

raw B-Bone RNA は直接表示しません。`Advanced` を展開すると semantic wrapper として次を編集できます。

- `Segments`: B-Bone 分割数（2–32）
- `Handle Length`: 初期ハンドル距離（source bone 長に対する比率）
- `Ease In / Out`
- `Roll In / Out`
- `Endpoint Scale` と `Scale In / Out`

これらは source bone の `bbone_*` 基準値と custom-handle 使用フラグへ compile 時に適用されます。ポーズ時の handle transform がその基準へ加わるため、ユーザーが source bone の raw 設定を手で管理する必要はありません。

`Roll In / Out` はハンドルが無回転のときの基準値です。アニメーターが三角ハンドルを local Y 回転すると、その値が基準値へ非破壊で加算されます。Driver は stage UUID と所有 handle bone の live tag で識別し、再コンパイルでは重複せず、stage 無効化時には source の元値を復元する前に削除されます。

## Secondary Motion との複合

1. B-Bone Bezier の後へ `Secondary Motion` stage を追加します。
2. `After UUIDs` に B-Bone Bezier stage の UUID を指定します。
3. `Apply Changes` すると Handle Out / Handle In と optional Mid に対応する SIM output が生成されます。
4. `Bake Secondary Motion` で deterministic spring motion を bake できます。

始点と終点は authored control のままです。Secondary Motion はハンドル（および有効時の中点）の後段だけへ接続されるため、曲線全体の位置決めと揺れを分離できます。既存の `Spline -> Secondary Motion` 経路とは分岐しており、Spline の Hook/pin 処理は変更しません。

## 検証

Blender 実機用 regression script:

```powershell
blender --background --factory-startup --python scripts/blender_rig_phase9_bbone_bezier_test.py
```

この script は次を確認します。

- point / handle 操作による evaluated B-Bone segment の変化
- ease / roll / scale と custom handle の間接設定
- Geometry Nodes 製 `ELLIPSE` / `TRIANGLE` custom shape
- Secondary Motion の後段接続
- 再 compile の冪等性
- presentation 失敗時の構造・raw RNA rollback
- `.blend` 保存／再読込後の pointer、widget、Secondary 接続
- stage 無効化時の元 B-Bone 設定復元
