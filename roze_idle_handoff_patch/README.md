# ロゼ：MotionBricks → idle.vrma の急回転を防ぐパッチ（独立モジュール）

## 動画で確認できたこと

提供動画の約4.0〜4.1秒の間にロゼが横向きへ急に回転しています。画面には「待機 idle.vrma」と表示されています。以前配布した v0.2 のウェブ画面とは異なり、現在のCursor版にはVRMA再生が追加されていると読み取れます。

**注意：** Cursor版の現在のソースコードは提供されていません。この ZIP は差し替え可能な完成プロジェクトではなく、既存アプリに組み込む部品です。実際の原因が `idle.vrma` への切替か、Python側の公式 `IdleState` のクリップ切替かは、イベントログで確定させる必要があります。

## 対処

1. MotionBricksが最後に表示した `VRM` の `hips` ローカル回転と位置を取得。
2. `createVRMAnimationClip()` で生成したVRMAの `hips.quaternion` と `hips.position` キーを現在姿勢基準に書き換える。元ファイルは書き換えない。
3. 待機中に身体全体が勝手に向きを変えないよう、標準では hips のYawを固定。
4. 0.45秒だけ、元の関節姿勢から新しい待機姿勢にクォータニオン補間。
5. 停止地点における `vrm.scene` の位置・回転を維持。最終フレームで位置・角度のスナップをしない。
6. その間、既存のMotionBricksポーズ更新を停止（両方で関節を書き込むと競合する）。

## インストールと接続

既存の Three.js プロジェクトに `idleHandoff.js` をコピーし、`INTEGRATION_EXAMPLE.js` のコメントに沿って組み込む。

`@pixiv/three-vrm-animation` がなければ、既存ウェブプロジェクトのフォルダで以下を実行：

```bash
npm install @pixiv/three-vrm-animation@^3
```

`GLTFLoader` に `new VRMAnimationLoaderPlugin(parser)` を登録し、読み込んだ `idle.vrma` から `createVRMAnimationClip(vrmAnimation, vrm)` を生成する。`IdleHandoff` が自前の `AnimationMixer` を使用するため、旧 `idle.vrma` ミキサーは同時に起動しない。

## 再現テスト

- 歩行して停止→1秒以上待機しても **身体全体の向きが急変しない**。
- 右向き・左向き・斜め向きのどこで止まっても、その方角を保持。
- 移行0.45秒間に足の接地位置と身体位置が不連続にならないか確認。
- もう一度クリックしたら、古いVRMAの再生を止め、MotionBricks操作に戻る。
- `debug: true` で `outgoingYawDeg` と `vrmaStartYawDeg` の差を記録。
- 90度ジャンプがまだ見られる場合は、`idle.vrma` 開始前にPythonから送られたHips姿勢の変化を測り、原因をPython側のクリップ引継ぎかVRMA側か分離する。

##制約と注意点

- `preserveYaw: true` は **待機VRMAによる身体全体の自動旋回を禁止する**。元の待機モーションに旋回が意図されている場合は `false` を指定する。
- MotionBricksからVRMAへの移行と、その逆の移行は別問題。再クリックでまた姿勢が飛ぶ場合、VRMA→MotionBricksの姿勢履歴の引継ぎが必要。
- `vrm.scene.position` と `hips.position` を別々に制御する設計。実際のCursor版でSceneの動かし方が異なれば適宜調整が必要。
- 足の接地固定、衝突・移動精度の改善、PoseLoomとSOMAの変換は今回の修正対象外。
- この環境ではGPUと実際のロゼVRM/idle.vrmaに対する映像テストはしていない。

## 参照

- NVIDIA Scene Preview: https://github.com/NVlabs/motionbricks/blob/main/docs/scene_preview.md
- pixiv three-vrm-animation example: https://github.com/pixiv/three-vrm/blob/dev/packages/three-vrm-animation/examples/loader-plugin.html
- pixiv VRM Animation Clip: https://pixiv.github.io/three-vrm/docs/functions/three-vrm-animation.createVRMAnimationClip.html
