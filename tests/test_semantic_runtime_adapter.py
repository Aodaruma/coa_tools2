import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = ROOT / "coa_tools2"
sys.path.insert(0, str(ADDON_ROOT))


if "bpy" not in sys.modules:
    bpy = types.ModuleType("bpy")
    bpy.data = SimpleNamespace(objects=[])
    bpy_app = types.ModuleType("bpy.app")
    bpy_app.driver_namespace = {}
    bpy_handlers = types.ModuleType("bpy.app.handlers")
    bpy_handlers.persistent = lambda function: function
    bpy.app = bpy_app
    bpy_app.handlers = bpy_handlers
    sys.modules["bpy"] = bpy
    sys.modules["bpy.app"] = bpy_app
    sys.modules["bpy.app.handlers"] = bpy_handlers


from rig_control.pose_field import evaluate_pose_field  # noqa: E402
from rig_control.blender.semantic_runtime import (  # noqa: E402
    _FIELD_CACHE,
    _rig_data,
    PoseFieldRuntimeKey,
    evaluate_continuous_component,
    evaluate_live_input_term,
    pose_field_driver_expression,
    pose_field_spec_from_property_group,
)


def pg(**values):
    return SimpleNamespace(**values)


def input_value(channel_uuid, value):
    return pg(channel_uuid=channel_uuid, value=value)


def output_value(output_uuid, value, arity=1, discrete_value=""):
    return pg(
        output_uuid=output_uuid,
        value=value,
        value_arity=arity,
        discrete_value=discrete_value,
    )


class SemanticRuntimeAdapterTests(unittest.TestCase):
    def make_stage(self):
        inputs = (
            pg(channel_uuid="channel.z", channel_id="z", scale=2.0),
            pg(channel_uuid="channel.x", channel_id="x", scale=1.0),
            pg(channel_uuid="channel.y", channel_id="y", scale=0.5),
        )
        outputs = (
            pg(
                output_uuid="output.vector",
                output_id="vector",
                value_arity=4,
                discrete=False,
                enabled=True,
            ),
            pg(
                output_uuid="output.slot",
                output_id="slot",
                value_arity=1,
                discrete=True,
                enabled=True,
            ),
            pg(
                output_uuid="output.disabled",
                output_id="disabled",
                value_arity=1,
                discrete=False,
                enabled=False,
            ),
        )
        sample_a = pg(
            sample_uuid="sample.a",
            label="A",
            enabled=True,
            inputs=(
                input_value("channel.x", 0.0),
                input_value("channel.y", 0.0),
                input_value("channel.z", 0.0),
            ),
            outputs=(
                output_value("output.vector", (0.0, 10.0, 99.0, 99.0), 2),
                output_value("output.slot", (999.0, 0.0, 0.0, 0.0), 1, "2"),
                output_value("output.disabled", (7.0, 0.0, 0.0, 0.0), 1),
            ),
        )
        # Sample inputs may use semantic channel IDs while older/current RNA
        # migrations settle on channel UUIDs.  Both resolve to stage order.
        sample_b = pg(
            sample_uuid="sample.b",
            label="B",
            enabled=True,
            inputs=(
                pg(channel_id="y", value=1.0),
                pg(channel_id="z", value=1.0),
                pg(channel_id="x", value=1.0),
            ),
            outputs=(
                output_value("output.vector", (1.0, 20.0, 88.0, 88.0), 2),
                output_value("output.slot", (111.0, 0.0, 0.0, 0.0), 1, "5"),
            ),
        )
        incomplete = pg(
            sample_uuid="sample.incomplete",
            label="Missing Y",
            enabled=True,
            inputs=(
                input_value("channel.x", 0.5),
                input_value("channel.z", 0.5),
            ),
            outputs=(output_value("output.vector", (0.5, 15.0, 0.0, 0.0), 2),),
        )
        return pg(
            stage_uuid="stage.pose",
            semantic_id="pose.test",
            inputs=inputs,
            outputs=outputs,
            samples=(sample_a, sample_b, incomplete),
            neighborhood_size=8,
            kernel_radius=4.0,
            exact_epsilon=1.0e-8,
        )

    def test_stage_inputs_define_arbitrary_dimension_order(self):
        spec = pose_field_spec_from_property_group(self.make_stage())

        self.assertEqual(
            ("channel.z", "channel.x", "channel.y"),
            tuple(dimension.channel_id for dimension in spec.dimensions),
        )
        self.assertEqual((2.0, 1.0, 0.5), tuple(item.scale for item in spec.dimensions))
        self.assertEqual(("sample.a", "sample.b"), tuple(item.sample_uuid for item in spec.samples))
        self.assertEqual((0.0, 0.0, 0.0), spec.samples[0].position)
        self.assertEqual((1.0, 1.0, 1.0), spec.samples[1].position)

    def test_output_metadata_controls_vector_slice_and_discrete_kind(self):
        spec = pose_field_spec_from_property_group(self.make_stage())
        first = spec.samples[0].outputs

        self.assertEqual((0.0, 10.0), first.continuous_value("output.vector"))
        self.assertEqual("2", first.discrete_value("output.slot"))
        self.assertEqual(1, len(first.continuous))
        self.assertEqual(1, len(first.discrete))

    def test_three_dimensional_field_blends_continuous_and_uses_nearest_discrete(self):
        spec = pose_field_spec_from_property_group(self.make_stage())
        middle = evaluate_pose_field(spec, (0.5, 0.5, 0.5)).outputs
        near_b = evaluate_pose_field(spec, (0.9, 0.9, 0.9)).outputs

        self.assertEqual((0.5, 15.0), middle.continuous_value("output.vector"))
        self.assertEqual("2", middle.discrete_value("output.slot"))
        self.assertEqual("5", near_b.discrete_value("output.slot"))

    def test_rig_data_supports_dedicated_and_legacy_property_groups(self):
        dedicated = object()
        legacy = object()

        self.assertIs(dedicated, _rig_data(pg(coa_tools2_rig=dedicated, coa_tools2=legacy)))
        self.assertIs(legacy, _rig_data(pg(coa_tools2=legacy)))

    def test_live_custom_property_term_honors_array_index(self):
        source = pg(path_resolve=lambda _path: (1.25, 2.5, 3.75))
        term = pg(
            source_object=source,
            source_kind="CUSTOM_PROPERTY",
            data_path='["semantic_vector"]',
            array_index=1,
        )

        self.assertEqual(2.5, evaluate_live_input_term(term, object()))

    def test_live_transform_space_uses_raw_channels(self):
        source = pg(
            type="EMPTY",
            location=(1.0, 2.0, 3.0),
            rotation_mode="XYZ",
            rotation_euler=(0.1, 0.2, 0.3),
            scale=(0.5, 1.5, 2.5),
        )
        armature = object()

        for transform_type, expected in (
            ("LOC_Y", 2.0),
            ("ROT_Z", 0.3),
            ("SCALE_X", 0.5),
        ):
            term = pg(
                source_object=source,
                source_kind="TRANSFORM",
                source_bone="",
                transform_type=transform_type,
                transform_space="TRANSFORM_SPACE",
                data_path="",
                array_index=-1,
            )
            self.assertEqual(expected, evaluate_live_input_term(term, armature))

    def test_vector_driver_expression_selects_one_component(self):
        expression = pose_field_driver_expression(
            "instance-1234567890",
            "component-1234567890",
            "stage-1234567890",
            "output-1234567890",
            (),
            component_index=2,
        )

        self.assertTrue(expression.startswith("coa_pose_field_component("))
        self.assertIn(",2)", expression)

    def test_vector_runtime_returns_requested_component(self):
        spec = pose_field_spec_from_property_group(self.make_stage())
        key = PoseFieldRuntimeKey("instance", "component", "stage", "outputvector")
        _FIELD_CACHE[key] = spec
        try:
            self.assertEqual(
                15.0,
                evaluate_continuous_component(
                    "instance", "component", "stage", "outputvector", 1,
                    0.5, 0.5, 0.5,
                ),
            )
            self.assertEqual(
                0.0,
                evaluate_continuous_component(
                    "instance", "component", "stage", "outputvector", 9,
                    0.5, 0.5, 0.5,
                ),
            )
        finally:
            _FIELD_CACHE.pop(key, None)


if __name__ == "__main__":
    unittest.main()
