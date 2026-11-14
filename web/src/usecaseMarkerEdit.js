/** マーカー座標を安定して比較・保存するための丸め。 */
export function roundCoord(value) {
  return Math.round(Number(value) * 100) / 100;
}

/** ユースケースの床上位置を更新する。 */
export function moveUsecaseMarker(usecase, x, z) {
  usecase.x = roundCoord(x);
  usecase.z = roundCoord(z);
  return {x: usecase.x, z: usecase.z};
}

/** マーカー付きユースケースだけを id → {x,z} にまとめる。 */
export function markerOverrides(cases) {
  const out = {};
  for (const usecase of cases) {
    if (usecase.marker === false) continue;
    if (!Number.isFinite(usecase.x) || !Number.isFinite(usecase.z)) continue;
    out[usecase.id] = {x: roundCoord(usecase.x), z: roundCoord(usecase.z)};
  }
  return out;
}

/** 保存済み上書きをユースケース配列へ反映する。 */
export function applyMarkerOverrides(cases, overrides) {
  if (!overrides || typeof overrides !== 'object') return cases;
  for (const usecase of cases) {
    const next = overrides[usecase.id];
    if (!next) continue;
    if (Number.isFinite(next.x)) usecase.x = roundCoord(next.x);
    if (Number.isFinite(next.z)) usecase.z = roundCoord(next.z);
  }
  return cases;
}

export function formatMarkerOverridesJson(cases) {
  return JSON.stringify(markerOverrides(cases), null, 2);
}

export function formatMarkerReadout(usecase) {
  if (!usecase) return 'リングをドラッグして位置を調整';
  return `${usecase.title}: x=${roundCoord(usecase.x).toFixed(2)}, z=${roundCoord(usecase.z).toFixed(2)}`;
}
