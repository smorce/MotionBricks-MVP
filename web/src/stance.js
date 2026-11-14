import * as THREE from 'three';

export const LEG_ADDUCT_MIN_DEG = 0;
export const LEG_ADDUCT_MAX_DEG = 24;
export const ARM_ABDUCT_MAX_DEG = 30;
export const TOE_FORWARD_MAX_DEG = 40;
export const FINGER_CURL_MAX_DEG = 45;
export const LEG_ADDUCT_DEFAULT_DEG = 11;
export const ARM_ABDUCT_DEFAULT_DEG = 8;
export const TOE_FORWARD_DEFAULT_DEG = 12.5;
export const FINGER_CURL_DEFAULT_DEG = 9.5;
export const ANKLE_ROLL_DEFAULT_DEG = 12;
export const ANKLE_ROLL_MIN_DEG = -15;
export const ANKLE_ROLL_MAX_DEG = 15;

/** スライダー1度あたりの関節角。近位を基準に、中節は少し深く、末節と親指は浅く曲げる。 */
export const FINGER_JOINTS = [
  ['leftThumbMetacarpal', 'rightThumbMetacarpal', 0.35],
  ['leftThumbProximal', 'rightThumbProximal', 0.6],
  ['leftThumbDistal', 'rightThumbDistal', 0.4],
  ['leftIndexProximal', 'rightIndexProximal', 1],
  ['leftIndexIntermediate', 'rightIndexIntermediate', 1.2],
  ['leftIndexDistal', 'rightIndexDistal', 0.55],
  ['leftMiddleProximal', 'rightMiddleProximal', 1],
  ['leftMiddleIntermediate', 'rightMiddleIntermediate', 1.2],
  ['leftMiddleDistal', 'rightMiddleDistal', 0.55],
  ['leftRingProximal', 'rightRingProximal', 1],
  ['leftRingIntermediate', 'rightRingIntermediate', 1.2],
  ['leftRingDistal', 'rightRingDistal', 0.55],
  ['leftLittleProximal', 'rightLittleProximal', 0.9],
  ['leftLittleIntermediate', 'rightLittleIntermediate', 1.1],
  ['leftLittleDistal', 'rightLittleDistal', 0.5],
];

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

/** 調整後に渡す姿勢データ。指の初期値は呼び出し側が渡す。 */
export function stanceData({legDeg = 0, armDeg = 0, toeDeg = 0, fingerDeg = 0, ankleDeg = 0} = {}) {
  return {
    leg_adduct_deg: Number(clampLegAdductDeg(legDeg).toFixed(1)),
    arm_abduct_deg: Number(clampDegrees(armDeg, 0, ARM_ABDUCT_MAX_DEG).toFixed(1)),
    toe_forward_deg: Number(clampDegrees(toeDeg, 0, TOE_FORWARD_MAX_DEG).toFixed(1)),
    finger_curl_deg: Number(clampDegrees(fingerDeg, 0, FINGER_CURL_MAX_DEG).toFixed(1)),
    ankle_roll_deg: Number(clampDegrees(ankleDeg, ANKLE_ROLL_MIN_DEG, ANKLE_ROLL_MAX_DEG).toFixed(1)),
  };
}

/** 保存がない項目は、画面で決めた初期姿勢を使う。明示した 0 は維持する。 */
export function stanceFromSaved(saved = {}) {
  const pick = (key, fallback) => Object.hasOwn(saved, key) ? saved[key] : fallback;
  return stanceData({
    legDeg: pick('leg_adduct_deg', LEG_ADDUCT_DEFAULT_DEG),
    armDeg: pick('arm_abduct_deg', ARM_ABDUCT_DEFAULT_DEG),
    toeDeg: pick('toe_forward_deg', TOE_FORWARD_DEFAULT_DEG),
    fingerDeg: pick('finger_curl_deg', FINGER_CURL_DEFAULT_DEG),
    ankleDeg: pick('ankle_roll_deg', ANKLE_ROLL_DEFAULT_DEG),
  });
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

/**
 * 指を前方軸まわりに曲げ、指先を掌（−Y）へ寄せる。
 * 正規化骨の安静時、左の指は +X、右の指は −X を向く。
 */
export function curlFinger(quaternion, side, radians) {
  _turn.setFromAxisAngle(_forward, (side === 'left' ? -1 : 1) * radians);
  quaternion.multiply(_turn);
}

/**
 * 足首を前方軸まわりに回し、足裏を左右へ傾ける。つま先の向きは変えない。
 * 正の radians で、左足の足裏は +X 側、右足の足裏は −X 側、つまり両足とも外側へ傾く。
 */
export function rollAnkles(leftQuaternion, rightQuaternion, radians) {
  _turn.setFromAxisAngle(_forward, radians);
  leftQuaternion.multiply(_turn);
  _turn.setFromAxisAngle(_forward, -radians);
  rightQuaternion.multiply(_turn);
}

function rad(deg) {
  return deg * Math.PI / 180;
}

/** 足のボーンへ、足裏の傾き（度）だけを足す。停止中は保存姿勢へ毎フレーム重ねる。 */
export function poseAnkles(getNode, deg) {
  const left = getNode('leftFoot');
  const right = getNode('rightFoot');
  if (left && right) rollAnkles(left.quaternion, right.quaternion, rad(deg));
}

const RETARGETED_FINGERS = new Set([
  'leftThumbDistal', 'rightThumbDistal',
  'leftMiddleDistal', 'rightMiddleDistal',
]);

/**
 * 指の各関節へ、握り角（度）を配分して足す。
 * replaceUnmapped のとき、配信で上書きされない関節は安静角から置き直す。毎フレーム掛けると重ならない。
 */
export function poseFingers(getNode, deg, {replaceUnmapped = false} = {}) {
  for (const [leftName, rightName, weight] of FINGER_JOINTS) {
    const angle = rad(deg) * weight;
    for (const [name, side] of [[leftName, 'left'], [rightName, 'right']]) {
      const node = getNode(name);
      if (!node) continue;
      if (replaceUnmapped && !RETARGETED_FINGERS.has(name)) node.quaternion.identity();
      curlFinger(node.quaternion, side, angle);
    }
  }
}

/**
 * 立ちと歩きの姿勢補正をまとめて掛ける。
 * sign が負のときは、掛けた順の逆で同じ量を外す。
 */
export function poseStance(getNode, data, sign = 1) {
  const turn = (deg) => rad(sign * deg);
  const pair = (leftName, rightName, fn, deg) => {
    const left = getNode(leftName);
    const right = getNode(rightName);
    if (left && right) fn(left.quaternion, right.quaternion, turn(deg));
  };
  const steps = [
    () => pair('leftUpperLeg', 'rightUpperLeg', adductUpperLegs, data.leg_adduct_deg),
    () => pair('leftUpperArm', 'rightUpperArm', abductUpperArms, data.arm_abduct_deg),
    () => pair('leftFoot', 'rightFoot', pointFeetForward, data.toe_forward_deg),
    () => pair('leftFoot', 'rightFoot', rollAnkles, data.ankle_roll_deg),
    () => poseFingers(getNode, sign * data.finger_curl_deg, {replaceUnmapped: sign > 0}),
  ];
  for (const step of sign < 0 ? [...steps].reverse() : steps) step();
}
