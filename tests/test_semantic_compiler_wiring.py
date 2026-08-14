import importlib.util
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = ROOT / "coa_tools2"
sys.path.insert(0, str(ADDON_ROOT))


def _stub_module(name, **attributes):
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def _load_compiler_helpers():
    import rig_control.blender

    noop = lambda *args, **kwargs: None
    error = type("StubError", (RuntimeError,), {})
    stubs = {
        "bpy": _stub_module(
            "bpy",
            data=SimpleNamespace(objects=SimpleNamespace(get=lambda _name: None)),
            ops=SimpleNamespace(),
            context=SimpleNamespace(),
        ),
        "mathutils": _stub_module("mathutils", Vector=lambda value: value),
        "rig_control.blender.artifacts": _stub_module(
            "rig_control.blender.artifacts",
            ensure_rig_instance_id=lambda _armature: "instance",
        ),
        "rig_control.blender.component_artifacts": _stub_module(
            "rig_control.blender.component_artifacts",
            ensure_depth_constraint=noop,
        ),
        "rig_control.blender.component_safety": _stub_module(
            "rig_control.blender.component_safety",
            ComponentPreflightError=error,
            capture_component_build_state=noop,
            ensure_unique_component_instance=noop,
            preflight_component_artifacts=noop,
            preserve_component_context=noop,
            rollback_component_build=noop,
        ),
        "rig_control.blender.semantic_artifacts": _stub_module(
            "rig_control.blender.semantic_artifacts",
            SemanticArtifactError=error,
            _frame_matrix=noop,
            _project_to_frame=noop,
            ensure_projected_ik_artifacts=noop,
            ensure_projected_transform_artifacts=noop,
            semantic_stage_role=lambda stage_uuid, role: f"semantic:{stage_uuid}:{role}",
        ),
        "rig_control.blender.semantic_contact": _stub_module(
            "rig_control.blender.semantic_contact",
            SemanticContactError=error,
            _clear_pin_constraint_marker=noop,
            _owned_contact_constraints=lambda *_args, **_kwargs: (),
            _owned_pin_property_locations=lambda *_args, **_kwargs: (),
            _remove_pin_property_artifact=noop,
            contact_uses_ik_override=lambda stage: (
                not str(getattr(stage, "pin_driven_bone", "") or "").strip()
                or bool(
                    str(
                        getattr(stage, "pin_driven_stage_uuid", "") or ""
                    ).strip()
                )
            ),
            ensure_contact_pin_artifacts=noop,
            validate_pin_ranges=noop,
        ),
        "rig_control.blender.semantic_outputs": _stub_module(
            "rig_control.blender.semantic_outputs",
            SemanticOutputError=error,
            capture_semantic_output_state=noop,
            preflight_semantic_outputs=noop,
            reconcile_semantic_outputs=noop,
            restore_semantic_output_state=noop,
        ),
        "rig_control.blender.semantic_secondary": _stub_module(
            "rig_control.blender.semantic_secondary",
            ensure_secondary_motion_artifacts=noop,
        ),
        "rig_control.blender.semantic_spline": _stub_module(
            "rig_control.blender.semantic_spline",
            ensure_spline_chain_artifacts=noop,
            retarget_spline_hooks=noop,
        ),
    }
    module_name = "rig_control.blender._semantic_compiler_wiring_test"
    path = ADDON_ROOT / "rig_control" / "blender" / "semantic_compiler.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    saved = {name: sys.modules.get(name) for name in stubs}
    sys.modules.update(stubs)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    return module


compiler = _load_compiler_helpers()


class FakeCollection(list):
    def add(self):
        value = SimpleNamespace()
        self.append(value)
        return value


def term(**values):
    defaults = dict(
        source_stage_uuid="",
        source_object=None,
        source_bone="",
        source_kind="TRANSFORM",
        transform_type="LOC_X",
        transform_space="LOCAL_SPACE",
        coefficient=1.0,
    )
    defaults.update(values)
    return SimpleNamespace(**defaults)


def stage(stage_uuid, stage_type, *, depends_on="", order=0, inputs=(), sources=()):
    return SimpleNamespace(
        stage_uuid=stage_uuid,
        stage_type=stage_type,
        depends_on=depends_on,
        order=order,
        enabled=True,
        label=stage_uuid,
        inputs=inputs,
        source_bones=[SimpleNamespace(bone_name=value) for value in sources],
        pin_driven_bone="",
        pin_driven_stage_uuid="",
        secondary_baked=False,
    )


class SemanticCompilerWiringTests(unittest.TestCase):
    def test_pose_map_rejects_recorded_output_arity_mismatch(self):
        output = SimpleNamespace(
            output_uuid="output.vector",
            label="Vector Output",
            value_arity=3,
            discrete=False,
            enabled=True,
        )
        sample = SimpleNamespace(
            sample_uuid="sample",
            label="Legacy Scalar Sample",
            inputs=(),
            outputs=(
                SimpleNamespace(
                    output_uuid="output.vector",
                    value_arity=1,
                ),
            ),
        )
        pose_map = SimpleNamespace(
            stage_type="POSE_MAP",
            samples=(sample,),
            inputs=(),
            outputs=(output,),
        )

        with self.assertRaisesRegex(
            compiler.SemanticRigCompileError,
            r"records Vec1, but the output expects Vec3.*Re-record or migrate",
        ):
            compiler._validate_pose_map_samples((pose_map,))

    def test_secondary_expected_roles_follow_compiled_spline_controls(self):
        secondary = stage(
            "secondary", "SECONDARY_MOTION", depends_on="pose_map"
        )
        component = SimpleNamespace(
            source_bones=(
                SimpleNamespace(bone_name="Upper"),
                SimpleNamespace(bone_name="Lower"),
            ),
        )
        built = compiler.SemanticStageBuildResult(
            "secondary",
            "SECONDARY_MOTION",
            spline_info=SimpleNamespace(
                control_bones=("Spline.0", "Spline.1", "Spline.2")
            ),
        )

        roles = compiler._expected_stage_roles(
            component,
            (secondary,),
            {secondary.stage_uuid: built},
        )

        self.assertIn("semantic:secondary:secondary_output:2", roles)
        self.assertIn("semantic:secondary:secondary_follow:2", roles)

    def test_topological_order_does_not_use_collection_order(self):
        first = stage("input", "PROJECTED_TRANSFORM", order=20)
        second = stage("map", "POSE_MAP", depends_on="input", order=0)
        component = SimpleNamespace(semantic_stages=(second, first))

        self.assertEqual(
            ("input", "map"),
            tuple(item.stage_uuid for item in compiler.ordered_semantic_stages(component)),
        )

    def test_multiple_dependency_requires_explicit_term_source(self):
        channel = SimpleNamespace(terms=(term(),))
        pose_map = stage(
            "map", "POSE_MAP", depends_on="left,right", inputs=(channel,)
        )

        with self.assertRaisesRegex(
            compiler.SemanticRigCompileError, "multiple dependencies"
        ):
            compiler._preflight_stage_wiring((pose_map,))

        channel.terms[0].source_stage_uuid = "right"
        compiler._preflight_stage_wiring((pose_map,))

    def test_pose_map_term_binds_to_its_named_dependency(self):
        input_term = term(source_stage_uuid="right")
        channel = SimpleNamespace(channel_id="turn", terms=FakeCollection((input_term,)))
        pose_map = stage(
            "map", "POSE_MAP", depends_on="left,right", inputs=(channel,)
        )
        left = compiler.SemanticStageBuildResult(
            "left", "PROJECTED_TRANSFORM", primary_control_bone="CTRL_Left"
        )
        right = compiler.SemanticStageBuildResult(
            "right", "PROJECTED_TRANSFORM", primary_control_bone="CTRL_Right"
        )
        armature = object()

        compiler._bind_pose_map_inputs(
            armature,
            pose_map,
            {"left": left, "right": right},
            {"map": pose_map},
        )

        self.assertIs(armature, input_term.source_object)
        self.assertEqual("CTRL_Right", input_term.source_bone)

    def test_compiled_pin_default_retargets_when_dependency_changes(self):
        pin = stage("pin", "CONTACT_PIN")
        pin.pin_driven_bone = "CTRL_Old"
        pin.pin_driven_stage_uuid = "old"
        replacement = compiler.SemanticStageBuildResult(
            "new",
            "CHAIN_IK",
            primary_control_bone="CTRL_New",
            contact_output_bone="CTRL_New",
        )

        self.assertEqual(
            ("CTRL_New", "new"),
            compiler._contact_default_driven(pin, (replacement,)),
        )
        pin.pin_driven_stage_uuid = ""
        self.assertEqual(
            ("CTRL_New", "new"),
            compiler._contact_default_driven(pin, (replacement,)),
        )

    def test_contact_requires_one_unique_chain_ik_provider(self):
        ik = stage("ik", "CHAIN_IK")
        pin = stage("pin", "CONTACT_PIN", depends_on="ik")
        compiler._validate_contact_ik_dependencies((ik, pin))

        standalone_fk = stage("fk", "CHAIN_FK")
        invalid = stage("invalid", "CONTACT_PIN", depends_on="fk")
        with self.assertRaisesRegex(
            compiler.SemanticRigCompileError,
            "dependency must be CHAIN_IK",
        ):
            compiler._validate_contact_ik_dependencies((standalone_fk, invalid))

        explicit = stage("generic", "CONTACT_PIN", depends_on="fk")
        explicit.pin_driven_bone = "CTRL_WorldPin"
        explicit.pin_driven_stage_uuid = ""
        compiler._validate_contact_ik_dependencies((standalone_fk, explicit))

        second = stage("pin.second", "CONTACT_PIN", depends_on="ik")
        with self.assertRaisesRegex(
            compiler.SemanticRigCompileError,
            "multiple automatic Contact",
        ):
            compiler._validate_contact_ik_dependencies((ik, pin, second))

    def test_chain_ik_definitions_exclusively_own_source_bones(self):
        first = stage("ik.a", "CHAIN_IK", sources=("Upper", "Lower"))
        second = stage("ik.b", "CHAIN_IK", sources=("Upper", "Lower"))
        component = SimpleNamespace(
            component_uuid="component",
            component_type="SEMANTIC",
            enabled=True,
            label="Arm",
            semantic_stages=(first, second),
            source_bones=(),
            artifacts=(),
        )
        armature = SimpleNamespace(
            rig_data=SimpleNamespace(rig_components=(component,)),
            pose=SimpleNamespace(bones={}),
        )
        properties = _stub_module(
            "rig_control.blender.properties",
            get_rig_data=lambda value: value.rig_data,
        )

        with patch.dict(
            sys.modules, {"rig_control.blender.properties": properties}
        ):
            with self.assertRaisesRegex(
                compiler.SemanticRigCompileError, "multiple semantic deformation"
            ):
                compiler.validate_chain_ik_source_ownership(
                    armature, component, (first, second)
                )

    def test_live_artifact_from_other_component_is_an_owner(self):
        current_stage = stage("ik.current", "CHAIN_IK", sources=("Upper",))
        current = SimpleNamespace(
            component_uuid="current",
            component_type="SEMANTIC",
            enabled=True,
            label="Current",
            semantic_stages=(current_stage,),
            source_bones=(),
            artifacts=(),
        )
        artifact = SimpleNamespace(
            role="semantic:ik.old:source_presentation:0",
            data_type="CONSTRAINT",
            bone_name="Upper",
            constraint_name="ExistingCopy",
        )
        old = SimpleNamespace(
            component_uuid="old",
            component_type="SEMANTIC",
            enabled=False,
            label="Old",
            semantic_stages=(),
            source_bones=(),
            artifacts=(artifact,),
        )
        constraints = SimpleNamespace(get=lambda name: object() if name == "ExistingCopy" else None)
        armature = SimpleNamespace(
            rig_data=SimpleNamespace(rig_components=(current, old)),
            pose=SimpleNamespace(
                bones={"Upper": SimpleNamespace(constraints=constraints)}
            ),
        )
        properties = _stub_module(
            "rig_control.blender.properties",
            get_rig_data=lambda value: value.rig_data,
        )

        with patch.dict(
            sys.modules, {"rig_control.blender.properties": properties}
        ):
            with self.assertRaisesRegex(
                compiler.SemanticRigCompileError, "multiple semantic deformation"
            ):
                compiler.validate_chain_ik_source_ownership(
                    armature, current, (current_stage,)
                )


if __name__ == "__main__":
    unittest.main()
