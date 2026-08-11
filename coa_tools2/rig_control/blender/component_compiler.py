"""Compile character posing component definitions to Blender artifacts."""

from __future__ import annotations

import bpy

from ... import functions
from ..component_validation import validate_component_spec
from .component_artifacts import (
    ComponentArtifactConflict,
    ensure_in_place_component,
    ensure_limb_component,
    ensure_parameter_component,
    find_component_bone,
)
from .component_outputs import (
    ComponentOutputError,
    capture_component_output_state,
    preflight_component_outputs,
    reconcile_component_outputs,
    restore_component_output_state,
)
from .component_safety import (
    ComponentPreflightError,
    capture_component_build_state,
    ensure_unique_component_instance,
    preflight_component_artifacts,
    preserve_component_context,
    rollback_component_build,
)
from .properties import component_to_spec


class RigComponentCompileError(RuntimeError):
    pass


def _source_bone_names(component):
    return tuple(reference.bone_name for reference in component.source_bones)


def _validate_blender_sources(armature, component):
    names = _source_bone_names(component)
    missing = [name for name in names if name not in armature.data.bones]
    if missing:
        raise RigComponentCompileError(
            "Missing source bone(s): " + ", ".join(missing)
        )
    if component.component_type in {"FK_CHAIN", "LIMB_IK", "SPINE_FK"}:
        for parent_name, child_name in zip(names, names[1:]):
            child = armature.data.bones[child_name]
            if child.parent is None or child.parent.name != parent_name:
                raise RigComponentCompileError(
                    f"Source bones must form one ordered parent chain: "
                    f"{parent_name} -> {child_name}."
                )


def _validate_limb_animation_conversion(armature, component):
    """Do not silently override existing FK animation before Phase 6C."""

    if (
        component.deformation_mode != "DIRECT_BONES"
        or component.component_type != "LIMB_IK"
        or component.artifacts
    ):
        return
    animation_data = armature.animation_data
    if animation_data is None:
        return
    source_prefixes = tuple(
        f"{armature.pose.bones[name].path_from_id()}."
        for name in _source_bone_names(component)
    )

    actions = {}

    def add_action(action):
        if action is not None:
            actions[action.name_full] = action

    def add_strip_actions(strips):
        for strip in strips:
            add_action(getattr(strip, "action", None))
            nested = getattr(strip, "strips", None)
            if nested is not None:
                add_strip_actions(nested)

    add_action(animation_data.action)
    for track in animation_data.nla_tracks:
        add_strip_actions(track.strips)
    coa_properties = getattr(armature, "coa_tools2", None)
    if coa_properties is not None:
        for item in coa_properties.anim_collections:
            add_action(
                bpy.data.actions.get(
                    functions.get_action_name(item, armature)
                )
            )

    if any(
        curve.data_path.startswith(source_prefixes)
        for action in actions.values()
        for curve in functions.iter_action_fcurves(action)
    ) or any(
        curve.data_path.startswith(source_prefixes)
        for curve in getattr(animation_data, "drivers", ())
    ):
        raise RigComponentCompileError(
            "The selected limb already has FK animation. "
            "Direct Bone IK/FK conversion and baking are not implemented; "
            "the source animation was left unchanged."
        )


def _built_deformation_mode(component):
    if component.compiled_deformation_mode:
        return component.compiled_deformation_mode
    if not component.artifacts:
        return ""
    if any(
        artifact.role == "ik_constraint"
        for artifact in component.artifacts
    ):
        return "DIRECT_BONES"
    if any(
        artifact.role == "control_frame"
        for artifact in component.artifacts
    ):
        return "PARAMETRIC"
    return "DIRECT_BONES"


def _validate_deformation_mode_transition(component):
    built_mode = _built_deformation_mode(component)
    if built_mode and built_mode != component.deformation_mode:
        raise RigComponentCompileError(
            "Changing Artwork Deformation after a component is built is not "
            "supported. Revert the mode or create a new component; a "
            "transactional conversion operator is planned for a later phase."
        )


def _resolve_generated_bone_names(armature, component):
    for role, field_name in (
        ("control_frame", "frame_bone"),
        ("control_bone", "control_bone"),
        ("bend_control", "pole_bone"),
    ):
        bone = find_component_bone(
            armature,
            component.component_uuid,
            role,
        )
        if bone is not None:
            previous_name = getattr(component, field_name)
            if previous_name and previous_name != bone.name:
                for artifact in component.artifacts:
                    if artifact.bone_name == previous_name:
                        artifact.bone_name = bone.name
            setattr(component, field_name, bone.name)


def compile_component(armature, component):
    if armature is None or armature.type != "ARMATURE":
        raise RigComponentCompileError(
            "Character posing components require an Armature SpriteObject."
        )
    if component.component_type == "SEMANTIC":
        from .semantic_compiler import compile_semantic_component

        return compile_semantic_component(armature, component)
    _validate_deformation_mode_transition(component)
    _resolve_generated_bone_names(armature, component)
    issues = validate_component_spec(component_to_spec(component))
    if issues:
        raise RigComponentCompileError("; ".join(issue.message for issue in issues))
    _validate_blender_sources(armature, component)
    _validate_limb_animation_conversion(armature, component)
    try:
        preflight_component_outputs(armature, component)
    except ComponentOutputError as exc:
        raise RigComponentCompileError(str(exc)) from exc
    with preserve_component_context(armature):
        try:
            preflight_component_artifacts(armature, component)
        except ComponentPreflightError as exc:
            raise RigComponentCompileError(str(exc)) from exc
        ensure_unique_component_instance(armature)
        try:
            preflight_component_artifacts(armature, component)
        except ComponentPreflightError as exc:
            raise RigComponentCompileError(str(exc)) from exc

        snapshot = capture_component_build_state(armature, component)
        output_snapshot = capture_component_output_state(armature, component)
        try:
            if component.deformation_mode == "PARAMETRIC":
                primary = ensure_parameter_component(armature, component)
            elif component.component_type in {"ROOT", "FK_CHAIN", "SPINE_FK"}:
                if component.build_mode != "IN_PLACE":
                    raise RigComponentCompileError(
                        "Generated Root/FK chains are not available in this phase."
                    )
                pose_bones = ensure_in_place_component(armature, component)
                primary = pose_bones[-1]
            elif component.component_type == "LIMB_IK":
                primary = ensure_limb_component(armature, component)
            else:
                raise RigComponentCompileError(
                    f"Unsupported pose component: {component.component_type}."
                )
            reconcile_component_outputs(armature, component)
        except Exception as exc:
            structural_rollback_error = None
            try:
                rollback_component_build(armature, component, snapshot)
            except Exception as rollback_error:
                structural_rollback_error = rollback_error
            output_rollback_error = None
            try:
                # Restore generated bones/constraints first. Some output
                # FCurves target a component-owned constraint data path that
                # does not exist until the structural rollback is complete.
                restore_component_output_state(
                    armature,
                    component,
                    output_snapshot,
                )
            except Exception as rollback_error:
                output_rollback_error = rollback_error
            if structural_rollback_error is not None:
                raise RigComponentCompileError(
                    f"{exc}; rollback also failed: "
                    f"{structural_rollback_error}"
                ) from exc
            if output_rollback_error is not None:
                raise RigComponentCompileError(
                    f"{exc}; output rollback also failed: "
                    f"{output_rollback_error}"
                ) from exc
            if isinstance(exc, RigComponentCompileError):
                raise
            if isinstance(exc, (ComponentArtifactConflict, ComponentOutputError)):
                raise RigComponentCompileError(str(exc)) from exc
            raise
    component.needs_rebuild = False
    component.last_error = ""
    component.compiled_deformation_mode = component.deformation_mode
    return {
        "component_uuid": component.component_uuid,
        "primary_control_bone": primary.name,
        "frame_bone": component.frame_bone,
        "artifacts": len(component.artifacts),
        "bindings": len(component.bindings),
    }
