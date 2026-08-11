import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = ROOT / "coa_tools2"
sys.path.insert(0, str(ADDON_ROOT))

from rig_control.pose_field import (  # noqa: E402
    PoseFieldDimension,
    PoseFieldSample,
    PoseFieldSpec,
    PoseOutputSnapshot,
    evaluate_pose_field,
    validate_pose_field,
)


def snapshot(value, slot="A"):
    return PoseOutputSnapshot.from_values(
        {"shape": value, "bone.location": (value, value * 2.0, 0.0)},
        {"slot": slot},
    )


class PoseFieldTests(unittest.TestCase):
    def test_five_dimensional_schema_round_trip(self):
        spec = PoseFieldSpec(
            "field.face",
            "face.direction.expression",
            tuple(PoseFieldDimension(f"input.{index}", index + 1.0) for index in range(5)),
            (
                PoseFieldSample(
                    "sample.neutral",
                    (0.0, 0.0, 0.0, 0.0, 0.0),
                    snapshot(0.0),
                ),
                PoseFieldSample(
                    "sample.pose",
                    (1.0, 2.0, 3.0, 4.0, 5.0),
                    snapshot(1.0, "B"),
                ),
            ),
        )
        self.assertEqual(spec, PoseFieldSpec.from_dict(spec.to_dict()))
        self.assertEqual((), validate_pose_field(spec))

    def test_exact_sample_is_reproduced_without_blending(self):
        spec = PoseFieldSpec(
            "field.exact",
            "exact",
            (PoseFieldDimension("x"), PoseFieldDimension("y"), PoseFieldDimension("z")),
            (
                PoseFieldSample("a", (0.0, 0.0, 0.0), snapshot(0.0, "A")),
                PoseFieldSample("b", (1.0, 2.0, 3.0), snapshot(0.75, "B")),
            ),
            kernel_radius=0.1,
            exact_epsilon=0.0,
        )
        result = evaluate_pose_field(spec, {"x": 1.0, "y": 2.0, "z": 3.0})
        self.assertEqual("b", result.exact_sample_uuid)
        self.assertEqual(snapshot(0.75, "B"), result.outputs)
        self.assertFalse(result.used_nearest_fallback)

    def test_normalized_local_rbf_blends_continuous_outputs(self):
        spec = PoseFieldSpec(
            "field.blend",
            "blend",
            (
                PoseFieldDimension("x"),
                PoseFieldDimension("y"),
                PoseFieldDimension("z"),
            ),
            (
                PoseFieldSample("left", (0.0, 0.0, 0.0), snapshot(0.0, "LEFT")),
                PoseFieldSample("right", (1.0, 0.0, 0.0), snapshot(1.0, "RIGHT")),
            ),
            kernel_radius=2.0,
        )
        result = evaluate_pose_field(spec, (0.5, 0.0, 0.0))
        self.assertAlmostEqual(1.0, sum(item.weight for item in result.sample_weights))
        self.assertAlmostEqual(0.5, result.outputs.continuous_value("shape"))
        self.assertEqual((0.5, 1.0, 0.0), result.outputs.continuous_value("bone.location"))
        self.assertEqual("LEFT", result.outputs.discrete_value("slot"))

    def test_discrete_output_uses_nearest_sample_while_continuous_blends(self):
        spec = PoseFieldSpec(
            "field.discrete",
            "discrete",
            (PoseFieldDimension("x"),),
            (
                PoseFieldSample("a", (0.0,), snapshot(0.0, "A")),
                PoseFieldSample("b", (1.0,), snapshot(1.0, "B")),
            ),
            kernel_radius=2.0,
        )
        result = evaluate_pose_field(spec, (0.75,))
        self.assertGreater(result.outputs.continuous_value("shape"), 0.5)
        self.assertEqual("B", result.outputs.discrete_value("slot"))

    def test_channel_scale_changes_distance_and_interpolation(self):
        samples = (
            PoseFieldSample("a", (0.0, 0.0), snapshot(0.0)),
            PoseFieldSample("b", (10.0, 1.0), snapshot(1.0)),
        )
        unscaled = PoseFieldSpec(
            "field.unscaled",
            "unscaled",
            (PoseFieldDimension("x"), PoseFieldDimension("y")),
            samples,
            kernel_radius=20.0,
        )
        scaled = PoseFieldSpec(
            "field.scaled",
            "scaled",
            (PoseFieldDimension("x", 100.0), PoseFieldDimension("y")),
            samples,
            kernel_radius=20.0,
        )
        unscaled_value = evaluate_pose_field(unscaled, (6.0, 0.0)).outputs.continuous_value("shape")
        scaled_value = evaluate_pose_field(scaled, (6.0, 0.0)).outputs.continuous_value("shape")
        self.assertGreater(unscaled_value, 0.5)
        self.assertLess(scaled_value, 0.5)

    def test_outside_compact_kernel_uses_nearest_fallback(self):
        spec = PoseFieldSpec(
            "field.fallback",
            "fallback",
            (PoseFieldDimension("x"), PoseFieldDimension("y"), PoseFieldDimension("z")),
            (
                PoseFieldSample("near", (0.0, 0.0, 0.0), snapshot(0.25, "NEAR")),
                PoseFieldSample("far", (10.0, 0.0, 0.0), snapshot(1.0, "FAR")),
            ),
            kernel_radius=0.1,
        )
        result = evaluate_pose_field(spec, (3.0, 4.0, 0.0))
        self.assertTrue(result.used_nearest_fallback)
        self.assertEqual("near", result.sample_weights[0].sample_uuid)
        self.assertEqual(0.25, result.outputs.continuous_value("shape"))

    def test_validation_rejects_duplicate_positions_and_output_dimensions(self):
        spec = PoseFieldSpec(
            "field.invalid",
            "invalid",
            (PoseFieldDimension("x", 0.0),),
            (
                PoseFieldSample(
                    "a",
                    (0.0,),
                    PoseOutputSnapshot.from_values({"shape": 0.0}),
                ),
                PoseFieldSample(
                    "b",
                    (0.0,),
                    PoseOutputSnapshot.from_values({"shape": (1.0, 2.0)}),
                ),
            ),
        )
        codes = {item.code for item in validate_pose_field(spec)}
        self.assertIn("pose_field.invalid_scale", codes)
        self.assertIn("pose_field.duplicate_position", codes)
        self.assertIn("pose_field.output_dimension_mismatch", codes)


if __name__ == "__main__":
    unittest.main()
