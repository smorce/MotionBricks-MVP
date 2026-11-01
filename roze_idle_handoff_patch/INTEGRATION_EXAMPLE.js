// Integration guide, not a complete entry point. Add in your EXISTING
// Three.js / three-vrm main renderer. Adapt variable names to the Cursor app.

import { IdleHandoff } from './idleHandoff.js';
import { VRMAnimationLoaderPlugin, createVRMAnimationClip } from '@pixiv/three-vrm-animation';

// 1) Register this plugin ONCE alongside the already-existing VRMLoaderPlugin:
// gltfLoader.register((parser) => new VRMAnimationLoaderPlugin(parser));

// 2) Load the VRMA and convert to a THREE.AnimationClip for YOUR loaded VRM:
// const gltfIdle = await gltfLoader.loadAsync('/idle.vrma');
// const idleClip = createVRMAnimationClip(gltfIdle.userData.vrmAnimations[0], vrm);

let handoff = null;

function onIdleStarted(vrm, idleClip) {
  if (handoff?.active) return;
  // Important: the MOST RECENT MotionBricks pose must already be displayed.
  handoff = new IdleHandoff(vrm, idleClip, {
    fadeSeconds: 0.45,
    preserveYaw: true, // don't turn 90 degrees to match the VRMA's authored heading
    debug: true,
  });
}

function onMoveRequested() {
  if (handoff) {
    handoff.stop();
    handoff = null;
  }
  // Then resume your existing MotionBricks path/click controller.
}

function animate(deltaSeconds) {
  // Crucial: EXACTLY ONE system must write the VRM bones per frame.
  if (handoff?.active) {
    handoff.update(deltaSeconds);
  } else {
    // applyMotionBricksPose(latestPose); // your existing code
  }
  // vrm.update(deltaSeconds);       // call after pose updates
  // renderer.render(scene, camera); // your existing code
}

// 3) Call onIdleStarted(vrm,idleClip) at your existing "idle.vrma" switch.
//    Never start an old AnimationMixer action at the same time.
// 4) Before a new click movement, call onMoveRequested().
// 5) Reset handoff on VRM reload so it never edits an unloaded model.
export { onIdleStarted, onMoveRequested, animate };
