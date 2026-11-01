import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {VRMLoaderPlugin, VRMUtils} from '@pixiv/three-vrm';

const status = document.querySelector('#status');
const background = document.querySelector('#background');
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(42, window.innerWidth/window.innerHeight, .1, 150);
camera.position.set(0, 4.2, 8.5);
camera.lookAt(0, 1, 0);
const renderer = new THREE.WebGLRenderer({antialias:true, alpha:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));
renderer.setSize(window.innerWidth,window.innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.insertBefore(renderer.domElement, document.querySelector('#toolbar'));
scene.add(new THREE.HemisphereLight(0xffffff, 0x596b7a, 2));
const sun = new THREE.DirectionalLight(0xffffff, 2.0);
sun.position.set(-2,6,3);
scene.add(sun);
const grid = new THREE.GridHelper(30,30,0x6f8cbb,0x334157);
scene.add(grid);
const clickFloor = new THREE.Mesh(new THREE.PlaneGeometry(200,200), new THREE.MeshBasicMaterial({transparent:true,opacity:0,depthWrite:false}));
clickFloor.rotation.x=-Math.PI/2;
scene.add(clickFloor);
const marker = new THREE.Mesh(new THREE.RingGeometry(.12,.17,40), new THREE.MeshBasicMaterial({color:0x34ffab,side:THREE.DoubleSide}));
marker.rotation.x=-Math.PI/2;
marker.position.y=.015;
marker.visible=false;
scene.add(marker);
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
let vrm=null;
let rig=null;
let currentPose=null;
let lastPose=null;
let socket=null;
let lastDecision='—';
let lastStage='';
let currentMotionState='';
let lastError='';

const MAP = {
  Hips:'hips', Spine1:'spine', Spine2:'chest', Chest:'upperChest',
  Neck1:'neck', Neck2:'neck', Head:'head',
  LeftShoulder:'leftShoulder', LeftArm:'leftUpperArm', LeftForeArm:'leftLowerArm', LeftHand:'leftHand',
  RightShoulder:'rightShoulder', RightArm:'rightUpperArm', RightForeArm:'rightLowerArm', RightHand:'rightHand',
  LeftLeg:'leftUpperLeg', LeftShin:'leftLowerLeg', LeftFoot:'leftFoot', LeftToeBase:'leftToes',
  RightLeg:'rightUpperLeg', RightShin:'rightLowerLeg', RightFoot:'rightFoot', RightToeBase:'rightToes',
};
// World basis conversion: NVIDIA demos Z-up => Three.js Y-up.
const basis=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1,0,0),-Math.PI/2);
const basisInv=basis.clone().invert();
const q=(arr)=>new THREE.Quaternion(arr[3],arr[4],arr[5],arr[6]);
function toThreeWorldQuat(v){return basis.clone().multiply(v).multiply(basisInv)}
function calcWorldQuats(pose,parents){
  const out=[];
  for(let i=0;i<pose.length;i++){
    const local=q(pose[i]);
    out.push(parents[i] < 0 ? local : out[parents[i]].clone().multiply(local));
  }
  return out;
}
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
function applyPose(pose){
  if(!rig||!vrm||!restSourceWorld.length||pose.length!==rig.joint_names.length)return;
  // Roze's scene origin follows the source hips ground position; don't add hips height twice.
  vrm.scene.position.set(pose[0][0]-rig.rest[0][0],pose[0][2]-rig.rest[0][2],-pose[0][1]+rig.rest[0][1]);
  vrm.scene.updateMatrixWorld(true);
  const world=calcWorldQuats(pose,rig.parents);
  const used=new Set();
  for(let i=0;i<world.length;i++){
    const bone=MAP[rig.joint_names[i]];
    if(!bone||used.has(bone)||!restDestWorld.has(bone))continue;
    used.add(bone);
    const node=vrm.humanoid.getNormalizedBoneNode(bone);
    if(!node)continue;
    const delta=world[i].clone().multiply(restSourceWorld[i].clone().invert());
    const desired=toThreeWorldQuat(delta).multiply(restDestWorld.get(bone));
    const parentWorld=node.parent.getWorldQuaternion(new THREE.Quaternion());
    node.quaternion.copy(parentWorld.invert().multiply(desired));
    node.updateMatrixWorld(true);
  }
}
const loader=new GLTFLoader();
loader.register(parser=>new VRMLoaderPlugin(parser));
document.querySelector('#vrmFile').addEventListener('change',async e=>{
  const file=e.target.files?.[0];
  if(!file)return;
  const url=URL.createObjectURL(file);
  try{
    const gltf=await loader.loadAsync(url);
    if(vrm){scene.remove(vrm.scene);VRMUtils.deepDispose(vrm.scene)}
    vrm=gltf.userData.vrm;
    if(!vrm)throw new Error('VRM model not found');
    VRMUtils.rotateVRM0(vrm);
    scene.add(vrm.scene);
    initializeRetarget();
    status.textContent='VRM読み込み済み。クリックで移動。';
  }catch(err){status.textContent=`VRMエラー: ${err.message}`}
  finally{URL.revokeObjectURL(url)}
});
document.querySelector('#backgroundFile').addEventListener('change',e=>{
  const file=e.target.files?.[0];
  if(!file)return;
  const url=URL.createObjectURL(file);
  background.style.backgroundImage=`url("${url}")`;
  grid.visible=false;
});
function connect(){
  socket=new WebSocket('ws://127.0.0.1:8765/ws');
  socket.onopen=()=>{status.textContent='接続済み。VRMを読み込んでください。'};
  socket.onmessage=(e)=>{
    const msg=JSON.parse(e.data);
    if(msg.type==='rig'){rig=msg;initializeRetarget()}
    if(msg.type==='frame'){lastPose=currentPose;currentPose=msg.poses}
    if(msg.type==='decision'){lastDecision=`${msg.pose_id} ${msg.name} (${msg.backend} / confidence ${msg.confidence.toFixed(2)})`}
    if(msg.type==='arrived'){lastStage=`停止完了: ${msg.pose_id} / SOMA姿勢 ${msg.pose_applied ? '適用済' : '未変換（公式idle）'} / 目標誤差 ${msg.arrival_error_m?.toFixed(2) ?? '—'}m`}
    if(msg.type==='stop_triggered'){lastStage=`減速→公式Idle遷移開始: 残り${msg.distance_m.toFixed(2)}m / 速度${msg.speed_mps.toFixed(2)}m/s`}
    if(msg.type==='motion_state'){currentMotionState=`停止制御: ${msg.phase} / 公式: ${msg.official_state} / 速度 ${msg.actual_speed_mps.toFixed(2)}m/s`}
    if(msg.type==='error'){lastError=msg.message}
  };
  socket.onclose=()=>{
    status.textContent='サーバー未接続。バックエンドを起動してください。';
    setTimeout(connect,1800);
  };
}
connect();
renderer.domElement.addEventListener('pointerdown',e=>{
  if(e.button!==0||!socket||socket.readyState!==WebSocket.OPEN)return;
  const rect=renderer.domElement.getBoundingClientRect();
  pointer.set(((e.clientX-rect.left)/rect.width)*2-1,-((e.clientY-rect.top)/rect.height)*2+1);
  raycaster.setFromCamera(pointer,camera);
  const hit=raycaster.intersectObject(clickFloor)[0];
  if(!hit)return;
  marker.position.x=hit.point.x;
  marker.position.z=hit.point.z;
  marker.visible=true;
  // Frontend coordinate Three(x,z) -> NVIDIA runtime(x,-z) in Z-up ground plane.
  socket.send(JSON.stringify({type:'move',x:hit.point.x,y:-hit.point.z,
    zone:document.querySelector('#zone').value,intent:document.querySelector('#intent').value}));
});
window.addEventListener('resize',()=>{
  camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();renderer.setSize(innerWidth,innerHeight);
});
const clock=new THREE.Clock();
let statusT=0;
function animate(){
  requestAnimationFrame(animate);
  const delta=Math.min(clock.getDelta(),.1);
  if(currentPose&&vrm){applyPose(currentPose);vrm.update(delta)}
  statusT+=delta;
  if(statusT>.5){
    statusT=0;
    status.textContent=[socket?.readyState===1?'MotionBricks 接続中':'サーバー未接続',
      vrm?'ロゼVRM 読み込み済み':'ロゼVRM 未読み込み',
      `Jev: ${lastDecision}`, currentMotionState, lastStage,lastError].filter(Boolean).join('\n');
  }
  renderer.render(scene,camera);
}
animate();
