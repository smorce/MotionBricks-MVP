import * as THREE from 'three';

export const LEG_ADDUCT_MIN_DEG = 0;
export const LEG_ADDUCT_MAX_DEG = 24;
export const ARM_ABDUCT_MAX_DEG = 30;
export const TOE_FORWARD_MAX_DEG = 40;

const _forward = new THREE.Vector3(0, 0, 1);
const _up = new THREE.Vector3(0, 1, 0);
const _turn = new THREE.Quaternion();

/** スライダーの入力を、指定した範囲の角度（度）へ揃える。 */
export function clampDegrees(value, min, max) {
  const n = Number(value);
  if (!Number.isFinite(n)) return min;
  return Math.min(max, Math.max(min, n));
}

/** スライダーの入力を、立ちと歩きに掛ける内転角（度）へ揃える。 */
export function clampLegAdductDeg(value) {
  return clampDegrees(value, LEG_ADDUCT_MIN_DEG, LEG_ADDUCT_MAX_DEG);
}

/** 調整後に渡す姿勢データ。 */
export function stanceData({legDeg = 0, armDeg = 0, toeDeg = 0} = {}) {
  return {
    leg_adduct_deg: Number(clampLegAdductDeg(legDeg).toFixed(1)),
    arm_abduct_deg: Number(clampDegrees(armDeg, 0, ARM_ABDUCT_MAX_DEG).toFixed(1)),
    toe_forward_deg: Number(clampDegrees(toeDeg, 0, TOE_FORWARD_MAX_DEG).toFixed(1)),
  };
}

/**
 * 正規化ヒューマノイドの大腿を、親空間の前方軸まわりに少し内転させる。
 * 左が +X のとき、正の radians で両ひざが体の中心へ寄る。
 */
export function adductUpperLegs(leftQuaternion, rightQuaternion, radians) {
  _turn.setFromAxisAngle(_forward, -radians);
  leftQuaternion.multiply(_turn);
  _turn.setFromAxisAngle(_forward, radians);
  rightQuaternion.multiply(_turn);
}

/**
 * 上腕を前方軸まわりに外転させ、手を体の横へ広げる。
 * 左が +X のとき、正の radians で両手とも外側へ動く。
 */
export function abductUpperArms(leftQuaternion, rightQuaternion, radians) {
  _turn.setFromAxisAngle(_forward, radians);
  leftQuaternion.multiply(_turn);
  _turn.setFromAxisAngle(_forward, -radians);
  rightQuaternion.multiply(_turn);
}

/**
 * 足を上向き軸まわりに内旋させ、外側を向いたつま先を正面へ戻す。
 * 正の radians で左足は +X 側から、右足は -X 側から、正面の +Z へ寄る。
 */
export function pointFeetForward(leftQuaternion, rightQuaternion, radians) {
  _turn.setFromAxisAngle(_up, -radians);
  leftQuaternion.multiply(_turn);
  _turn.setFromAxisAngle(_up, radians);
  rightQuaternion.multiply(_turn);
}
