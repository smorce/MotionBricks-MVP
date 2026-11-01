/** 停止姿勢の所有者。速度では破棄しない。WebSocket の遅延フレームは moveId で捨てる。 */

export function emptyOwner() {
  return {mode: 'live', moveId: null, settleSeq: 0, capture: false, blend: false, seenMove: null};
}

export function reduceOwner(owner, frame) {
  const moveId = frame.moveId ?? null;
  const settleSeq = frame.settleSeq ?? 0;
  if (owner.seenMove != null && moveId != null && moveId < owner.seenMove) return owner;
  if (moveId === owner.moveId && settleSeq < owner.settleSeq) return owner;
  if (frame.phase === 'settled' && frame.bothPlanted !== true) {
    return {...owner, mode: 'live', capture: false, blend: false};
  }
  if (frame.phase === 'collect_preparing') {
    return {...owner, mode:'collect_preparing', capture:false, blend:false};
  }
  if (frame.phase === 'collecting') {
    return {...owner, mode:'collecting', capture:false, blend:false};
  }
  if (frame.phase === 'settled') {
    const stale = owner.mode === 'live' && owner.seenMove != null && moveId != null && moveId !== owner.seenMove;
    if (stale) return owner;
    if (['settled','collect_preparing'].includes(owner.mode) && owner.settleSeq === settleSeq && owner.moveId === moveId) {
      return {...owner, mode:'settled', capture: owner.capture, blend: false};
    }
    return {
      mode: 'settled',
      moveId,
      settleSeq,
      capture: true,
      blend: false,
      seenMove: moveId ?? owner.seenMove,
    };
  }
  if (owner.mode === 'settled') {
    return {mode: 'live', moveId, settleSeq, capture: false, blend: true, seenMove: moveId ?? owner.seenMove};
  }
  return {
    mode: 'live',
    moveId,
    settleSeq,
    capture: false,
    blend: owner.blend,
    seenMove: moveId ?? owner.seenMove,
  };
}

/** 停止姿勢のスナップショットには、歩行中のスライダー補正が既に入っている。 */
export function shouldApplyStance(owner) {
  return !['settled','collect_preparing'].includes(owner.mode);
}
