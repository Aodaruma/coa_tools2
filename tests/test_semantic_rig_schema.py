import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = ROOT / "coa_tools2"
sys.path.insert(0, str(ADDON_ROOT))

from rig_control.semantic_schema import (  # noqa: E402
    ChainIKSolverSpec,
    ContactPinSolverSpec,
    FrameRole,
    OutputPolicy,
    OutputTargetKind,
    OutputTargetSpec,
    PoseMapSolverSpec,
    ProjectedTransformSolverSpec,
    RigFrameSpec,
    SecondaryMotionSolverSpec,
    SemanticChannelSpec,
    SemanticOutputSpec,
    SemanticRigSpec,
    SolverNodeSpec,
    SolverType,
    SplineSolverSpec,
    WidgetPresentationRef,
    validate_semantic_rig,
)


class SemanticRigSchemaTests(unittest.TestCase):
    def _valid_spec(self):
        frames = tuple(
            RigFrameSpec(f"frame.{role.value.lower()}", role)
            for role in FrameRole
        ) + (
            RigFrameSpec("frame.effector", FrameRole.MECHANISM),
            RigFrameSpec("frame.pole", FrameRole.MECHANISM),
            RigFrameSpec("frame.contact", FrameRole.MECHANISM),
        )
        channels = tuple(
            SemanticChannelSpec(channel_id)
            for channel_id in (
                "control.transform",
                "apparent.depth",
                "pose.corrective",
                "ik.pose",
                "pin.weight",
                "pinned.pose",
                "spline.pose",
                "stiffness",
                "secondary.pose",
            )
        )
        nodes = (
            SolverNodeSpec(
                "node.project",
                "project.hand",
                ProjectedTransformSolverSpec(
                    "frame.display", "frame.input", "frame.art"
                ),
                input_channels=("control.transform",),
                output_channels=("apparent.depth",),
            ),
            SolverNodeSpec(
                "node.pose_map",
                "pose.hand",
                PoseMapSolverSpec("field.hand"),
                input_channels=("apparent.depth",),
                output_channels=("pose.corrective",),
                depends_on=("node.project",),
            ),
            SolverNodeSpec(
                "node.ik",
                "ik.arm",
                ChainIKSolverSpec(
                    "frame.mechanism",
                    "frame.effector",
                    ("upper_arm.L", "forearm.L", "hand.L"),
                    pole_frame_id="frame.pole",
                ),
                input_channels=("control.transform",),
                output_channels=("ik.pose",),
                depends_on=("node.pose_map",),
            ),
            SolverNodeSpec(
                "node.pin",
                "contact.hand",
                ContactPinSolverSpec(
                    "frame.mechanism", "frame.contact", "pin.weight"
                ),
                input_channels=("ik.pose", "pose.corrective"),
                output_channels=("pinned.pose",),
                depends_on=("node.ik", "node.pose_map"),
            ),
            SolverNodeSpec(
                "node.spline",
                "spline.hair",
                SplineSolverSpec(
                    "frame.mechanism",
                    ("hair.001", "hair.002", "hair.003"),
                    "curve.hair",
                ),
                output_channels=("spline.pose",),
            ),
            SolverNodeSpec(
                "node.secondary",
                "secondary.hair",
                SecondaryMotionSolverSpec(
                    "frame.mechanism", stiffness_channel_id="stiffness"
                ),
                input_channels=("spline.pose",),
                output_channels=("secondary.pose",),
                depends_on=("node.spline",),
            ),
        )
        outputs = (
            SemanticOutputSpec(
                "output.hand",
                "pinned.pose",
                OutputTargetSpec(
                    OutputTargetKind.BONE_TRANSFORM,
                    "CharacterRig",
                    "hand.L",
                    bone_name="hand.L",
                ),
                OutputPolicy.HYBRID,
                art_frame_id="frame.art",
            ),
            SemanticOutputSpec(
                "output.corrective",
                "pose.corrective",
                OutputTargetSpec(
                    OutputTargetKind.SHAPE_KEY, "HandArt", "HandDepth"
                ),
                OutputPolicy.PARAMETRIC,
            ),
        )
        return SemanticRigSpec(
            "rig.character",
            "character.motion",
            "Character Motion",
            frames,
            channels,
            nodes,
            outputs,
            (
                WidgetPresentationRef(
                    "presentation.hand",
                    "control.hand",
                    "frame.display",
                    geometry_node_group="COA_Widget_Hand",
                ),
            ),
        )

    def test_round_trip_preserves_all_composable_solver_types(self):
        spec = self._valid_spec()
        restored = SemanticRigSpec.from_dict(spec.to_dict())
        self.assertEqual(spec, restored)
        self.assertEqual(
            (
                SolverType.PROJECTED_TRANSFORM,
                SolverType.POSE_MAP,
                SolverType.CHAIN_IK,
                SolverType.CONTACT_PIN,
                SolverType.SPLINE,
                SolverType.SECONDARY_MOTION,
            ),
            tuple(node.solver.solver_type for node in restored.nodes),
        )

    def test_pose_map_ik_and_contact_can_form_one_pipeline(self):
        spec = self._valid_spec()
        self.assertEqual((), validate_semantic_rig(spec))
        pin = next(node for node in spec.nodes if node.node_uuid == "node.pin")
        self.assertEqual(("node.ik", "node.pose_map"), pin.depends_on)

    def test_validation_reports_unknown_references_and_cycles(self):
        spec = self._valid_spec()
        bad_node = SolverNodeSpec(
            "node.bad",
            "bad",
            PoseMapSolverSpec(""),
            input_channels=("unknown.channel",),
            depends_on=("node.bad",),
        )
        bad = SemanticRigSpec(
            spec.rig_uuid,
            spec.semantic_id,
            spec.display_name,
            spec.frames,
            spec.channels,
            spec.nodes + (bad_node,),
            spec.outputs,
            spec.presentations,
        )
        codes = {item.code for item in validate_semantic_rig(bad)}
        self.assertIn("semantic.unknown_node_channel", codes)
        self.assertIn("semantic.missing_pose_field", codes)
        self.assertIn("semantic.node_cycle", codes)

    def test_validation_requires_all_four_frame_roles(self):
        spec = self._valid_spec()
        bad = SemanticRigSpec(
            spec.rig_uuid,
            spec.semantic_id,
            spec.display_name,
            tuple(frame for frame in spec.frames if frame.role is not FrameRole.ART),
            spec.channels,
            spec.nodes,
            spec.outputs,
            spec.presentations,
        )
        missing = [
            item
            for item in validate_semantic_rig(bad)
            if item.code == "semantic.missing_frame_role"
        ]
        self.assertEqual(["ART"], [item.subject_id for item in missing])


if __name__ == "__main__":
    unittest.main()
