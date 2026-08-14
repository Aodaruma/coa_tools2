import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = ROOT / "coa_tools2"
sys.path.insert(0, str(ADDON_ROOT))

from rig_control.blender.semantic_bbone import (  # noqa: E402
    SemanticBboneError,
    bbone_bezier_name_plan,
    validate_bbone_source_names,
)
from rig_control.component_schema import (  # noqa: E402
    RigWidgetPresentationSpec,
    RigWidgetShape,
)
from rig_control.semantic_schema import (  # noqa: E402
    BboneBezierSolverSpec,
    FrameRole,
    RigFrameSpec,
    SemanticRigSpec,
    SolverNodeSpec,
    SolverType,
    WidgetPresentationRef,
    WidgetTargetRole,
    validate_semantic_rig,
)


class _Owner:
    def __init__(self, component_uuid="", stage_uuid="", semantic_id=""):
        self.component_uuid = component_uuid
        self.stage_uuid = stage_uuid
        self.semantic_id = semantic_id


class SemanticBboneTests(unittest.TestCase):
    def _spec(self, solver=None):
        frames = tuple(
            RigFrameSpec(f"frame.{role.value.lower()}", role)
            for role in FrameRole
        )
        solver = solver or BboneBezierSolverSpec(
            "frame.mechanism",
            "spine.bendy",
            segments=12,
            use_mid_control=True,
            ease_in=0.8,
            ease_out=1.2,
            roll_in=-0.1,
            roll_out=0.2,
            scale_in=(1.0, 0.9, 1.0),
            scale_out=(1.0, 1.1, 1.0),
        )
        return SemanticRigSpec(
            "rig.bbone",
            "body.bezier",
            "Body Bezier",
            frames,
            (),
            (SolverNodeSpec("node.bbone", "body.bezier", solver),),
            presentations=(
                WidgetPresentationRef(
                    "widget.points",
                    "bbone.points",
                    "frame.display",
                    target_role=WidgetTargetRole.BBONE_POINT,
                    settings=RigWidgetPresentationSpec(
                        shape=RigWidgetShape.ELLIPSE,
                        width=0.68,
                        height=0.68,
                    ),
                ),
                WidgetPresentationRef(
                    "widget.handles",
                    "bbone.handles",
                    "frame.display",
                    target_role=WidgetTargetRole.BBONE_HANDLE,
                    settings=RigWidgetPresentationSpec(
                        shape=RigWidgetShape.TRIANGLE,
                    ),
                ),
            ),
        )

    def test_schema_round_trip_preserves_bbone_parameters_and_roles(self):
        spec = self._spec()
        self.assertEqual((), validate_semantic_rig(spec))
        restored = SemanticRigSpec.from_dict(spec.to_dict())
        self.assertEqual(spec, restored)
        self.assertEqual(
            SolverType.BBONE_BEZIER,
            restored.nodes[0].solver.solver_type,
        )
        self.assertEqual(
            (WidgetTargetRole.BBONE_POINT, WidgetTargetRole.BBONE_HANDLE),
            tuple(item.target_role for item in restored.presentations),
        )

    def test_schema_rejects_missing_bone_segments_and_nonpositive_scale(self):
        bad = BboneBezierSolverSpec(
            "frame.mechanism",
            "",
            segments=1,
            scale_out=(1.0, 0.0, 1.0),
        )
        codes = {item.code for item in validate_semantic_rig(self._spec(bad))}
        self.assertIn("semantic.missing_bbone_deform_bone", codes)
        self.assertIn("semantic.invalid_bbone_segments", codes)
        self.assertIn("semantic.invalid_bbone_scale", codes)

    def test_name_plan_is_stable_unique_and_blender_bounded(self):
        component = _Owner(
            component_uuid="component-123456789",
            semantic_id="Upper Body Bezier",
        )
        stage = _Owner(stage_uuid="stage-abcdefghijk")
        first = bbone_bezier_name_plan(component, stage)
        second = bbone_bezier_name_plan(component, stage)
        self.assertEqual(first, second)
        names = tuple(first.__dict__.values())
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(len(name) <= 63 for name in names))

    def test_runtime_source_contract_requires_exactly_one_bone(self):
        self.assertEqual(("spine",), validate_bbone_source_names(("spine",)))
        for names in ((), ("a", "b")):
            with self.assertRaises(SemanticBboneError):
                validate_bbone_source_names(names)


if __name__ == "__main__":
    unittest.main()
