"""Blender artifacts and transactional baking for Secondary Motion stages.

Generated SIM bones normally follow their ordered source bones through managed
Copy Transforms constraints.  A successful bake writes location-only motion to
a dedicated generated Action/NLA track, then mutes those follow constraints.
Sampling, filtering and Action construction happen before the visible NLA swap
so a failure leaves the previous bake usable.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import uuid
from typing import Callable, Iterable, Sequence

from ..secondary_motion import SecondaryMotionSettings, filter_secondary_motion
from .semantic_artifacts import semantic_stage_role


class SemanticSecondaryError(RuntimeError):
    """Raised when Secondary Motion artifacts or baking cannot be completed."""


@dataclass(frozen=True)
class SecondaryMotionNamePlan:
    output_bones: tuple[str, ...]
    action: str
    nla_track: str


@dataclass(frozen=True)
class SecondaryMotionArtifacts:
    source_bones: tuple[str, ...]
    output_bones: tuple[str, ...]
    follow_constraints: tuple[str, ...]


@dataclass(frozen=True)
class SecondaryMotionBakeResult:
    artifacts: SecondaryMotionArtifacts
    action_name: str
    nla_track_name: str
    frame_start: int
    frame_end: int
    sample_count: int

    @property
    def source_bones(self) -> tuple[str, ...]:
        return self.artifacts.source_bones

    @property
    def output_bones(self) -> tuple[str, ...]:
        return self.artifacts.output_bones


def _slug(value: str, fallback: str) -> str:
    result = re.sub(r"[^0-9A-Za-z_]+", "_", str(value).strip()).strip("_")
    return result or fallback


def secondary_motion_name_plan(
    component_uuid: str,
    stage_uuid: str,
    source_bones: Sequence[str],
) -> SecondaryMotionNamePlan:
    """Return deterministic, Blender-safe names for one Secondary stage."""

    component_key = _slug(component_uuid.replace("-", ""), "component")[:8]
    stage_key = _slug(stage_uuid.replace("-", ""), "secondary")[:8]
    output_bones = tuple(
        (
            f"MCH_SIM_{component_key}_{stage_key}_{index:02d}_"
            f"{_slug(source, 'bone')[:20]}"
        )[:63]
        for index, source in enumerate(source_bones)
    )
    stem = f"COA_SIM_{component_key}_{stage_key}"
    return SecondaryMotionNamePlan(output_bones, stem, stem)


def _identifier(owner, *names: str) -> str:
    for name in names:
        value = getattr(owner, name, "")
        if value:
            return str(value)
    return ""


def _reference_names(references: Iterable[object]) -> tuple[str, ...]:
    names = tuple(
        str(getattr(reference, "bone_name", reference) or "")
        for reference in references
    )
    return tuple(name for name in names if name)


def _source_names(component, stage, default_source_bones=()) -> tuple[str, ...]:
    references = tuple(getattr(stage, "source_bones", ()) or ())
    if references:
        return _reference_names(references)
    defaults = tuple(default_source_bones or ())
    if defaults:
        return _reference_names(defaults)
    return _reference_names(tuple(getattr(component, "source_bones", ()) or ()))


def _component_uuid(component) -> str:
    value = _identifier(component, "component_uuid", "rig_uuid")
    if not value:
        raise SemanticSecondaryError("Rig component UUID is required.")
    return value


def _stage_uuid(stage) -> str:
    value = _identifier(stage, "stage_uuid", "node_uuid")
    if not value:
        raise SemanticSecondaryError("Secondary Motion stage UUID is required.")
    return value


def _constraint_name(stage_uuid: str, index: int) -> str:
    key = _slug(stage_uuid.replace("-", ""), "secondary")[:8]
    return f"COA_SIM_FOLLOW_{key}_{index:02d}"


def ensure_secondary_motion_artifacts(
    armature,
    component,
    stage,
    default_source_bones=(),
) -> SecondaryMotionArtifacts:
    """Idempotently generate ordered SIM output bones for a stage.

    Before baking, every SIM bone follows its source using a managed Copy
    Transforms constraint.  Existing baked stages keep that constraint muted
    so their generated NLA motion remains authoritative.
    """

    if armature is None or getattr(armature, "type", "") != "ARMATURE":
        raise SemanticSecondaryError("Secondary Motion requires an Armature.")
    component_uuid = _component_uuid(component)
    stage_uuid = _stage_uuid(stage)
    source_names = _source_names(
        component, stage, default_source_bones=default_source_bones
    )
    if not source_names:
        raise SemanticSecondaryError("Secondary Motion requires source bones.")
    if len(set(source_names)) != len(source_names):
        raise SemanticSecondaryError("Secondary Motion source bones must be unique.")
    missing = [name for name in source_names if name not in armature.data.bones]
    if missing:
        raise SemanticSecondaryError("Missing source bone(s): " + ", ".join(missing))

    from ... import functions
    from .component_artifacts import (
        COMPONENT_MECHANISM_COLLECTION,
        ComponentArtifactConflict,
        _managed_constraint,
        _record_artifact,
        _set_edit_bone_matrix,
        _switch_to_edit_mode,
        _tag_owned_bone,
        find_component_bone,
    )
    from .semantic_artifacts import _assign_collection, _ensure_edit_bone

    plan = secondary_motion_name_plan(
        component_uuid, stage_uuid, source_names
    )
    roles = tuple(
        semantic_stage_role(stage_uuid, f"secondary_output:{index}")
        for index in range(len(source_names))
    )
    existing_names = tuple(
        (
            bone.name
            if (
                bone := find_component_bone(armature, component_uuid, role)
            ) is not None
            else ""
        )
        for role in roles
    )
    helpers = {
        "functions": functions,
        "mechanism_collection": COMPONENT_MECHANISM_COLLECTION,
        "conflict": ComponentArtifactConflict,
        "managed_constraint": _managed_constraint,
        "record_artifact": _record_artifact,
        "set_edit_bone_matrix": _set_edit_bone_matrix,
        "switch_to_edit_mode": _switch_to_edit_mode,
        "tag_owned_bone": _tag_owned_bone,
        "find_component_bone": find_component_bone,
    }

    helpers["switch_to_edit_mode"](armature)
    try:
        source_edit_bones = tuple(
            armature.data.edit_bones[name] for name in source_names
        )
        output_names = []
        for index, (source, role, default_name, existing_name) in enumerate(
            zip(source_edit_bones, roles, plan.output_bones, existing_names)
        ):
            output = _ensure_edit_bone(
                armature,
                component,
                role=role,
                default_name=default_name,
                existing_name=existing_name,
                helpers=helpers,
            )
            output.parent = None
            output.use_connect = False
            _set_edit_bone_matrix(
                output, source.matrix.copy(), max(float(source.length), 0.01)
            )
            output_names.append(output.name)
    finally:
        import bpy

        if armature.mode == "EDIT":
            bpy.ops.object.mode_set(mode="POSE")

    constraint_names = []
    for index, (source_name, output_name, role) in enumerate(
        zip(source_names, output_names, roles)
    ):
        output_pose = armature.pose.bones[output_name]
        _tag_owned_bone(armature, output_pose.bone, component, role)
        _record_artifact(
            component, role, "BONE", bone_name=output_name, owned=True
        )
        output_pose.bone.hide_select = True
        _assign_collection(
            armature,
            output_pose,
            COMPONENT_MECHANISM_COLLECTION,
            helpers,
            visible=False,
        )
        constraint_name = _constraint_name(stage_uuid, index)
        constraint_role = semantic_stage_role(
            stage_uuid, f"secondary_follow:{index}"
        )
        constraint = _managed_constraint(
            output_pose,
            component,
            constraint_name,
            "COPY_TRANSFORMS",
            role=constraint_role,
        )
        constraint.target = armature
        constraint.subtarget = source_name
        constraint.target_space = "WORLD"
        constraint.owner_space = "WORLD"
        if hasattr(constraint, "mix_mode"):
            constraint.mix_mode = "REPLACE"
        constraint.mute = bool(getattr(stage, "secondary_baked", False))
        _record_artifact(
            component,
            constraint_role,
            "CONSTRAINT",
            bone_name=output_name,
            constraint_name=constraint.name,
            binding_uuid=stage_uuid,
            owned=True,
        )
        constraint_names.append(constraint.name)

    if hasattr(stage, "mechanism_frame_bone"):
        stage.mechanism_frame_bone = output_names[0]
    return SecondaryMotionArtifacts(
        source_names,
        tuple(output_names),
        tuple(constraint_names),
    )


def _action_is_owned(action, instance_id: str, component_uuid: str, stage_uuid: str):
    return (
        action is not None
        and action.get("coa_rig_instance_id") == instance_id
        and action.get("coa_rig_component_uuid") == component_uuid
        and action.get("coa_semantic_stage_uuid") == stage_uuid
    )


def _owned_tracks(animation_data, instance_id, component_uuid, stage_uuid):
    if animation_data is None:
        return ()
    return tuple(
        track
        for track in animation_data.nla_tracks
        if any(
            _action_is_owned(
                strip.action, instance_id, component_uuid, stage_uuid
            )
            for strip in track.strips
        )
    )


def _new_action_channelbag(action, armature):
    """Return an FCurve collection for legacy or Blender 4.4+ Actions."""

    if hasattr(action, "fcurves"):
        return action.fcurves
    slot = action.slots.new("OBJECT", armature.name)
    layer = action.layers.new("Secondary Motion")
    strip = layer.strips.new(type="KEYFRAME")
    return strip.channelbag(slot, ensure=True).fcurves


def _write_location_curves(
    action,
    armature,
    output_bones: Sequence[str],
    frames: Sequence[int],
    local_locations: Sequence[Sequence[Sequence[float]]],
) -> None:
    curves = _new_action_channelbag(action, armature)
    for bone_index, bone_name in enumerate(output_bones):
        pose_bone = armature.pose.bones[bone_name]
        data_path = pose_bone.path_from_id("location")
        for axis in range(3):
            curve = curves.new(
                data_path=data_path,
                index=axis,
                group_name=bone_name,
            )
            curve.keyframe_points.add(len(frames))
            for point, frame, location in zip(
                curve.keyframe_points,
                frames,
                local_locations[bone_index],
            ):
                point.co = (float(frame), float(location[axis]))
                point.interpolation = "LINEAR"
            curve.update()


def _sample_world_locations(
    armature,
    source_bones: Sequence[str],
    frames: Sequence[int],
):
    import bpy

    scene = bpy.context.scene
    tracks = [[] for _ in source_bones]
    armature_world_matrices = []
    for frame in frames:
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = armature.evaluated_get(depsgraph)
        armature_world_matrices.append(evaluated.matrix_world.copy())
        for index, bone_name in enumerate(source_bones):
            pose_bone = evaluated.pose.bones.get(bone_name)
            if pose_bone is None:
                raise SemanticSecondaryError(
                    f"Source bone {bone_name!r} disappeared during sampling."
                )
            world = evaluated.matrix_world @ pose_bone.matrix
            tracks[index].append(tuple(world.translation))
    return (
        tuple(tuple(track) for track in tracks),
        tuple(armature_world_matrices),
    )


def _world_to_output_locations(
    armature,
    output_bones: Sequence[str],
    filtered_world: Sequence[Sequence[Sequence[float]]],
    armature_world_matrices,
):
    from mathutils import Vector

    result = []
    for bone_name, world_track in zip(output_bones, filtered_world):
        if len(world_track) != len(armature_world_matrices):
            raise SemanticSecondaryError(
                "Filtered Secondary samples and Armature transforms must align."
            )
        rest = armature.data.bones[bone_name].matrix_local
        inverse_rotation = rest.to_3x3().inverted_safe()
        rest_origin = rest.translation
        local_track = []
        for world_location, armature_world in zip(
            world_track, armature_world_matrices
        ):
            armature_location = (
                armature_world.inverted_safe() @ Vector(world_location)
            )
            channel_location = inverse_rotation @ (
                armature_location - rest_origin
            )
            local_track.append(tuple(channel_location))
        result.append(tuple(local_track))
    return tuple(result)


def _capture_bone_selection(armature):
    from .selection import active_pose_bone

    selected = tuple(
        pose_bone.name
        for pose_bone in armature.pose.bones
        if (
            getattr(pose_bone, "select", False)
            or getattr(pose_bone.bone, "select", False)
        )
    )
    active = active_pose_bone(armature)
    return selected, active.name if active is not None else ""


def _restore_bone_selection(armature, selected, active):
    from .selection import select_pose_bones

    if active and armature.pose.bones.get(active) is not None:
        select_pose_bones(armature, selected, active)
        return
    for pose_bone in armature.pose.bones:
        if hasattr(pose_bone, "select"):
            pose_bone.select = False
        elif hasattr(pose_bone.bone, "select"):
            pose_bone.bone.select = False


def _run_failure_hook(hook: Callable[[str], None] | None, point: str):
    if hook is not None:
        hook(point)


def bake_secondary_motion(
    armature,
    component,
    stage,
    *,
    default_source_bones=(),
    frame_start: int | None = None,
    frame_end: int | None = None,
    failure_hook: Callable[[str], None] | None = None,
) -> SecondaryMotionBakeResult:
    """Bake a stage through sample -> pure filter -> atomic NLA swap.

    All dependency-graph samples are captured before the pure kernel runs.
    The new Action and muted NLA track are complete before the previous owned
    track is replaced.  Scene frame, active Action/slot, existing NLA state,
    object mode and selection are restored even when a failure is injected.
    """

    import bpy

    from .artifacts import ensure_rig_instance_id
    from .component_safety import (
        capture_component_build_state,
        preserve_component_context,
        rollback_component_build,
    )

    if armature is None or getattr(armature, "type", "") != "ARMATURE":
        raise SemanticSecondaryError("Secondary Motion requires an Armature.")
    if getattr(stage, "stage_type", "SECONDARY_MOTION") != "SECONDARY_MOTION":
        raise SemanticSecondaryError("The selected stage is not Secondary Motion.")

    component_uuid = _component_uuid(component)
    stage_uuid = _stage_uuid(stage)
    instance_id = ensure_rig_instance_id(armature)
    scene = bpy.context.scene
    start = int(
        frame_start
        if frame_start is not None
        else getattr(stage, "bake_start", scene.frame_start)
    )
    end = int(
        frame_end
        if frame_end is not None
        else getattr(stage, "bake_end", scene.frame_end)
    )
    if end < start:
        raise SemanticSecondaryError("Bake end must not precede bake start.")
    pre_roll_frames = max(0, int(getattr(stage, "pre_roll", 0)))
    sample_start = start - pre_roll_frames
    sample_frames = tuple(range(sample_start, end + 1))
    baked_frames = tuple(range(start, end + 1))
    baked_offset = start - sample_start
    fps = float(scene.render.fps) / float(scene.render.fps_base)
    if fps <= 0.0:
        raise SemanticSecondaryError("Scene FPS must be positive.")

    previous_frame = scene.frame_current
    previous_subframe = scene.frame_subframe
    selected_bones, active_bone = _capture_bone_selection(armature)
    previous_baked = bool(getattr(stage, "secondary_baked", False))
    previous_source_signature = str(
        getattr(stage, "secondary_source_signature", "") or ""
    )
    previous_mechanism_frame = str(
        getattr(stage, "mechanism_frame_bone", "") or ""
    )
    had_animation_data = armature.animation_data is not None
    animation_data = armature.animation_data
    previous_action = animation_data.action if animation_data else None
    previous_action_slot = (
        animation_data.action_slot
        if animation_data is not None and hasattr(animation_data, "action_slot")
        else None
    )
    old_track_states = {
        track: bool(track.mute)
        for track in animation_data.nla_tracks
    } if animation_data is not None else {}

    temp_action = None
    temp_track = None
    old_action_names = {}
    follow_constraints = ()
    committed = False
    artifacts = None
    with preserve_component_context(armature):
        structural_state = capture_component_build_state(armature, component)
        try:
            artifacts = ensure_secondary_motion_artifacts(
                armature,
                component,
                stage,
                default_source_bones=default_source_bones,
            )
            follow_constraints = tuple(
                armature.pose.bones[bone_name].constraints[constraint_name]
                for bone_name, constraint_name in zip(
                    artifacts.output_bones, artifacts.follow_constraints
                )
            )
            previous_constraint_mutes = tuple(
                constraint.mute for constraint in follow_constraints
            )

            # Pass 1: evaluate and copy every source location before filtering.
            sampled, sampled_armature_world = _sample_world_locations(
                armature, artifacts.source_bones, sample_frames
            )
            _run_failure_hook(failure_hook, "after_sample")

            # Pass 2: pure deterministic filtering, one ordered source track at
            # a time.  Historical pre-roll samples are discarded from output.
            settings = SecondaryMotionSettings(
                frequency_hz=float(getattr(stage, "frequency_hz", 3.0)),
                damping_ratio=float(getattr(stage, "damping_ratio", 0.65)),
                substeps=int(getattr(stage, "substeps", 2)),
                dt=1.0 / fps,
                pre_roll=0.0,
            )
            filtered = tuple(
                filter_secondary_motion(track, settings)[baked_offset:]
                for track in sampled
            )
            local_locations = _world_to_output_locations(
                armature,
                artifacts.output_bones,
                filtered,
                sampled_armature_world[baked_offset:],
            )
            _run_failure_hook(failure_hook, "after_filter")

            animation_data = armature.animation_data_create()
            plan = secondary_motion_name_plan(
                component_uuid, stage_uuid, artifacts.source_bones
            )
            existing_stable = bpy.data.actions.get(plan.action)
            if existing_stable is not None and not _action_is_owned(
                existing_stable, instance_id, component_uuid, stage_uuid
            ):
                raise SemanticSecondaryError(
                    f"Action {plan.action!r} exists and is not owned by this stage."
                )
            owned_actions = tuple(
                action
                for action in bpy.data.actions
                if _action_is_owned(
                    action, instance_id, component_uuid, stage_uuid
                )
            )
            old_tracks = _owned_tracks(
                animation_data, instance_id, component_uuid, stage_uuid
            )

            temp_action = bpy.data.actions.new(
                f"{plan.action}__BUILD_{uuid.uuid4().hex[:8]}"
            )
            temp_action.use_fake_user = True
            temp_action["coa_rig_instance_id"] = instance_id
            temp_action["coa_rig_component_uuid"] = component_uuid
            temp_action["coa_semantic_stage_uuid"] = stage_uuid
            temp_action["coa_rig_managed"] = True
            temp_action["coa_rig_component_role"] = semantic_stage_role(
                stage_uuid, "secondary_action"
            )
            _write_location_curves(
                temp_action,
                armature,
                artifacts.output_bones,
                baked_frames,
                local_locations,
            )
            _run_failure_hook(failure_hook, "after_action")

            temp_track = animation_data.nla_tracks.new()
            temp_track.name = f"{plan.nla_track}__BUILD"
            temp_track.mute = True
            strip = temp_track.strips.new(
                f"{plan.nla_track}_Strip", start, temp_action
            )
            strip.blend_type = "REPLACE"
            strip.extrapolation = "NOTHING"
            strip.action_frame_start = float(start)
            strip.action_frame_end = float(end)
            _run_failure_hook(failure_hook, "after_track")

            # Swap only after the replacement is fully evaluable.
            for action in owned_actions:
                old_action_names[action] = action.name
                if action.name == plan.action:
                    action.name = f"{plan.action}__OLD_{uuid.uuid4().hex[:8]}"
            for track in old_tracks:
                track.mute = True
            _run_failure_hook(failure_hook, "before_swap")
            temp_action.name = plan.action
            temp_track.name = plan.nla_track
            temp_track.mute = False
            for constraint in follow_constraints:
                constraint.mute = True
            stage.secondary_baked = True
            if hasattr(stage, "secondary_source_signature"):
                stage.secondary_source_signature = "\n".join(
                    artifacts.source_bones
                )
            _run_failure_hook(failure_hook, "after_swap")

            # Cleanup follows the non-failing state switch.  If an Action has
            # an unexpected external user, keep its renamed backup rather than
            # unlinking user data outside this generated stage.
            for track in old_tracks:
                animation_data.nla_tracks.remove(track)
            for action in owned_actions:
                if action != temp_action and action.users <= 1:
                    bpy.data.actions.remove(action)
            from .component_artifacts import _record_artifact

            _record_artifact(
                component,
                semantic_stage_role(stage_uuid, "secondary_action"),
                "ACTION",
                object_name=temp_action.name,
                binding_uuid=stage_uuid,
                owned=True,
            )
            _record_artifact(
                component,
                semantic_stage_role(stage_uuid, "secondary_nla_track"),
                "NLA_TRACK",
                object_name=armature.name,
                constraint_name=temp_track.name,
                binding_uuid=stage_uuid,
                owned=True,
            )
            committed = True
        except Exception as exc:
            rollback_error = None
            if temp_track is not None and armature.animation_data is not None:
                tracks = armature.animation_data.nla_tracks
                if any(track == temp_track for track in tracks):
                    tracks.remove(temp_track)
            if temp_action is not None and temp_action.name in bpy.data.actions:
                bpy.data.actions.remove(temp_action)
            for action, name in old_action_names.items():
                if action.name in bpy.data.actions:
                    action.name = name
            for track, mute in old_track_states.items():
                try:
                    track.mute = mute
                except ReferenceError:
                    pass
            if follow_constraints:
                for constraint, mute in zip(
                    follow_constraints, previous_constraint_mutes
                ):
                    constraint.mute = mute
            stage.secondary_baked = previous_baked
            if hasattr(stage, "secondary_source_signature"):
                stage.secondary_source_signature = previous_source_signature
            if hasattr(stage, "mechanism_frame_bone"):
                stage.mechanism_frame_bone = previous_mechanism_frame
            try:
                rollback_component_build(
                    armature, component, structural_state
                )
            except Exception as rollback_exc:
                rollback_error = rollback_exc
            if rollback_error is not None:
                raise SemanticSecondaryError(
                    f"{exc}; structural rollback failed: {rollback_error}"
                ) from exc
            if isinstance(exc, SemanticSecondaryError):
                raise
            raise SemanticSecondaryError(str(exc)) from exc
        finally:
            scene.frame_set(previous_frame, subframe=previous_subframe)
            if armature.animation_data is not None:
                armature.animation_data.action = previous_action
                if (
                    hasattr(armature.animation_data, "action_slot")
                    and previous_action_slot is not None
                ):
                    armature.animation_data.action_slot = previous_action_slot
            if not committed:
                for track, mute in old_track_states.items():
                    try:
                        track.mute = mute
                    except ReferenceError:
                        pass
                if not had_animation_data and armature.animation_data is not None:
                    data = armature.animation_data
                    if (
                        data.action is None
                        and not data.nla_tracks
                        and not data.drivers
                    ):
                        armature.animation_data_clear()
            _restore_bone_selection(armature, selected_bones, active_bone)
            bpy.context.view_layer.update()

    if not committed or artifacts is None:
        raise SemanticSecondaryError("Secondary Motion bake did not commit.")
    return SecondaryMotionBakeResult(
        artifacts,
        temp_action.name,
        temp_track.name,
        start,
        end,
        len(baked_frames),
    )


__all__ = [
    "SecondaryMotionArtifacts",
    "SecondaryMotionBakeResult",
    "SecondaryMotionNamePlan",
    "SemanticSecondaryError",
    "bake_secondary_motion",
    "ensure_secondary_motion_artifacts",
    "secondary_motion_name_plan",
]
