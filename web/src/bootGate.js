/** ロゼ表示前に揃える初期化条件。どれか欠けると位置がズレる。 */

export function isSceneBootReady({spawn, hasVrm, hasRig, hasPose, hasRetarget}) {
  return Boolean(
    spawn &&
    Number.isFinite(spawn.x) &&
    Number.isFinite(spawn.z) &&
    hasVrm &&
    hasRig &&
    hasPose &&
    hasRetarget,
  );
}

/** spawn 未確定なら null。仮の 0 補完はしない。 */
export function spawnOffset(spawn) {
  if (!spawn || !Number.isFinite(spawn.x) || !Number.isFinite(spawn.z)) return null;
  return {x: spawn.x, z: spawn.z};
}
