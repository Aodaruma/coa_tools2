"""Isolation helpers for copied State/Graph Rig Control definitions."""

from __future__ import annotations

import bpy

from ..instance_fork import (
    RigControlIdentifierSnapshot,
    build_rig_control_identifier_forks,
)
from .artifacts import (
    limit_distance_name,
    limit_location_name,
    limit_rotation_name,
    rail_constraint_name,
)
from .component_safety import ensure_unique_component_instance
from .drivers import find_driver
from .properties import get_rig_data


class RigControlForkError(RuntimeError):
    """Raised before a copy fork would mutate a source-owned target."""


def _rig_controls(owner):
    rig_data = getattr(owner, "coa_tools2_rig", None)
    return tuple(rig_data.rig_controls) if rig_data is not None else ()


def _collision_peers(armature, old_instance_id, control_uuids):
    peers = []
    for owner in bpy.data.objects:
        if owner == armature or getattr(owner, "type", "") != "ARMATURE":
            continue
        rig_data = getattr(owner, "coa_tools2_rig", None)
        if rig_data is None:
            continue
        owner_control_ids = {
            item.control_uuid for item in rig_data.rig_controls if item.control_uuid
        }
        if (
            old_instance_id
            and rig_data.rig_instance_id == old_instance_id
        ) or control_uuids.intersection(owner_control_ids):
            peers.append(owner)
    return tuple(peers)


def _shape_key_owner(target_object):
    if target_object is None or getattr(target_object, "type", "") != "MESH":
        return None
    return getattr(target_object.data, "shape_keys", None)


def _same_driven_target(left, right, target_kind="SHAPE_KEY_VALUE"):
    if left is None or right is None:
        return False
    if target_kind == "SHAPE_KEY_VALUE":
        left_keys = _shape_key_owner(left)
        return left_keys is not None and left_keys == _shape_key_owner(right)
    return left == right


def _preflight_driven_target_isolation(controls, peers):
    """Reject a copy that still writes into the source character's target."""

    peer_controls = tuple(
        control
        for peer in peers
        for control in _rig_controls(peer)
        if control.control_uuid
    )
    for control in controls:
        matches = tuple(
            peer_control
            for peer_control in peer_controls
            if peer_control.control_uuid == control.control_uuid
        )
        for peer_control in matches:
            peer_bindings = {
                binding.binding_uuid: binding
                for binding in peer_control.bindings
                if binding.binding_uuid
            }
            for binding in control.bindings:
                if not binding.enabled or binding.target_object is None:
                    continue
                peer_binding = peer_bindings.get(binding.binding_uuid)
                if peer_binding is None:
                    continue
                if _same_driven_target(
                    binding.target_object,
                    peer_binding.target_object,
                    binding.target_kind,
                ):
                    raise RigControlForkError(
                        "Copied Rig Control still shares a driven target with "
                        "its source. Duplicate/remap the target object before "
                        f"Update: {control.label} / {binding.target_name}."
                    )

            peer_points = {
                point.state_uuid: point
                for point in peer_control.state_points
                if point.state_uuid
            }
            for point in control.state_points:
                if (
                    not point.enabled
                    or point.is_empty
                    or point.target_object is None
                    or not point.target_name
                ):
                    continue
                peer_point = peer_points.get(point.state_uuid)
                if peer_point is None:
                    continue
                if _same_driven_target(
                    point.target_object,
                    peer_point.target_object,
                ):
                    raise RigControlForkError(
                        "Copied State Rig still shares Shape Keys with its "
                        "source. Duplicate/remap the target mesh before "
                        f"Update: {control.label} / {point.target_name}."
                    )


def _make_armature_data_single_user(armature):
    if armature.data.users <= 1:
        return
    original_mode = armature.mode
    if bpy.context.active_object != armature:
        if bpy.context.active_object and bpy.context.active_object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature
    if armature.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    armature.data = armature.data.copy()
    if original_mode == "POSE":
        bpy.ops.object.mode_set(mode="POSE")


def _binding_driver(binding):
    target = binding.target_object
    if target is None:
        return None
    if binding.target_kind == "SHAPE_KEY_VALUE":
        shape_keys = _shape_key_owner(target)
        if shape_keys is None or binding.target_name not in shape_keys.key_blocks:
            return None
        data_path = shape_keys.key_blocks[binding.target_name].path_from_id("value")
        return find_driver(shape_keys, data_path)
    if binding.target_kind == "CONSTRAINT_INFLUENCE":
        pose_bone = target.pose.bones.get(binding.target_bone)
        constraint = (
            pose_bone.constraints.get(binding.target_name)
            if pose_bone is not None
            else None
        )
        return (
            find_driver(target, constraint.path_from_id("influence"))
            if constraint
            else None
        )
    return None


def _state_driver(point):
    shape_keys = _shape_key_owner(point.target_object)
    if shape_keys is None or point.target_name not in shape_keys.key_blocks:
        return None
    data_path = shape_keys.key_blocks[point.target_name].path_from_id("value")
    return find_driver(shape_keys, data_path)


def _retarget_copied_driver(fcurve, armature, peers, control_bone):
    if fcurve is None:
        return
    for variable in fcurve.driver.variables:
        if variable.type != "TRANSFORMS":
            continue
        target = variable.targets[0]
        if target.id in peers and target.bone_target == control_bone:
            target.id = armature


def _retarget_copied_drivers(armature, controls, peers):
    for control in controls:
        for binding in control.bindings:
            _retarget_copied_driver(
                _binding_driver(binding),
                armature,
                peers,
                control.control_bone,
            )
        for point in control.state_points:
            _retarget_copied_driver(
                _state_driver(point),
                armature,
                peers,
                control.control_bone,
            )


def _remove_copied_constraints(armature, controls):
    for control in controls:
        pose_bone = armature.pose.bones.get(control.control_bone)
        if pose_bone is None:
            continue
        names = {
            limit_location_name(control.control_uuid),
            limit_distance_name(control.control_uuid),
            limit_rotation_name(control.control_uuid),
            rail_constraint_name(control.control_uuid),
        }
        for constraint in tuple(pose_bone.constraints):
            if constraint.name in names:
                pose_bone.constraints.remove(constraint)


def _retag_owned_objects(armature, new_instance_id, uuid_map):
    retagged_names = {}
    for obj in bpy.data.objects:
        old_control_uuid = obj.get("coa_rig_control_uuid")
        if (
            obj.parent != armature
            or old_control_uuid not in uuid_map
            or obj.get("coa_rig_artifact_role") not in {"name_text", "rail_target"}
        ):
            continue
        obj["coa_rig_instance_id"] = new_instance_id
        obj["coa_rig_control_uuid"] = uuid_map[old_control_uuid]
        if obj.get("coa_rig_artifact_role") == "name_text":
            if obj.data is not None and obj.data.users > 1:
                obj.data = obj.data.copy()
            retagged_names[old_control_uuid] = obj.name
    return retagged_names


def ensure_unique_rig_control_instance(armature):
    """Fork all normal Rig Controls when this Armature is a copied owner.

    Component instance isolation is reused for the shared Armature-level ID and
    semantic artifacts.  Control, state, widget, constraint, and ordinary
    object ownership are then forked as one cohort before compilation.
    """

    rig_data = get_rig_data(armature)
    controls = tuple(rig_data.rig_controls)
    if not controls:
        return False
    old_instance_id = rig_data.rig_instance_id
    control_uuids = {
        control.control_uuid for control in controls if control.control_uuid
    }
    peers = _collision_peers(armature, old_instance_id, control_uuids)
    if not peers:
        return False

    _preflight_driven_target_isolation(controls, peers)
    instance_collision = any(
        getattr(peer, "coa_tools2_rig", None) is not None
        and peer.coa_tools2_rig.rig_instance_id == old_instance_id
        for peer in peers
    )
    if instance_collision:
        ensure_unique_component_instance(armature)
    # The component helper returns early when a legacy empty instance ID is
    # initialized before its peer can match.  Enforce data isolation here as
    # well so retagging copied bones can never touch shared Armature data.
    _make_armature_data_single_user(armature)
    new_instance_id = rig_data.rig_instance_id
    if instance_collision and new_instance_id == old_instance_id:
        raise RigControlForkError(
            "Could not allocate an isolated Armature rig instance ID."
        )

    # Drivers copied with independent target data still point to the source
    # Armature. Retarget them while old bone names/UUIDs remain available, so
    # the normal compiler can safely recognize and replace its own FCurves.
    _retarget_copied_drivers(armature, controls, peers)
    _remove_copied_constraints(armature, controls)

    snapshots = tuple(
        RigControlIdentifierSnapshot(
            control_uuid=control.control_uuid,
            tip_widget_uuid=control.tip_widget_uuid,
            base_widget_uuid=control.base_widget_uuid,
            binding_uuids=tuple(item.binding_uuid for item in control.bindings),
            state_uuids=tuple(item.state_uuid for item in control.state_points),
            cell_uuids=tuple(item.cell_uuid for item in control.state_cells),
        )
        for control in controls
    )
    forks = build_rig_control_identifier_forks(snapshots)
    control_uuid_map = {
        snapshot.control_uuid: fork.control_uuid
        for snapshot, fork in zip(snapshots, forks)
        if snapshot.control_uuid
    }
    text_names = _retag_owned_objects(
        armature,
        new_instance_id,
        control_uuid_map,
    )

    for bone in armature.data.bones:
        old_control_uuid = bone.get("coa_rig_control_uuid")
        if old_control_uuid in control_uuid_map:
            bone["coa_rig_instance_id"] = new_instance_id
            bone["coa_rig_control_uuid"] = control_uuid_map[old_control_uuid]

    for control, snapshot, fork in zip(controls, snapshots, forks):
        old_control_uuid = snapshot.control_uuid
        control.control_uuid = fork.control_uuid
        control.tip_widget_uuid = fork.tip_widget_uuid
        control.base_widget_uuid = fork.base_widget_uuid
        control.name_text_object = text_names.get(old_control_uuid, "")
        for binding, binding_uuid in zip(control.bindings, fork.binding_uuids):
            binding.binding_uuid = binding_uuid
            binding.control_uuid = fork.control_uuid
        state_uuid_map = dict(fork.state_uuid_remap)
        for point, state_uuid in zip(control.state_points, fork.state_uuids):
            old_fallback = point.fallback_state_uuid
            point.state_uuid = state_uuid
            point.control_uuid = fork.control_uuid
            point.fallback_state_uuid = state_uuid_map.get(old_fallback, "")
        for cell, cell_uuid in zip(control.state_cells, fork.cell_uuids):
            cell.cell_uuid = cell_uuid
            cell.control_uuid = fork.control_uuid
        control.needs_rebuild = True
        control.auto_rebuild_error = ""

    rig_data.rig_validation_issues.clear()
    return True


def preflight_isolated_rig_control_mutation(armature):
    """Require copied controls to be explicitly updated before definition edits."""

    rig_data = get_rig_data(armature)
    controls = tuple(rig_data.rig_controls)
    control_uuids = {
        control.control_uuid for control in controls if control.control_uuid
    }
    peers = _collision_peers(
        armature,
        rig_data.rig_instance_id,
        control_uuids,
    )
    if not peers:
        return
    _preflight_driven_target_isolation(controls, peers)
    raise RigControlForkError(
        "This is a copied Rig Control definition. Run Update Rig Control "
        "once to isolate its IDs and artifacts before changing State layout."
    )
