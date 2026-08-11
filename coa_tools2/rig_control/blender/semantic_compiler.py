"""Transactional compiler for composable semantic character rig stages."""

from __future__ import annotations

from dataclasses import dataclass
import uuid

import bpy
from mathutils import Vector

from ..pose_field import validate_pose_field
from .artifacts import ensure_rig_instance_id
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
    semantic_stage_role,
)
from .semantic_contact import (
    _clear_pin_constraint_marker,
    _owned_contact_constraints,
    _owned_pin_property_locations,
    _remove_pin_property_artifact,
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
from .semantic_secondary import (
    ensure_secondary_motion_artifacts,
)
from .semantic_spline import (
    ensure_spline_chain_artifacts,
    retarget_spline_hooks,
)


class SemanticRigCompileError(RuntimeError):
    pass


@dataclass(frozen=True)
class SemanticStageBuildResult:
    """Physical connection points exported by one semantic DAG stage.

    A component-level ``control_bone`` remains as a backwards-compatible UI
    summary only.  Stage composition must use this per-stage result instead.
    ``spline_info`` is intentionally opaque so the spline/secondary adapters
    can add their build result without coupling this compiler to its type.
    """

    stage_uuid: str
    stage_type: str
    primary_control_bone: str = ""
    art_frame_bone: str = ""
    display_frame_bone: str = ""
    mechanism_frame_bone: str = ""
    projection_source_bone: str = ""
    projection_stage_uuid: str = ""
    spline_info: object | None = None


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


def _preflight_stage_wiring(stages):
    for stage in stages:
        dependencies = _stage_dependencies(stage)
        if stage.stage_type in {"PROJECTED_TRANSFORM", "CHAIN_IK"}:
            if stage.projection_mode != "ART_PLANE":
                raise SemanticRigCompileError(
                    f"Stage '{stage.label}' uses {stage.projection_mode}; Phase 7 "
                    "currently supports the explicit Art Plane projection only."
                )
            if not stage.preserve_art_plane:
                raise SemanticRigCompileError(
                    f"Stage '{stage.label}' must preserve the Art Plane in the "
                    "current presentation adapter."
                )
        if (
            stage.stage_type == "CONTACT_PIN"
            and (
                not stage.pin_driven_bone
                or bool(getattr(stage, "pin_driven_stage_uuid", ""))
            )
        ):
            if not dependencies:
                raise SemanticRigCompileError(
                    f"Contact / Pin '{stage.label}' needs a dependency or an "
                    "explicit Driven Bone."
                )
        if stage.stage_type != "POSE_MAP":
            continue
        for channel in stage.inputs:
            for term in channel.terms:
                requested = str(
                    getattr(term, "source_stage_uuid", "") or ""
                ).strip()
                unresolved = term.source_object is None and not term.source_bone
                if requested and requested not in dependencies:
                    raise SemanticRigCompileError(
                        f"Pose Map '{stage.label}' input term references stage "
                        f"'{requested}', which is not a direct dependency."
                    )
                if unresolved and not requested and len(dependencies) != 1:
                    if dependencies:
                        raise SemanticRigCompileError(
                            f"Pose Map '{stage.label}' has multiple dependencies; "
                            "set Source Stage UUID on each automatically wired input term."
                        )
                    raise SemanticRigCompileError(
                        f"Pose Map '{stage.label}' has an unresolved input but no "
                        "dependency."
                    )


def _validate_sources(armature, component):
    if not component.source_bones:
        raise SemanticRigCompileError("A semantic rig needs at least one source bone.")
    missing = [item.bone_name for item in component.source_bones if item.bone_name not in armature.data.bones]
    if missing:
        raise SemanticRigCompileError("Missing source bone(s): " + ", ".join(missing))


def _validate_pose_map_samples(stages):
    """Reject incomplete/ambiguous recorded data instead of silently dropping it."""

    from .semantic_runtime import pose_field_spec_from_property_group

    for stage in stages:
        if stage.stage_type != "POSE_MAP" or not stage.samples:
            continue
        channel_aliases = tuple(
            {
                value
                for value in (channel.channel_uuid, channel.channel_id)
                if value
            }
            for channel in stage.inputs
        )
        enabled_outputs = {
            output.output_uuid for output in stage.outputs if output.enabled
        }
        for sample in stage.samples:
            recorded = {item.channel_id for item in sample.inputs if item.channel_id}
            missing_channels = [
                channel.label or channel.channel_id
                for channel, aliases in zip(stage.inputs, channel_aliases)
                if not (recorded & aliases)
            ]
            if missing_channels:
                raise SemanticRigCompileError(
                    f"Pose sample '{sample.label}' is missing dimension(s): "
                    + ", ".join(missing_channels)
                )
            recorded_outputs = {
                item.output_uuid for item in sample.outputs if item.output_uuid
            }
            missing_outputs = enabled_outputs - recorded_outputs
            if missing_outputs:
                raise SemanticRigCompileError(
                    f"Pose sample '{sample.label}' is missing {len(missing_outputs)} "
                    "enabled output value(s). Re-record or migrate the sample."
                )
        spec = pose_field_spec_from_property_group(stage)
        issues = validate_pose_field(spec)
        if issues:
            issue = issues[0]
            raise SemanticRigCompileError(
                f"Pose Map '{stage.label}' is invalid ({issue.code}): {issue.message}"
            )


def _semantic_stage_source_names(component, stage):
    references = stage.source_bones if len(stage.source_bones) else component.source_bones
    return tuple(reference.bone_name for reference in references if reference.bone_name)


def _artifact_stage_uuid(role):
    prefix = "semantic:"
    marker = ":source_presentation:"
    if not role.startswith(prefix) or marker not in role:
        return ""
    return role[len(prefix):].split(marker, 1)[0]


def validate_chain_ik_source_ownership(armature, component, stages):
    """Reject multiple exclusive IK deformation writers before any build.

    Active definitions catch not-yet-built collisions.  Live artifact records
    catch a stale or separately built component that still owns a source-bone
    presentation constraint.  Artifacts of the component currently being
    rebuilt are omitted when their defining stage was removed, because this
    same transaction will reconcile them.
    """

    from .properties import get_rig_data

    rig_data = get_rig_data(armature)
    components = tuple(rig_data.rig_components)
    current_index = next(
        (index for index, candidate in enumerate(components) if candidate == component),
        -1,
    )
    claims = {}

    def add_claim(bone_name, owner, description):
        if not bone_name:
            return
        claims.setdefault(bone_name, {})[owner] = description

    active_stage_ids = {}
    for component_index, candidate in enumerate(components):
        if candidate.component_type != "SEMANTIC":
            continue
        if not candidate.enabled and component_index != current_index:
            continue
        candidate_stages = (
            stages if component_index == current_index else tuple(candidate.semantic_stages)
        )
        stage_ids = set()
        for stage in candidate_stages:
            if not stage.enabled or stage.stage_type not in {"CHAIN_IK", "SPLINE"}:
                continue
            stage_ids.add(stage.stage_uuid)
            owner = (component_index, stage.stage_uuid)
            description = (
                f"{candidate.label or candidate.component_uuid} / "
                f"{stage.label or stage.stage_uuid}"
            )
            for bone_name in _semantic_stage_source_names(candidate, stage):
                add_claim(bone_name, owner, description)
        active_stage_ids[component_index] = stage_ids

    for component_index, candidate in enumerate(components):
        if candidate.component_type != "SEMANTIC":
            continue
        for artifact in candidate.artifacts:
            stage_uuid = _artifact_stage_uuid(artifact.role)
            if not stage_uuid or artifact.data_type != "CONSTRAINT":
                continue
            # Removed stages in the component being rebuilt will be cleaned in
            # this transaction and must not create a false self-conflict.
            if (
                component_index == current_index
                and stage_uuid not in active_stage_ids.get(component_index, set())
            ):
                continue
            pose_bone = armature.pose.bones.get(artifact.bone_name)
            constraint = (
                pose_bone.constraints.get(artifact.constraint_name)
                if pose_bone is not None
                else None
            )
            if constraint is None:
                continue
            owner = (component_index, stage_uuid)
            description = (
                f"{candidate.label or candidate.component_uuid} / "
                f"existing stage {stage_uuid}"
            )
            add_claim(artifact.bone_name, owner, description)

    conflicts = {
        bone_name: tuple(owners.values())
        for bone_name, owners in claims.items()
        if len(owners) > 1
    }
    if conflicts:
        bone_name = sorted(conflicts)[0]
        owners = " | ".join(conflicts[bone_name])
        raise SemanticRigCompileError(
            f"Source bone '{bone_name}' has multiple semantic deformation "
            f"owners ({owners}). Add an explicit blend layer before sharing it."
        )


def _ensure_projected_stage(armature, component, stage):
    frames = ensure_projected_transform_artifacts(armature, component, stage)
    control = armature.pose.bones[frames.control_bone]
    ensure_depth_constraint(control, component)
    return SemanticStageBuildResult(
        stage_uuid=stage.stage_uuid,
        stage_type=stage.stage_type,
        primary_control_bone=frames.control_bone,
        art_frame_bone=frames.art_frame_bone,
        display_frame_bone=frames.display_frame_bone,
        projection_source_bone=frames.control_bone,
        projection_stage_uuid=stage.stage_uuid,
    )


def _ensure_ik_stage(armature, component, stage):
    result = ensure_projected_ik_artifacts(armature, component, stage)
    return SemanticStageBuildResult(
        stage_uuid=stage.stage_uuid,
        stage_type=stage.stage_type,
        primary_control_bone=result.frames.control_bone,
        art_frame_bone=result.frames.art_frame_bone,
        display_frame_bone=result.frames.display_frame_bone,
        mechanism_frame_bone=(result.mechanism_bones[0] if result.mechanism_bones else ""),
        projection_source_bone=result.frames.control_bone,
        projection_stage_uuid=stage.stage_uuid,
    )


def _dependency_results(stage, built_stages):
    return tuple(built_stages[value] for value in _stage_dependencies(stage))


def _unique_result_value(results, attribute):
    values = {
        getattr(result, attribute)
        for result in results
        if getattr(result, attribute)
    }
    return next(iter(values)) if len(values) == 1 else ""


def _passthrough_stage_result(stage, dependencies):
    """Propagate a non-physical stage's unambiguous connection points."""

    spline_infos = [
        result.spline_info for result in dependencies if result.spline_info is not None
    ]
    return SemanticStageBuildResult(
        stage_uuid=stage.stage_uuid,
        stage_type=stage.stage_type,
        primary_control_bone=_unique_result_value(
            dependencies, "primary_control_bone"
        ),
        art_frame_bone=_unique_result_value(dependencies, "art_frame_bone"),
        display_frame_bone=_unique_result_value(
            dependencies, "display_frame_bone"
        ),
        mechanism_frame_bone=_unique_result_value(
            dependencies, "mechanism_frame_bone"
        ),
        projection_source_bone=_unique_result_value(
            dependencies, "projection_source_bone"
        ),
        projection_stage_uuid=_unique_result_value(
            dependencies, "projection_stage_uuid"
        ),
        spline_info=spline_infos[0] if len(spline_infos) == 1 else None,
    )


def _term_dependency_uuid(stage, term, dependencies):
    dependency_ids = tuple(result.stage_uuid for result in dependencies)
    requested = str(getattr(term, "source_stage_uuid", "") or "").strip()
    unresolved = term.source_object is None and not term.source_bone
    if requested:
        if requested not in dependency_ids:
            raise SemanticRigCompileError(
                f"Pose Map '{stage.label}' input term references stage "
                f"'{requested}', which is not a direct dependency."
            )
        return requested
    if not unresolved:
        return ""
    if len(dependency_ids) == 1:
        return dependency_ids[0]
    if not dependency_ids:
        raise SemanticRigCompileError(
            f"Pose Map '{stage.label}' has an unresolved input but no dependency."
        )
    raise SemanticRigCompileError(
        f"Pose Map '{stage.label}' has multiple dependencies; set Source Stage UUID "
        "on each automatically wired input term."
    )


def _bind_apparent_depth(
    armature,
    stage,
    channel,
    dependency_uuid,
    built_stages,
    stages_by_uuid,
):
    dependency = built_stages[dependency_uuid]
    if not dependency.primary_control_bone:
        raise SemanticRigCompileError(
            f"Dependency '{dependency_uuid}' does not export a primary control "
            f"for Pose Map '{stage.label}'."
        )
    projection_uuid = dependency.projection_stage_uuid
    projection_stage = stages_by_uuid.get(projection_uuid)
    art_bone = armature.data.bones.get(dependency.art_frame_bone)
    if projection_stage is None or art_bone is None:
        return False
    frame = art_bone.matrix_local.to_3x3()
    visual = Vector(tuple(projection_stage.visual_axis))
    normal = frame.col[2].normalized()
    visual -= normal * visual.dot(normal)
    if visual.length <= 1.0e-8:
        return False
    visual.normalize()
    channel.terms.clear()
    for transform, coefficient in (
        ("LOC_X", visual.dot(frame.col[0].normalized())),
        ("LOC_Y", visual.dot(frame.col[1].normalized())),
    ):
        term = channel.terms.add()
        term.term_uuid = str(uuid.uuid4())
        term.source_stage_uuid = dependency_uuid
        term.source_object = armature
        term.source_bone = dependency.primary_control_bone
        term.source_kind = "TRANSFORM"
        term.transform_type = transform
        term.transform_space = "LOCAL_SPACE"
        term.coefficient = coefficient
    return True


def _bind_pose_map_inputs(armature, stage, built_stages, stages_by_uuid):
    dependencies = _dependency_results(stage, built_stages)
    by_dependency = {result.stage_uuid: result for result in dependencies}
    for channel in stage.inputs:
        # A single automatically wired apparent-depth term is expanded into
        # the two art-plane axes defined by its dependency's projected frame.
        if len(channel.terms) == 1 and channel.channel_id == "apparent_depth":
            term = channel.terms[0]
            dependency_uuid = _term_dependency_uuid(stage, term, dependencies)
            if dependency_uuid and _bind_apparent_depth(
                armature,
                stage,
                channel,
                dependency_uuid,
                built_stages,
                stages_by_uuid,
            ):
                continue
        for term in channel.terms:
            dependency_uuid = _term_dependency_uuid(stage, term, dependencies)
            if dependency_uuid:
                dependency = by_dependency[dependency_uuid]
                if not dependency.primary_control_bone:
                    raise SemanticRigCompileError(
                        f"Dependency '{dependency_uuid}' does not export a primary "
                        f"control for Pose Map '{stage.label}'."
                    )
                term.source_stage_uuid = dependency_uuid
                term.source_object = armature
                term.source_bone = dependency.primary_control_bone
            elif term.source_object is None and term.source_bone:
                # An explicit bone source without an object means this rig.
                term.source_object = armature


def _contact_default_driven(stage, dependencies):
    auto_wired = bool(getattr(stage, "pin_driven_stage_uuid", ""))
    if stage.pin_driven_bone and not auto_wired:
        return "", ""
    controls = {
        result.primary_control_bone
        for result in dependencies
        if result.primary_control_bone
    }
    if len(controls) == 1:
        control = next(iter(controls))
        provider = next(
            result.stage_uuid
            for result in dependencies
            if result.primary_control_bone == control
        )
        return control, provider
    if not controls:
        raise SemanticRigCompileError(
            f"Contact / Pin '{stage.label}' dependencies do not export a primary control."
        )
    raise SemanticRigCompileError(
        f"Contact / Pin '{stage.label}' dependencies export multiple controls; "
        "set Driven Bone explicitly."
    )


def _contact_stage_result(stage, pin, dependencies):
    inherited = _passthrough_stage_result(stage, dependencies)
    return SemanticStageBuildResult(
        stage_uuid=stage.stage_uuid,
        stage_type=stage.stage_type,
        primary_control_bone=pin.driven_bone,
        art_frame_bone=inherited.art_frame_bone,
        display_frame_bone=inherited.display_frame_bone,
        mechanism_frame_bone=inherited.mechanism_frame_bone,
        projection_source_bone=inherited.projection_source_bone,
        projection_stage_uuid=inherited.projection_stage_uuid,
        spline_info=inherited.spline_info,
    )


def _ensure_spline_stage(armature, component, stage, dependencies):
    dependency_frames = {
        result.art_frame_bone
        for result in dependencies
        if result.art_frame_bone
    }
    if len(dependency_frames) > 1:
        raise SemanticRigCompileError(
            f"Spline '{stage.label}' dependencies export multiple Art Frames."
        )
    art_frame_bone = next(iter(dependency_frames), "")
    spline = ensure_spline_chain_artifacts(
        armature,
        component,
        stage,
        art_frame_bone=art_frame_bone,
    )
    return SemanticStageBuildResult(
        stage_uuid=stage.stage_uuid,
        stage_type=stage.stage_type,
        primary_control_bone=spline.primary_control_bone,
        art_frame_bone=spline.art_frame_bone,
        mechanism_frame_bone=(
            spline.mechanism_bones[0] if spline.mechanism_bones else ""
        ),
        projection_source_bone=spline.primary_control_bone,
        projection_stage_uuid=stage.stage_uuid,
        spline_info=spline,
    )


def _ensure_secondary_stage(armature, component, stage, dependencies):
    spline_results = [
        result for result in dependencies if result.spline_info is not None
    ]
    if len(spline_results) != 1:
        raise SemanticRigCompileError(
            f"Secondary Motion '{stage.label}' needs exactly one Spline dependency."
        )
    inherited = _passthrough_stage_result(stage, dependencies)
    spline = spline_results[0].spline_info
    configured_sources = tuple(
        reference.bone_name
        for reference in stage.source_bones
        if reference.bone_name
    ) or tuple(spline.control_bones)
    source_signature = "\n".join(configured_sources)
    if (
        stage.secondary_baked
        and stage.secondary_source_signature != source_signature
    ):
        # A bake is tied to an ordered source list.  Structural Spline edits
        # must fall back to live following until the user explicitly rebakes.
        stage.secondary_baked = False
        stage.secondary_source_signature = ""
    secondary = ensure_secondary_motion_artifacts(
        armature,
        component,
        stage,
        default_source_bones=spline.control_bones,
    )
    if len(secondary.output_bones) != len(spline.hook_bindings):
        raise SemanticRigCompileError(
            f"Secondary Motion '{stage.label}' has {len(secondary.output_bones)} "
            f"outputs for {len(spline.hook_bindings)} Spline points."
        )
    # Pinned endpoints stay authored controls; every movable point receives
    # the corresponding deterministic SIM output.  This keeps root/tip pin
    # policy independent from the spring layer.
    hook_targets = tuple(
        binding.bone_name if binding.pinned else output_bone
        for binding, output_bone in zip(
            spline.hook_bindings, secondary.output_bones
        )
    )
    retarget_spline_hooks(
        spline.curve_object,
        hook_targets,
        armature=armature,
        hook_names=spline.hook_modifiers,
    )
    return SemanticStageBuildResult(
        stage_uuid=stage.stage_uuid,
        stage_type=stage.stage_type,
        primary_control_bone=inherited.primary_control_bone,
        art_frame_bone=inherited.art_frame_bone,
        display_frame_bone=inherited.display_frame_bone,
        mechanism_frame_bone=(
            secondary.output_bones[0]
            if secondary.output_bones
            else inherited.mechanism_frame_bone
        ),
        projection_source_bone=inherited.projection_source_bone,
        projection_stage_uuid=inherited.projection_stage_uuid,
        spline_info=spline,
    )


def _restore_stage_fields(component, snapshot):
    by_uuid = {stage.stage_uuid: stage for stage in component.semantic_stages}
    for stage_uuid, values in snapshot.items():
        stage = by_uuid.get(stage_uuid)
        if stage is None:
            continue
        for name, value in values.items():
            setattr(stage, name, value)


def _expected_stage_roles(component, stages, built_stages=None):
    expected = set()
    for stage in stages:
        role = lambda value: semantic_stage_role(stage.stage_uuid, value)
        if stage.stage_type in {"PROJECTED_TRANSFORM", "CHAIN_IK"}:
            expected.update(
                {
                    role("art_frame"),
                    role("display_frame"),
                    role("control_bone"),
                    role("display_follow"),
                    role("display_plane_limit"),
                }
            )
        if stage.stage_type == "CHAIN_IK":
            count = len(stage.source_bones) or len(component.source_bones)
            expected.add(role("ik_constraint"))
            for index in range(count):
                expected.update(
                    {
                        role(f"mechanism_bone:{index}"),
                        role(f"presentation_bone:{index}"),
                        role(f"presentation_copy:{index}"),
                        role(f"presentation_stretch:{index}"),
                        role(f"source_bone:{index}"),
                        role(f"source_presentation:{index}"),
                    }
                )
            for index in range(count + 1):
                expected.update(
                    {
                        role(f"projected_joint:{index}"),
                        role(f"joint_copy:{index}"),
                        role(f"joint_plane_limit:{index}"),
                    }
                )
            if stage.use_pole:
                expected.update(
                    {
                        role("pole_control"),
                        role("pole_bend_center"),
                        role("pole_distance_constraint"),
                    }
                )
        elif stage.stage_type == "CONTACT_PIN":
            expected.update(
                {
                    role("pin_anchor"),
                    role("pin_constraint"),
                    role("pin_influence_driver"),
                    role("pin_property"),
                }
            )
        elif stage.stage_type == "SPLINE":
            source_count = len(stage.source_bones) or len(component.source_bones)
            control_count = int(stage.spline_control_count)
            expected.update({role("spline_curve"), role("spline_ik_constraint")})
            built = (built_stages or {}).get(stage.stage_uuid)
            spline = built.spline_info if built is not None else None
            if spline is not None and spline.art_frame_owned:
                expected.add(role("art_frame"))
            for index in range(source_count):
                expected.update(
                    {
                        role(f"spline_mechanism:{index}"),
                        role(f"presentation_bone:{index}"),
                        role(f"presentation_copy:{index}"),
                        role(f"presentation_stretch:{index}"),
                        role(f"source_bone:{index}"),
                        role(f"source_presentation:{index}"),
                    }
                )
            for index in range(source_count + 1):
                expected.update(
                    {
                        role(f"projected_joint:{index}"),
                        role(f"joint_copy:{index}"),
                        role(f"joint_plane_limit:{index}"),
                    }
                )
            for index in range(control_count):
                expected.update(
                    {
                        role(f"spline_control:{index}"),
                        role(f"spline_hook:{index}"),
                    }
                )
        elif stage.stage_type == "SECONDARY_MOTION":
            built = (built_stages or {}).get(stage.stage_uuid)
            spline = built.spline_info if built is not None else None
            # A successful Secondary build is required to match the Spline's
            # Hook/control count.  Use that reconciled result when available,
            # including through pass-through Pose Map or Contact stages.
            source_count = len(spline.control_bones) if spline is not None else 0
            if not source_count:
                source_count = len(stage.source_bones)
            if not source_count:
                dependencies = _stage_dependencies(stage)
                dependency = next(
                    (
                        candidate
                        for candidate in stages
                        if candidate.stage_uuid in dependencies
                        and candidate.stage_type == "SPLINE"
                    ),
                    None,
                )
                source_count = (
                    int(dependency.spline_control_count)
                    if dependency is not None
                    else len(component.source_bones)
                )
            for index in range(source_count):
                expected.update(
                    {
                        role(f"secondary_output:{index}"),
                        role(f"secondary_follow:{index}"),
                    }
                )
            if stage.secondary_baked:
                expected.update(
                    {
                        role("secondary_action"),
                        role("secondary_nla_track"),
                    }
                )
    return expected


def _matches_semantic_owner(owner, armature, component, role):
    return (
        owner is not None
        and bool(owner.get("coa_rig_managed"))
        and owner.get("coa_rig_instance_id")
        == ensure_rig_instance_id(armature)
        and owner.get("coa_rig_component_uuid") == component.component_uuid
        and owner.get("coa_rig_component_role") == role
    )


def _owned_constraint_locations(armature, component, role):
    from .component_artifacts import _recorded_constraint

    artifacts = [
        artifact
        for artifact in component.artifacts
        if artifact.owned
        and artifact.data_type == "CONSTRAINT"
        and artifact.role == role
    ]
    if len(artifacts) > 1:
        raise SemanticRigCompileError(
            f"Multiple Constraint artifacts use role '{role}'."
        )
    if not artifacts:
        return ()
    artifact = artifacts[0]

    # A generated owner bone can be renamed safely because Bone ID properties
    # are supported. Resolve it through the companion BONE artifact role, then
    # synchronize the Constraint artifact before applying the conservative
    # name/type resolver used by normal builds.
    pose_bone = None
    owner_records = [
        candidate
        for candidate in component.artifacts
        if candidate.data_type == "BONE"
        and candidate.bone_name == artifact.bone_name
    ]
    for owner_record in owner_records:
        tagged = [
            candidate
            for candidate in armature.data.bones
            if _matches_semantic_owner(
                candidate,
                armature,
                component,
                owner_record.role,
            )
        ]
        if len(tagged) > 1:
            raise SemanticRigCompileError(
                f"Multiple generated bones use role '{owner_record.role}'."
            )
        if tagged:
            pose_bone = armature.pose.bones.get(tagged[0].name)
            artifact.bone_name = tagged[0].name
            break
    if pose_bone is None:
        pose_bone = armature.pose.bones.get(artifact.bone_name)
    if pose_bone is None:
        return ()

    constraint_type = _semantic_constraint_type(role)
    if not constraint_type:
        raise SemanticRigCompileError(
            f"Unknown generated Constraint role '{role}'."
        )
    constraint = _recorded_constraint(
        pose_bone,
        component,
        role,
        constraint_type,
        allow_missing=True,
    )
    return ((pose_bone, constraint),) if constraint is not None else ()


def _semantic_constraint_type(role):
    detail = ":".join(str(role).split(":")[2:])
    if detail == "ik_constraint":
        return "IK"
    if detail == "pole_distance_constraint":
        return "LIMIT_DISTANCE"
    if detail == "spline_ik_constraint":
        return "SPLINE_IK"
    if detail == "display_follow":
        return "COPY_LOCATION"
    if detail.startswith(("joint_copy:", "presentation_copy:")):
        return "COPY_LOCATION"
    if detail == "display_plane_limit":
        return "LIMIT_LOCATION"
    if detail.startswith("joint_plane_limit:"):
        return "LIMIT_LOCATION"
    if detail.startswith("presentation_stretch:"):
        return "STRETCH_TO"
    if detail.startswith(("source_presentation:", "secondary_follow:")):
        return "COPY_TRANSFORMS"
    return ""


def _owned_modifier_locations(armature, component, role):
    artifacts = [
        artifact
        for artifact in component.artifacts
        if artifact.owned
        and artifact.data_type == "MODIFIER"
        and artifact.role == role
    ]
    if len(artifacts) > 1:
        raise SemanticRigCompileError(
            f"Multiple Modifier artifacts use role '{role}'."
        )
    if not artifacts:
        return ()
    artifact = artifacts[0]
    parts = str(role).split(":")
    stage_prefix = ":".join(parts[:2]) if len(parts) >= 2 else ""
    curve_role = f"{stage_prefix}:spline_curve"
    tagged_objects = [
        obj
        for obj in bpy.data.objects
        if _matches_semantic_owner(
            obj,
            armature,
            component,
            curve_role,
        )
    ]
    if len(tagged_objects) > 1:
        raise SemanticRigCompileError(
            f"Multiple generated Curves use role '{curve_role}'."
        )
    obj = tagged_objects[0] if tagged_objects else bpy.data.objects.get(
        artifact.object_name
    )
    if obj is None:
        return ()
    if tagged_objects:
        for candidate in component.artifacts:
            if (
                candidate.data_type == "MODIFIER"
                and candidate.role.startswith(f"{stage_prefix}:spline_hook:")
            ):
                candidate.object_name = obj.name
    referenced_names = {
        candidate.constraint_name
        for candidate in component.artifacts
        if candidate.owned
        and candidate.data_type == "MODIFIER"
        and candidate.object_name == obj.name
        and candidate.constraint_name
    }
    unrecorded_hooks = [
        modifier
        for modifier in obj.modifiers
        if modifier.type == "HOOK" and modifier.name not in referenced_names
    ]
    modifier = obj.modifiers.get(artifact.constraint_name)
    if modifier is None:
        if unrecorded_hooks:
            raise SemanticRigCompileError(
                f"Generated Hook for role '{role}' may have been renamed; "
                "ownership is ambiguous."
            )
        return ()
    if modifier.type != "HOOK":
        raise SemanticRigCompileError(
            f"Recorded Hook name '{artifact.constraint_name}' is now used by "
            "an incompatible Modifier."
        )
    if unrecorded_hooks:
        raise SemanticRigCompileError(
            f"Hook ownership for role '{role}' is ambiguous after a rename."
        )
    return ((obj, modifier),)


def _remove_owned_pin_driver(armature, binding_uuid, valid_paths):
    animation_data = armature.animation_data
    if animation_data is None or not binding_uuid or not valid_paths:
        return
    token = "".join(
        character for character in binding_uuid if character.isalnum()
    )
    markers = {f"cp_{token}", f"cp_{token[:8]}"}
    for fcurve in tuple(animation_data.drivers):
        if fcurve.data_path not in valid_paths:
            continue
        owned = any(
            variable.name in markers
            and any(target.id == armature for target in variable.targets)
            for variable in fcurve.driver.variables
        )
        if not owned:
            continue
        try:
            armature.driver_remove(fcurve.data_path, fcurve.array_index)
        except (AttributeError, KeyError, RuntimeError, TypeError):
            try:
                armature.driver_remove(fcurve.data_path)
            except (AttributeError, KeyError, RuntimeError, TypeError):
                pass


def _secondary_action_role(nla_role):
    prefix, _separator, _leaf = nla_role.rpartition(":")
    return f"{prefix}:secondary_action"


def _remove_owned_nla_tracks(armature, component, role):
    animation_data = armature.animation_data
    if animation_data is None:
        return
    action_role = _secondary_action_role(role)
    for track in tuple(animation_data.nla_tracks):
        if any(
            strip.action is not None
            and _matches_semantic_owner(
                strip.action,
                armature,
                component,
                action_role,
            )
            for strip in track.strips
        ):
            animation_data.nla_tracks.remove(track)


def _remove_owned_actions(armature, component, role):
    for action in tuple(bpy.data.actions):
        if not _matches_semantic_owner(action, armature, component, role):
            continue
        # One user is the generated Action's fake-user.  Preserve anything
        # that is also linked from data outside this stage.
        if action.users <= 1:
            bpy.data.actions.remove(action)


def _cleanup_obsolete_stage_artifacts(armature, component, expected_roles):
    obsolete = [
        {
            "index": index,
            "role": artifact.role,
            "data_type": artifact.data_type,
            "object_name": artifact.object_name,
            "bone_name": artifact.bone_name,
            "constraint_name": artifact.constraint_name,
            "data_path": artifact.data_path,
            "binding_uuid": artifact.binding_uuid,
            "owned": artifact.owned,
        }
        for index, artifact in enumerate(component.artifacts)
        if artifact.role.startswith("semantic:")
        and artifact.role not in expected_roles
    ]
    # NLA tracks own users of their Actions, so remove them before Actions.
    for item in obsolete:
        if item["owned"] and item["data_type"] == "NLA_TRACK":
            _remove_owned_nla_tracks(
                armature,
                component,
                item["role"],
            )

    # Resolve Pin owners while the live stage driver still identifies its
    # constraint. Saved names may be stale and are never destructive authority.
    pin_constraint_locations = {}
    for item in obsolete:
        if not item["owned"]:
            continue
        role = item["role"]
        if role.endswith(":pin_constraint"):
            pin_constraint_locations.setdefault(
                role,
                _owned_contact_constraints(armature, component, role),
            )
        elif role.endswith(":pin_property") or role.endswith(
            ":pin_influence_driver"
        ):
            prefix, _separator, _leaf = role.rpartition(":")
            constraint_role = f"{prefix}:pin_constraint"
            pin_constraint_locations.setdefault(
                constraint_role,
                _owned_contact_constraints(armature, component, constraint_role),
            )

    pin_property_owners = {}
    for item in obsolete:
        if not item["owned"] or item["data_type"] != "ID_PROPERTY":
            continue
        prefix, _separator, _leaf = item["role"].rpartition(":")
        constraint_role = f"{prefix}:pin_constraint"
        locations = pin_constraint_locations.get(constraint_role, ())
        stage_uuid = item["binding_uuid"] or prefix.removeprefix("semantic:")
        property_locations = (
            _owned_pin_property_locations(
                armature,
                component,
                stage_uuid,
            )
            if stage_uuid
            else ()
        )
        if len(property_locations) == 1:
            pin_property_owners[item["role"]] = property_locations[0]
        elif len(locations) == 1:
            pin_property_owners[item["role"]] = (
                locations[0][0],
                item["constraint_name"],
            )

    # A PoseBone ID property has no native ownership tags.  Remove it while
    # its companion marker or live Pin driver proves the actual owner; never
    # use the artifact's saved bone or object name as authority.
    active_action = armature.animation_data.action if armature.animation_data else None
    for item in obsolete:
        if not item["owned"] or item["data_type"] != "ID_PROPERTY":
            continue
        owner_and_property = pin_property_owners.get(item["role"])
        prefix, _separator, _leaf = item["role"].rpartition(":")
        stage_uuid = item["binding_uuid"] or prefix.removeprefix("semantic:")
        if owner_and_property is None or not stage_uuid:
            continue
        owner, property_name = owner_and_property
        _remove_pin_property_artifact(
            armature,
            component,
            stage_uuid,
            owner,
            property_name,
            action=active_action,
            allow_legacy_owned=True,
        )

    # Remove the live driver before its constraint.  Cache resolution above is
    # required because Constraints cannot carry ownership ID properties in
    # Blender 5.1; the driver's stage marker is the authoritative live link.
    for item in obsolete:
        if (
            not item["owned"]
            or item["data_type"] != "DRIVER"
            or not item["role"].endswith(":pin_influence_driver")
        ):
            continue
        prefix, _separator, _leaf = item["role"].rpartition(":")
        constraint_role = f"{prefix}:pin_constraint"
        stage_uuid = item["binding_uuid"] or prefix.removeprefix("semantic:")
        valid_paths = {
            constraint.path_from_id("influence")
            for _pose_bone, constraint in pin_constraint_locations.get(
                constraint_role,
                (),
            )
        }
        _remove_owned_pin_driver(
            armature,
            stage_uuid,
            valid_paths,
        )

    for item in obsolete:
        if not item["owned"]:
            continue
        role = item["role"]
        data_type = item["data_type"]
        if data_type == "DRIVER":
            if role.endswith(":pin_influence_driver"):
                # Removed from the cached live constraint in the Pin pre-pass.
                continue
            prefix, _separator, _leaf = role.rpartition(":")
            constraint_role = f"{prefix}:pin_constraint"
            stage_uuid = item["binding_uuid"] or prefix.removeprefix("semantic:")
            valid_paths = {
                constraint.path_from_id("influence")
                for _pose_bone, constraint in pin_constraint_locations.get(
                    constraint_role,
                    (),
                )
            }
            _remove_owned_pin_driver(
                armature,
                stage_uuid,
                valid_paths,
            )
        elif data_type == "CONSTRAINT":
            locations = (
                pin_constraint_locations.get(role, ())
                if role.endswith(":pin_constraint")
                else _owned_constraint_locations(armature, component, role)
            )
            for pose_bone, constraint in locations:
                if role.endswith(":pin_constraint"):
                    prefix, _separator, _leaf = role.rpartition(":")
                    stage_uuid = prefix.removeprefix("semantic:")
                    _clear_pin_constraint_marker(
                        armature,
                        component,
                        stage_uuid,
                        pose_bone,
                    )
                pose_bone.constraints.remove(constraint)
        elif data_type == "MODIFIER":
            for obj, modifier in _owned_modifier_locations(
                armature,
                component,
                role,
            ):
                obj.modifiers.remove(modifier)
        elif data_type == "ACTION":
            _remove_owned_actions(armature, component, role)
        elif data_type == "ID_PROPERTY":
            # Removed in the ownership-proving pre-pass above.
            pass

    owned_bones = {
        bone.name
        for item in obsolete
        if item["owned"] and item["data_type"] == "BONE"
        for bone in armature.data.bones
        if _matches_semantic_owner(
            bone,
            armature,
            component,
            item["role"],
        )
    }
    if owned_bones:
        if armature.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.context.view_layer.objects.active = armature
        armature.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        for bone_name in owned_bones:
            edit_bone = armature.data.edit_bones.get(bone_name)
            if edit_bone is not None:
                armature.data.edit_bones.remove(edit_bone)
        bpy.ops.object.mode_set(mode="POSE")
    for item in obsolete:
        if item["owned"] and item["data_type"] == "OBJECT":
            for obj in tuple(bpy.data.objects):
                if _matches_semantic_owner(
                    obj,
                    armature,
                    component,
                    item["role"],
                ):
                    # Only a tag match, never a reused serialized name, can
                    # authorize deleting Blender data.
                    if obj.users_collection or obj.users <= 1:
                        bpy.data.objects.remove(obj, do_unlink=True)

    for index in sorted(
        (item["index"] for item in obsolete),
        reverse=True,
    ):
        if index < len(component.artifacts):
            component.artifacts.remove(index)
    # Remove legacy records whose owner vanished with a semantic stage.
    for index in range(len(component.artifacts) - 1, -1, -1):
        artifact = component.artifacts[index]
        if artifact.data_type == "CONSTRAINT" and artifact.bone_name:
            pose_bone = armature.pose.bones.get(artifact.bone_name)
            if pose_bone is None or pose_bone.constraints.get(artifact.constraint_name) is None:
                component.artifacts.remove(index)


def compile_semantic_component(armature, component):
    if armature is None or armature.type != "ARMATURE":
        raise SemanticRigCompileError("Semantic character rigs require an Armature.")
    if component.component_type != "SEMANTIC":
        raise SemanticRigCompileError("Not a semantic character rig component.")
    if component.deformation_mode != "PARAMETRIC":
        raise SemanticRigCompileError(
            "Semantic rigs separate mechanism and artwork; use Parametric deformation."
        )
    if component.bindings:
        raise SemanticRigCompileError(
            "Character Rig has legacy Pose Outputs. Remove them and use a "
            "Recorded Pose Map stage instead."
        )
    stages = ordered_semantic_stages(component)
    _validate_sources(armature, component)
    _validate_pose_map_samples(stages)
    _preflight_stage_wiring(stages)
    validate_chain_ik_source_ownership(armature, component, stages)
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
                "pin_driven_bone": stage.pin_driven_bone,
                "pin_driven_stage_uuid": stage.pin_driven_stage_uuid,
                "curve_object": stage.curve_object,
                "secondary_baked": stage.secondary_baked,
                "secondary_source_signature": stage.secondary_source_signature,
            }
            for stage in component.semantic_stages
        }
        built_stages = {}
        stages_by_uuid = {stage.stage_uuid: stage for stage in stages}
        try:
            for stage in stages:
                dependencies = _dependency_results(stage, built_stages)
                if stage.stage_type == "PROJECTED_TRANSFORM":
                    result = _ensure_projected_stage(armature, component, stage)
                elif stage.stage_type == "POSE_MAP":
                    _bind_pose_map_inputs(
                        armature,
                        stage,
                        built_stages,
                        stages_by_uuid,
                    )
                    result = _passthrough_stage_result(stage, dependencies)
                elif stage.stage_type == "CHAIN_IK":
                    result = _ensure_ik_stage(armature, component, stage)
                elif stage.stage_type == "CONTACT_PIN":
                    default_driven, provider_uuid = _contact_default_driven(
                        stage, dependencies
                    )
                    if provider_uuid:
                        # Remove the prior compiled default so the contact
                        # builder cannot accidentally prefer a stale field.
                        stage.pin_driven_bone = ""
                    pin = ensure_contact_pin_artifacts(
                        armature,
                        component,
                        stage,
                        default_driven_bone=default_driven,
                    )
                    stage.pin_driven_stage_uuid = provider_uuid
                    result = _contact_stage_result(stage, pin, dependencies)
                elif stage.stage_type == "SPLINE":
                    result = _ensure_spline_stage(
                        armature, component, stage, dependencies
                    )
                elif stage.stage_type == "SECONDARY_MOTION":
                    result = _ensure_secondary_stage(
                        armature, component, stage, dependencies
                    )
                else:
                    result = _passthrough_stage_result(stage, dependencies)
                built_stages[stage.stage_uuid] = result
            # The initial preflight compares explicit destinations or DAG
            # identities.  Once all Contact layers are built, verify the
            # actual driven bones as well; this catches two branches that
            # converge onto the same control without rejecting independent
            # branches that merely share a component.
            validate_pin_ranges(component, resolved=True)
            primary_result = next(
                (
                    built_stages[stage.stage_uuid]
                    for stage in reversed(stages)
                    if built_stages[stage.stage_uuid].primary_control_bone
                ),
                None,
            )
            if primary_result is None:
                raise SemanticRigCompileError(
                    "Add a Projected Transform, Kinematic Chain, or Spline input stage."
                )
            # Backwards-compatible summary fields only.  DAG connections above
            # always resolve through ``built_stages`` and never read these.
            component.control_bone = primary_result.primary_control_bone
            component.frame_bone = primary_result.art_frame_bone
            component.pole_bone = next(
                (
                    stage.pole_bone
                    for stage in reversed(stages)
                    if stage.stage_type == "CHAIN_IK" and stage.pole_bone
                ),
                "",
            )
            compiled_outputs = reconcile_semantic_outputs(armature, component)
            _cleanup_obsolete_stage_artifacts(
                armature,
                component,
                _expected_stage_roles(component, stages, built_stages),
            )
            for candidate in component.semantic_stages:
                if (
                    candidate.stage_type != "SECONDARY_MOTION"
                    or not candidate.enabled
                ):
                    candidate.secondary_baked = False
                    candidate.secondary_source_signature = ""
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
        "primary_control_bone": primary_result.primary_control_bone,
        "frame_bone": component.frame_bone,
        "artifacts": len(component.artifacts),
        "bindings": compiled_outputs,
        "semantic_stages": len(stages),
        "stage_results": built_stages,
    }
