import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "coa_tools2"))

from rig_control.semantic_schema import (  # noqa: E402
    ChainFKSolverSpec,
    ContactPinSolverSpec,
    ContactMode,
    FrameRole,
    RigFrameSpec,
    RigMode,
    SemanticChannelSpec,
    SemanticRigSpec,
    SolverNodeSpec,
    SolverType,
    WidgetTargetRole,
    validate_semantic_rig,
)


class SemanticFKSchemaTests(unittest.TestCase):
    def test_fk_solver_round_trip_preserves_chain(self):
        node = SolverNodeSpec(
            "node.fk",
            "fk.arm",
            ChainFKSolverSpec(
                "frame.mechanism",
                ("upper_arm.L", "forearm.L", "hand.L"),
            ),
            output_channels=("fk.pose",),
        )
        restored = SolverNodeSpec.from_dict(node.to_dict())
        self.assertEqual(node, restored)
        self.assertEqual(SolverType.CHAIN_FK, restored.solver.solver_type)

    def test_public_modes_are_two_discrete_states(self):
        self.assertEqual(("FK", "IK"), tuple(item.value for item in RigMode))
        self.assertEqual(("OFF", "ON"), tuple(item.value for item in ContactMode))

    def test_fk_is_an_independent_node_that_can_feed_contact(self):
        frames = tuple(
            RigFrameSpec(f"frame.{role.value.lower()}", role)
            for role in FrameRole
        )
        channels = (
            SemanticChannelSpec("fk.pose"),
            SemanticChannelSpec("pin.weight"),
            SemanticChannelSpec("pinned.pose"),
        )
        fk_node = SolverNodeSpec(
            "node.fk",
            "fk.arm",
            ChainFKSolverSpec(
                "frame.mechanism",
                ("upper_arm.L", "forearm.L", "hand.L"),
            ),
            output_channels=("fk.pose",),
        )
        contact_node = SolverNodeSpec(
            "node.contact",
            "contact.hand",
            ContactPinSolverSpec(
                "frame.mechanism",
                "frame.mechanism",
                "pin.weight",
            ),
            input_channels=("fk.pose",),
            output_channels=("pinned.pose",),
            depends_on=("node.fk",),
        )
        spec = SemanticRigSpec(
            "rig.fk.contact",
            "character.arm",
            "FK Contact",
            frames,
            channels,
            (fk_node, contact_node),
        )
        self.assertEqual((), validate_semantic_rig(spec))
        self.assertEqual(spec, SemanticRigSpec.from_dict(spec.to_dict()))
        self.assertEqual("FK_CONTROL", WidgetTargetRole.FK_CONTROL.value)


if __name__ == "__main__":
    unittest.main()
