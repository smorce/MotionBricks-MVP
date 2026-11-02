// 保存状態の評価と、新しく生成した動作の評価を区別して表示する。
export function formatVisualStop(frame){
 if(frame.stop_mode!=='visual')return '実行方式：従来の停止制御';
 const selected=frame.visual_selection;
 const goal=frame.destination_xy,root=frame.poses?.[0];
 const error=goal&&root?` / 目的地まで ${Math.hypot(goal[0]-root[0],goal[1]-root[1]).toFixed(2)}m`:'';
 if(!selected)return '実行方式：目視11候補 / 地面をクリックして開始';
 if(selected.status!=='matched')return `実行方式：目視11候補 / 現在の状態は未確認${error}\n${frame.phase==='stop_failed'?'評価済み条件に一致しなかったため、この姿勢で停止しています。':'近い評価済み状態を探しています。未確認のまま近づいた場合は停止姿勢を保持します。'}`;
 const state={'stop-distance-lab':'通常速度','left-swing':'左脚が遊脚','right-swing':'右脚が遊脚','after-turn':'旋回後'}[selected.reviewed_state]||'評価済み状態';
 return `実行方式：目視11候補 / ${state}\n${selected.candidate.id} / X=${Math.round(selected.x_m*100)}cm / 類似度 ${Math.round(selected.similarity*100)}%\n${selected.candidate.target_pose_type||'F001'} / 足固定なし\n${selected.action==='walk'?'歩行を継続・停止条件を毎フレーム確認':frame.phase==='settled'?'停止済み・GroundedIdleへ移行':'現在の履歴から停止生成'}${error}\n新しい実動作の自然さ：評価待ち`;
}
