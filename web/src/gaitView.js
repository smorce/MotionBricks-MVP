/** デバッグ表示の色と文面。描画ライブラリには依存しない。 */

export function markerColor(planted) {
  return planted ? 0x3ddc84 : 0xff4d4d;
}

export function formatGaitStatus(gait) {
  if (!gait) return '';
  const left = gait.feet?.left?.planted ? '左接地' : '左遊脚';
  const right = gait.feet?.right?.planted ? '右接地' : '右遊脚';
  const speed = Number(gait.actual_speed_mps);
  const shown = Number.isFinite(speed) ? `${speed.toFixed(2)}m/s` : '';
  const metric = (name) => Number.isFinite(gait[name]) ? `${name}=${gait[name].toFixed(3)}m` : '';
  return [gait.phase, gait.mode, shown, `${left}/${right}`,
    metric('goal_error_m'), metric('stop_prediction_m'),
    gait.final_stop_metrics?.stage,
    gait.final_stop_metrics?.reason && `final_stop_metrics.reason=${gait.final_stop_metrics.reason}`,
    gait.stop_failure_reason && `stop_failure_reason=${gait.stop_failure_reason}`,
  ].filter(Boolean).join(' ');
}
