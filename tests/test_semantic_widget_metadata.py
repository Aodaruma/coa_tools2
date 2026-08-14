import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = ROOT / "coa_tools2"
sys.path.insert(0, str(ADDON_ROOT))

from rig_control.blender.semantic_widgets import (  # noqa: E402
    SEMANTIC_WIDGET_FAMILIES,
    SemanticWidgetShape,
    expected_semantic_widget_node_group_names,
    normalize_semantic_widget_parameters,
    semantic_widget_family,
    semantic_widget_parameter_defaults,
)


class SemanticWidgetMetadataTests(unittest.TestCase):
    def test_all_shapes_have_distinct_groups_and_edge_loop_contract(self):
        self.assertEqual(len(SemanticWidgetShape), 10)
        self.assertEqual(len(SEMANTIC_WIDGET_FAMILIES), 10)
        names = expected_semantic_widget_node_group_names()
        self.assertEqual(len(names), 10)
        for family in SEMANTIC_WIDGET_FAMILIES.values():
            self.assertEqual(family.topology, "SINGLE_CLOSED_EDGE_LOOP")
            self.assertEqual(family.expected_faces, 0)

    def test_spatial_shapes_default_to_high_resolution(self):
        for shape in (
            SemanticWidgetShape.CYLINDER_ARROW_1D,
            SemanticWidgetShape.SPHERE_ARROW_2D,
        ):
            defaults = semantic_widget_parameter_defaults(shape)
            self.assertEqual(defaults["Segments"], 96)
            segments = next(
                parameter
                for parameter in semantic_widget_family(shape).parameters
                if parameter.name == "Segments"
            )
            self.assertEqual(segments.maximum, 256)

    def test_sector_interface_matches_presentation_spec(self):
        family = semantic_widget_family(SemanticWidgetShape.SECTOR)
        self.assertEqual(
            tuple(parameter.name for parameter in family.parameters),
            (
                "Inner Radius",
                "Outer Radius",
                "Start Angle",
                "Sweep Angle",
                "Segments",
            ),
        )
        self.assertEqual(
            semantic_widget_parameter_defaults(SemanticWidgetShape.SECTOR),
            {
                "Inner Radius": 0.0,
                "Outer Radius": 1.0,
                "Start Angle": 0.0,
                "Sweep Angle": math.pi * 0.5,
                "Segments": 96,
            },
        )
        segments = family.parameters[-1]
        self.assertEqual((segments.minimum, segments.maximum), (3, 256))

    def test_sector_value_normalization_preserves_signed_sweep(self):
        values = normalize_semantic_widget_parameters(
            SemanticWidgetShape.SECTOR,
            {
                "Inner Radius": -2.0,
                "Outer Radius": 2000.0,
                "Start Angle": -0.25,
                "Sweep Angle": -math.pi,
                "Segments": 999,
            },
        )
        self.assertEqual(values["Inner Radius"], 0.0)
        self.assertEqual(values["Outer Radius"], 1000.0)
        self.assertEqual(values["Start Angle"], -0.25)
        self.assertEqual(values["Sweep Angle"], -math.pi)
        self.assertEqual(values["Segments"], 256)


if __name__ == "__main__":
    unittest.main()
