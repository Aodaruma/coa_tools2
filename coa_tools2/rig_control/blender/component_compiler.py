"""Compile character posing component definitions to Blender artifacts."""

from __future__ import annotations

import bpy

from ... import functions
from ..component_validation import validate_component_spec
from .component_artifacts import (
    ComponentArtifactConflict,
    ensure_in_place_component,
    ensure_limb_component,
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

    if component.component_type != "LIMB_IK" or component.artifacts:
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
            "IK/FK conversion and baking are planned for Phase 6C; "
            "the source animation was left unchanged."
        )


def compile_component(armature, component):
    if armature is None or armature.type != "ARMATURE":
        raise RigComponentCompileError(
            "Character posing components require an Armature SpriteObject."
        )
    issues = validate_component_spec(component_to_spec(component))
    if issues:
        raise RigComponentCompileError("; ".join(issue.message for issue in issues))
    _validate_blender_sources(armature, component)
    _validate_limb_animation_conversion(armature, component)
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
        try:
            if component.component_type in {"ROOT", "FK_CHAIN", "SPINE_FK"}:
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
        except Exception as exc:
            try:
                rollback_component_build(armature, component, snapshot)
            except Exception as rollback_error:
                raise RigComponentCompileError(
                    f"{exc}; rollback also failed: {rollback_error}"
                ) from exc
            if isinstance(exc, RigComponentCompileError):
                raise
            if isinstance(exc, ComponentArtifactConflict):
                raise RigComponentCompileError(str(exc)) from exc
            raise
    component.needs_rebuild = False
    component.last_error = ""
    return {
        "component_uuid": component.component_uuid,
        "primary_control_bone": primary.name,
        "frame_bone": component.frame_bone,
        "artifacts": len(component.artifacts),
    }
