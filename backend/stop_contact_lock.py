"""F001接続の接地区間を公式IK補正器へ渡す。"""
import numpy as np
from final_stop import contact_points, foot_points


def floor_targets(pose, parents, names, ground):
    feet = contact_points(foot_points(pose, parents, names), ground)
    targets = {}
    for side, points in feet.items():
        correction = ground['floor_z'] - .01 - min(p[2] for p in points.values())
        if correction > 0:
            anchor = np.array(pose, copy=True)
            anchor[0, 2] += correction
            targets[side] = anchor
    return targets


class StopContactLock:
    def __init__(self, original, contacts, parents, names, ground):
        self.parents, self.names, self.ground = parents, names, ground
        self.anchors = {}
        self.releasing = {}
        self.update(original, contacts)

    def update(self, pose, contacts):
        feet = contact_points(foot_points(pose, self.parents, self.names), self.ground)
        for side, offset in (('left', 0), ('right', 2)):
            planted = max(contacts[offset:offset+2]) >= .5 and min(p[2] for p in feet[side].values()) <= self.ground['floor_z'] + .02
            if planted:
                self.releasing.pop(side, None)
                self.anchors.setdefault(side, np.array(pose, copy=True))
            else:
                anchor = self.anchors.pop(side, None)
                if anchor is not None:
                    self.releasing[side] = (anchor, 1.)
        for side, (anchor, weight) in list(self.releasing.items()):
            if weight > .25:
                self.releasing[side] = (anchor, weight - .25)
            else:
                self.releasing.pop(side)
        return self.anchors

    def apply(self, character, rt):
        wp = rt['wp']
        corrector = character._target_pose_ik_corrector
        pose = character.current_pose.numpy().reshape((-1, 7))
        contacts = character.current_foot_contacts.numpy().reshape(-1)
        self.update(pose, contacts)
        constraints = {side: (anchor, 1.) for side, anchor in self.anchors.items()}
        constraints.update(self.releasing)
        for side, (anchor, weight) in constraints.items():
            mask = rt['IKPin'].LEFT_FOOT if side == 'left' else rt['IKPin'].RIGHT_FOOT
            corrector.capture_pins(wp.array(anchor.astype(np.float32), dtype=wp.transform, device=character.engine.device),
                                   mask, stream=character.engine.stream)
            corrector.apply(character.current_pose, weight, stream=character.engine.stream)
        pose = character.current_pose.numpy().reshape((-1, 7))
        for side, anchor in floor_targets(pose, self.parents, self.names, self.ground).items():
            mask = rt['IKPin'].LEFT_FOOT if side == 'left' else rt['IKPin'].RIGHT_FOOT
            corrector.capture_pins(wp.array(anchor.astype(np.float32), dtype=wp.transform, device=character.engine.device),
                                   mask, stream=character.engine.stream)
            corrector.apply(character.current_pose, 1., stream=character.engine.stream)
        corrector.clear_pins()
