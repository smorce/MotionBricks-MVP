/** Three.js の床平面 (x, z) を、Z-up ランタイムの地面 (x, y) にする。 */
export function threePointToRuntime(x, z) {
  return {x, y: -z};
}

/** ランタイムの関節（Z-up）を、ルートと同じ補正で Three.js のシーンへ置く。 */
export function runtimeJointToThree(point, restRoot, spawn, floorTop) {
  return {
    x: point.x - restRoot.x + spawn.x,
    y: point.z - restRoot.z + floorTop,
    z: -point.y + restRoot.y + spawn.z,
  };
}

export function threeJointToRuntime(point, restRoot, spawn, floorTop) {
  return {
    x: point.x + restRoot.x - spawn.x,
    y: -(point.z - restRoot.y - spawn.z),
    z: point.y + restRoot.z - floorTop,
  };
}
