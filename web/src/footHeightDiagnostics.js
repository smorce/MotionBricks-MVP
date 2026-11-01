/** 床を基準に、SOMAと描画済みVRMの足首・足先を同じ単位で比較する。 */
export function compareFootHeights(feet, sample, somaFloorZ, floorTop) {
  return Object.fromEntries(['left', 'right'].map(side => {
    const soma = {ankle: feet[side].z - somaFloorZ, toe: feet[side].toe_z - somaFloorZ};
    const vrm = {ankle: sample[side].foot[1] - floorTop, toe: sample[side].toe[1] - floorTop};
    return [side, {planted: feet[side].planted, soma_height_m: soma, vrm_height_m: vrm,
      ankle_delta_m: vrm.ankle - soma.ankle, toe_delta_m: vrm.toe - soma.toe}];
  }));
}
