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
    GraphInterpolation,
    GraphPointShape,
    LipSyncPreset,
    StateCellSpec,
    StateDataSpec,
    StateMixPolicy,
    StateMode,
    StatePointSpec,
    TargetKind,
    WidgetLayout,
    WidgetSpec,
    dial_point,
    dial_rest_angle,
    graph_fallback_edges,
    graph_state_weights,
    lip_sync_preset_points,
    resolve_phoneme_viseme,
    state_point_position,
    summarize_state_mix,
    state_weights,
    validate_state_cells,
    validate_graph_state_points,
    validate_state_points,
)
from rig_control.component_schema import (  # noqa: E402
    RigComponentOutputSpec,
    RigDeformationMode,
    RigComponentSide,
    RigComponentSpec,
    RigComponentType,
    RigComponentWidget,
    RigBendAxis,
    RigDepthMode,
    RigEndRotationMode,
    RigOrientationMode,
    RigParameterChannel,
    RigSolverMode,
    RigWidgetPresentationSpec,
    RigWidgetShape,
)
from rig_control.component_validation import validate_component_spec  # noqa: E402
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

        graph = WidgetSpec(
            widget_uuid="widget-graph",
            layout=WidgetLayout.GRAPH,
            graph_points=((0.0, 0.0), (1.0, 1.0)),
            graph_edges=((0, 1),),
            graph_point_shapes=(
                GraphPointShape.CIRCLE,
                GraphPointShape.CUSTOM_OBJECT,
            ),
            graph_custom_object_names=("", "WGT_CustomMouth"),
        )
        self.assertEqual(graph, WidgetSpec.from_dict(graph.to_dict()))

    def test_tip_radius_defaults_to_twice_node_radius(self):
        spec = WidgetSpec(widget_uuid="widget-tip", layout=WidgetLayout.TIP)
        self.assertEqual(spec.node_radius * 2.0, spec.tip_radius)

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

    def test_rig_component_round_trip_preserves_visual_axes(self):
        output = RigComponentOutputSpec(
            binding_uuid="component-output-1",
            source_component=RigParameterChannel.ROT_Y,
            target_kind=TargetKind.SHAPE_KEY_VALUE,
            target_object_name="HandArt",
            target_name="TurnY",
            input_min=-0.75,
            input_max=0.75,
        )
        spec = RigComponentSpec(
            component_uuid="component-arm-l",
            semantic_id="limb.arm.l",
            display_name="Arm.L",
            component_type=RigComponentType.LIMB_IK,
            source_bones=("upper_arm.L", "forearm.L", "hand.L"),
            side=RigComponentSide.LEFT,
            deformation_mode=RigDeformationMode.PARAMETRIC,
            orientation_mode=RigOrientationMode.SOURCE_BONE,
            orientation_reference="hand.L",
            depth_mode=RigDepthMode.LIMITED,
            depth_min=-0.5,
            depth_max=0.75,
            widget=RigComponentWidget.HAND,
            solver_mode=RigSolverMode.PLANAR,
            bend_axis=RigBendAxis.Y,
            use_bend_hint=True,
            pole_distance=1.25,
            end_rotation_mode=RigEndRotationMode.COPY_LOCAL,
            presentation=RigWidgetPresentationSpec(
                shape=RigWidgetShape.CYLINDER_ARROW_1D,
                bar_width=0.2,
                head_length=0.4,
                head_width=0.65,
                radius=1.25,
                arc_angle=math.pi * 1.25,
                segments=96,
                live_preview=False,
            ),
            bindings=(output,),
        )
        self.assertEqual(spec, RigComponentSpec.from_dict(spec.to_dict()))
        self.assertFalse(validate_component_spec(spec))

    def test_widget_presentation_round_trip_preserves_all_shape_parameters(self):
        spec = RigWidgetPresentationSpec(
            shape=RigWidgetShape.SECTOR,
            custom_object_name="IgnoredForSector",
            width=3.0,
            height=2.0,
            corner_radius=0.2,
            bar_width=0.25,
            head_length=0.5,
            head_width=0.75,
            radius=2.0,
            arc_angle=math.pi,
            sector_inner_radius=0.5,
            sector_outer_radius=2.5,
            sector_start_angle=-0.25,
            sector_sweep_angle=1.75,
            segments=128,
            wire_width=2.5,
            live_preview=False,
        )
        self.assertEqual(spec, RigWidgetPresentationSpec.from_dict(spec.to_dict()))

    def test_version_two_component_gets_non_destructive_presentation_default(self):
        data = {
            "schema_version": 2,
            "component_uuid": "component-v2",
            "semantic_id": "legacy.widget",
            "display_name": "Version 2",
            "component_type": "ROOT",
            "source_bones": ("root",),
            "widget": "ROOT",
        }
        spec = RigComponentSpec.from_dict(data)
        self.assertEqual(RigWidgetShape.NONE, spec.presentation.shape)
        self.assertEqual(RigComponentWidget.ROOT, spec.widget)

    def test_component_validation_checks_selected_presentation_shape(self):
        spec = RigComponentSpec(
            component_uuid="component-presentation-bad",
            semantic_id="presentation.bad",
            display_name="Bad Presentation",
            component_type=RigComponentType.ROOT,
            source_bones=("root",),
            presentation=RigWidgetPresentationSpec(
                shape=RigWidgetShape.SECTOR,
                sector_inner_radius=2.0,
                sector_outer_radius=1.0,
                sector_sweep_angle=0.0,
                segments=2,
                wire_width=0.25,
            ),
        )
        codes = {issue.code for issue in validate_component_spec(spec)}
        self.assertIn("component.presentation_invalid_sector_radius", codes)
        self.assertIn("component.presentation_invalid_sector_sweep", codes)
        self.assertIn("component.presentation_invalid_segments", codes)
        self.assertIn("component.presentation_invalid_wire_width", codes)

    def test_version_one_component_defaults_to_legacy_direct_deformation(self):
        data = {
            "schema_version": 1,
            "component_uuid": "legacy-component",
            "semantic_id": "legacy.root",
            "display_name": "Legacy Root",
            "component_type": "ROOT",
            "source_bones": ("root",),
        }
        spec = RigComponentSpec.from_dict(data)
        self.assertEqual(RigDeformationMode.DIRECT_BONES, spec.deformation_mode)

    def test_rig_component_validation_rejects_bad_limb_and_depth(self):
        spec = RigComponentSpec(
            component_uuid="component-bad",
            semantic_id="limb.bad",
            display_name="Bad Limb",
            component_type=RigComponentType.LIMB_IK,
            source_bones=("upper", "upper"),
            orientation_mode=RigOrientationMode.SOURCE_BONE,
            orientation_reference="missing",
            depth_mode=RigDepthMode.LIMITED,
            depth_min=1.0,
            depth_max=-1.0,
            widget_size=0.0,
            ik_chain_length=2,
        )
        codes = {issue.code for issue in validate_component_spec(spec)}
        self.assertIn("component.duplicate_source_bone", codes)
        self.assertIn("component.insufficient_source_bones", codes)
        self.assertIn("component.invalid_orientation_reference", codes)
        self.assertIn("component.invalid_depth_range", codes)
        self.assertIn("component.invalid_widget_size", codes)
        self.assertIn("component.ik_chain_exceeds_sources", codes)

    def test_state_data_round_trip_and_matrix_weights(self):
        points = tuple(
            StatePointSpec(
                state_uuid=f"state-{column}-{row}",
                control_uuid="control-matrix",
                column=column,
                row=row,
                target_object_name="Face",
                target_name=f"Pose_{column}_{row}",
            )
            for row in range(2)
            for column in range(3)
        )
        cells = (
            StateCellSpec("cell-0", "control-matrix", 0, 0, True),
            StateCellSpec("cell-1", "control-matrix", 1, 0, False),
        )
        spec = StateDataSpec(
            control_uuid="control-matrix",
            mode=StateMode.MATRIX_2D,
            columns=3,
            rows=2,
            points=points,
            cells=cells,
            mix_policy=StateMixPolicy.PARTIAL,
        )
        self.assertEqual(spec, StateDataSpec.from_dict(spec.to_dict()))
        self.assertEqual((0.5, 1.0), state_point_position(1, 1, 3, 2))
        weights = state_weights(0.25, 0.5, 3, 2)
        self.assertAlmostEqual(1.0, sum(weights))
        self.assertEqual((0.25, 0.25, 0.0, 0.25, 0.25, 0.0), weights)
        self.assertEqual((), validate_state_points(points, 3, 2))
        self.assertEqual((), validate_state_cells(cells, 3, 2))
        self.assertEqual(StateMixPolicy.PARTIAL, summarize_state_mix(cells))

    def test_matrix_widget_cell_mask_round_trip(self):
        spec = WidgetSpec(
            widget_uuid="matrix-mask",
            layout=WidgetLayout.MATRIX,
            columns=2,
            rows=3,
            mix_cells=(True, False),
        )
        self.assertEqual(spec, WidgetSpec.from_dict(spec.to_dict()))
        self.assertFalse(validate_widget_spec(spec))

    def test_state_validation_allows_explicit_empty_points(self):
        points = (
            StatePointSpec("a", "control", 0, 0, is_empty=True),
            StatePointSpec("b", "control", 1, 0),
        )
        self.assertEqual(
            ("state.unassigned_point",),
            validate_state_points(points, 2, 1),
        )

    def test_graph_state_round_trip_edges_and_weights(self):
        points = (
            StatePointSpec(
                "rest",
                "mouth",
                0,
                0,
                display_name="REST",
                target_object_name="Face",
                target_name="Mouth_REST",
                position=(0.5, 0.0),
                point_shape=GraphPointShape.DIAMOND,
            ),
            StatePointSpec(
                "wide",
                "mouth",
                1,
                0,
                display_name="WIDE",
                target_object_name="Face",
                target_name="Mouth_WIDE",
                position=(0.0, 1.0),
                fallback_state_uuid="rest",
            ),
            StatePointSpec(
                "round",
                "mouth",
                2,
                0,
                display_name="ROUND",
                target_object_name="Face",
                target_name="Mouth_ROUND",
                position=(1.0, 1.0),
                fallback_state_uuid="rest",
                target_name_candidates=("Mouth_ROUND", "mouth_round"),
                phoneme_aliases=("O", "U"),
            ),
        )
        spec = StateDataSpec(
            control_uuid="mouth",
            mode=StateMode.GRAPH_2D,
            columns=3,
            rows=1,
            points=points,
            graph_interpolation=GraphInterpolation.HYBRID,
            graph_radius=0.8,
            lip_sync_preset=LipSyncPreset.STANDARD_2D,
        )
        self.assertEqual(spec, StateDataSpec.from_dict(spec.to_dict()))
        self.assertEqual(((0, 1), (0, 2)), graph_fallback_edges(points))
        self.assertEqual((), validate_graph_state_points(points))

        at_round = graph_state_weights(
            1.0,
            1.0,
            points,
            GraphInterpolation.MAP_2D,
            0.8,
        )
        self.assertEqual((0.0, 0.0, 1.0), at_round)
        on_rest_round = graph_state_weights(
            0.75,
            0.5,
            points,
            GraphInterpolation.NAMED_GRAPH,
        )
        self.assertAlmostEqual(1.0, sum(on_rest_round))
        self.assertAlmostEqual(0.5, on_rest_round[0])
        self.assertAlmostEqual(0.5, on_rest_round[2])

    def test_lip_sync_presets_are_target_agnostic_and_have_alias_fallbacks(self):
        self.assertEqual(
            ("REST", "A_E", "I", "U_O"),
            tuple(
                point.name
                for point in lip_sync_preset_points(LipSyncPreset.MINIMAL)
            ),
        )
        self.assertEqual(
            ("REST", "A", "I", "U", "E", "O", "MBP"),
            tuple(
                point.name
                for point in lip_sync_preset_points(LipSyncPreset.JP_VOWELS_MBP)
            ),
        )
        advanced = lip_sync_preset_points(LipSyncPreset.ADVANCED_PHONEME)
        self.assertEqual(10, len(advanced))
        self.assertTrue(all(point.target_name_candidates for point in advanced))
        self.assertEqual(
            "FV",
            resolve_phoneme_viseme("f", LipSyncPreset.ADVANCED_PHONEME),
        )
        self.assertEqual(
            "ETC",
            resolve_phoneme_viseme("unknown", LipSyncPreset.ADVANCED_PHONEME),
        )

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
