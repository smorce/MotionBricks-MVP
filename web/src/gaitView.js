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
    ...['left', 'right'].map(side => {
      const height = gait.foot_height_diagnostics?.[side];
      return height && `${side}: SOMA足先=${height.soma_height_m.toe.toFixed(3)}m VRM足先=${height.vrm_height_m.toe.toFixed(3)}m 差=${height.toe_delta_m.toFixed(3)}m`;
    }),
  ].filter(Boolean).join(' ');
}
