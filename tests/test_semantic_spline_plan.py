import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = ROOT / "coa_tools2"
sys.path.insert(0, str(ADDON_ROOT))

from rig_control.blender.semantic_spline import (  # noqa: E402
    SplineChainArtifacts,
    SplineHookBinding,
    semantic_spline_name_plan,
)


class SemanticSplinePlanTests(unittest.TestCase):
    def setUp(self):
        self.component = SimpleNamespace(
            component_uuid="component-aaaa-bbbb-cccc",
            semantic_id="Hair Tail",
        )
        self.stage = SimpleNamespace(
            stage_uuid="stage-1111-2222-3333",
            semantic_id="Hair Flow",
        )

    def test_plan_is_stable_and_point_ordered(self):
        first = semantic_spline_name_plan(
            self.component,
            self.stage,
            source_count=5,
            control_count=3,
        )
        second = semantic_spline_name_plan(
            self.component,
            self.stage,
            source_count=5,
            control_count=3,
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first.mechanism_bones), 5)
        self.assertEqual(len(first.control_bones), 3)
        self.assertEqual(len(first.projected_joints), 6)
        self.assertEqual(len(first.presentation_bones), 5)
        self.assertTrue(first.art_frame.startswith("MCH_"))
        self.assertTrue(first.hook_modifiers[0].endswith("Hook_00"))
        self.assertTrue(first.hook_modifiers[2].endswith("Hook_02"))

    def test_stage_uuid_separates_curve_and_hook_names(self):
        other = SimpleNamespace(
            stage_uuid="stage-9999-8888-7777",
            semantic_id=self.stage.semantic_id,
        )
        left = semantic_spline_name_plan(
            self.component,
            self.stage,
            source_count=2,
            control_count=2,
        )
        right = semantic_spline_name_plan(
            self.component,
            other,
            source_count=2,
            control_count=2,
        )
        self.assertNotEqual(left.curve_object, right.curve_object)
        self.assertNotEqual(left.hook_modifiers, right.hook_modifiers)

    def test_invalid_counts_and_uuids_are_rejected(self):
        with self.assertRaises(ValueError):
            semantic_spline_name_plan(
                self.component,
                self.stage,
                source_count=1,
                control_count=3,
            )
        with self.assertRaises(ValueError):
            semantic_spline_name_plan(
                self.component,
                self.stage,
                source_count=3,
                control_count=1,
            )
        with self.assertRaises(ValueError):
            semantic_spline_name_plan(
                SimpleNamespace(component_uuid=""),
                self.stage,
                source_count=3,
                control_count=3,
            )

    def test_result_preserves_curve_point_hook_mapping(self):
        bindings = (
            SplineHookBinding(0, "Hook_00", "CTRL_00", True),
            SplineHookBinding(1, "Hook_01", "CTRL_01", False),
        )
        result = SplineChainArtifacts(
            primary_control_bone="CTRL_01",
            control_bones=("CTRL_00", "CTRL_01"),
            mechanism_bones=("MCH_00", "MCH_01"),
            curve_object="CRV_Test",
            source_bones=("Source_00", "Source_01"),
            hook_bindings=bindings,
            projected_joint_bones=("P_00", "P_01", "P_02"),
            presentation_bones=("ART_00", "ART_01"),
            art_frame_bone="ART_FRAME",
            art_frame_owned=True,
        )
        self.assertEqual(result.curve, "CRV_Test")
        self.assertEqual(result.hook_modifiers, ("Hook_00", "Hook_01"))
        self.assertEqual(result.hook_bones, ("CTRL_00", "CTRL_01"))
        self.assertEqual(
            result.generated_bones,
            (
                "CTRL_00",
                "CTRL_01",
                "MCH_00",
                "MCH_01",
                "P_00",
                "P_01",
                "P_02",
                "ART_00",
                "ART_01",
                "ART_FRAME",
            ),
        )


if __name__ == "__main__":
    unittest.main()
