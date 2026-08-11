"""Transactional compiler for composable semantic character rig stages."""

from __future__ import annotations

import uuid

from mathutils import Vector

from .component_artifacts import ensure_depth_constraint
from .component_safety import (
    ComponentPreflightError,
    capture_component_build_state,
    ensure_unique_component_instance,
    preflight_component_artifacts,
    preserve_component_context,
    rollback_component_build,
)
from .semantic_artifacts import (
    SemanticArtifactError,
    ensure_projected_ik_artifacts,
    ensure_projected_transform_artifacts,
)
from .semantic_contact import (
    SemanticContactError,
    ensure_contact_pin_artifacts,
    validate_pin_ranges,
)
from .semantic_outputs import (
    SemanticOutputError,
    capture_semantic_output_state,
    preflight_semantic_outputs,
    reconcile_semantic_outputs,
    restore_semantic_output_state,
)


class SemanticRigCompileError(RuntimeError):
    pass


def _stage_dependencies(stage):
    return tuple(token.strip() for token in stage.depends_on.split(",") if token.strip())


def ordered_semantic_stages(component):
    enabled = [stage for stage in component.semantic_stages if stage.enabled]
    uuids = [stage.stage_uuid for stage in enabled]
    if any(not value for value in uuids):
        raise SemanticRigCompileError("Every semantic stage needs a UUID.")
    if len(set(uuids)) != len(uuids):
        raise SemanticRigCompileError("Semantic stage UUIDs must be unique.")
    by_uuid = {stage.stage_uuid: stage for stage in enabled}
    incoming = {value: set(_stage_dependencies(stage)) for value, stage in by_uuid.items()}
    for stage_uuid, dependencies in incoming.items():
        missing = dependencies - set(by_uuid)
        if missing:
            raise SemanticRigCompileError(
                f"Stage {stage_uuid} references missing dependencies: {', '.join(sorted(missing))}"
            )
        if stage_uuid in dependencies:
            raise SemanticRigCompileError("A semantic stage cannot depend on itself.")
    ordered = []
    remaining = set(by_uuid)
    while remaining:
        ready = sorted(
            (value for value in remaining if not (incoming[value] & remaining)),
            key=lambda value: (by_uuid[value].order, value),
        )
        if not ready:
            raise SemanticRigCompileError("Semantic stage dependencies contain a cycle.")
        for value in ready:
            ordered.append(by_uuid[value])
            remaining.remove(value)
    return tuple(ordered)


def _validate_sources(armature, component):
    if not component.source_bones:
        raise SemanticRigCompileError("A semantic rig needs at least one source bone.")
    missing = [item.bone_name for item in component.source_bones if item.bone_name not in armature.data.bones]
    if missing:
        raise SemanticRigCompileError("Missing source bone(s): " + ", ".join(missing))


def _ensure_projected_stage(armature, component, stage):
    frames = ensure_projected_transform_artifacts(armature, component, stage)
    component.control_bone = frames.control_bone
    component.frame_bone = frames.art_frame_bone
    control = armature.pose.bones[frames.control_bone]
    ensure_depth_constraint(control, component)
    return control


def _ensure_ik_stage(armature, component, stage):
    result = ensure_projected_ik_artifacts(armature, component, stage)
    component.control_bone = result.frames.control_bone
    component.frame_bone = result.frames.art_frame_bone
    component.pole_bone = result.pole_bone
    return armature.pose.bones[result.frames.control_bone]


def _bind_unresolved_input_terms(armature, component, control_bone):
    for stage in component.semantic_stages:
        if stage.stage_type != "POSE_MAP":
            continue
        for channel in stage.inputs:
            unresolved = all(
                term.source_object is None and not term.source_bone
                for term in channel.terms
            )
            if unresolved and channel.channel_id == "apparent_depth":
                projected = next(
                    (
                        candidate
                        for candidate in component.semantic_stages
                        if candidate.enabled
                        and candidate.stage_type == "PROJECTED_TRANSFORM"
                        and candidate.art_frame_bone
                    ),
                    None,
                )
                art_bone = (
                    armature.data.bones.get(projected.art_frame_bone)
                    if projected is not None
                    else None
                )
                if art_bone is not None:
                    frame = art_bone.matrix_local.to_3x3()
                    visual = Vector(tuple(projected.visual_axis))
                    normal = frame.col[2].normalized()
                    visual -= normal * visual.dot(normal)
                    if visual.length > 1.0e-8:
                        visual.normalize()
                        channel.terms.clear()
                        for transform, coefficient in (
                            ("LOC_X", visual.dot(frame.col[0].normalized())),
                            ("LOC_Y", visual.dot(frame.col[1].normalized())),
                        ):
                            term = channel.terms.add()
                            term.term_uuid = str(uuid.uuid4())
                            term.source_object = armature
                            term.source_bone = control_bone
                            term.source_kind = "TRANSFORM"
                            term.transform_type = transform
                            term.transform_space = "LOCAL_SPACE"
                            term.coefficient = coefficient
            for term in channel.terms:
                if term.source_object is None:
                    term.source_object = armature
                if term.source_kind == "TRANSFORM" and not term.source_bone:
                    term.source_bone = control_bone


def _restore_stage_fields(component, snapshot):
    by_uuid = {stage.stage_uuid: stage for stage in component.semantic_stages}
    for stage_uuid, values in snapshot.items():
        stage = by_uuid.get(stage_uuid)
        if stage is None:
            continue
        for name, value in values.items():
            setattr(stage, name, value)


def compile_semantic_component(armature, component):
    if armature is None or armature.type != "ARMATURE":
        raise SemanticRigCompileError("Semantic character rigs require an Armature.")
    if component.component_type != "SEMANTIC":
        raise SemanticRigCompileError("Not a semantic character rig component.")
    if component.deformation_mode != "PARAMETRIC":
        raise SemanticRigCompileError(
            "Semantic rigs separate mechanism and artwork; use Parametric deformation."
        )
    stages = ordered_semantic_stages(component)
    _validate_sources(armature, component)
    try:
        validate_pin_ranges(component)
    except SemanticContactError as exc:
        raise SemanticRigCompileError(str(exc)) from exc
    try:
        preflight_semantic_outputs(armature, component)
    except SemanticOutputError as exc:
        raise SemanticRigCompileError(str(exc)) from exc

    with preserve_component_context(armature):
        try:
            preflight_component_artifacts(armature, component)
        except ComponentPreflightError as exc:
            raise SemanticRigCompileError(str(exc)) from exc
        ensure_unique_component_instance(armature)
        structural = capture_component_build_state(armature, component)
        outputs = capture_semantic_output_state(armature, component)
        stage_fields = {
            stage.stage_uuid: {
                "control_bone": stage.control_bone,
                "display_frame_bone": stage.display_frame_bone,
                "mechanism_frame_bone": stage.mechanism_frame_bone,
                "art_frame_bone": stage.art_frame_bone,
                "pole_bone": stage.pole_bone,
                "pin_property": stage.pin_property,
                "curve_object": stage.curve_object,
                "secondary_baked": stage.secondary_baked,
            }
            for stage in component.semantic_stages
        }
        primary = None
        try:
            for stage in stages:
                if stage.stage_type == "PROJECTED_TRANSFORM":
                    primary = _ensure_projected_stage(armature, component, stage)
                elif stage.stage_type == "CHAIN_IK":
                    primary = _ensure_ik_stage(armature, component, stage)
                elif stage.stage_type == "CONTACT_PIN":
                    if primary is None and not stage.pin_driven_bone:
                        raise SemanticRigCompileError(
                            "Contact / Pin needs a preceding input or IK stage."
                        )
                    pin = ensure_contact_pin_artifacts(
                        armature,
                        component,
                        stage,
                        default_driven_bone=primary.name if primary else "",
                    )
                    primary = armature.pose.bones[pin.driven_bone]
            if primary is None:
                raise SemanticRigCompileError(
                    "Add a Projected Transform or Kinematic Chain input stage."
                )
            _bind_unresolved_input_terms(armature, component, primary.name)
            compiled_outputs = reconcile_semantic_outputs(armature, component)
        except Exception as exc:
            structural_error = None
            try:
                rollback_component_build(armature, component, structural)
                _restore_stage_fields(component, stage_fields)
            except Exception as rollback_error:
                structural_error = rollback_error
            output_error = None
            try:
                restore_semantic_output_state(armature, outputs)
            except Exception as rollback_error:
                output_error = rollback_error
            if structural_error is not None:
                raise SemanticRigCompileError(
                    f"{exc}; structural rollback failed: {structural_error}"
                ) from exc
            if output_error is not None:
                raise SemanticRigCompileError(
                    f"{exc}; output rollback failed: {output_error}"
                ) from exc
            if isinstance(exc, SemanticRigCompileError):
                raise
            raise SemanticRigCompileError(str(exc)) from exc

    component.needs_rebuild = False
    component.last_error = ""
    component.compiled_deformation_mode = component.deformation_mode
    return {
        "component_uuid": component.component_uuid,
        "primary_control_bone": primary.name,
        "frame_bone": component.frame_bone,
        "artifacts": len(component.artifacts),
        "bindings": compiled_outputs,
        "semantic_stages": len(stages),
    }
