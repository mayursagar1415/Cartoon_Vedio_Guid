"""Tests for 2-bone IK solver, walk cycle continuity, and Action Library playback."""

import math
from pathlib import Path
import unittest

from flat_puppet.core.actions import ActionLibrary
from flat_puppet.core.kinematics import articulated_leg_pose, rotate_point_pil, solve_2bone_ik


ROOT = Path(__file__).resolve().parent.parent


class TestKinematicsAndActions(unittest.TestCase):
    def test_2bone_ik_reaches_target(self) -> None:
        root = (100.0, 100.0)
        elbow_rest = (100.0, 160.0)
        wrist_rest = (100.0, 220.0)
        target = (150.0, 170.0)

        upper_ang, lower_rel = solve_2bone_ik(root, elbow_rest, wrist_rest, target, bend_sign=1)
        new_elbow = rotate_point_pil(elbow_rest, root, upper_ang)
        # Rotate wrist around original elbow by total angle, then translate by elbow delta
        rotated_wrist = rotate_point_pil(wrist_rest, elbow_rest, upper_ang + lower_rel)
        dx = new_elbow[0] - elbow_rest[0]
        dy = new_elbow[1] - elbow_rest[1]
        final_wrist = (rotated_wrist[0] + dx, rotated_wrist[1] + dy)

        self.assertAlmostEqual(final_wrist[0], target[0], places=1)
        self.assertAlmostEqual(final_wrist[1], target[1], places=1)

    def test_walk_cycle_action_loops_smoothly(self) -> None:
        lib = ActionLibrary(ROOT / "configs" / "actions")
        walk = lib.get("walk_cycle")
        self.assertAlmostEqual(
            walk.eval_normalized("leg_near_thigh", 0.0),
            walk.eval_normalized("leg_near_thigh", 0.9999),
            delta=0.1,
        )
        self.assertLess(walk.eval_normalized("leg_near_knee", 0.775), -10.0)

    def test_articulated_leg_pose_continuity(self) -> None:
        a0, _, l0 = articulated_leg_pose(0.5499)
        a1, _, l1 = articulated_leg_pose(0.5501)
        self.assertAlmostEqual(a0, a1, delta=0.1)
        self.assertAlmostEqual(l0, l1, delta=0.2)
