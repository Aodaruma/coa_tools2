"""Contact / Pin layer for semantic character rigs."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re

import bpy

from ... import functions
from .artifacts import ensure_rig_instance_id
from .component_artifacts import (
    ComponentArtifactConflict,
    _record_artifact,
    find_component_object,
)
from .semantic_artifacts import semantic_stage_role


class SemanticContactError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContactPinArtifacts:
    driven_bone: str
    anchor_object: str
    constraint_name: str
    property_name: str


def _short(value):
    return re.sub(r"[^0-9A-Za-z]", "", str(value or ""))[:8]


def _driver_marker(stage_uuid):
    token = re.sub(r"[^0-9A-Za-z]", "", str(stage_uuid or ""))
    return f"cp_{token}"


def _mechanism_collection(scene):
    name = "COA Semantic Mechanisms"
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
    if collection.name not in scene.collection.children:
        scene.collection.children.link(collection)
    collection.hide_render = True
    return collection


def _tag_object(armature, component, obj, role):
    instance_id = ensure_rig_instance_id(armature)
    owner = obj.get("coa_rig_component_uuid")
    if owner not in {None, "", component.component_uuid}:
        raise ComponentArtifactConflict(
            f"Object '{obj.name}' belongs to another rig component."
        )
    obj["coa_rig_instance_id"] = instance_id
    obj["coa_rig_component_uuid"] = component.component_uuid
    obj["coa_rig_component_role"] = role
    obj["coa_rig_managed"] = True


def _ensure_anchor(armature, component, stage, driven_pose):
    role = semantic_stage_role(stage.stage_uuid, "pin_anchor")
    anchor = find_component_object(armature, component.component_uuid, role)
    created = anchor is None
    if anchor is None:
        name = f"MCH_PIN_{_short(component.component_uuid)}_{_short(stage.stage_uuid)}"
        if bpy.data.objects.get(name) is not None:
            raise ComponentArtifactConflict(f"Object '{name}' already exists and is unmanaged.")
        anchor = bpy.data.objects.new(name, None)
        _mechanism_collection(bpy.context.scene).objects.link(anchor)
        anchor.empty_display_type = "PLAIN_AXES"
        anchor.empty_display_size = max(driven_pose.length * 0.2, 0.05)
        anchor.hide_viewport = True
    _tag_object(armature, component, anchor, role)
    if created:
        anchor.matrix_world = armature.matrix_world @ driven_pose.matrix

    world = anchor.matrix_world.copy()
    if stage.pin_space == "WORLD":
        anchor.parent = None
        anchor.parent_type = "OBJECT"
        anchor.parent_bone = ""
    elif stage.pin_space == "CHARACTER":
        anchor.parent = armature
        anchor.parent_type = "OBJECT"
        anchor.parent_bone = ""
    elif stage.pin_space == "TARGET":
        if stage.pin_target_object is None:
            raise SemanticContactError("Target-space Pin requires a target object.")
        anchor.parent = stage.pin_target_object
        if stage.pin_target_bone and stage.pin_target_object.type == "ARMATURE":
            if stage.pin_target_bone not in stage.pin_target_object.data.bones:
                raise SemanticContactError(
                    f"Pin target bone not found: {stage.pin_target_bone}"
                )
            anchor.parent_type = "BONE"
            anchor.parent_bone = stage.pin_target_bone
        else:
            anchor.parent_type = "OBJECT"
            anchor.parent_bone = ""
    else:
        raise SemanticContactError(f"Unsupported Pin space: {stage.pin_space}")
    anchor.matrix_world = world
    _record_artifact(
        component,
        role,
        "OBJECT",
        object_name=anchor.name,
        owned=True,
    )
    return anchor


def _constraint_type(stage):
    if stage.pin_position and stage.pin_orientation:
        return "COPY_TRANSFORMS"
    if stage.pin_position:
        return "COPY_LOCATION"
    if stage.pin_orientation:
        return "COPY_ROTATION"
    raise SemanticContactError("Pin must affect position, orientation, or both.")


def _constraint_marker_name(stage_uuid):
    token = re.sub(r"[^0-9A-Za-z]", "", str(stage_uuid or ""))
    return f"_coa_pin_constraint_{token}"


def _constraint_marker_prefix(armature, component, stage_uuid):
    return (
        f"{ensure_rig_instance_id(armature)}|{component.component_uuid}|"
        f"{stage_uuid}|"
    )


def _mark_pin_constraint(armature, component, stage_uuid, pose_bone, constraint):
    pose_bone[_constraint_marker_name(stage_uuid)] = (
        _constraint_marker_prefix(armature, component, stage_uuid) + constraint.name
    )


def _clear_pin_constraint_marker(armature, component, stage_uuid, pose_bone):
    marker_name = _constraint_marker_name(stage_uuid)
    marker = pose_bone.get(marker_name)
    if isinstance(marker, str) and marker.startswith(
        _constraint_marker_prefix(armature, component, stage_uuid)
    ):
        del pose_bone[marker_name]


def _owned_contact_constraints(armature, component, role):
    """Resolve Pin constraints through their live owned driver.

    Blender 5.1 Constraints cannot carry ID properties.  A saved constraint
    name (including the PoseBone companion marker) becomes ambiguous after a
    rename, so it is never enough for destructive ownership.  The Pin driver's
    stage-specific variable plus its target Armature gives us a live path that
    remains tied to this rig instance.
    """

    prefix = "semantic:"
    suffix = ":pin_constraint"
    if not role.startswith(prefix) or not role.endswith(suffix):
        return ()
    stage_uuid = role[len(prefix) : -len(suffix)]
    animation_data = armature.animation_data
    if animation_data is None:
        return ()
    result = []
    for fcurve in animation_data.drivers:
        if not _driver_is_owned(fcurve, armature, stage_uuid, fcurve.data_path):
            continue
        for pose_bone in armature.pose.bones:
            for constraint in pose_bone.constraints:
                if constraint.path_from_id("influence") != fcurve.data_path:
                    continue
                if not any(
                    candidate[1] == constraint for candidate in result
                ):
                    result.append((pose_bone, constraint))
    return tuple(result)


def _property_data_path(property_name):
    return f"[{json.dumps(str(property_name))}]"


def _pin_property_marker_name(stage_uuid):
    token = re.sub(r"[^0-9A-Za-z]", "", str(stage_uuid or ""))
    return f"_coa_pin_owner_{token}"


def _pin_property_marker_value(pose_bone, component, stage_uuid, property_name):
    armature = pose_bone.id_data
    return (
        f"{ensure_rig_instance_id(armature)}|{component.component_uuid}|"
        f"{stage_uuid}|{property_name}"
    )


def _pin_property_is_owned(pose_bone, component, stage_uuid, property_name):
    marker_name = _pin_property_marker_name(stage_uuid)
    return pose_bone.get(marker_name) == _pin_property_marker_value(
        pose_bone,
        component,
        stage_uuid,
        property_name,
    )


def _marked_pin_property_name(pose_bone, component, stage_uuid):
    marker = pose_bone.get(_pin_property_marker_name(stage_uuid))
    prefix = (
        f"{ensure_rig_instance_id(pose_bone.id_data)}|{component.component_uuid}|"
        f"{stage_uuid}|"
    )
    if isinstance(marker, str) and marker.startswith(prefix):
        return marker[len(prefix) :]
    return ""


def _owned_pin_property_locations(armature, component, stage_uuid):
    result = []
    for pose_bone in armature.pose.bones:
        property_name = _marked_pin_property_name(pose_bone, component, stage_uuid)
        if property_name and property_name in pose_bone:
            result.append((pose_bone, property_name))
    return tuple(result)


def _claim_pin_property(pose_bone, component, stage_uuid, property_name, *, legacy_owned=False):
    marker_name = _pin_property_marker_name(stage_uuid)
    marker_value = _pin_property_marker_value(
        pose_bone,
        component,
        stage_uuid,
        property_name,
    )
    existing_marker = pose_bone.get(marker_name)
    if property_name in pose_bone and existing_marker != marker_value and not legacy_owned:
        raise ComponentArtifactConflict(
            f"Pose property '{property_name}' already exists and is not owned by this Pin stage."
        )
    if existing_marker not in {None, "", marker_value} and not legacy_owned:
        raise ComponentArtifactConflict(
            "The Pin ownership marker belongs to another property identity."
        )
    if property_name not in pose_bone:
        pose_bone[property_name] = 0.0
    pose_bone[marker_name] = marker_value


def _driver_is_owned(fcurve, armature, stage_uuid, valid_path):
    if fcurve is None or fcurve.data_path != valid_path:
        return False
    marker = _driver_marker(stage_uuid)
    legacy_marker = f"cp_{_short(stage_uuid)}"
    return any(
        variable.name in {marker, legacy_marker}
        and any(target.id == armature for target in variable.targets)
        for variable in fcurve.driver.variables
    )


def _remove_owned_influence_driver(armature, stage_uuid, constraint):
    animation_data = armature.animation_data
    if animation_data is None or constraint is None:
        return
    path = constraint.path_from_id("influence")
    for fcurve in tuple(animation_data.drivers):
        if not _driver_is_owned(fcurve, armature, stage_uuid, path):
            continue
        try:
            armature.driver_remove(path, fcurve.array_index)
        except (AttributeError, KeyError, RuntimeError, TypeError):
            try:
                armature.driver_remove(path)
            except (AttributeError, KeyError, RuntimeError, TypeError):
                pass


def _remove_action_fcurve(action, fcurve):
    legacy = getattr(action, "fcurves", None)
    if legacy is not None:
        legacy.remove(fcurve)
        return
    for layer in getattr(action, "layers", ()):
        for strip in layer.strips:
            if hasattr(strip, "channelbags"):
                channelbags = tuple(strip.channelbags)
            else:
                channelbags = tuple(
                    bag
                    for slot in getattr(action, "slots", ())
                    if (bag := strip.channelbag(slot)) is not None
                )
            for channelbag in channelbags:
                if any(candidate == fcurve for candidate in channelbag.fcurves):
                    channelbag.fcurves.remove(fcurve)
                    return


def _iter_action_fcurves_for_armature(armature, action):
    """Yield only the Action slot assigned to ``armature`` when available."""

    if action is None:
        return
    legacy = getattr(action, "fcurves", None)
    if legacy is not None:
        yield from legacy
        return
    animation_data = armature.animation_data
    slot = (
        getattr(animation_data, "action_slot", None)
        if animation_data is not None and animation_data.action == action
        else None
    )
    if slot is None:
        # Without a live slot association no channel bag can be proven to
        # belong to this Armature, so destructive callers see no curves.
        return
    for layer in getattr(action, "layers", ()):
        for strip in layer.strips:
            try:
                channelbag = strip.channelbag(slot)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                channelbag = None
            if channelbag is not None:
                yield from channelbag.fcurves


def _remove_pin_property_artifact(
    armature,
    component,
    stage_uuid,
    pose_bone,
    property_name,
    *,
    action=None,
    allow_legacy_owned=False,
    require_tagged_constraint=True,
):
    """Remove an owned Pin property without trusting saved artifact names.

    A PoseBone custom property has no native ID tags.  Its companion marker is
    therefore the primary identity.  Legacy files may use an exact artifact,
    but only while the stage's live driver resolves its constraint to this owner.
    Animation cleanup is intentionally limited to the Armature's active Action;
    an Action that is not currently assigned cannot be proven to belong to this
    particular Armature instance.
    """

    if pose_bone is None or armature.pose.bones.get(pose_bone.name) != pose_bone:
        return False
    constraint_role = semantic_stage_role(stage_uuid, "pin_constraint")
    tagged = _owned_contact_constraints(armature, component, constraint_role)
    tagged_owner = len(tagged) == 1 and tagged[0][0] == pose_bone
    marker_owned = _pin_property_is_owned(
        pose_bone,
        component,
        stage_uuid,
        property_name,
    )
    legacy_proven = allow_legacy_owned and tagged_owner
    if require_tagged_constraint and not (tagged_owner or marker_owned):
        return False
    if not marker_owned and not legacy_proven:
        return False

    full_path = pose_bone.path_from_id(_property_data_path(property_name))
    if action is None:
        action = armature.animation_data.action if armature.animation_data else None
    active_action = armature.animation_data.action if armature.animation_data else None
    real_users = (
        action.users - int(bool(getattr(action, "use_fake_user", False)))
        if action is not None
        else 0
    )
    if action is not None and action == active_action and real_users <= 1:
        for fcurve in tuple(_iter_action_fcurves_for_armature(armature, action)):
            if fcurve.data_path == full_path:
                _remove_action_fcurve(action, fcurve)
    if property_name in pose_bone:
        del pose_bone[property_name]
    marker_name = _pin_property_marker_name(stage_uuid)
    expected_marker = _pin_property_marker_value(
        pose_bone,
        component,
        stage_uuid,
        property_name,
    )
    if pose_bone.get(marker_name) == expected_marker:
        del pose_bone[marker_name]
    return True


def _reconcile_contact_identity(
    armature,
    component,
    stage,
    driven_pose,
    constraint_name,
    constraint_type,
    property_name,
):
    """Reconcile a Pin using live role tags, never artifact names alone."""

    constraint_role = semantic_stage_role(stage.stage_uuid, "pin_constraint")
    driver_role = semantic_stage_role(stage.stage_uuid, "pin_influence_driver")
    property_role = semantic_stage_role(stage.stage_uuid, "pin_property")
    related_roles = {constraint_role, driver_role, property_role}
    relevant_artifacts = [
        artifact for artifact in component.artifacts if artifact.role in related_roles
    ]
    for artifact in relevant_artifacts:
        if not artifact.owned:
            raise ComponentArtifactConflict(
                f"The existing Pin artifact '{artifact.role}' is not component-owned."
            )

    tagged = _owned_contact_constraints(armature, component, constraint_role)
    if len(tagged) > 1:
        raise ComponentArtifactConflict(
            f"Multiple managed constraints use role '{constraint_role}'."
        )
    constraint_pose, old_constraint = tagged[0] if tagged else (None, None)
    old_property_artifacts = [
        artifact
        for artifact in relevant_artifacts
        if artifact.role == property_role and artifact.data_type == "ID_PROPERTY"
    ]
    property_locations = _owned_pin_property_locations(
        armature,
        component,
        stage.stage_uuid,
    )
    if len(property_locations) > 1:
        raise ComponentArtifactConflict(
            "Multiple Pose properties are marked for the same Pin stage."
        )
    property_pose, old_property_name = (
        property_locations[0] if property_locations else (None, "")
    )
    legacy_property = False
    if (
        property_pose is None
        and constraint_pose is not None
        and old_property_artifacts
    ):
        # Migration path for pre-marker files.  This name is trusted only in
        # conjunction with the live, role-tagged constraint resolved above.
        property_pose = constraint_pose
        old_property_name = old_property_artifacts[0].constraint_name
        legacy_property = True
    same_property_identity = (
        property_pose == driven_pose and old_property_name == property_name
    )
    legacy_owned = bool(
        same_property_identity
        and old_constraint is not None
        and old_property_artifacts
    )

    desired_property_owned = _pin_property_is_owned(
        driven_pose,
        component,
        stage.stage_uuid,
        property_name,
    )
    if (
        property_name in driven_pose
        and not desired_property_owned
        and not legacy_owned
    ):
        raise ComponentArtifactConflict(
            f"Pose property '{property_name}' already exists and is not owned by this Pin stage."
        )
    name_collision = driven_pose.constraints.get(constraint_name)
    old_reusable_by_owner = (
        constraint_pose == driven_pose
        and old_constraint is not None
        and old_constraint.type == constraint_type
    )
    if name_collision is not None and name_collision != old_constraint and not old_reusable_by_owner:
        raise ComponentArtifactConflict(
            f"Constraint '{constraint_name}' has no live owned Pin driver."
        )

    if property_pose is not None and old_property_name and not same_property_identity:
        _remove_pin_property_artifact(
            armature,
            component,
            stage.stage_uuid,
            property_pose,
            old_property_name,
            allow_legacy_owned=legacy_property,
            require_tagged_constraint=legacy_property,
        )
    elif same_property_identity:
        _claim_pin_property(
            driven_pose,
            component,
            stage.stage_uuid,
            property_name,
            legacy_owned=legacy_owned,
        )

    reusable = (
        constraint_pose == driven_pose
        and old_constraint is not None
        and old_constraint.type == constraint_type
    )
    if old_constraint is not None and not reusable:
        _remove_owned_influence_driver(armature, stage.stage_uuid, old_constraint)
        constraint_pose.constraints.remove(old_constraint)
        _clear_pin_constraint_marker(
            armature,
            component,
            stage.stage_uuid,
            constraint_pose,
        )

    # Artifact records are summaries, not authority.  Re-record them from the
    # resolved live IDs after the build succeeds.
    for index in range(len(component.artifacts) - 1, -1, -1):
        if component.artifacts[index].role in related_roles:
            component.artifacts.remove(index)

    if property_name in driven_pose:
        _claim_pin_property(
            driven_pose,
            component,
            stage.stage_uuid,
            property_name,
            legacy_owned=legacy_owned,
        )


def _ensure_pin_constraint(
    armature,
    component,
    stage,
    driven_pose,
    constraint_name,
    constraint_type,
):
    role = semantic_stage_role(stage.stage_uuid, "pin_constraint")
    tagged = _owned_contact_constraints(armature, component, role)
    if len(tagged) > 1:
        raise ComponentArtifactConflict(
            f"Multiple managed constraints use role '{role}'."
        )
    if tagged:
        owner, constraint = tagged[0]
        if owner != driven_pose or constraint.type != constraint_type:
            raise ComponentArtifactConflict(
                "The resolved Pin constraint identity does not match its requested owner."
            )
    else:
        constraint = driven_pose.constraints.get(constraint_name)
        if constraint is not None:
            # Neither artifact names nor a PoseBone marker can distinguish a
            # renamed generated constraint from a user constraint that later
            # reused its old name.  Refuse the destructive ambiguity.
            raise ComponentArtifactConflict(
                f"Constraint '{constraint_name}' has no live owned Pin driver."
            )
        constraint = driven_pose.constraints.new(constraint_type)
        constraint.name = constraint_name
    _mark_pin_constraint(
        armature,
        component,
        stage.stage_uuid,
        driven_pose,
        constraint,
    )
    return constraint


def _ensure_influence_driver(armature, component, stage, driven_pose, constraint, property_name):
    _claim_pin_property(
        driven_pose,
        component,
        stage.stage_uuid,
        property_name,
    )
    try:
        driven_pose.id_properties_ui(property_name).update(
            min=0.0, max=1.0, soft_min=0.0, soft_max=1.0
        )
    except (AttributeError, TypeError):
        pass
    fcurve = constraint.driver_add("influence")
    driver = fcurve.driver
    driver.type = "SCRIPTED"
    while driver.variables:
        driver.variables.remove(driver.variables[0])
    variable = driver.variables.new()
    variable.name = _driver_marker(stage.stage_uuid)
    variable.type = "SINGLE_PROP"
    target = variable.targets[0]
    target.id = armature
    target.data_path = driven_pose.path_from_id(_property_data_path(property_name))
    driver.expression = variable.name
    role = semantic_stage_role(stage.stage_uuid, "pin_influence_driver")
    _record_artifact(
        component,
        role,
        "DRIVER",
        object_name=armature.name,
        bone_name=driven_pose.name,
        constraint_name=constraint.name,
        data_path=constraint.path_from_id("influence"),
        binding_uuid=stage.stage_uuid,
        owned=True,
    )


def ensure_contact_pin_artifacts(armature, component, stage, *, default_driven_bone=""):
    driven_name = stage.pin_driven_bone or default_driven_bone
    driven_pose = armature.pose.bones.get(driven_name)
    if driven_pose is None:
        raise SemanticContactError("Pin layer needs a generated or existing driven bone.")
    stage.pin_driven_bone = driven_pose.name
    property_name = stage.pin_property or f"pin_{_short(stage.stage_uuid)}"
    stage.pin_property = property_name
    constraint_name = f"COA_PIN_{_short(component.component_uuid)}_{_short(stage.stage_uuid)}"
    constraint_type = _constraint_type(stage)
    _reconcile_contact_identity(
        armature,
        component,
        stage,
        driven_pose,
        constraint_name,
        constraint_type,
        property_name,
    )
    anchor = _ensure_anchor(armature, component, stage, driven_pose)
    role = semantic_stage_role(stage.stage_uuid, "pin_constraint")
    constraint = _ensure_pin_constraint(
        armature,
        component,
        stage,
        driven_pose,
        constraint_name,
        constraint_type,
    )
    constraint.target = anchor
    constraint.owner_space = "WORLD"
    constraint.target_space = "WORLD"
    if hasattr(constraint, "mix_mode"):
        constraint.mix_mode = "REPLACE"
    _record_artifact(
        component,
        role,
        "CONSTRAINT",
        bone_name=driven_pose.name,
        constraint_name=constraint.name,
        owned=True,
    )
    _claim_pin_property(
        driven_pose,
        component,
        stage.stage_uuid,
        property_name,
    )
    _record_artifact(
        component,
        semantic_stage_role(stage.stage_uuid, "pin_property"),
        "ID_PROPERTY",
        object_name=armature.name,
        bone_name=driven_pose.name,
        constraint_name=property_name,
        data_path=driven_pose.path_from_id(_property_data_path(property_name)),
        binding_uuid=stage.stage_uuid,
        owned=True,
    )
    _ensure_influence_driver(
        armature, component, stage, driven_pose, constraint, property_name
    )
    return ContactPinArtifacts(
        driven_bone=driven_pose.name,
        anchor_object=anchor.name,
        constraint_name=constraint.name,
        property_name=property_name,
    )


def _range_support(stage):
    return stage.pin_start - stage.blend_in, stage.pin_end + stage.blend_out


def _pin_range_identity(stage, *, resolved):
    if resolved:
        return ("BONE", stage.pin_driven_bone) if stage.pin_driven_bone else None
    # A user-entered bone is already an exact destination.  Automatically
    # wired bones are derived from the current DAG dependency instead, so a
    # stale name from the previous build cannot make two unrelated branches
    # appear to overlap.
    if stage.pin_driven_bone and not stage.pin_driven_stage_uuid:
        return "BONE", stage.pin_driven_bone
    dependencies = tuple(
        value.strip() for value in stage.depends_on.split(",") if value.strip()
    )
    if len(dependencies) == 1:
        return "STAGE", dependencies[0]
    if stage.pin_driven_stage_uuid in dependencies:
        return "STAGE", stage.pin_driven_stage_uuid
    return None


def validate_pin_ranges(component, *, resolved=False):
    stages = [
        stage
        for stage in component.semantic_stages
        if stage.enabled and stage.stage_type == "CONTACT_PIN"
    ]
    for stage in stages:
        if stage.pin_end < stage.pin_start:
            raise SemanticContactError("Pin end frame must not precede its start.")
    for index, left in enumerate(stages):
        left_start, left_end = _range_support(left)
        left_identity = _pin_range_identity(left, resolved=resolved)
        if resolved and left_identity is None:
            raise SemanticContactError(
                f"Pin '{left.label}' has no resolved driven bone."
            )
        for right in stages[index + 1 :]:
            right_identity = _pin_range_identity(right, resolved=resolved)
            if resolved and right_identity is None:
                raise SemanticContactError(
                    f"Pin '{right.label}' has no resolved driven bone."
                )
            if (
                left_identity is None
                or right_identity is None
                or left_identity != right_identity
            ):
                continue
            right_start, right_end = _range_support(right)
            if max(left_start, right_start) <= min(left_end, right_end):
                raise SemanticContactError(
                    f"Pin ranges overlap on "
                    f"'{left.pin_driven_bone or left.label}'."
                )


_KEYFRAME_ATTRIBUTES = (
    "interpolation",
    "easing",
    "amplitude",
    "back",
    "period",
    "handle_left_type",
    "handle_right_type",
    "type",
)


def _snapshot_keyframe_points(fcurve):
    snapshots = []
    for point in fcurve.keyframe_points:
        snapshot = {
            "co": tuple(point.co),
            "handle_left": tuple(point.handle_left),
            "handle_right": tuple(point.handle_right),
        }
        for attribute in _KEYFRAME_ATTRIBUTES:
            if hasattr(point, attribute):
                snapshot[attribute] = getattr(point, attribute)
        snapshots.append(snapshot)
    return tuple(snapshots)


def _clear_keyframe_points(fcurve):
    while fcurve.keyframe_points:
        fcurve.keyframe_points.remove(fcurve.keyframe_points[-1], fast=True)
    fcurve.update()


def _snapshot_action_curves(armature, action, data_path):
    if action is None:
        return ()
    return tuple(
        (fcurve, _snapshot_keyframe_points(fcurve))
        for fcurve in _iter_action_fcurves_for_armature(armature, action)
        if fcurve.data_path == data_path
    )


def _restore_action_curves(armature, action, data_path, snapshots):
    if action is None:
        return
    originals = tuple(fcurve for fcurve, _points in snapshots)
    for fcurve in tuple(_iter_action_fcurves_for_armature(armature, action)):
        if fcurve.data_path == data_path and not any(
            fcurve == original for original in originals
        ):
            _remove_action_fcurve(action, fcurve)
    for fcurve, points in snapshots:
        _clear_keyframe_points(fcurve)
        for snapshot in points:
            point = fcurve.keyframe_points.insert(
                snapshot["co"][0],
                snapshot["co"][1],
                options={"FAST"},
            )
            # Handle types affect auto-handle positions, so restore scalar
            # settings before writing the exact coordinates last.
            for attribute in _KEYFRAME_ATTRIBUTES:
                if attribute in snapshot:
                    try:
                        setattr(point, attribute, snapshot[attribute])
                    except (AttributeError, TypeError, ValueError):
                        pass
            point.co = snapshot["co"]
            point.handle_left = snapshot["handle_left"]
            point.handle_right = snapshot["handle_right"]
        fcurve.update()


def _insert_pin_key(pose_bone, data_path, frame):
    return pose_bone.keyframe_insert(
        data_path=data_path,
        frame=frame,
        group=pose_bone.name,
    )


def key_pin_range(armature, component, stage):
    validate_pin_ranges(component, resolved=True)
    pose_bone = armature.pose.bones.get(stage.pin_driven_bone)
    if pose_bone is None or not stage.pin_property:
        raise SemanticContactError("Build the Pin layer before keying its range.")
    constraint_role = semantic_stage_role(stage.stage_uuid, "pin_constraint")
    tagged = _owned_contact_constraints(armature, component, constraint_role)
    if len(tagged) != 1 or tagged[0][0] != pose_bone:
        raise SemanticContactError("The Pin destination is not owned by this stage.")
    if not _pin_property_is_owned(
        pose_bone,
        component,
        stage.stage_uuid,
        stage.pin_property,
    ):
        raise SemanticContactError("The Pin property is not owned by this stage.")
    anchor_role = semantic_stage_role(stage.stage_uuid, "pin_anchor")
    anchor = find_component_object(armature, component.component_uuid, anchor_role)
    if anchor is None:
        raise SemanticContactError("Pin anchor is missing.")

    scene = bpy.context.scene
    previous_frame = scene.frame_current
    property_name = stage.pin_property
    data_path = _property_data_path(property_name)
    full_path = pose_bone.path_from_id(data_path)
    previous_property_exists = property_name in pose_bone
    previous_property_value = pose_bone.get(property_name)
    previous_anchor_matrix = anchor.matrix_world.copy()
    previous_animation_data = armature.animation_data
    previous_action = previous_animation_data.action if previous_animation_data else None
    curve_snapshots = _snapshot_action_curves(armature, previous_action, full_path)
    values = (
        (stage.pin_start - stage.blend_in, 0.0),
        (stage.pin_start, 1.0),
        (stage.pin_end, 1.0),
        (stage.pin_end + stage.blend_out, 0.0),
    )
    restore_destination = False
    try:
        if previous_action is not None:
            for fcurve in _iter_action_fcurves_for_armature(
                armature,
                previous_action,
            ):
                if fcurve.data_path != full_path:
                    continue
                _clear_keyframe_points(fcurve)
        pose_bone[property_name] = 0.0
        scene.frame_set(stage.pin_start)
        bpy.context.view_layer.update()
        anchor.matrix_world = armature.matrix_world @ pose_bone.matrix
        for frame, value in values:
            pose_bone[property_name] = value
            if not _insert_pin_key(pose_bone, data_path, frame):
                raise SemanticContactError(
                    f"Could not key Pin property '{property_name}' at frame {frame}."
                )
        action = armature.animation_data.action if armature.animation_data else None
        if action is not None:
            for fcurve in _iter_action_fcurves_for_armature(armature, action):
                if fcurve.data_path == full_path:
                    for point in fcurve.keyframe_points:
                        point.interpolation = "LINEAR"
        pose_bone[property_name] = 0.0
    except Exception:
        # Restore the exact destination state before exposing the failure.  In
        # particular, a partial key insertion must not replace an animator's
        # prior Pin curve or silently switch the Armature's active Action.
        current_action = armature.animation_data.action if armature.animation_data else None
        if previous_action is not None:
            if armature.animation_data is None:
                armature.animation_data_create()
            armature.animation_data.action = previous_action
            _restore_action_curves(
                armature,
                previous_action,
                full_path,
                curve_snapshots,
            )
        elif armature.animation_data is not None:
            armature.animation_data.action = None
        if (
            current_action is not None
            and current_action != previous_action
            and current_action.users == 0
        ):
            bpy.data.actions.remove(current_action)
        restore_destination = True
        raise
    finally:
        scene.frame_set(previous_frame)
        bpy.context.view_layer.update()
        if restore_destination:
            # Frame evaluation may reapply the keyed value or parent motion,
            # so destination state is restored after returning to the caller's
            # frame rather than before it.
            anchor.matrix_world = previous_anchor_matrix
            if previous_property_exists:
                pose_bone[property_name] = previous_property_value
            elif property_name in pose_bone:
                del pose_bone[property_name]
    return values


__all__ = [
    "ContactPinArtifacts",
    "SemanticContactError",
    "ensure_contact_pin_artifacts",
    "key_pin_range",
    "validate_pin_ranges",
]
