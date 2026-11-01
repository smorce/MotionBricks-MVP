import * as THREE from 'three';
import {runtimeJointToThree} from './coords.js';
import {markerColor} from './gaitView.js';

function sphere(color) {
  const mesh = new THREE.Mesh(
    new THREE.SphereGeometry(0.035, 12, 10),
    new THREE.MeshBasicMaterial({color, depthTest: false}),
  );
  mesh.renderOrder = 4;
  return mesh;
}

/** 接地は緑、遊脚は赤。滑っている足の軌跡を足元に残す。 */
export class GaitDebug {
  constructor(scene) {
    this.enabled = false;
    this.left = sphere(0x3ddc84);
    this.right = sphere(0xff4d4d);
    this.trail = new THREE.Line(
      new THREE.BufferGeometry(),
      new THREE.LineBasicMaterial({color: 0xffcc66, depthTest: false}),
    );
    this.trail.frustumCulled = false;
    this.trail.renderOrder = 4;
    this.points = [];
    scene.add(this.left, this.right, this.trail);
    this.setEnabled(false);
  }

  setEnabled(on) {
    this.enabled = Boolean(on);
    this.left.visible = this.enabled;
    this.right.visible = this.enabled;
    this.trail.visible = this.enabled && this.points.length > 1;
    if (!this.enabled) this.points = [];
  }

  update(gait, rig, spawn, floorTop) {
    if (!this.enabled || !gait?.feet || !rig?.rest?.[0]) return;
    const rest = {x: rig.rest[0][0], y: rig.rest[0][1], z: rig.rest[0][2]};
    const origin = {x: spawn?.x || 0, z: spawn?.z || 0};
    this._place(this.left, gait.feet.left, rest, origin, floorTop);
    this._place(this.right, gait.feet.right, rest, origin, floorTop);
    this.left.material.color.setHex(markerColor(Boolean(gait.feet.left.planted)));
    this.right.material.color.setHex(markerColor(Boolean(gait.feet.right.planted)));
    const slip = Math.max(Number(gait.left_slip_m) || 0, Number(gait.right_slip_m) || 0);
    if (slip > 0.005) {
      const foot = (Number(gait.left_slip_m) || 0) >= (Number(gait.right_slip_m) || 0) ? gait.feet.left : gait.feet.right;
      const point = runtimeJointToThree(foot, rest, origin, floorTop);
      this.points.push(new THREE.Vector3(point.x, point.y + 0.02, point.z));
      if (this.points.length > 120) this.points.shift();
      this.trail.geometry.dispose();
      this.trail.geometry = new THREE.BufferGeometry().setFromPoints(this.points);
      this.trail.visible = this.points.length > 1;
    }
  }

  _place(mesh, foot, rest, origin, floorTop) {
    const point = runtimeJointToThree(foot, rest, origin, floorTop);
    mesh.position.set(point.x, point.y, point.z);
  }
}
