/** Three.js の床平面 (x, z) を、Z-up ランタイムの地面 (x, y) にする。 */
export function threePointToRuntime(x, z) {
  return {x, y: -z};
}
