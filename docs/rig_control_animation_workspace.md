# Rig: Animate / Setup

COA Tools2 のサイドバー先頭にある `Rig` で、日常のアニメーション操作と構築設定を切り替える。
セッション開始時は `Animate`。タブの切替自体はリグやポーズを変更しない。

## Animate

- Pose Mode でビューポートのコントロールを選択する。
- FK / IK コントロールでは、そのチェーンの `Mode` と `Contact Pin` をまとめて表示する。Setup 側のレイヤー選択には依存しない。
- 切替は既存の Pose Match とキー記録を実行する。離散プロパティの補間は Constant、Contact の遷移は既存の補償処理に従う。
- State Rig では、ハンドル位置から評価した各状態の混合率を読み取り専用で表示する。複数の状態を同時に含められ、独立した重みスライダーや単一状態のトグルは持たない。
- 混合率は既存の Matrix / Graph の補間結果を使う。Graph の出力未割当状態も表示し、UI で再正規化して実際の出力と食い違わせることはしない。
- `Key Control` は State Rig の入力チャンネルをキー記録する。口形はハンドル位置をアニメーションさせる。
- B-Bone のポイントと接線ハンドルは、通常の Blender の移動・回転・スケールで操作する。

## Setup

既存の `State Rig` と `Character Rig` をここにまとめる。
Semantic レイヤーの `Input Layers` は、UUID の手入力をやめ、レイヤー名のチェックリストで選択する。循環参照と存在しない入力は拒否する。

### 手の IK シェイプ

CHAIN_IK の Primary Presentation が `Tombstone` の場合、`Align to Hand Rest` が既定で有効。

- 終端の hand ボーンの **レスト時の head → tail** を Art Plane に投影して向きを決める。
- かまぼこ型の底辺中央が手首、丸い側が指先を向く。
- 現在のアニメーション姿勢からレスト方向を取り直さない。
- 表示用メッシュに補正を適用し、ソルバーの軸、コントロールのレスト行列、既存のキーフレームを変更しない。
- hand のレストや Presentation の設定を変えたら、既存の更新／再構築操作で表示を更新する。
- この設定を無効にすると従来の表示フレームに戻る。Custom Object と追加の表示オフセットは引き続き利用できる。

### Viewport

`Use Animator Display` は生成済みの COA コントロールを役割別に着色し、生成ヘルパーとボーン名を非表示にする。
元の表示は blend 内に保存され、`Restore Display` で戻せる。再適用しても最初のバックアップを上書きしない。
ソースボーンやユーザーのボーン、ボーンコレクション、ビューポートのテーマ設定は変更しない。

## 確認用サンプル

`samples/semantic_animation_controls_demo.blend` に更新済みの手のシェイプと表示プリセットを反映している。
このチェックアウトのアドオンを隔離プロファイルに読み込み、サンプルの一時コピーを開く:

```powershell
.\scripts\launch_blender_rig_manual_test.ps1 -OpenAnimationControlsSample
```

Graph の fallback / 補間仕様、Secondary Motion の方式、既存のソルバー構成は今回の UI 変更では変更しない。
