"""Blender artifacts for a semantic B-Bone Bezier stage.

The source artwork bone remains the deforming B-Bone.  Animators manipulate
compiler-owned start/end points and tangent handles; hidden effective handles
sit between those authored controls and Blender's raw B-Bone RNA.  This extra
indirection lets Secondary Motion retarget only the handles without changing
the endpoint controls or exposing implementation properties in the main UI.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re

from .semantic_artifacts import semantic_stage_role


BBONE_STATE_KEY = "coa_rig_bbone_state"


class SemanticBboneError(RuntimeError):
    """Raised when B-Bone artifacts cannot be reconciled safely."""


@dataclass(frozen=True)
class BboneBezierNamePlan:
    start_point: str
    end_point: str
    handle_out: str
    handle_in: str
    mid_point: str
    effective_start: str
    effective_end: str
    start_follow: str
    end_stretch: str
    handle_start_follow: str
    handle_end_follow: str
    mid_start_pull: str
    mid_end_pull: str


@dataclass(frozen=True)
class BboneBezierArtifacts:
    primary_control_bone: str
    source_bone: str
    point_control_bones: tuple[str, ...]
    handle_control_bones: tuple[str, ...]
    effective_handle_bones: tuple[str, str]
    secondary_control_bones: tuple[str, ...]
    handle_follow_constraints: tuple[str, str]
    mid_pull_constraints: tuple[str, ...] = ()

    @property
    def control_bones(self) -> tuple[str, ...]:
        return self.point_control_bones + self.handle_control_bones


def _identifier(owner, *names: str) -> str:
    for name in names:
        value = getattr(owner, name, "")
        if value:
            return str(value)
    return ""


def _slug(value: str, fallback: str) -> str:
    result = re.sub(r"[^0-9A-Za-z_]+", "_", str(value or "")).strip("_")
    return result or fallback


def bbone_bezier_name_plan(component, stage) -> BboneBezierNamePlan:
    """Return deterministic names without importing Blender."""

    component_uuid = _identifier(component, "component_uuid", "rig_uuid")
    stage_uuid = _identifier(stage, "stage_uuid", "node_uuid")
    if not component_uuid:
        raise ValueError("Rig component UUID is required.")
    if not stage_uuid:
        raise ValueError("Semantic stage UUID is required.")
    semantic_id = _identifier(stage, "semantic_id", "label") or _identifier(
        component, "semantic_id", "label"
    )
    stem = (
        f"{_slug(semantic_id, 'bbone')[:20]}_"
        f"{_slug(component_uuid.replace('-', ''), 'component')[:8]}_"
        f"{_slug(stage_uuid.replace('-', ''), 'stage')[:8]}"
    )
    constraint_stem = (
        f"COA_BB_{_slug(component_uuid.replace('-', ''), 'component')[:8]}_"
        f"{_slug(stage_uuid.replace('-', ''), 'stage')[:8]}"
    )
    return BboneBezierNamePlan(
        start_point=f"CTRL_{stem}_START",
        end_point=f"CTRL_{stem}_END",
        handle_out=f"CTRL_{stem}_HANDLE_OUT",
        handle_in=f"CTRL_{stem}_HANDLE_IN",
        mid_point=f"CTRL_{stem}_MID",
        effective_start=f"MCH_{stem}_HANDLE_START",
        effective_end=f"MCH_{stem}_HANDLE_END",
        start_follow=f"{constraint_stem}_Start",
        end_stretch=f"{constraint_stem}_End",
        handle_start_follow=f"{constraint_stem}_HandleStart",
        handle_end_follow=f"{constraint_stem}_HandleEnd",
        mid_start_pull=f"{constraint_stem}_MidStart",
        mid_end_pull=f"{constraint_stem}_MidEnd",
    )


def _source_names(component, stage) -> tuple[str, ...]:
    references = tuple(getattr(stage, "source_bones", ()) or ())
    if not references:
        references = tuple(getattr(component, "source_bones", ()) or ())
    return tuple(
        name
        for reference in references
        if (name := str(getattr(reference, "bone_name", reference) or ""))
    )


def validate_bbone_source_names(source_names) -> tuple[str, ...]:
    names = tuple(str(name or "") for name in source_names if str(name or ""))
    if len(names) != 1:
        raise SemanticBboneError(
            "A B-Bone Bezier stage requires exactly one source deform bone."
        )
    return names


def _runtime_helpers():
    import bpy
    from mathutils import Vector

    from ... import functions
    from .component_artifacts import (
        COMPONENT_CONTROL_COLLECTION,
        COMPONENT_MECHANISM_COLLECTION,
        ComponentArtifactConflict,
        _managed_constraint,
        _record_artifact,
        _set_edit_bone_matrix,
        _switch_to_edit_mode,
        _tag_owned_bone,
        find_component_bone,
    )
    from .semantic_artifacts import (
        _assign_collection,
        _ensure_edit_bone,
        _reconcile_owned_bone_renames,
    )

    return {
        "bpy": bpy,
        "Vector": Vector,
        "functions": functions,
        "control_collection": COMPONENT_CONTROL_COLLECTION,
        "mechanism_collection": COMPONENT_MECHANISM_COLLECTION,
        "conflict": ComponentArtifactConflict,
        "managed_constraint": _managed_constraint,
        "record_artifact": _record_artifact,
        "set_edit_bone_matrix": _set_edit_bone_matrix,
        "switch_to_edit_mode": _switch_to_edit_mode,
        "tag_owned_bone": _tag_owned_bone,
        "find_component_bone": find_component_bone,
        "assign_collection": _assign_collection,
        "ensure_edit_bone": _ensure_edit_bone,
        "reconcile_owned_bone_renames": _reconcile_owned_bone_renames,
    }


def _component_uuid(component) -> str:
    value = _identifier(component, "component_uuid", "rig_uuid")
    if not value:
        raise SemanticBboneError("Rig component UUID is required.")
    return value


def _stage_uuid(stage) -> str:
    value = _identifier(stage, "stage_uuid", "node_uuid")
    if not value:
        raise SemanticBboneError("Semantic stage UUID is required.")
    return value


def _rna_owner(pose_bone, data_bone, name: str):
    if hasattr(pose_bone, name):
        return pose_bone
    if hasattr(data_bone, name):
        return data_bone
    return None


def _rna_value(pose_bone, data_bone, name: str):
    owner = _rna_owner(pose_bone, data_bone, name)
    return getattr(owner, name) if owner is not None else None


def _custom_handle_owner(data_bone, name: str):
    """Return the writable B-Bone custom-handle owner.

    Blender 5.1 exposes a read-only PoseBone proxy for these properties.  The
    actual relationship is writable only on the Armature data Bone.
    """

    return data_bone if hasattr(data_bone, name) else None


def _set_rna_value(pose_bone, data_bone, name: str, value) -> bool:
    owner = _rna_owner(pose_bone, data_bone, name)
    if owner is None:
        return False
    # Blender 5.1 represents the custom-handle scale switches as a
    # BoolVector (XYZ), whereas older API references describe scalar bools.
    # Follow live RNA metadata so the adapter remains correct for both forms.
    rna_property = owner.bl_rna.properties.get(name)
    array_length = int(getattr(rna_property, "array_length", 0) or 0)
    if array_length and not isinstance(value, (tuple, list)):
        value = tuple(value for _index in range(array_length))
    setattr(owner, name, value)
    return True


def _plain_value(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return list(value)
    except TypeError:
        return value


def _roll_driver_marker(stage_uuid: str, endpoint: str) -> str:
    token = re.sub(r"[^0-9A-Za-z]", "", str(stage_uuid or ""))
    return f"bb_{token}_{endpoint}"


def _roll_driver_role(stage_uuid: str, endpoint: str) -> str:
    return semantic_stage_role(stage_uuid, f"bbone_roll_driver:{endpoint}")


def _roll_handle_role(stage_uuid: str, endpoint: str) -> str:
    handle = "out" if endpoint == "in" else "in"
    return semantic_stage_role(stage_uuid, f"bbone_handle:{handle}")


def _roll_driver_property(endpoint: str) -> str:
    if endpoint not in {"in", "out"}:
        raise ValueError(f"Unknown B-Bone roll endpoint: {endpoint}")
    return f"bbone_roll{endpoint}"


def _driver_is_owned(
    fcurve,
    armature,
    component,
    stage_uuid: str,
    endpoint: str,
) -> bool:
    """Prove live B-Bone roll-driver ownership without trusting saved names."""

    marker = _roll_driver_marker(stage_uuid, endpoint)
    expected_role = _roll_handle_role(stage_uuid, endpoint)
    from .artifacts import ensure_rig_instance_id

    instance_id = ensure_rig_instance_id(armature)
    for variable in fcurve.driver.variables:
        if variable.name != marker or variable.type != "TRANSFORMS":
            continue
        for target in variable.targets:
            if target.id != armature:
                continue
            data_bone = armature.data.bones.get(target.bone_target)
            if data_bone is None:
                continue
            if (
                bool(data_bone.get("coa_rig_managed"))
                and data_bone.get("coa_rig_instance_id") == instance_id
                and data_bone.get("coa_rig_component_uuid")
                == _component_uuid(component)
                and data_bone.get("coa_rig_component_role") == expected_role
            ):
                return True
    return False


def _owned_roll_drivers(
    armature,
    component,
    stage_uuid: str,
    endpoint: str,
):
    animation_data = armature.animation_data
    if animation_data is None:
        return ()
    return tuple(
        fcurve
        for fcurve in animation_data.drivers
        if _driver_is_owned(
            fcurve,
            armature,
            component,
            stage_uuid,
            endpoint,
        )
    )


def _remove_driver(armature, fcurve) -> bool:
    try:
        return bool(armature.driver_remove(fcurve.data_path, fcurve.array_index))
    except (AttributeError, KeyError, RuntimeError, TypeError):
        try:
            return bool(armature.driver_remove(fcurve.data_path))
        except (AttributeError, KeyError, RuntimeError, TypeError):
            return False


def remove_bbone_roll_drivers(
    armature,
    component,
    stage_uuid: str,
) -> int:
    """Remove only live roll drivers proven to belong to one B-Bone stage."""

    removed = 0
    seen = set()
    for endpoint in ("in", "out"):
        for fcurve in _owned_roll_drivers(
            armature,
            component,
            stage_uuid,
            endpoint,
        ):
            pointer = fcurve.as_pointer()
            if pointer in seen:
                continue
            seen.add(pointer)
            removed += int(_remove_driver(armature, fcurve))
    return removed


def _record_roll_driver_artifact(
    component,
    *,
    stage_uuid: str,
    endpoint: str,
    armature,
    source_name: str,
    data_path: str,
):
    role = _roll_driver_role(stage_uuid, endpoint)
    matches = [
        index
        for index, artifact in enumerate(component.artifacts)
        if artifact.role == role and artifact.data_type == "DRIVER"
    ]
    for index in reversed(matches[1:]):
        component.artifacts.remove(index)
    if matches:
        artifact = component.artifacts[matches[0]]
        artifact.object_name = armature.name
        artifact.bone_name = source_name
        artifact.constraint_name = ""
        artifact.data_path = data_path
        artifact.binding_uuid = stage_uuid
        artifact.owned = True
        return artifact
    from .component_artifacts import _record_artifact

    return _record_artifact(
        component,
        role,
        "DRIVER",
        object_name=armature.name,
        bone_name=source_name,
        data_path=data_path,
        binding_uuid=stage_uuid,
        owned=True,
    )


def _ensure_roll_driver(
    armature,
    component,
    stage_uuid: str,
    *,
    endpoint: str,
    source_pose,
    handle_name: str,
    base_roll: float,
):
    """Drive source roll from the authored tangent handle's local Y rotation."""

    property_name = _roll_driver_property(endpoint)
    data_path = source_pose.path_from_id(property_name)
    owned = _owned_roll_drivers(
        armature,
        component,
        stage_uuid,
        endpoint,
    )
    if len(owned) > 1:
        raise SemanticBboneError(
            f"Multiple managed B-Bone roll drivers use endpoint '{endpoint}'."
        )
    if owned and owned[0].data_path != data_path:
        raise SemanticBboneError(
            "A managed B-Bone roll driver still targets another source bone."
        )
    animation_data = armature.animation_data
    path_matches = tuple(
        fcurve
        for fcurve in (animation_data.drivers if animation_data else ())
        if fcurve.data_path == data_path
    )
    if len(path_matches) > 1:
        raise SemanticBboneError(
            f"Multiple drivers target '{data_path}'."
        )
    if path_matches:
        fcurve = path_matches[0]
        if not _driver_is_owned(
            fcurve,
            armature,
            component,
            stage_uuid,
            endpoint,
        ):
            raise SemanticBboneError(
                f"B-Bone roll channel '{data_path}' already has an unmanaged driver."
            )
    else:
        fcurve = source_pose.driver_add(property_name)

    driver = fcurve.driver
    driver.type = "SCRIPTED"
    if hasattr(driver, "use_self"):
        driver.use_self = False
    while driver.variables:
        driver.variables.remove(driver.variables[0])
    variable = driver.variables.new()
    variable.name = _roll_driver_marker(stage_uuid, endpoint)
    variable.type = "TRANSFORMS"
    target = variable.targets[0]
    target.id = armature
    target.bone_target = handle_name
    target.transform_type = "ROT_Y"
    target.transform_space = "LOCAL_SPACE"
    if hasattr(target, "rotation_mode"):
        target.rotation_mode = "AUTO"
    driver.expression = f"({float(base_roll):.17g})+{variable.name}"
    _record_roll_driver_artifact(
        component,
        stage_uuid=stage_uuid,
        endpoint=endpoint,
        armature=armature,
        source_name=source_pose.name,
        data_path=fcurve.data_path,
    )
    return fcurve


_BBONE_SCALAR_PROPERTIES = (
    "bbone_segments",
    "bbone_handle_type_start",
    "bbone_handle_type_end",
    "bbone_handle_use_ease_start",
    "bbone_handle_use_ease_end",
    "bbone_handle_use_scale_start",
    "bbone_handle_use_scale_end",
    "bbone_easein",
    "bbone_easeout",
    "bbone_rollin",
    "bbone_rollout",
    "bbone_scaleinx",
    "bbone_scaleiny",
    "bbone_scaleoutx",
    "bbone_scaleouty",
)
_BBONE_VECTOR_PROPERTIES = ("bbone_scalein", "bbone_scaleout")
_BBONE_HANDLE_PROPERTIES = (
    "bbone_custom_handle_start",
    "bbone_custom_handle_end",
)


def _capture_bbone_state(armature, component, stage, source_name: str) -> None:
    pose_bone = armature.pose.bones[source_name]
    data_bone = armature.data.bones[source_name]
    component_uuid = _component_uuid(component)
    stage_uuid = _stage_uuid(stage)
    encoded = data_bone.get(BBONE_STATE_KEY)
    if encoded:
        try:
            state = json.loads(str(encoded))
        except (TypeError, ValueError) as exc:
            raise SemanticBboneError(
                f"Bone '{source_name}' has an unreadable B-Bone ownership marker."
            ) from exc
        if (
            state.get("component_uuid") != component_uuid
            or state.get("stage_uuid") != stage_uuid
        ):
            raise SemanticBboneError(
                f"Bone '{source_name}' is already managed by another B-Bone stage."
            )
        return

    values = {}
    for name in _BBONE_SCALAR_PROPERTIES + _BBONE_VECTOR_PROPERTIES:
        owner = _rna_owner(pose_bone, data_bone, name)
        if owner is not None:
            values[name] = _plain_value(getattr(owner, name))
    handles = {}
    for name in _BBONE_HANDLE_PROPERTIES:
        owner = _custom_handle_owner(data_bone, name)
        handle = getattr(owner, name) if owner is not None else None
        handles[name] = getattr(handle, "name", "") if handle is not None else ""
    state = {
        "component_uuid": component_uuid,
        "stage_uuid": stage_uuid,
        "source_bone": source_name,
        "values": values,
        "handles": handles,
    }
    data_bone[BBONE_STATE_KEY] = json.dumps(state, sort_keys=True)


def _restore_state_on_bone(armature, data_bone, state) -> None:
    pose_bone = armature.pose.bones.get(data_bone.name)
    if pose_bone is None:
        return
    for name, value in state.get("values", {}).items():
        try:
            _set_rna_value(pose_bone, data_bone, name, value)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
    for name, bone_name in state.get("handles", {}).items():
        owner = _custom_handle_owner(data_bone, name)
        if owner is None:
            continue
        target = armature.data.bones.get(bone_name) if bone_name else None
        try:
            setattr(owner, name, target)
        except (AttributeError, RuntimeError, TypeError):
            pass
    try:
        del data_bone[BBONE_STATE_KEY]
    except KeyError:
        pass


def restore_bbone_stage_state(armature, component, stage_uuid: str) -> int:
    """Restore every source marker owned by one removed/disabled stage."""

    # A driven RNA value cannot be restored authoritatively while its driver
    # is still evaluating.  Remove the two live-owned roll drivers first, then
    # put back the source bone's pre-stage values and custom handles.
    remove_bbone_roll_drivers(armature, component, stage_uuid)
    restored = 0
    for data_bone in tuple(armature.data.bones):
        encoded = data_bone.get(BBONE_STATE_KEY)
        if not encoded:
            continue
        try:
            state = json.loads(str(encoded))
        except (TypeError, ValueError):
            continue
        if (
            state.get("component_uuid") != _component_uuid(component)
            or state.get("stage_uuid") != stage_uuid
        ):
            continue
        _restore_state_on_bone(armature, data_bone, state)
        restored += 1
    return restored


def _restore_prior_source_if_changed(
    armature, component, stage_uuid: str, source_name: str
) -> None:
    for data_bone in tuple(armature.data.bones):
        if data_bone.name == source_name:
            continue
        encoded = data_bone.get(BBONE_STATE_KEY)
        if not encoded:
            continue
        try:
            state = json.loads(str(encoded))
        except (TypeError, ValueError):
            continue
        if (
            state.get("component_uuid") == _component_uuid(component)
            and state.get("stage_uuid") == stage_uuid
        ):
            from .component_artifacts import _recorded_constraint

            remove_bbone_roll_drivers(armature, component, stage_uuid)
            pose_bone = armature.pose.bones.get(data_bone.name)
            if pose_bone is not None:
                for leaf, constraint_type in (
                    ("bbone_start_follow", "COPY_LOCATION"),
                    ("bbone_end_stretch", "STRETCH_TO"),
                ):
                    role = semantic_stage_role(stage_uuid, leaf)
                    records = [
                        artifact
                        for artifact in component.artifacts
                        if artifact.owned
                        and artifact.data_type == "CONSTRAINT"
                        and artifact.role == role
                    ]
                    if not records:
                        raise SemanticBboneError(
                            f"B-Bone source constraint record '{role}' is missing."
                        )
                    constraint = _recorded_constraint(
                        pose_bone,
                        component,
                        role,
                        constraint_type,
                        allow_missing=False,
                    )
                    pose_bone.constraints.remove(constraint)
                    for index in range(len(component.artifacts) - 1, -1, -1):
                        artifact = component.artifacts[index]
                        if artifact.data_type == "CONSTRAINT" and artifact.role == role:
                            component.artifacts.remove(index)
            _restore_state_on_bone(armature, data_bone, state)


def _record_state_artifact(component, role: str, source_name: str, stage_uuid: str):
    matches = [
        index
        for index, artifact in enumerate(component.artifacts)
        if artifact.role == role and artifact.data_type == "BBONE_STATE"
    ]
    for index in reversed(matches[1:]):
        component.artifacts.remove(index)
    if matches:
        artifact = component.artifacts[matches[0]]
        artifact.object_name = ""
        artifact.bone_name = source_name
        artifact.constraint_name = ""
        artifact.data_path = BBONE_STATE_KEY
        artifact.binding_uuid = stage_uuid
        artifact.owned = True
        return artifact
    from .component_artifacts import _record_artifact

    return _record_artifact(
        component,
        role,
        "BBONE_STATE",
        bone_name=source_name,
        data_path=BBONE_STATE_KEY,
        binding_uuid=stage_uuid,
        owned=True,
    )


def _record_bone(component, role, name, helpers) -> None:
    helpers["record_artifact"](
        component, role, "BONE", bone_name=name, owned=True
    )


def _record_constraint(component, role, owner, constraint, stage_uuid, helpers):
    helpers["record_artifact"](
        component,
        role,
        "CONSTRAINT",
        bone_name=owner.name,
        constraint_name=constraint.name,
        binding_uuid=stage_uuid,
        owned=True,
    )


def _configure_constraint(
    owner,
    component,
    *,
    name,
    constraint_type,
    role,
    armature,
    subtarget,
    stage_uuid,
    helpers,
):
    constraint = helpers["managed_constraint"](
        owner, component, name, constraint_type, role=role
    )
    constraint.target = armature
    constraint.subtarget = subtarget
    if hasattr(constraint, "owner_space"):
        constraint.owner_space = "WORLD"
    if hasattr(constraint, "target_space"):
        constraint.target_space = "WORLD"
    _record_constraint(component, role, owner, constraint, stage_uuid, helpers)
    return constraint


def _set_scale_properties(pose_bone, data_bone, prefix: str, value) -> None:
    vector_name = f"bbone_scale{prefix}"
    if _set_rna_value(pose_bone, data_bone, vector_name, tuple(value)):
        return
    _set_rna_value(pose_bone, data_bone, f"{vector_name}x", float(value[0]))
    _set_rna_value(pose_bone, data_bone, f"{vector_name}y", float(value[1]))


def _set_custom_handle(pose_bone, data_bone, name: str, target_pose, target_data):
    owner = _custom_handle_owner(data_bone, name)
    if owner is None:
        raise SemanticBboneError(
            f"This Blender version does not expose '{name}'."
        )
    setattr(owner, name, target_data)


def ensure_bbone_bezier_artifacts(
    armature,
    component,
    stage,
) -> BboneBezierArtifacts:
    """Build one point/handle driven B-Bone stage idempotently."""

    if armature is None or getattr(armature, "type", "") != "ARMATURE":
        raise SemanticBboneError("B-Bone Bezier stages require an Armature.")
    component_uuid = _component_uuid(component)
    stage_uuid = _stage_uuid(stage)
    source_name = validate_bbone_source_names(_source_names(component, stage))[0]
    if source_name not in armature.data.bones:
        raise SemanticBboneError(f"Missing B-Bone source bone: {source_name}")

    _restore_prior_source_if_changed(armature, component, stage_uuid, source_name)
    _capture_bbone_state(armature, component, stage, source_name)
    state_role = semantic_stage_role(stage_uuid, "bbone_source_state")
    _record_state_artifact(component, state_role, source_name, stage_uuid)

    helpers = _runtime_helpers()
    plan = bbone_bezier_name_plan(component, stage)
    use_mid = bool(getattr(stage, "bbone_use_mid_control", False))
    role_names = {
        "start": semantic_stage_role(stage_uuid, "bbone_point:start"),
        "end": semantic_stage_role(stage_uuid, "bbone_point:end"),
        "handle_out": semantic_stage_role(stage_uuid, "bbone_handle:out"),
        "handle_in": semantic_stage_role(stage_uuid, "bbone_handle:in"),
        "effective_start": semantic_stage_role(
            stage_uuid, "bbone_effective_handle:start"
        ),
        "effective_end": semantic_stage_role(
            stage_uuid, "bbone_effective_handle:end"
        ),
    }
    if use_mid:
        role_names["mid"] = semantic_stage_role(stage_uuid, "bbone_point:mid")
    helpers["reconcile_owned_bone_renames"](
        armature, component, tuple(role_names.values()), helpers
    )
    existing = {}
    for key, role in role_names.items():
        bone = helpers["find_component_bone"](armature, component_uuid, role)
        existing[key] = bone.name if bone is not None else ""

    helpers["switch_to_edit_mode"](armature)
    try:
        source = armature.data.edit_bones[source_name]
        length = max(float(source.length), 1.0e-4)
        helper_length = max(length * 0.1, 0.02)
        handle_distance = length * float(
            getattr(stage, "bbone_handle_length", 0.33)
        )
        direction = source.tail - source.head
        if direction.length < 1.0e-8:
            raise SemanticBboneError("The B-Bone source has zero length.")
        direction.normalize()
        locations = {
            "start": source.head.copy(),
            "end": source.tail.copy(),
            "handle_out": source.head + direction * handle_distance,
            "handle_in": source.tail - direction * handle_distance,
            "effective_start": source.head + direction * handle_distance,
            "effective_end": source.tail - direction * handle_distance,
        }
        if use_mid:
            locations["mid"] = source.head.lerp(source.tail, 0.5)
        defaults = {
            "start": plan.start_point,
            "end": plan.end_point,
            "handle_out": plan.handle_out,
            "handle_in": plan.handle_in,
            "mid": plan.mid_point,
            "effective_start": plan.effective_start,
            "effective_end": plan.effective_end,
        }
        generated = {}
        for key, role in role_names.items():
            bone = helpers["ensure_edit_bone"](
                armature,
                component,
                role=role,
                default_name=defaults[key],
                existing_name=existing.get(key, ""),
                helpers=helpers,
            )
            matrix = source.matrix.copy()
            matrix.translation = locations[key]
            bone.parent = source.parent
            bone.use_connect = False
            bone.use_deform = False
            helpers["set_edit_bone_matrix"](bone, matrix, helper_length)
            generated[key] = bone.name
    finally:
        if armature.mode == "EDIT":
            helpers["bpy"].ops.object.mode_set(mode="POSE")

    control_keys = ["start", "end", "handle_out", "handle_in"]
    if use_mid:
        control_keys.append("mid")
    for key in control_keys:
        role = role_names[key]
        pose_bone = armature.pose.bones[generated[key]]
        helpers["tag_owned_bone"](armature, pose_bone.bone, component, role)
        _record_bone(component, role, pose_bone.name, helpers)
        pose_bone.bone.hide_select = False
        pose_bone.rotation_mode = "XYZ"
        pose_bone.lock_location = (False, False, False)
        is_handle = key in {"handle_out", "handle_in"}
        # Native B-Bone custom handles use transform scale for ease/endpoint
        # scale and their orientation for roll.  Keep those authored channels
        # available only on tangent handles; point controls remain positional.
        pose_bone.lock_rotation = (
            (False, False, False) if is_handle else (True, True, True)
        )
        pose_bone.lock_scale = (
            (False, False, False) if is_handle else (True, True, True)
        )
        helpers["assign_collection"](
            armature,
            pose_bone,
            helpers["control_collection"],
            helpers,
            visible=True,
        )
    for key in ("effective_start", "effective_end"):
        role = role_names[key]
        pose_bone = armature.pose.bones[generated[key]]
        helpers["tag_owned_bone"](armature, pose_bone.bone, component, role)
        _record_bone(component, role, pose_bone.name, helpers)
        pose_bone.bone.hide_select = True
        helpers["assign_collection"](
            armature,
            pose_bone,
            helpers["mechanism_collection"],
            helpers,
            visible=False,
        )

    constraint_roles = {
        "start": semantic_stage_role(stage_uuid, "bbone_start_follow"),
        "end": semantic_stage_role(stage_uuid, "bbone_end_stretch"),
        "handle_start": semantic_stage_role(
            stage_uuid, "bbone_handle_follow:start"
        ),
        "handle_end": semantic_stage_role(
            stage_uuid, "bbone_handle_follow:end"
        ),
    }
    source_pose = armature.pose.bones[source_name]
    start_follow = _configure_constraint(
        source_pose,
        component,
        name=plan.start_follow,
        constraint_type="COPY_LOCATION",
        role=constraint_roles["start"],
        armature=armature,
        subtarget=generated["start"],
        stage_uuid=stage_uuid,
        helpers=helpers,
    )
    start_follow.use_offset = False
    end_stretch = _configure_constraint(
        source_pose,
        component,
        name=plan.end_stretch,
        constraint_type="STRETCH_TO",
        role=constraint_roles["end"],
        armature=armature,
        subtarget=generated["end"],
        stage_uuid=stage_uuid,
        helpers=helpers,
    )
    end_stretch.rest_length = max(float(source_pose.length), 1.0e-4)
    if hasattr(end_stretch, "volume"):
        end_stretch.volume = "NO_VOLUME"

    effective_start = armature.pose.bones[generated["effective_start"]]
    effective_end = armature.pose.bones[generated["effective_end"]]
    handle_start = _configure_constraint(
        effective_start,
        component,
        name=plan.handle_start_follow,
        constraint_type="COPY_TRANSFORMS",
        role=constraint_roles["handle_start"],
        armature=armature,
        subtarget=generated["handle_out"],
        stage_uuid=stage_uuid,
        helpers=helpers,
    )
    handle_end = _configure_constraint(
        effective_end,
        component,
        name=plan.handle_end_follow,
        constraint_type="COPY_TRANSFORMS",
        role=constraint_roles["handle_end"],
        armature=armature,
        subtarget=generated["handle_in"],
        stage_uuid=stage_uuid,
        helpers=helpers,
    )
    mid_constraints = []
    if use_mid:
        for key, owner, name in (
            ("start", effective_start, plan.mid_start_pull),
            ("end", effective_end, plan.mid_end_pull),
        ):
            role = semantic_stage_role(stage_uuid, f"bbone_mid_pull:{key}")
            constraint = _configure_constraint(
                owner,
                component,
                name=name,
                constraint_type="COPY_LOCATION",
                role=role,
                armature=armature,
                subtarget=generated["mid"],
                stage_uuid=stage_uuid,
                helpers=helpers,
            )
            constraint.influence = float(
                getattr(stage, "bbone_mid_influence", 0.5)
            )
            mid_constraints.append(constraint.name)

    source_data = armature.data.bones[source_name]
    _set_rna_value(
        source_pose,
        source_data,
        "bbone_segments",
        int(getattr(stage, "bbone_segments", 8)),
    )
    _set_rna_value(source_pose, source_data, "bbone_handle_type_start", "ABSOLUTE")
    _set_rna_value(source_pose, source_data, "bbone_handle_type_end", "ABSOLUTE")
    _set_custom_handle(
        source_pose,
        source_data,
        "bbone_custom_handle_start",
        effective_start,
        effective_start.bone,
    )
    _set_custom_handle(
        source_pose,
        source_data,
        "bbone_custom_handle_end",
        effective_end,
        effective_end.bone,
    )
    _set_rna_value(
        source_pose, source_data, "bbone_easein", float(stage.bbone_ease_in)
    )
    _set_rna_value(
        source_pose, source_data, "bbone_easeout", float(stage.bbone_ease_out)
    )
    _set_rna_value(
        source_pose, source_data, "bbone_rollin", float(stage.bbone_roll_in)
    )
    _set_rna_value(
        source_pose, source_data, "bbone_rollout", float(stage.bbone_roll_out)
    )
    _ensure_roll_driver(
        armature,
        component,
        stage_uuid,
        endpoint="in",
        source_pose=source_pose,
        handle_name=generated["handle_out"],
        base_roll=float(stage.bbone_roll_in),
    )
    _ensure_roll_driver(
        armature,
        component,
        stage_uuid,
        endpoint="out",
        source_pose=source_pose,
        handle_name=generated["handle_in"],
        base_roll=float(stage.bbone_roll_out),
    )
    use_scale = bool(getattr(stage, "bbone_use_scale", False))
    _set_rna_value(
        source_pose, source_data, "bbone_handle_use_ease_start", True
    )
    _set_rna_value(source_pose, source_data, "bbone_handle_use_ease_end", True)
    _set_rna_value(
        source_pose, source_data, "bbone_handle_use_scale_start", use_scale
    )
    _set_rna_value(
        source_pose, source_data, "bbone_handle_use_scale_end", use_scale
    )
    _set_scale_properties(
        source_pose,
        source_data,
        "in",
        stage.bbone_scale_in if use_scale else (1.0, 1.0, 1.0),
    )
    _set_scale_properties(
        source_pose,
        source_data,
        "out",
        stage.bbone_scale_out if use_scale else (1.0, 1.0, 1.0),
    )

    stage.bbone_start_bone = generated["start"]
    stage.bbone_end_bone = generated["end"]
    stage.bbone_handle_out_bone = generated["handle_out"]
    stage.bbone_handle_in_bone = generated["handle_in"]
    stage.bbone_mid_bone = generated.get("mid", "")
    stage.control_bone = generated["end"]
    stage.mechanism_frame_bone = generated["effective_start"]
    point_controls = (generated["start"], generated["end"])
    if use_mid:
        point_controls += (generated["mid"],)
    handle_controls = (generated["handle_out"], generated["handle_in"])
    secondary_controls = handle_controls + (
        (generated["mid"],) if use_mid else ()
    )
    return BboneBezierArtifacts(
        primary_control_bone=generated["end"],
        source_bone=source_name,
        point_control_bones=point_controls,
        handle_control_bones=handle_controls,
        effective_handle_bones=(
            generated["effective_start"],
            generated["effective_end"],
        ),
        secondary_control_bones=secondary_controls,
        handle_follow_constraints=(handle_start.name, handle_end.name),
        mid_pull_constraints=tuple(mid_constraints),
    )


def retarget_bbone_handles(
    armature,
    artifacts: BboneBezierArtifacts,
    target_bones,
) -> None:
    """Retarget hidden handle followers to Secondary Motion outputs."""

    targets = tuple(str(name or "") for name in target_bones)
    if len(targets) != len(artifacts.secondary_control_bones):
        raise SemanticBboneError(
            "Secondary outputs must match the B-Bone handle/mid control count."
        )
    missing = [name for name in targets if name not in armature.data.bones]
    if missing:
        raise SemanticBboneError(
            "Missing B-Bone Secondary target(s): " + ", ".join(missing)
        )
    for owner_name, constraint_name, target_name in zip(
        artifacts.effective_handle_bones,
        artifacts.handle_follow_constraints,
        targets[:2],
    ):
        owner = armature.pose.bones.get(owner_name)
        constraint = owner.constraints.get(constraint_name) if owner else None
        if constraint is None or constraint.type != "COPY_TRANSFORMS":
            raise SemanticBboneError(
                f"Managed B-Bone handle constraint '{constraint_name}' is missing."
            )
        constraint.target = armature
        constraint.subtarget = target_name
    if artifacts.mid_pull_constraints:
        mid_target = targets[-1]
        for owner_name, constraint_name in zip(
            artifacts.effective_handle_bones,
            artifacts.mid_pull_constraints,
        ):
            owner = armature.pose.bones.get(owner_name)
            constraint = owner.constraints.get(constraint_name) if owner else None
            if constraint is None or constraint.type != "COPY_LOCATION":
                raise SemanticBboneError(
                    f"Managed B-Bone midpoint constraint '{constraint_name}' is missing."
                )
            constraint.target = armature
            constraint.subtarget = mid_target
