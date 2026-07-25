"""Preflight, isolation, and rollback helpers for pose components."""

from __future__ import annotations

from contextlib import contextmanager
import math
import uuid

import bpy

from .artifacts import ensure_rig_instance_id, slugify
from .properties import get_rig_data
from .widgets import ensure_widget_collection


class ComponentPreflightError(RuntimeError):
    pass


def _component_owns_constraint(component, bone_name, constraint_name):
    return any(
        artifact.data_type == "CONSTRAINT"
        and artifact.bone_name == bone_name
        and artifact.constraint_name == constraint_name
        and artifact.owned
        for artifact in component.artifacts
    )


def ensure_unique_component_instance(armature):
    """Fork copied component artifacts before either Armature is rebuilt."""

    rig_data = get_rig_data(armature)
    old_instance_id = ensure_rig_instance_id(armature)
    duplicate_owner = next(
        (
            obj
            for obj in bpy.data.objects
            if obj != armature
            and obj.type == "ARMATURE"
            and getattr(obj, "coa_tools2_rig", None) is not None
            and obj.coa_tools2_rig.rig_instance_id == old_instance_id
        ),
        None,
    )
    if duplicate_owner is None:
        return False

    if armature.data.users > 1:
        original_mode = armature.mode
        if bpy.context.active_object != armature:
            armature.select_set(True)
            bpy.context.view_layer.objects.active = armature
        if armature.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        armature.data = armature.data.copy()
        if original_mode == "POSE":
            bpy.ops.object.mode_set(mode="POSE")

    new_instance_id = str(uuid.uuid4())
    rig_data.rig_instance_id = new_instance_id
    for data_bone in armature.data.bones:
        if data_bone.get("coa_rig_instance_id") == old_instance_id:
            data_bone["coa_rig_instance_id"] = new_instance_id

    widget_collection = ensure_widget_collection()
    for component in rig_data.rig_components:
        replacements = {}
        for artifact in component.artifacts:
            if artifact.data_type != "OBJECT" or not artifact.object_name:
                continue
            source = bpy.data.objects.get(artifact.object_name)
            if (
                source is None
                or source.get("coa_rig_instance_id") != old_instance_id
                or source.get("coa_rig_component_uuid") != component.component_uuid
            ):
                continue
            replacement = replacements.get(source.name)
            if replacement is None:
                replacement = source.copy()
                if source.data is not None:
                    replacement.data = source.data.copy()
                widget_collection.objects.link(replacement)
                replacement["coa_rig_instance_id"] = new_instance_id
                replacements[source.name] = replacement
            artifact.object_name = replacement.name
        if not replacements:
            continue
        for pose_bone in armature.pose.bones:
            if pose_bone.custom_shape is None:
                continue
            replacement = replacements.get(pose_bone.custom_shape.name)
            if replacement is not None:
                pose_bone.custom_shape = replacement
    return True


def _managed_shape(shape, instance_id, component_uuid):
    return (
        shape is not None
        and shape.get("coa_rig_instance_id") == instance_id
        and shape.get("coa_rig_component_uuid") == component_uuid
    )


def preflight_component_artifacts(armature, component):
    """Reject known conflicts before changing any Blender data."""

    instance_id = ensure_rig_instance_id(armature)
    source_names = [reference.bone_name for reference in component.source_bones]
    for name in source_names:
        data_bone = armature.data.bones.get(name)
        pose_bone = armature.pose.bones.get(name)
        if data_bone is None or pose_bone is None:
            continue
        owner_uuid = data_bone.get("coa_rig_component_uuid")
        owner_instance = data_bone.get("coa_rig_instance_id")
        if owner_uuid not in {None, "", component.component_uuid}:
            raise ComponentPreflightError(
                f"Source bone '{name}' belongs to another pose component."
            )
        if owner_uuid == component.component_uuid and owner_instance != instance_id:
            raise ComponentPreflightError(
                f"Source bone '{name}' belongs to another Armature instance."
            )
        if (
            component.deformation_mode == "DIRECT_BONES"
            and component.component_type in {"ROOT", "FK_CHAIN", "SPINE_FK"}
        ):
            shape = pose_bone.custom_shape
            if shape is not None and not _managed_shape(
                shape,
                instance_id,
                component.component_uuid,
            ):
                raise ComponentPreflightError(
                    f"Source bone '{name}' already has an unmanaged custom shape."
                )

    depth_owner = None
    if component.deformation_mode == "PARAMETRIC" and component.control_bone:
        depth_owner = armature.pose.bones.get(component.control_bone)
    elif component.component_type == "ROOT" and source_names:
        depth_owner = armature.pose.bones.get(source_names[0])
    elif component.component_type == "LIMB_IK" and component.control_bone:
        depth_owner = armature.pose.bones.get(component.control_bone)
    if depth_owner is not None:
        depth_name = f"COA_COMP_{component.component_uuid[:8]}_Depth"
        depth_constraint = depth_owner.constraints.get(depth_name)
        if depth_constraint is not None and not _component_owns_constraint(
            component,
            depth_owner.name,
            depth_name,
        ):
            raise ComponentPreflightError(
                f"Constraint '{depth_name}' is unmanaged."
            )

    slug = slugify(component.semantic_id or component.label)
    expected_bones = ()
    if (
        component.deformation_mode == "PARAMETRIC"
        or component.component_type == "LIMB_IK"
    ):
        expected_bones = (
            (component.frame_bone or f"MCH_{slug}_FRAME", "control_frame"),
            (component.control_bone or f"CTRL_{slug}", "control_bone"),
        )
        if (
            component.deformation_mode == "DIRECT_BONES"
            and component.component_type == "LIMB_IK"
            and component.use_bend_hint
            and component.ik_solver_mode == "SPATIAL"
        ):
            expected_bones += (
                (component.pole_bone or f"CTRL_{slug}_BEND", "bend_control"),
                (
                    f"MCH_{slug}_BEND_CENTER",
                    "bend_center",
                ),
            )
    for bone_name, role in expected_bones:
        existing = armature.data.bones.get(bone_name)
        if existing is None:
            continue
        if not (
            existing.get("coa_rig_instance_id") == instance_id
            and existing.get("coa_rig_component_uuid") == component.component_uuid
            and existing.get("coa_rig_component_role") == role
        ):
            raise ComponentPreflightError(
                f"Bone '{bone_name}' already exists and is unmanaged."
            )

    if (
        component.deformation_mode != "DIRECT_BONES"
        or component.component_type != "LIMB_IK"
    ):
        return

    owner = armature.pose.bones.get(source_names[-2])
    end = armature.pose.bones.get(source_names[-1])
    if owner is None or end is None:
        return
    ik_name = f"COA_COMP_{component.component_uuid[:8]}_IK"
    for constraint in owner.constraints:
        if constraint.type != "IK":
            continue
        if (
            constraint.name != ik_name
            or not _component_owns_constraint(component, owner.name, ik_name)
        ):
            raise ComponentPreflightError(
                f"Bone '{owner.name}' already has an unmanaged IK constraint."
            )
    if (
        component.use_bend_hint
        and component.ik_solver_mode == "SPATIAL"
    ):
        pole_name = component.pole_bone or f"CTRL_{slug}_BEND"
        pole = armature.pose.bones.get(pole_name)
        bend_distance_name = (
            f"COA_COMP_{component.component_uuid[:8]}_BendDistance"
        )
        bend_distance = (
            pole.constraints.get(bend_distance_name)
            if pole is not None
            else None
        )
        if (
            bend_distance is not None
            and not _component_owns_constraint(
                component,
                pole.name,
                bend_distance_name,
            )
        ):
            raise ComponentPreflightError(
                f"Constraint '{bend_distance_name}' is unmanaged."
            )
    rotation_name = f"COA_COMP_{component.component_uuid[:8]}_EndRotation"
    for constraint in end.constraints:
        if constraint.type != "COPY_ROTATION":
            continue
        if (
            constraint.name != rotation_name
            or not _component_owns_constraint(component, end.name, rotation_name)
        ):
            raise ComponentPreflightError(
                f"Bone '{end.name}' already has an unmanaged Copy Rotation constraint."
            )

    for name in source_names[-1 - component.ik_chain_length : -1]:
        pose_bone = armature.pose.bones.get(name)
        data_bone = armature.data.bones.get(name)
        if pose_bone is None or data_bone is None:
            continue
        has_unsupported_settings = any(
            getattr(pose_bone, f"use_ik_limit_{axis}", False)
            for axis in "xyz"
        ) or any(
            not math.isclose(
                getattr(pose_bone, f"ik_stiffness_{axis}", 0.0),
                0.0,
                abs_tol=1e-6,
            )
            for axis in "xyz"
        )
        if has_unsupported_settings:
            raise ComponentPreflightError(
                f"Bone '{name}' has unmanaged IK channel settings."
            )
        if data_bone.get("coa_rig_component_uuid") == component.component_uuid:
            continue
        if (
            pose_bone.lock_ik_x
            or pose_bone.lock_ik_y
            or pose_bone.lock_ik_z
            or not math.isclose(pose_bone.ik_stretch, 0.0, abs_tol=1e-6)
        ):
            raise ComponentPreflightError(
                f"Bone '{name}' has unmanaged IK channel settings."
            )


def _constraint_snapshot(constraint, index):
    attributes = (
        "influence",
        "mute",
        "owner_space",
        "target_space",
        "use_transform_limit",
        "use_min_x",
        "use_max_x",
        "use_min_y",
        "use_max_y",
        "use_min_z",
        "use_max_z",
        "min_x",
        "max_x",
        "min_y",
        "max_y",
        "min_z",
        "max_z",
        "target",
        "subtarget",
        "pole_target",
        "pole_subtarget",
        "pole_angle",
        "chain_count",
        "use_stretch",
        "distance",
        "limit_mode",
    )
    values = {}
    for name in attributes:
        if hasattr(constraint, name):
            values[name] = getattr(constraint, name)
    return {
        "name": constraint.name,
        "type": constraint.type,
        "index": index,
        "values": values,
    }


def _pose_bone_snapshot(pose_bone):
    return {
        "custom_shape": pose_bone.custom_shape,
        "use_custom_shape_bone_size": pose_bone.use_custom_shape_bone_size,
        "custom_shape_wire_width": getattr(
            pose_bone,
            "custom_shape_wire_width",
            None,
        ),
        "rotation_mode": pose_bone.rotation_mode,
        "lock_location": tuple(pose_bone.lock_location),
        "lock_rotation": tuple(pose_bone.lock_rotation),
        "lock_scale": tuple(pose_bone.lock_scale),
        "lock_rotation_w": pose_bone.lock_rotation_w,
        "lock_rotations_4d": pose_bone.lock_rotations_4d,
        "lock_ik_x": pose_bone.lock_ik_x,
        "lock_ik_y": pose_bone.lock_ik_y,
        "lock_ik_z": pose_bone.lock_ik_z,
        "ik_stretch": pose_bone.ik_stretch,
        "hide_select": pose_bone.bone.hide_select,
        "bone_collections": tuple(
            collection.name for collection in pose_bone.bone.collections
        ),
        "bone_tags": {
            key: value
            for key, value in pose_bone.bone.items()
            if key.startswith("coa_rig_")
        },
    }


def _data_bone_snapshot(data_bone):
    attributes = (
        "use_deform",
        "use_connect",
        "inherit_scale",
        "use_inherit_rotation",
        "use_local_location",
        "use_relative_parent",
        "head_radius",
        "tail_radius",
        "envelope_distance",
        "envelope_weight",
    )
    values = {}
    for name in attributes:
        if hasattr(data_bone, name):
            values[name] = getattr(data_bone, name)
    return {
        "matrix": data_bone.matrix_local.copy(),
        "head": data_bone.head_local.copy(),
        "tail": data_bone.tail_local.copy(),
        "roll": getattr(data_bone, "roll", None),
        "length": data_bone.length,
        "parent_name": data_bone.parent.name if data_bone.parent else "",
        "values": values,
    }


def _component_bone_names(component):
    names = {
        reference.bone_name
        for reference in component.source_bones
        if reference.bone_name
    }
    names.update(
        name
        for name in (
            component.frame_bone,
            component.control_bone,
            component.pole_bone,
            component.constraint_bone,
        )
        if name
    )
    names.update(
        artifact.bone_name
        for artifact in component.artifacts
        if artifact.bone_name
    )
    return names


def capture_component_build_state(armature, component):
    widget_geometry = {}
    for obj in bpy.data.objects:
        if (
            obj.type == "MESH"
            and obj.get("coa_rig_component_uuid") == component.component_uuid
            and obj.get("coa_rig_instance_id") == ensure_rig_instance_id(armature)
        ):
            widget_geometry[obj.name] = {
                "vertices": tuple(tuple(vertex.co) for vertex in obj.data.vertices),
                "edges": tuple(tuple(edge.vertices) for edge in obj.data.edges),
            }
    constraints = {
        pose_bone.name: tuple(
            _constraint_snapshot(constraint, index)
            for index, constraint in enumerate(pose_bone.constraints)
        )
        for pose_bone in armature.pose.bones
    }
    pose_states = {
        name: _pose_bone_snapshot(armature.pose.bones[name])
        for name in _component_bone_names(component)
        if name in armature.pose.bones
    }
    bone_states = {
        name: _data_bone_snapshot(armature.data.bones[name])
        for name in _component_bone_names(component)
        if name in armature.data.bones
    }
    return {
        "object_names": frozenset(obj.name for obj in bpy.data.objects),
        "bone_names": frozenset(bone.name for bone in armature.data.bones),
        "constraints": constraints,
        "pose_states": pose_states,
        "bone_states": bone_states,
        "widget_geometry": widget_geometry,
        "artifacts": tuple(
            {
                "artifact_uuid": artifact.artifact_uuid,
                "role": artifact.role,
                "data_type": artifact.data_type,
                "object_name": artifact.object_name,
                "bone_name": artifact.bone_name,
                "constraint_name": artifact.constraint_name,
                "data_path": artifact.data_path,
                "binding_uuid": artifact.binding_uuid,
                "owned": artifact.owned,
            }
            for artifact in component.artifacts
        ),
        "component_fields": {
            name: getattr(component, name)
            for name in (
                "frame_bone",
                "control_bone",
                "pole_bone",
                "pole_angle",
                "pole_angle_valid",
                "constraint_bone",
                "constraint_name",
                "compiled_deformation_mode",
                "needs_rebuild",
                "last_error",
            )
        },
    }


def _restore_constraint(pose_bone, snapshot):
    constraint = pose_bone.constraints.get(snapshot["name"])
    if constraint is not None and constraint.type != snapshot["type"]:
        pose_bone.constraints.remove(constraint)
        constraint = None
    if constraint is None:
        constraint = pose_bone.constraints.new(snapshot["type"])
        constraint.name = snapshot["name"]
    for name, value in snapshot["values"].items():
        try:
            setattr(constraint, name, value)
        except (AttributeError, RuntimeError, TypeError):
            pass
    current_index = tuple(pose_bone.constraints).index(constraint)
    target_index = min(snapshot["index"], len(pose_bone.constraints) - 1)
    if current_index != target_index and hasattr(pose_bone.constraints, "move"):
        pose_bone.constraints.move(current_index, target_index)


def _restore_pose_bone(armature, name, snapshot):
    pose_bone = armature.pose.bones.get(name)
    if pose_bone is None:
        return
    pose_bone.custom_shape = snapshot["custom_shape"]
    pose_bone.use_custom_shape_bone_size = snapshot["use_custom_shape_bone_size"]
    if snapshot["custom_shape_wire_width"] is not None:
        pose_bone.custom_shape_wire_width = snapshot["custom_shape_wire_width"]
    pose_bone.rotation_mode = snapshot["rotation_mode"]
    pose_bone.lock_location = snapshot["lock_location"]
    pose_bone.lock_rotation = snapshot["lock_rotation"]
    pose_bone.lock_scale = snapshot["lock_scale"]
    pose_bone.lock_rotation_w = snapshot["lock_rotation_w"]
    pose_bone.lock_rotations_4d = snapshot["lock_rotations_4d"]
    pose_bone.lock_ik_x = snapshot["lock_ik_x"]
    pose_bone.lock_ik_y = snapshot["lock_ik_y"]
    pose_bone.lock_ik_z = snapshot["lock_ik_z"]
    pose_bone.ik_stretch = snapshot["ik_stretch"]
    pose_bone.bone.hide_select = snapshot["hide_select"]

    for key in tuple(pose_bone.bone.keys()):
        if key.startswith("coa_rig_"):
            del pose_bone.bone[key]
    for key, value in snapshot["bone_tags"].items():
        pose_bone.bone[key] = value

    expected_collections = set(snapshot["bone_collections"])
    for collection in armature.data.collections:
        assigned = pose_bone.bone.name in collection.bones
        if assigned and collection.name not in expected_collections:
            collection.unassign(pose_bone.bone)
        elif not assigned and collection.name in expected_collections:
            collection.assign(pose_bone.bone)


def rollback_component_build(armature, component, snapshot):
    """Remove new artifacts and restore existing source state after failure."""

    if armature.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="POSE")

    previous_constraints = snapshot["constraints"]
    affected_bone_names = set(snapshot["pose_states"])
    affected_bone_names.update(_component_bone_names(component))
    current_owned_constraint_pairs = {
        (artifact.bone_name, artifact.constraint_name)
        for artifact in component.artifacts
        if artifact.data_type == "CONSTRAINT"
        and artifact.bone_name
        and artifact.constraint_name
        and artifact.owned
    }
    previous_owned_constraint_pairs = {
        (artifact["bone_name"], artifact["constraint_name"])
        for artifact in snapshot["artifacts"]
        if artifact["data_type"] == "CONSTRAINT"
        and artifact["bone_name"]
        and artifact["constraint_name"]
        and artifact["owned"]
    }
    owned_constraint_pairs = (
        current_owned_constraint_pairs | previous_owned_constraint_pairs
    )
    constraint_prefix = f"COA_COMP_{component.component_uuid[:8]}_"
    generated_constraint_names = {
        f"{constraint_prefix}Depth",
        f"{constraint_prefix}IK",
        f"{constraint_prefix}EndRotation",
        f"{constraint_prefix}BendDistance",
    }

    # Detach all component-owned constraints before restoring or recreating
    # their generated target bones. User constraints remain untouched.
    for pose_bone in armature.pose.bones:
        if pose_bone.name not in affected_bone_names:
            continue
        previous_names = {
            item["name"]
            for item in previous_constraints.get(pose_bone.name, ())
        }
        for constraint in tuple(pose_bone.constraints):
            if (
                (pose_bone.name, constraint.name) in owned_constraint_pairs
                or (
                    constraint.name in generated_constraint_names
                    and constraint.name not in previous_names
                )
            ):
                pose_bone.constraints.remove(constraint)

    owned_bone_names = _component_bone_names(component)
    instance_id = ensure_rig_instance_id(armature)
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.mode_set(mode="EDIT")
    for edit_bone in tuple(armature.data.edit_bones):
        if edit_bone.name in snapshot["bone_names"]:
            continue
        if (
            edit_bone.name in owned_bone_names
            or (
                edit_bone.get("coa_rig_instance_id") == instance_id
                and edit_bone.get("coa_rig_component_uuid")
                == component.component_uuid
            )
        ):
            armature.data.edit_bones.remove(edit_bone)

    # Recreate component-owned bones that a failed reconcile deleted, then
    # restore hierarchy and exact rest frames for every pre-existing bone.
    for name in snapshot["bone_states"]:
        if armature.data.edit_bones.get(name) is None:
            armature.data.edit_bones.new(name)
    for name, state in snapshot["bone_states"].items():
        edit_bone = armature.data.edit_bones[name]
        parent_name = state["parent_name"]
        edit_bone.parent = (
            armature.data.edit_bones.get(parent_name)
            if parent_name
            else None
        )
        if hasattr(edit_bone, "use_connect"):
            edit_bone.use_connect = False
        edit_bone.head = state["head"]
        edit_bone.tail = state["tail"]
        if state["roll"] is not None:
            edit_bone.roll = state["roll"]
        else:
            edit_bone.matrix = state["matrix"]
            edit_bone.length = state["length"]
        for attribute, value in state["values"].items():
            if attribute == "use_connect":
                continue
            try:
                setattr(edit_bone, attribute, value)
            except (AttributeError, RuntimeError, TypeError):
                pass
        if "use_connect" in state["values"]:
            edit_bone.use_connect = state["values"]["use_connect"]
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.mode_set(mode="POSE")

    for name, state in snapshot["pose_states"].items():
        _restore_pose_bone(armature, name, state)

    # Constraint targets are now valid again, so restore the prior managed
    # stack and its original ordering.
    for bone_name, constraint_name in previous_owned_constraint_pairs:
        pose_bone = armature.pose.bones.get(bone_name)
        if pose_bone is None:
            continue
        item = next(
            (
                value
                for value in previous_constraints.get(bone_name, ())
                if value["name"] == constraint_name
            ),
            None,
        )
        if item is not None:
            _restore_constraint(pose_bone, item)

    owned_object_names = {
        artifact.object_name
        for artifact in component.artifacts
        if artifact.data_type == "OBJECT"
        and artifact.object_name
        and artifact.owned
    }
    for obj in tuple(bpy.data.objects):
        if obj.name in snapshot["object_names"]:
            continue
        if (
            obj.name in owned_object_names
            or (
                obj.get("coa_rig_instance_id") == instance_id
                and obj.get("coa_rig_component_uuid")
                == component.component_uuid
            )
        ):
            bpy.data.objects.remove(obj, do_unlink=True)
    for object_name, geometry in snapshot["widget_geometry"].items():
        obj = bpy.data.objects.get(object_name)
        if obj is None or obj.type != "MESH":
            continue
        obj.data.clear_geometry()
        obj.data.from_pydata(geometry["vertices"], geometry["edges"], ())
        obj.data.update()

    component.artifacts.clear()
    for values in snapshot["artifacts"]:
        artifact = component.artifacts.add()
        for name, value in values.items():
            setattr(artifact, name, value)
    for name, value in snapshot["component_fields"].items():
        setattr(component, name, value)


@contextmanager
def preserve_component_context(armature):
    active_object = bpy.context.active_object
    selected_objects = tuple(bpy.context.selected_objects)
    original_mode = armature.mode
    try:
        yield
    finally:
        if armature.name not in bpy.data.objects:
            return
        if armature.mode != "OBJECT":
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except RuntimeError:
                pass
        for obj in tuple(bpy.context.selected_objects):
            obj.select_set(False)
        for obj in selected_objects:
            if obj.name in bpy.data.objects:
                obj.select_set(True)
        if active_object is not None and active_object.name in bpy.data.objects:
            bpy.context.view_layer.objects.active = active_object
        else:
            armature.select_set(True)
            bpy.context.view_layer.objects.active = armature
        if active_object == armature and original_mode in {"POSE", "EDIT"}:
            try:
                bpy.ops.object.mode_set(mode=original_mode)
            except RuntimeError:
                pass
