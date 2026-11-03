// 保存状態の評価と、新しく生成した動作の評価を区別して表示する。
export function formatVisualStop(frame){
 if(frame.stop_mode==='prepared'){
  const s=frame.visual_selection;
  const goal=frame.destination_xy,root=frame.poses?.[0];
  const distance=goal&&root?` / 目的地まで ${Math.hypot(goal[0]-root[0],goal[1]-root[1]).toFixed(2)}m`:'';
  if(!s)return '新実験：停止準備 → F001接続 / 地面をクリックして開始';
  const action=frame.phase==='stop_relaxing'?'停止生成できなかったため、SOMAの待機姿勢へゆっくり移行中':frame.phase==='stop_relaxed'?'停止生成は失敗・SOMAの待機姿勢へ移行済み':frame.phase==='stop_failed'?'生成できなかったため姿勢を保持しています':frame.phase==='settled'?'停止済み・接地後にGroundedIdleへ':s.action==='stop'?'現在の直近4姿勢から停止生成':s.preparation_active?'停止準備中・評価済み条件を探索':'歩行中';
  const basis=s.status==='matched'?'評価済み状態の近傍':'未評価のA方式（保存候補は生成条件の参考）';
  const metrics=frame.gait?.final_stop_metrics;
  const labels={knees:'膝',ankles:'足裏・回転',support:'推定足滑り',swing:'遊脚・着地',idle:'終端の微動',progress:'前進量・通過'};
  const diagnostics=metrics?.policy==='prepared-minimum-guards-v1'?`\n最低限ガード：${metrics.accepted?'通過（自然さは未評価）':'保留'} / 診断：${(metrics.warnings||[]).map(name=>labels[name]||name).join('・')||'警告なし'}`:'';
  return `新実験：停止準備 → F001接続${distance}\n${action}\n${basis}\n参照 ${s.candidate?.id||'なし'} / F001・足固定なし\n停止開始距離 ${Math.round((s.target_pose_distance_m||0)*100)}cm / 人間の目視評価待ち${diagnostics}`;
 }
 if(frame.stop_mode!=='visual')return '実行方式：従来の停止制御';
 const selected=frame.visual_selection;
 const goal=frame.destination_xy,root=frame.poses?.[0];
 const error=goal&&root?` / 目的地まで ${Math.hypot(goal[0]-root[0],goal[1]-root[1]).toFixed(2)}m`:'';
 if(!selected)return '実行方式：目視11候補 / 地面をクリックして開始';
 if(selected.status!=='matched')return `実行方式：目視11候補 / 現在の状態は未確認${error}\n${frame.phase==='stop_failed'?'評価済み条件に一致しなかったため、この姿勢で停止しています。':'近い評価済み状態を探しています。未確認のまま近づいた場合は停止姿勢を保持します。'}`;
 const state={'stop-distance-lab':'通常速度','left-swing':'左脚が遊脚','right-swing':'右脚が遊脚','after-turn':'旋回後'}[selected.reviewed_state]||'評価済み状態';
 return `実行方式：目視11候補 / ${state}\n${selected.candidate.id} / X=${Math.round(selected.x_m*100)}cm / 類似度 ${Math.round(selected.similarity*100)}%\n${selected.candidate.target_pose_type||'F001'} / 足固定なし\n${selected.action==='walk'?'歩行を継続・停止条件を毎フレーム確認':frame.phase==='settled'?'停止済み・GroundedIdleへ移行':'現在の履歴から停止生成'}${error}\n新しい実動作の自然さ：評価待ち`;
}
