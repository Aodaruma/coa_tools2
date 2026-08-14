import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = ROOT / "coa_tools2"
sys.path.insert(0, str(ADDON_ROOT))

from rig_control.blender.semantic_artifacts import (  # noqa: E402
    ProjectedIKArtifacts,
    ProjectedTransformArtifacts,
    semantic_artifact_name_plan,
    semantic_stage_role,
)


class SemanticArtifactPlanTests(unittest.TestCase):
    def setUp(self):
        self.component = SimpleNamespace(
            component_uuid="component-a",
            semantic_id="Left Arm",
        )
        self.stage = SimpleNamespace(
            stage_uuid="12345678-abcd-ef00-1111-222233334444",
            semantic_id="Arm Reach",
        )

    def test_roles_are_scoped_by_full_stage_uuid(self):
        role = semantic_stage_role(self.stage.stage_uuid, "art_frame")
        self.assertEqual(
            role,
            "semantic:12345678-abcd-ef00-1111-222233334444:art_frame",
        )

    def test_name_plan_is_stable_and_allocates_joint_tail(self):
        first = semantic_artifact_name_plan(
            self.component,
            self.stage,
            chain_size=3,
        )
        second = semantic_artifact_name_plan(
            self.component,
            self.stage,
            chain_size=3,
        )
        self.assertEqual(first, second)
        self.assertIn("Arm_Reach_12345678", first.art_frame)
        self.assertEqual(len(first.mechanism_bones), 3)
        self.assertEqual(len(first.presentation_bones), 3)
        self.assertEqual(len(first.projected_joints), 4)
        self.assertEqual(len(set(first.projected_joints)), 4)

    def test_distinct_stage_uuids_do_not_share_names_or_roles(self):
        other = SimpleNamespace(
            stage_uuid="87654321-abcd-ef00-1111-222233334444",
            semantic_id=self.stage.semantic_id,
        )
        left = semantic_artifact_name_plan(self.component, self.stage, chain_size=2)
        right = semantic_artifact_name_plan(self.component, other, chain_size=2)
        self.assertNotEqual(left.control, right.control)
        self.assertNotEqual(
            semantic_stage_role(self.stage.stage_uuid, "control_bone"),
            semantic_stage_role(other.stage_uuid, "control_bone"),
        )

    def test_missing_stage_uuid_is_rejected(self):
        with self.assertRaises(ValueError):
            semantic_stage_role("", "control_bone")
        with self.assertRaises(ValueError):
            semantic_artifact_name_plan(
                self.component,
                SimpleNamespace(stage_uuid="", semantic_id="bad"),
            )

    def test_result_objects_expose_primary_and_generated_bones(self):
        frames = ProjectedTransformArtifacts("ART", "DISPLAY", "CONTROL")
        result = ProjectedIKArtifacts(
            frames=frames,
            mechanism_bones=("IK_A", "IK_B"),
            projected_joint_bones=("P0", "P1", "P2"),
            presentation_bones=("D0", "D1"),
            source_bones=("SRC_A", "SRC_B"),
            pole_bone="POLE",
        )
        self.assertEqual(result.primary_control_bone, "CONTROL")
        self.assertEqual(frames.primary_control_bone, "CONTROL")
        self.assertEqual(result.generated_bones[0:3], frames.generated_bones)
        self.assertEqual(result.generated_bones[-1], "POLE")


if __name__ == "__main__":
    unittest.main()
