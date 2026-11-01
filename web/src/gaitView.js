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
  return [gait.phase, gait.mode, shown, `${left}/${right}`].filter(Boolean).join(' ');
}
