import {PlaybackBuffer} from './playbackBuffer.js';
const playbackBuffer = new PlaybackBuffer(100);
import {MAP, calcWorldQuats, applySomaRotations} from './somaRetarget.js';
import {preflightCollect} from './collectValidation.js';
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {VRMLoaderPlugin, VRMUtils} from '@pixiv/three-vrm';
import {threePointToRuntime} from './coords.js';
import {abductUpperArms, adductUpperLegs, pointFeetForward, stanceData} from './stance.js';
import {IdleHandoff} from './idleHandoff.js';
import {GroundedIdle} from './groundedIdle.js';
import {emptyOwner, reduceOwner, shouldApplyStance} from './poseOwner.js';
import {isSceneBootReady, spawnOffset} from './bootGate.js';
import {GaitDebug} from './gaitDebug.js';
import {formatGaitStatus} from './gaitView.js';
import {formatVisualStop} from './visualStopView.js';
import {compareFootHeights} from './footHeightDiagnostics.js';
import idleMotionUrl from '../../motions/idle.vrma?url';
import idleBreakMotionUrl from '../../motions/idle_06.vrma?url';
import {buildKit} from '../../ModernRestaurantCafekit/kit.mjs';
import {stage} from '../../ModernRestaurantCafekit/stage.mjs';
import cafeFolderUrl from '../../ModernRestaurantCafekit/kit.json?url';
import cafeUsecases from '../../backend/cafe_usecases.json';

const FLOOR_TOP=0.05;
// false のとき公式 Idle / VRMA 全身再生はしない。settled の上半身寄せには idle.vrma を使う。
const USE_VRMA_IDLE=false;
const IDLE_QUIET_MS=5000;
const IDLE_FADE_SEC=0.8;
const UPPER_BLEND_MAX=0.65;
const IDLE_SPEED_MAX=0.2;
const USECASE_SNAP_M=1.0;
const camOffset=new THREE.Vector3(3.6, 2.35, 4.8);
const lookHeight=1.05;
const status = document.querySelector('#status');
const background = document.querySelector('#background');
const stanceInputs={
  leg:document.querySelector('#legAdduct'),
  arm:document.querySelector('#armAbduct'),
  toe:document.querySelector('#toeForward'),
}
const stanceOut={
  leg:document.querySelector('#legAdductOut'),
  arm:document.querySelector('#armAbductOut'),
  toe:document.querySelector('#toeForwardOut'),
}
const stanceDataEl=document.querySelector('#stanceData')
const STANCE_KEY='roze.stanceAdjust'

function currentStance(){
  return stanceData({
    legDeg:stanceInputs.leg?.value,
    armDeg:stanceInputs.arm?.value,
    toeDeg:stanceInputs.toe?.value,
  })
}
function formatStance(data){
  return `{"leg_adduct_deg":${data.leg_adduct_deg.toFixed(1)},"arm_abduct_deg":${data.arm_abduct_deg.toFixed(1)},"toe_forward_deg":${data.toe_forward_deg.toFixed(1)}}`
}
function renderStanceReadout(){
  const data=currentStance()
  if(stanceOut.leg) stanceOut.leg.textContent=`${data.leg_adduct_deg.toFixed(1)}°`
  if(stanceOut.arm) stanceOut.arm.textContent=`${data.arm_abduct_deg.toFixed(1)}°`
  if(stanceOut.toe) stanceOut.toe.textContent=`${data.toe_forward_deg.toFixed(1)}°`
  if(stanceDataEl) stanceDataEl.textContent=formatStance(data)
}
function rememberStance(){
  try{ localStorage.setItem(STANCE_KEY, JSON.stringify(currentStance())) }catch{ /* private mode */ }
}
function restoreStance(){
  let saved={}
  try{
    const raw=localStorage.getItem(STANCE_KEY)
    if(raw) saved=JSON.parse(raw)
    else{
      const legacy=localStorage.getItem('roze.legAdductDeg')
      if(legacy!=null) saved={leg_adduct_deg:Number(legacy)}
    }
  }catch{ saved={} }
  const data=stanceData({
    legDeg:saved.leg_adduct_deg,
    armDeg:saved.arm_abduct_deg,
    toeDeg:saved.toe_forward_deg,
  })
  if(stanceInputs.leg) stanceInputs.leg.value=String(data.leg_adduct_deg)
  if(stanceInputs.arm) stanceInputs.arm.value=String(data.arm_abduct_deg)
  if(stanceInputs.toe) stanceInputs.toe.value=String(data.toe_forward_deg)
}
restoreStance()
renderStanceReadout()
for(const input of Object.values(stanceInputs)){
  input?.addEventListener('input', ()=>{
    rememberStance()
    renderStanceReadout()
  })
}
document.querySelector('#stanceCopy')?.addEventListener('click', async ()=>{
  const text=stanceDataEl?.textContent??''
  const button=document.querySelector('#stanceCopy')
  try{
    await navigator.clipboard.writeText(text)
    if(button){
      button.textContent='コピーしました'
      setTimeout(()=>{ button.textContent='この数値をコピー' }, 1200)
    }
  }catch{
    if(button) button.textContent='Copy failed'
  }
})
let stanceApplied=false
function adjustStance(){
  if(!vrm) return
  const data=currentStance()
  const human=vrm.humanoid
  const leftLeg=human.getNormalizedBoneNode('leftUpperLeg')
  const rightLeg=human.getNormalizedBoneNode('rightUpperLeg')
  if(leftLeg&&rightLeg){
    adductUpperLegs(leftLeg.quaternion, rightLeg.quaternion, THREE.MathUtils.degToRad(data.leg_adduct_deg))
  }
  const leftArm=human.getNormalizedBoneNode('leftUpperArm')
  const rightArm=human.getNormalizedBoneNode('rightUpperArm')
  if(leftArm&&rightArm){
    abductUpperArms(leftArm.quaternion, rightArm.quaternion, THREE.MathUtils.degToRad(data.arm_abduct_deg))
  }
  const leftFoot=human.getNormalizedBoneNode('leftFoot')
  const rightFoot=human.getNormalizedBoneNode('rightFoot')
  if(leftFoot&&rightFoot){
    pointFeetForward(leftFoot.quaternion, rightFoot.quaternion, THREE.MathUtils.degToRad(data.toe_forward_deg))
  }
  stanceApplied=true
}
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(42, window.innerWidth/window.innerHeight, .1, 150);
camera.position.set(2.2, 1.7, 3.2);
camera.lookAt(0, 1.1, 0);
camera.far = 400;
camera.updateProjectionMatrix();
const renderer = new THREE.WebGLRenderer({antialias:true, alpha:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));
renderer.setSize(window.innerWidth,window.innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.insertBefore(renderer.domElement, document.querySelector('#toolbar'));
const controls = new OrbitControls(camera, renderer.domElement);
// 自動検証時だけ、同一姿勢を三方向から描画して骨座標と対応づける。
if (new URLSearchParams(location.search).has('observation')) {
  window.motionBricksObservation = {
    state() { return lastFrame; },
    move(dx, dy) {
      if (!vrm || !sceneReady || socket?.readyState !== WebSocket.OPEN || !lastFrame) {
        throw new Error('Scene is not ready');
      }
      socket.send(JSON.stringify({type:'move', x:lastFrame.poses[0][0]+dx,
        y:lastFrame.poses[0][1]+dy, ...beginMoveSource(), hold_stance:true, stop_mode:document.querySelector('#stopMode').value}));
    },
    capture() {
      if (!vrm || !sceneReady || !lastFrame) throw new Error('Scene is not ready');
      const position = camera.position.clone();
      const rotation = camera.quaternion.clone();
      const root = vrm.scene.position.clone();
      vrm.scene.updateMatrixWorld(true);
      const hips = vrm.humanoid.getNormalizedBoneNode('hips');
      const facing = new THREE.Vector3(0,0,1).applyQuaternion(hips.getWorldQuaternion(new THREE.Quaternion()));
      facing.y=0;
      facing.normalize();
      const target = root.clone().add(new THREE.Vector3(0, 0.9, 0));
      const joints = {};
      for (const side of ['left', 'right']) {
        joints[side] = {};
        for (const part of ['UpperLeg', 'LowerLeg', 'Foot', 'Toes']) {
          const node = vrm.humanoid.getRawBoneNode(side+part);
          joints[side][part] = node?.getWorldPosition(new THREE.Vector3()).toArray() ?? null;
        }
      }
      const images = {};
      for (const [name, angle] of [['front',0], ['side',Math.PI/2], ['45deg',Math.PI/4]]) {
        const offset = new THREE.Vector3(3.2*Math.sin(angle),1.2,3.2*Math.cos(angle));
        offset.applyAxisAngle(new THREE.Vector3(0,1,0),Math.atan2(facing.x,facing.z));
        camera.position.copy(root).add(offset);
        camera.lookAt(target);
        renderer.render(scene,camera);
        images[name] = renderer.domElement.toDataURL('image/png');
      }
      camera.position.copy(position);
      camera.quaternion.copy(rotation);
      renderer.render(scene,camera);
      return {capturedAt:performance.now(), displayFrame:observationFrame, displayedPose:observationPose, frame:lastFrame, facing:facing.toArray(), floorY:FLOOR_TOP, joints, images};
    },
    environment(clear) {
      place.group.visible=!clear;
      clickFloor.material.opacity=clear?1:0;
      clickFloor.material.color.setHex(0x777777);
    },
  };
}
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.enablePan = true;
controls.screenSpacePanning = true;
controls.minDistance = 1.2;
controls.maxDistance = 36;
controls.maxPolarAngle = Math.PI * 0.495;
controls.target.set(0, 1.1, 0);
// 左ドラッグで回転、右ドラッグで平行移動。短い左クリックは床への移動指示。
controls.mouseButtons = {
  LEFT: THREE.MOUSE.ROTATE,
  MIDDLE: THREE.MOUSE.DOLLY,
  RIGHT: THREE.MOUSE.PAN,
};
controls.touches = {
  ONE: THREE.TOUCH.ROTATE,
  TWO: THREE.TOUCH.DOLLY_PAN,
};
controls.update();
renderer.domElement.addEventListener('contextmenu', (e)=>e.preventDefault());
const fill = new THREE.HemisphereLight(0xffffff, 0x596b7a, 2);
const sun = new THREE.DirectionalLight(0xffffff, 2.0);
sun.position.set(-2,6,3);
scene.add(fill, sun);
const grid = new THREE.GridHelper(30,30,0x6f8cbb,0x334157);
scene.add(grid);
const clickFloor = new THREE.Mesh(new THREE.PlaneGeometry(200,200), new THREE.MeshBasicMaterial({transparent:true,opacity:0,depthWrite:false}));
clickFloor.rotation.x=-Math.PI/2;
scene.add(clickFloor);
const marker = new THREE.Mesh(new THREE.RingGeometry(.12,.17,40), new THREE.MeshBasicMaterial({color:0x34ffab,side:THREE.DoubleSide}));
marker.rotation.x=-Math.PI/2;
marker.position.y=FLOOR_TOP+0.02;
marker.visible=false;
scene.add(marker);
const gaitDebug = new GaitDebug(scene);
let gait = null;
let owner = emptyOwner();
let gaitDebugOn = false;
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
let vrm=null;
let rig=null;
let currentPose=null;
let lastPose=null;
let lastFrame=null;
let observationFrame=0;
let observationPose=null;
let socket=null;
let lastDecision='—';
let lastStage='';
let currentMotionState='';
let lastError='';
let poseStamp=0;
let renderFrames=0;
let fps=0;
let fpsStamp=performance.now();
let clickAt=0;
let clickLatency=null;
let generateMs=null;
let place=null;
let look=null;
let spawn=null;
let sceneReady=false;
let placeNote='カフェを読み込み中';
let pendingCase='';
let motionPhase='idle';
let officialState='';
let actualSpeed=null;
let moveRequested=false;
let lastInputAt=performance.now();
let idleClip=null;
let idleBreakClip=null;
let handoff=null;
let handoffClip='';
let motionToken=0;
const usecasePicks=[];
const markerCases=cafeUsecases.filter((item)=>item.marker!==false && Number.isFinite(item.x) && Number.isFinite(item.z));
const openFloor=cafeUsecases.find((item)=>item.id==='open-floor') ?? {
  id:'open-floor', title:'空いた床', intent:'カフェの空いた床に着いた。自然に立つ。', hints:['自然に立つ'], marker:false,
};

let restSourceWorld=[];
let restDestWorld=new Map();
function initializeRetarget(){
  if(!rig||!vrm)return;
  restSourceWorld=calcWorldQuats(rig.rest,rig.parents);
  vrm.scene.updateMatrixWorld(true);
  restDestWorld.clear();
  for(const bone of new Set(Object.values(MAP))){
    const node=vrm.humanoid.getNormalizedBoneNode(bone);
    if(node) restDestWorld.set(bone,node.getWorldQuaternion(new THREE.Quaternion()));
  }
  console.log('Normalized VRM bones calibrated (approximate):',restDestWorld.size);
}
function lerpPose(a, b, t){
  if(!a || a.length!==b.length) return b;
  return b.map((joint,i)=>{
    const out=joint.slice();
    for(let k=0;k<3;k++) out[k]=a[i][k]+(joint[k]-a[i][k])*t;
    const qa=new THREE.Quaternion(a[i][3],a[i][4],a[i][5],a[i][6]);
    const qb=new THREE.Quaternion(joint[3],joint[4],joint[5],joint[6]);
    if(qa.dot(qb)<0) qb.set(-qb.x,-qb.y,-qb.z,-qb.w);
    qa.slerp(qb, t);
    out[3]=qa.x; out[4]=qa.y; out[5]=qa.z; out[6]=qa.w;
    return out;
  });
}
function placeRoot(pose){
  if(!rig||!vrm||!pose?.length) return;
  const origin=spawnOffset(spawn);
  if(!origin) return;
  vrm.scene.position.set(pose[0][0]-rig.rest[0][0]+origin.x, pose[0][2]-rig.rest[0][2]+FLOOR_TOP, -pose[0][1]+rig.rest[0][1]+origin.z);
}
function applyPose(pose){
  if(!rig||!vrm||!restSourceWorld.length||!spawn||pose.length!==rig.joint_names.length)return;
  // Roze's scene origin follows the source hips ground position; don't add hips height twice.
  placeRoot(pose);
  vrm.scene.updateMatrixWorld(true);
  applySomaRotations(vrm, rig, pose, restSourceWorld, restDestWorld);
}
function markInput(){
  lastInputAt=performance.now();
}
function desiredIdleKind(){
  return performance.now()-lastInputAt>=IDLE_QUIET_MS?'idle_06':'idle';
}
function officialIsIdle(){
  if(!officialState) return motionPhase==='idle'||motionPhase==='pose_done';
  return /idle/i.test(officialState);
}
function standingStill(){
  if(!USE_VRMA_IDLE||moveRequested) return false;
  if(motionPhase!=='idle'&&motionPhase!=='pose_done') return false;
  if(!officialIsIdle()) return false;
  return Number.isFinite(actualSpeed)&&actualSpeed<=IDLE_SPEED_MAX;
}
function releaseVrmaIdle(){
  if(handoff){
    handoff.stop();
    handoff=null;
    handoffClip='';
  }
  exitBlend=null;
}
let groundedIdle=null;
let idleReadySent=null;
let collectBlendStarted=null;
let collectFinalUpper=null;
let idleExit=null;
const followTarget=new THREE.Vector3();
const lastFollow=new THREE.Vector3();
let followReady=false;
function clearHeldStop(){
  groundedIdle=null;
}
function bootReady(){
  return isSceneBootReady({
    spawn,
    hasVrm:Boolean(vrm),
    hasRig:Boolean(rig),
    hasPose:Boolean(currentPose?.length),
    hasRetarget:restSourceWorld.length>0,
  });
}
function syncCameraToCharacter(){
  if(!vrm) return;
  const feet=vrm.scene.position;
  controls.target.set(feet.x, FLOOR_TOP+lookHeight, feet.z);
  camera.position.set(feet.x+camOffset.x, FLOOR_TOP+camOffset.y, feet.z+camOffset.z);
  followTarget.set(feet.x, feet.y+lookHeight, feet.z);
  lastFollow.copy(followTarget);
  followReady=true;
  controls.update();
}
function captureSettledIdle(){
  if(!vrm||!currentPose) return;
  applyPose(currentPose);
  adjustStance();
  if(collectFinalUpper){
    for(const bone of collectFinalUpper) bone.node.quaternion.copy(bone.q);
    collectFinalUpper=null;
  }
  groundedIdle=new GroundedIdle(vrm, {
    idleClip,
    fadeSeconds:IDLE_FADE_SEC,
    upperBlendMax:UPPER_BLEND_MAX,
  });
  owner={...owner, capture:false};
  moveRequested=false;
}
function tryRevealCharacter(){
  if(sceneReady||!bootReady()) return;
  // 表示前にバックエンド座標を確定する。停止姿勢の保存は位置確定の後だけ。
  if(owner.mode==='settled'||owner.capture){
    captureSettledIdle();
  }else{
    applyPose(currentPose);
    if(shouldApplyStance(owner)) adjustStance();
  }
  syncCameraToCharacter();
  vrm.scene.visible=true;
  sceneReady=true;
  status.textContent='ロゼの位置を同期しました。地面をクリックすると移動します。';
}
function captureCharacterPose(){
  const held=[];
  vrm.scene.traverse((node)=>{
    if(!node.quaternion||!node.position) return;
    held.push({node, quaternion:node.quaternion.clone(), position:node.position.clone()});
  });
  return held;
}
function restoreCharacterPose(held){
  for(const item of held){
    item.node.quaternion.copy(item.quaternion);
    item.node.position.copy(item.position);
  }
}
function sampleVrmCollect(){
  vrm.humanoid.update();
  vrm.scene.updateMatrixWorld(true);
  const point=name=>{
    const node=vrm.humanoid.getRawBoneNode(name);
    if(!node) throw new Error(`VRM validation bone missing: ${name}`);
    return node.getWorldPosition(new THREE.Vector3()).toArray();
  };
  const sample={root:vrm.scene.getWorldPosition(new THREE.Vector3()).toArray()};
  for(const side of ['left','right']){
    sample[side]={hip:point(`${side}UpperLeg`),knee:point(`${side}LowerLeg`),foot:point(`${side}Foot`),toe:point(`${side}Toes`)};
  }
  return sample;
}
function reviewCollect(msg){
  if(msg.move_id!==owner.moveId||msg.settle_seq!==owner.settleSeq||owner.mode!=='collect_preparing') return;
  let metrics={accepted:false,reason:'VRM is not ready'};
  if(vrm&&sceneReady&&rig&&groundedIdle){
    const previousStance=stanceApplied;
    try{
      metrics=preflightCollect(msg.frames,{
        capture:()=>{
          const held=captureCharacterPose();
          const seen=new Set(held.map(item=>item.node));
          vrm.humanoid.normalizedHumanBonesRoot.traverse(node=>{
            if(!seen.has(node)) held.push({node,quaternion:node.quaternion.clone(),position:node.position.clone()});
          });
          return held;
        },
        restore:held=>{restoreCharacterPose(held);vrm.scene.updateMatrixWorld(true);},
        apply:frame=>{applyPose(frame);adjustStance();},
        sample:sampleVrmCollect,
      },msg.metrics?.swing);
    }catch(error){
      metrics={accepted:false,reason:`VRM validation failed: ${error.message}`};
    }finally{
      stanceApplied=previousStance;
    }
  }
  socket.send(JSON.stringify({type:'collect_review',move_id:msg.move_id,settle_seq:msg.settle_seq,accepted:metrics.accepted,metrics}));
}
function undoStance(){
  if(!vrm||!stanceApplied) return;
  const data=currentStance();
  const human=vrm.humanoid;
  const leftLeg=human.getNormalizedBoneNode('leftUpperLeg');
  const rightLeg=human.getNormalizedBoneNode('rightUpperLeg');
  if(leftLeg&&rightLeg){
    adductUpperLegs(leftLeg.quaternion, rightLeg.quaternion, -THREE.MathUtils.degToRad(data.leg_adduct_deg));
  }
  const leftArm=human.getNormalizedBoneNode('leftUpperArm');
  const rightArm=human.getNormalizedBoneNode('rightUpperArm');
  if(leftArm&&rightArm){
    abductUpperArms(leftArm.quaternion, rightArm.quaternion, -THREE.MathUtils.degToRad(data.arm_abduct_deg));
  }
  const leftFoot=human.getNormalizedBoneNode('leftFoot');
  const rightFoot=human.getNormalizedBoneNode('rightFoot');
  if(leftFoot&&rightFoot){
    pointFeetForward(leftFoot.quaternion, rightFoot.quaternion, -THREE.MathUtils.degToRad(data.toe_forward_deg));
  }
  stanceApplied=false;
}
let exitBlend=null;
function ease01(t){
  const x=Math.max(0, Math.min(1, t));
  return x*x*(3-2*x);
}
// 表示中の待機姿勢から MotionBricks の姿勢へ重ねる。その場で再生を切らない。
function beginExitFromVrma(){
  if(exitBlend||!handoff?.active||!vrm) return;
  const displayed=captureCharacterPose();
  handoff.stop();
  const released=captureCharacterPose();
  const restPosition=new Map(released.map((item)=>[item.node, item.position]));
  restoreCharacterPose(displayed);
  handoff=null;
  handoffClip='';
  exitBlend={
    nodes:displayed.map((item)=>({
      node:item.node,
      quaternion:item.quaternion,
      position:item.position,
      restPosition:restPosition.get(item.node)?.clone()||item.position.clone(),
    })),
    startedAt:performance.now(),
  };
}
function blendExit(){
  if(!exitBlend||!vrm) return;
  const weight=ease01((performance.now()-exitBlend.startedAt)/(IDLE_FADE_SEC*1000));
  for(const item of exitBlend.nodes){
    const liveQuaternion=item.node.quaternion.clone();
    const livePosition=item.node.position.clone();
    const positionTarget=item.node===vrm.scene?livePosition:item.restPosition;
    item.node.quaternion.slerpQuaternions(item.quaternion, liveQuaternion, weight);
    item.node.position.lerpVectors(item.position, positionTarget, weight);
  }
  if(weight>=1) exitBlend=null;
}
// 画面に出ている姿勢から VRMA へ補間する。スライダー分は控える前に外し、後の adjustStance と二重に掛けない。
function beginHandoff(which){
  const clip=which==='idle_06'?idleBreakClip:idleClip;
  if(!clip||!vrm) return;
  undoStance();
  const held=captureCharacterPose();
  handoff?.stop();
  restoreCharacterPose(held);
  handoff=new IdleHandoff(vrm, clip, {
    fadeSeconds:IDLE_FADE_SEC,
    preserveYaw:which!=='idle_06',
    preserveLegPose:which==='idle',
  });
  handoffClip=which;
}
let motionLoader=null;
async function bindIdleMotions(token){
  const target=vrm;
  const {VRMAnimationLoaderPlugin, createVRMAnimationClip}=await import('@pixiv/three-vrm-animation');
  if(!motionLoader){
    motionLoader=new GLTFLoader();
    motionLoader.register((parser)=>new VRMAnimationLoaderPlugin(parser));
  }
  // settled の上半身 Idle 用。USE_VRMA_IDLE が false でも base は読む。
  const baseGltf=await motionLoader.loadAsync(idleMotionUrl);
  if(token!==motionToken||vrm!==target) return;
  const baseAnim=baseGltf.userData.vrmAnimations?.[0];
  if(!baseAnim) throw new Error('VRMA animation not found');
  idleClip=createVRMAnimationClip(baseAnim, target);
  if(!USE_VRMA_IDLE){
    idleBreakClip=null;
    return;
  }
  const breakGltf=await motionLoader.loadAsync(idleBreakMotionUrl);
  if(token!==motionToken||vrm!==target) return;
  const breakAnim=breakGltf.userData.vrmAnimations?.[0];
  if(!breakAnim) throw new Error('VRMA break animation not found');
  idleBreakClip=createVRMAnimationClip(breakAnim, target);
}
const loader=new GLTFLoader();
loader.register(parser=>new VRMLoaderPlugin(parser));
async function loadVrm(url, revoke=false){
  const token=++motionToken;
  try{
    const gltf=await loader.loadAsync(url);
    if(vrm){scene.remove(vrm.scene);VRMUtils.deepDispose(vrm.scene)}
    releaseVrmaIdle();
    idleClip=null;
    idleBreakClip=null;
    clearHeldStop();
    idleExit=null;
    stanceApplied=false;
    sceneReady=false;
    followReady=false;
    vrm=gltf.userData.vrm;
    if(!vrm)throw new Error('VRM model not found');
    VRMUtils.rotateVRM0(vrm);
    vrm.scene.visible=false;
    vrm.scene.traverse((obj)=>{ if(obj.isMesh){ obj.castShadow=true; obj.receiveShadow=true; } });
    scene.add(vrm.scene);
    initializeRetarget();
    bindIdleMotions(token).catch((err)=>{
      console.error(err);
      lastError=`Idle motion failed to load: ${err.message}`;
    });
    status.textContent='ロゼを読み込みました。位置同期を待っています…';
    tryRevealCharacter();
  }catch(err){status.textContent=`VRMエラー: ${err.message}`}
  finally{if(revoke) URL.revokeObjectURL(url)}
}
document.querySelector('#vrmFile').addEventListener('change',e=>{
  const file=e.target.files?.[0];
  if(!file)return;
  loadVrm(URL.createObjectURL(file), true);
});
loadVrm('http://127.0.0.1:8765/roze.vrm');
function chooseSpawn(built){
  // spots / openSpot は乱数を使わないため、同じキットならリロード後も同じ点になる。
  const spots=built.spots(12);
  const dining=spots.find((p)=>/encaustic|timber/.test(built.surfaceAt(p.x, p.z) || ''));
  return dining || spots[0] || built.openSpot() || built.bounds.getCenter(new THREE.Vector3());
}
async function loadCafe(){
  try{
    const folder=new URL('./', new URL(cafeFolderUrl, window.location.href)).href;
    place=await buildKit({
      folder,
      onProgress:(done,total)=>{ placeNote=`カフェの部品 ${done}/${total}`; },
    });
    spawn=chooseSpawn(place);
    console.log('cafe spawn', {x:spawn.x, z:spawn.z});
    scene.add(place.group);
    const size=place.bounds.getSize(new THREE.Vector3());
    const center=place.bounds.getCenter(new THREE.Vector3());
    clickFloor.geometry.dispose();
    clickFloor.geometry=new THREE.PlaneGeometry(Math.max(size.x, 16)+6, Math.max(size.z, 16)+6);
    clickFloor.position.set(center.x, FLOOR_TOP, center.z);
    scene.remove(fill, sun);
    grid.visible=false;
    look=stage(renderer, scene, {time:'day'});
    look.shadows(place.group);
    look.ground(place);
    look.follow(vrm?.scene ?? place.group);
    controls.target.set(spawn.x, FLOOR_TOP+lookHeight, spawn.z);
    camera.position.set(spawn.x+camOffset.x, FLOOR_TOP+camOffset.y, spawn.z+camOffset.z);
    followReady=false;
    controls.update();
    addUsecaseMarkers();
    placeNote='Modern Restaurant Cafe';
    tryRevealCharacter();
  }catch(err){
    placeNote=`カフェ読込エラー: ${err.message}`;
    console.error(err);
  }
}
loadCafe();
document.querySelector('#backgroundFile').addEventListener('change',e=>{
  const file=e.target.files?.[0];
  if(!file)return;
  const url=URL.createObjectURL(file);
  background.style.backgroundImage=`url("${url}")`;
  grid.visible=false;
});
function makeUsecaseLabel(text){
  const canvas=document.createElement('canvas');
  canvas.width=512;
  canvas.height=64;
  const ctx=canvas.getContext('2d');
  ctx.fillStyle='rgba(16,22,35,0.88)';
  ctx.fillRect(0,0,512,64);
  ctx.fillStyle='#f8f1e7';
  ctx.font='24px "Yu Gothic UI", Meiryo, sans-serif';
  ctx.textAlign='center';
  ctx.textBaseline='middle';
  ctx.fillText(text, 256, 32);
  const sprite=new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(canvas), transparent:true, depthTest:false}));
  sprite.position.y=1.55;
  sprite.scale.set(2.15, 0.27, 1);
  sprite.renderOrder=2;
  return sprite;
}
function addUsecaseMarkers(){
  const ringMat=new THREE.MeshBasicMaterial({color:0xe0a96d, side:THREE.DoubleSide});
  for(const usecase of markerCases){
    const group=new THREE.Group();
    group.position.set(usecase.x, FLOOR_TOP, usecase.z);
    const ring=new THREE.Mesh(new THREE.RingGeometry(0.28, 0.4, 40), ringMat);
    ring.rotation.x=-Math.PI/2;
    ring.position.y=0.03;
    const pick=new THREE.Mesh(
      new THREE.CylinderGeometry(1.0, 1.0, 2.4, 12),
      new THREE.MeshBasicMaterial({transparent:true, opacity:0, depthWrite:false}),
    );
    pick.position.y=1.2;
    pick.userData.usecase=usecase;
    group.add(ring, pick, makeUsecaseLabel(usecase.title));
    scene.add(group);
    usecasePicks.push(pick);
  }
}
function nearestUsecase(x, z){
  let best=null;
  let bestDistance=USECASE_SNAP_M;
  for(const usecase of markerCases){
    const distance=Math.hypot(usecase.x-x, usecase.z-z);
    if(distance<=bestDistance){
      best=usecase;
      bestDistance=distance;
    }
  }
  return best;
}
function markActive(id){
  document.querySelectorAll('#cases button').forEach((button)=>{
    button.classList.toggle('active', button.dataset.id===id);
  });
}
function sendArrival(usecase, x, z){
  markInput();
  if(!socket||socket.readyState!==WebSocket.OPEN||!spawn||!sceneReady){
    status.textContent='カフェかサーバーの準備ができていません。';
    return;
  }
  pendingCase=usecase.title;
  moveRequested=true;
  beginExitFromVrma();
  markActive(usecase.id);
  marker.position.set(x, FLOOR_TOP+0.02, z);
  marker.visible=true;
  clickAt=performance.now();
  lastDecision=`${usecase.title} を選択中…`;
  const goal=threePointToRuntime(x-spawn.x, z-spawn.z);
  socket.send(JSON.stringify({type:'move', x:goal.x, y:goal.y, ...beginMoveSource(), usecase:usecase.id, intent:usecase.intent, hold_stance:usecase.id==='open-floor', retarget_settings:currentStance(), stop_mode:document.querySelector('#stopMode').value}));
}
function buildUsecaseList(){
  const root=document.querySelector('#cases');
  for(const usecase of markerCases){
    const button=document.createElement('button');
    button.type='button';
    button.dataset.id=usecase.id;
    button.textContent=usecase.title;
    button.addEventListener('click', ()=>sendArrival(usecase, usecase.x, usecase.z));
    root.appendChild(button);
  }
}
buildUsecaseList();
let newestStreamMove=null;
let appliedSequence=-1;
function beginMoveSource(){
  playbackBuffer.beginMove(newestStreamMove??0);
  lastPose=currentPose=lastFrame.poses;
  poseStamp=performance.now();
  return {source_sequence:lastFrame.sequence,source_move_id:lastFrame.gait?.move_id};
}
function acceptFrame(msg){
      document.querySelector('#visualStopStatus').textContent=formatVisualStop(msg);
      if(owner.seenMove!=null && msg.gait?.move_id!=null && msg.gait.move_id<owner.seenMove) return;
      if(msg.gait?.move_id===owner.moveId && msg.gait?.settle_seq<owner.settleSeq) return;
      if(msg.phase){
        motionPhase=msg.phase;
        officialState=String(msg.official_state||'');
        actualSpeed=Number(msg.actual_speed_mps);
      }
      if(msg.gait) {
        gait=msg.gait;
        if(gait.collect_failure_reason) lastStage='収束失敗・停止姿勢維持';
        else if(msg.phase==='collect_preparing') lastStage='収束モーション生成中';
        else if(msg.phase==='collecting') lastStage='収束モーション再生中';
        else if(msg.phase==='settled') lastStage=gait.collect_attempted?'収束完了':gait.collect_checked?'収束不要':'上半身Idle移行中・足幅判定待ち';
        if(gait.collect_metrics?.before) lastStage+=` / 足幅 前 ${gait.collect_metrics.before.map(v=>v.toFixed(3)).join('/')}m → 後 ${gait.collect_metrics.after.map(v=>v.toFixed(3)).join('/')}m`;
      }
      const reduced=reduceOwner(owner, {
        bothPlanted: gait.feet?.left?.planted === true && gait.feet?.right?.planted === true,
        phase: msg.phase || motionPhase,
        moveId: msg.gait?.move_id ?? owner.moveId,
        settleSeq: msg.gait?.settle_seq ?? owner.settleSeq,
      });
      if(reduced===owner) return;
      if(reduced.capture && owner.mode==='collecting' && groundedIdle){
        collectFinalUpper=groundedIdle.upper.map(bone=>({node:bone.node,q:bone.node.quaternion.clone()}));
      }
      if(reduced.mode==='collecting' && owner.mode!=='collecting'){
        groundedIdle?.captureUpper();
        collectBlendStarted=performance.now();
      }
      lastPose=currentPose; currentPose=msg.poses; lastFrame=msg; poseStamp=performance.now();
      if(reduced.capture) lastPose=currentPose;
      owner=reduced;
      if(clickAt){clickLatency=performance.now()-clickAt; clickAt=0}
      if(Number.isFinite(msg.generate_ms)) generateMs=msg.generate_ms;
      tryRevealCharacter();

}
function connect(){
  const observationPort=new URLSearchParams(location.search).has('observation')
    ? new URLSearchParams(location.search).get('wsPort') : null;
  socket=new WebSocket(`ws://127.0.0.1:${observationPort||8765}/ws`);
  socket.onopen=()=>{playbackBuffer.clear();status.textContent='接続済み。VRMを読み込んでください。'};
  socket.onmessage=(e)=>{
    const msg=JSON.parse(e.data);
    if(msg.type==='rig'){
      rig=msg;
      initializeRetarget();
      tryRevealCharacter();
    }
    if(msg.type==='collect_candidate') reviewCollect(msg);
    if(msg.type==='frame'){
      if(msg.gait?.move_id!=null && newestStreamMove!=null && msg.gait.move_id<newestStreamMove)return;
      if(msg.gait?.move_id!==newestStreamMove){playbackBuffer.clear();newestStreamMove=msg.gait?.move_id;}
      playbackBuffer.push(msg,performance.now());
    }
    if(msg.type==='metrics' && Number.isFinite(msg.generate_ms)) generateMs=msg.generate_ms;
    if(msg.type==='decision'){
      const size=Number(msg.catalog_size)||1173;
      lastDecision=`${msg.usecase_title||pendingCase} → ${msg.pose_id} ${msg.name} [${msg.category||''}] (${msg.backend} / ${size}件 / confidence ${Number(msg.confidence).toFixed(2)} / ${Number(msg.elapsed_ms||0).toFixed(0)} ms)`;
    }
    if(msg.type==='arrived'){
      const errorM=Number(msg.arrival_error_m);
      const errorText=Number.isFinite(errorM)?` / 目標誤差 ${errorM.toFixed(2)}m`:'';
      lastStage=`${pendingCase} / 停止完了${msg.pose_applied ? ` / 到着姿勢 ${msg.pose_id}` : ' / 着地姿勢を維持'}${errorText}`;
    }
    if(msg.type==='stop_triggered'){
      lastStage=`最後の一歩: 残り${Number(msg.distance_m).toFixed(2)}m / 速度${Number(msg.speed_mps).toFixed(2)}m/s`;
    }
    if(msg.type==='motion_state'){
      const phase={
        idle:'待機', moving:'移動', decelerating:'減速', final_step:'最後の一歩',
        waiting_for_foot_contact:'着地待ち', contact_recovery:'接地回復中', stop_failed:'停止失敗（歩行停止済み）', settled:'停止姿勢',
        pose_pending:'ポーズ準備', pose_transition:'ポーズ移行', pose_done:'ポーズ完了',
      }[msg.phase]||msg.phase;
      currentMotionState=`動作: ${phase} / 公式: ${msg.official_state} / 速度 ${Number(msg.actual_speed_mps).toFixed(2)}m/s`;
    }
    if(msg.type==='error'){lastError=msg.message}
  };
  socket.onclose=()=>{
    status.textContent='サーバー未接続。バックエンドを起動してください。';
    setTimeout(connect,1800);
  };
}
connect();
function setGaitDebug(on){
  gaitDebugOn=on;
  gaitDebug.setEnabled(on);
  const button=document.querySelector('#gaitDebug');
  if(button) button.textContent=on?'歩行デバッグを隠す':'歩行デバッグを表示';
}
document.querySelector('#gaitDebug')?.addEventListener('click', ()=>setGaitDebug(!gaitDebugOn));
document.querySelector('#gaitLog')?.addEventListener('click', async ()=>{
  const button=document.querySelector('#gaitLog');
  try{
    const response=await fetch('http://127.0.0.1:8765/gait-log');
    if(!response.ok) throw new Error('Gait log is not available');
    const blob=await response.blob();
    const url=URL.createObjectURL(blob);
    const link=document.createElement('a');
    link.href=url;
    link.download='gait-log.json';
    link.click();
    URL.revokeObjectURL(url);
  }catch(err){
    if(button) button.textContent='Log download failed';
    console.error(err);
  }
});
window.addEventListener('keydown', (event)=>{
  if(event.repeat || event.metaKey || event.ctrlKey || event.altKey) return;
  const tag=document.activeElement?.tagName;
  if(tag==='INPUT' || tag==='TEXTAREA') return;
  if(event.key==='d' || event.key==='D') setGaitDebug(!gaitDebugOn);
});
let pointerDownAt=null;
renderer.domElement.addEventListener('wheel', ()=>{ markInput(); }, {passive:true});
renderer.domElement.addEventListener('pointerdown',e=>{
  markInput();
  if(e.button!==0)return;
  pointerDownAt={x:e.clientX,y:e.clientY};
});
renderer.domElement.addEventListener('pointerup',e=>{
  if(e.button!==0||!pointerDownAt||!socket||socket.readyState!==WebSocket.OPEN||!spawn||!sceneReady){
    pointerDownAt=null;
    return;
  }
  const dx=e.clientX-pointerDownAt.x;
  const dy=e.clientY-pointerDownAt.y;
  pointerDownAt=null;
  // ドラッグ開始と誤判定しないよう、短いクリックのみ移動指示にする。
  if(dx*dx+dy*dy>36)return;
  const rect=renderer.domElement.getBoundingClientRect();
  pointer.set(((e.clientX-rect.left)/rect.width)*2-1,-((e.clientY-rect.top)/rect.height)*2+1);
  raycaster.setFromCamera(pointer,camera);
  const picked=raycaster.intersectObjects(usecasePicks, false)[0];
  if(picked){
    const usecase=picked.object.userData.usecase;
    sendArrival(usecase, usecase.x, usecase.z);
    return;
  }
  const hit=raycaster.intersectObject(clickFloor)[0];
  if(!hit)return;
  const near=nearestUsecase(hit.point.x, hit.point.z);
  if(near){
    sendArrival(near, near.x, near.z);
    return;
  }
  sendArrival(openFloor, hit.point.x, hit.point.z);
});
window.addEventListener('resize',()=>{
  camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();renderer.setSize(innerWidth,innerHeight);
});
const clock=new THREE.Clock();
let statusT=0;
const renderIntervals=[];
const renderDurations=[];
let lastRenderAt=null;
let renderReportAt=0;
window.motionBricksPerformance=()=>{
  const summary=values=>{const sorted=[...values].sort((a,b)=>a-b);return {count:sorted.length,p95_ms:sorted[Math.floor(sorted.length*.95)],max_ms:sorted.at(-1)};};
  return {render_interval:summary(renderIntervals),render_duration:summary(renderDurations)};
};
function animate(){
  requestAnimationFrame(animate);
  const renderStarted=performance.now();
  if(lastRenderAt!==null){renderIntervals.push(renderStarted-lastRenderAt);if(renderIntervals.length>4096)renderIntervals.shift();}
  lastRenderAt=renderStarted;
  const delta=Math.min(clock.getDelta(),.1);
  const blend=Math.min(1,(performance.now()-poseStamp)/(1000/60));
  const buffered=playbackBuffer.sample(performance.now());
  if(buffered){
    const visible=buffered.blend>=1?buffered.b:buffered.a;
    if(visible.sequence!==appliedSequence){acceptFrame(visible);appliedSequence=visible.sequence;}
  }
  const pose=buffered?lerpPose(buffered.a.poses,buffered.b.poses,buffered.blend):currentPose?lerpPose(lastPose, currentPose, blend):null;
  observationPose=pose;
  if(vrm){
    if(!sceneReady){
      tryRevealCharacter();
    }else if(owner.capture && currentPose){
      captureSettledIdle();
    }else if(['settled','collect_preparing'].includes(owner.mode) && groundedIdle){
      groundedIdle.update(delta);
      const readyId=`${owner.moveId}:${owner.settleSeq}`;
      if(owner.mode==='settled' && groundedIdle.ready && idleReadySent!==readyId && socket?.readyState===WebSocket.OPEN){
        socket.send(JSON.stringify({type:'upper_idle_ready',move_id:owner.moveId,settle_seq:owner.settleSeq}));
        idleReadySent=readyId;
      }
    }else if(owner.mode==='collecting'){
      if(pose) applyPose(pose);
      adjustStance();
      groundedIdle?.blendUpperToLive((performance.now()-collectBlendStarted)/300);
    }else{
      if(owner.blend && groundedIdle){
        idleExit={pose:groundedIdle, startedAt:performance.now()};
        groundedIdle=null;
        owner={...owner, blend:false};
      }
      const clipsReady=Boolean(idleClip&&idleBreakClip);
      const holdIdle=USE_VRMA_IDLE&&standingStill()&&clipsReady&&!exitBlend;
      if(holdIdle){
        const want=desiredIdleKind();
        if(!handoff?.active){
          if(!stanceApplied && pose) applyPose(pose);
          lastInputAt=performance.now();
          beginHandoff('idle');
        }else if(handoffClip!==want){
          beginHandoff(want);
        }
        handoff?.update(delta);
        adjustStance();
      }else if(handoff?.active||exitBlend){
        if(handoff?.active) beginExitFromVrma();
        if(pose) applyPose(pose);
        if(shouldApplyStance(owner)) adjustStance();
        blendExit();
      }else{
        if(pose) applyPose(pose);
        if(shouldApplyStance(owner)) adjustStance();
        if(idleExit){
          const t=(performance.now()-idleExit.startedAt)/240;
          idleExit.pose.blendToLive(t);
          if(t>=1) idleExit=null;
        }
      }
    }
    if(sceneReady) gaitDebug.update(gait, rig, spawn, FLOOR_TOP);
    vrm.update(delta);
    if(sceneReady && gait?.feet && rig?.rest?.[0]){
      vrm.scene.updateMatrixWorld(true);
      const sample={};
      for(const side of ['left','right']){
        const foot=vrm.humanoid.getRawBoneNode(`${side}Foot`);
        const toe=vrm.humanoid.getRawBoneNode(`${side}Toes`);
        if(foot && toe) sample[side]={foot:foot.getWorldPosition(new THREE.Vector3()).toArray(),toe:toe.getWorldPosition(new THREE.Vector3()).toArray()};
      }
      gait.foot_height_diagnostics=sample.left && sample.right && rig.stop_ground
        ? compareFootHeights(gait.feet, sample, rig.stop_ground.floor_z, FLOOR_TOP) : null;
    }
  }
  if(place) place.tick(clock.elapsedTime);
  if(vrm && look && sceneReady) look.follow(vrm.scene);
  look?.update();
  if(vrm && sceneReady){
    const feet=vrm.scene.position;
    followTarget.set(feet.x, feet.y+lookHeight, feet.z);
    // 手動の回転・ズーム・パンは維持し、ロゼの移動分だけ視点を平行移動する。
    if(followReady){
      const dx=followTarget.x-lastFollow.x;
      const dy=followTarget.y-lastFollow.y;
      const dz=followTarget.z-lastFollow.z;
      if(dx||dy||dz){
        controls.target.x+=dx; controls.target.y+=dy; controls.target.z+=dz;
        camera.position.x+=dx; camera.position.y+=dy; camera.position.z+=dz;
      }
    }
    lastFollow.copy(followTarget);
    followReady=true;
  }
  controls.update();
  renderFrames+=1;
  if(performance.now()-fpsStamp>500){
    fps=renderFrames*1000/(performance.now()-fpsStamp);
    renderFrames=0;
    fpsStamp=performance.now();
  }
  statusT+=delta;
  if(statusT>.5){
    statusT=0;
    const readout=document.querySelector('#gaitReadout');
    if(readout) readout.textContent=formatGaitStatus(gait);
    const bootNote=sceneReady?'表示準備完了':[
      spawn?'spawn確定':'spawn待ち',
      vrm?'VRM済':'VRM待ち',
      rig?'骨格済':'骨格待ち',
      currentPose?'姿勢済':'姿勢待ち',
      restSourceWorld.length?'変換済':'変換待ち',
    ].join(' / ');
    status.textContent=[placeNote, socket?.readyState===1?'MotionBricks 接続中':'サーバー未接続',
      vrm?'ロゼVRM 読み込み済み':'ロゼVRM 未読み込み',
      bootNote,
      exitBlend?'待機から歩行へ':handoff?.active?`待機 ${handoffClip}.vrma`:'',
      formatGaitStatus(gait),
      `表示 ${fps.toFixed(0)} fps`,
      generateMs!=null?`生成 ${generateMs.toFixed(0)} ms`:'',
      clickLatency!=null?`クリックから姿勢更新 ${clickLatency.toFixed(0)} ms`:'',
      `d3-mini: ${lastDecision}`,currentMotionState,lastStage,lastError].filter(Boolean).join('\n');
  }
  renderer.render(scene,camera);
  renderDurations.push(performance.now()-renderStarted);if(renderDurations.length>4096)renderDurations.shift();
  if(sceneReady && performance.now()-renderReportAt>=5000){
    renderReportAt=performance.now();
    fetch('http://127.0.0.1:8765/performance/render',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({...window.motionBricksPerformance(),scene_ready:true})}).catch(()=>{});
  }
  observationFrame+=1;
}
animate();
