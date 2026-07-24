import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = ROOT / "coa_tools2"
sys.path.insert(0, str(ADDON_ROOT))

from rig_control.schema import (  # noqa: E402
    BindingSpec,
    ControlAxis,
    ControlSpec,
    ControlType,
    TargetKind,
    WidgetLayout,
    WidgetSpec,
    dial_point,
    dial_rest_angle,
)
from rig_control.validation import (  # noqa: E402
    find_duplicate_ids,
    validate_binding_spec,
    validate_control_spec,
    validate_widget_spec,
)
from rig_control.planning import ArtifactAction, plan_artifact  # noqa: E402


class RigControlSchemaTests(unittest.TestCase):
    def test_widget_spec_round_trip(self):
        spec = WidgetSpec(
            widget_uuid="widget-1",
            layout=WidgetLayout.LINEAR,
            width=5.0,
            stroke_radius=0.05,
        )
        self.assertEqual(spec, WidgetSpec.from_dict(spec.to_dict()))

    def test_control_spec_round_trip(self):
        spec = ControlSpec(
            control_uuid="control-1",
            semantic_id="face.smile",
            display_name="Smile",
            control_type=ControlType.SLIDER_1D,
            axis=ControlAxis.X,
            control_bone="CTRL_face_smile",
            display_bone="DISP_face_smile",
            widget_spec_id="widget-1",
        )
        self.assertEqual(spec, ControlSpec.from_dict(spec.to_dict()))

    def test_dial_helpers_use_top_as_zero_and_clamp_rest_to_arc(self):
        self.assertEqual(0.0, dial_rest_angle(-1.0, 1.0))
        self.assertEqual(0.5, dial_rest_angle(0.5, 1.0))
        x, y = dial_point(2.0, math.pi * 0.5)
        self.assertAlmostEqual(-2.0, x)
        self.assertAlmostEqual(0.0, y)

    def test_binding_spec_round_trip(self):
        spec = BindingSpec(
            binding_uuid="binding-1",
            control_uuid="control-1",
            source_component=ControlAxis.X,
            target_kind=TargetKind.SHAPE_KEY_VALUE,
            target_object_name="Face",
            target_name="Smile",
        )
        self.assertEqual(spec, BindingSpec.from_dict(spec.to_dict()))

    def test_invalid_specs_produce_structured_issues(self):
        widget = WidgetSpec(
            widget_uuid="",
            layout=WidgetLayout.LINEAR,
            width=0.0,
        )
        control = ControlSpec(
            control_uuid="",
            semantic_id="",
            display_name="",
            control_type=ControlType.SLIDER_1D,
            axis=ControlAxis.X,
            control_bone="",
            display_bone="",
            widget_spec_id="",
            value_min=(1.0, 0.0),
            value_max=(1.0, 0.0),
        )
        binding = BindingSpec(
            binding_uuid="",
            control_uuid="",
            source_component=ControlAxis.X,
            target_kind=TargetKind.SHAPE_KEY_VALUE,
            target_object_name="",
            target_name="",
            input_min=1.0,
            input_max=1.0,
        )
        self.assertTrue(validate_widget_spec(widget))
        self.assertTrue(validate_control_spec(control))
        self.assertTrue(validate_binding_spec(binding))

    def test_duplicate_ids_are_sorted_and_unique(self):
        issues = find_duplicate_ids(["b", "a", "b", "a", "a"], "control")
        self.assertEqual(["a", "b"], [issue.subject_id for issue in issues])

    def test_artifact_plan_distinguishes_create_update_keep_and_conflict(self):
        self.assertEqual(
            ArtifactAction.CREATE,
            plan_artifact("bone", "a", exists=False, owned=False, matches=False).action,
        )
        self.assertEqual(
            ArtifactAction.CONFLICT,
            plan_artifact("bone", "a", exists=True, owned=False, matches=False).action,
        )
        self.assertEqual(
            ArtifactAction.KEEP,
            plan_artifact("bone", "a", exists=True, owned=True, matches=True).action,
        )
        self.assertEqual(
            ArtifactAction.UPDATE_OWNED,
            plan_artifact("bone", "a", exists=True, owned=True, matches=False).action,
        )


if __name__ == "__main__":
    unittest.main()
