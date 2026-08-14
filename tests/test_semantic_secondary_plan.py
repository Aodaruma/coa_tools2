import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = ROOT / "coa_tools2"
sys.path.insert(0, str(ADDON_ROOT))

from rig_control.blender.semantic_secondary import (  # noqa: E402
    _source_names,
    secondary_motion_name_plan,
)


class _Reference:
    def __init__(self, bone_name):
        self.bone_name = bone_name


class _Owner:
    def __init__(self, source_bones=()):
        self.source_bones = source_bones


class SemanticSecondaryPlanTests(unittest.TestCase):
    def test_name_plan_is_ordered_stable_and_bounded(self):
        first = secondary_motion_name_plan(
            "component-123456789",
            "stage-abcdefghijk",
            ("Spline Root", "Spline/Middle", "Spline Tip"),
        )
        second = secondary_motion_name_plan(
            "component-123456789",
            "stage-abcdefghijk",
            ("Spline Root", "Spline/Middle", "Spline Tip"),
        )
        self.assertEqual(first, second)
        self.assertEqual(3, len(first.output_bones))
        self.assertTrue(all(len(name) <= 63 for name in first.output_bones))
        self.assertIn("Spline_Root", first.output_bones[0])
        self.assertIn("Spline_Tip", first.output_bones[2])

    def test_source_order_prefers_explicit_then_default_then_component(self):
        component = _Owner((_Reference("component.a"), _Reference("component.b")))
        explicit = _Owner((_Reference("stage.a"), _Reference("stage.b")))
        empty = _Owner(())
        self.assertEqual(
            ("stage.a", "stage.b"),
            _source_names(component, explicit, ("default.a", "default.b")),
        )
        self.assertEqual(
            ("default.a", "default.b"),
            _source_names(component, empty, ("default.a", "default.b")),
        )
        self.assertEqual(
            ("component.a", "component.b"),
            _source_names(component, empty),
        )


if __name__ == "__main__":
    unittest.main()
