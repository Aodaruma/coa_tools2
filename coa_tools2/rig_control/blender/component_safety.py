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
                if (
                    replacement.data is not None
                    and replacement.data.get("coa_rig_instance_id")
                    == old_instance_id
                    and replacement.data.get("coa_rig_component_uuid")
                    == component.component_uuid
                ):
                    replacement.data["coa_rig_instance_id"] = new_instance_id
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

    # A duplicated Armature shares Action datablocks with its source.  Do not
    # retag or delete those Actions: detach only the duplicate's generated NLA
    # tracks and fall back to the already generated live-follow constraints.
    animation_data = armature.animation_data
    for component in rig_data.rig_components:
        for stage in component.semantic_stages:
            if stage.stage_type != "SECONDARY_MOTION":
                continue
            stage_uuid = stage.stage_uuid
            if animation_data is not None:
                for track in tuple(animation_data.nla_tracks):
                    owned = any(
                        strip.action is not None
                        and strip.action.get("coa_rig_managed")
                        and strip.action.get("coa_rig_instance_id")
                        == old_instance_id
                        and strip.action.get("coa_rig_component_uuid")
                        == component.component_uuid
                        and strip.action.get("coa_semantic_stage_uuid")
                        == stage_uuid
                        for strip in track.strips
                    )
                    if owned:
                        animation_data.nla_tracks.remove(track)
            follow_prefix = f"semantic:{stage_uuid}:secondary_follow:"
            for artifact in component.artifacts:
                if not (
                    artifact.owned
                    and artifact.data_type == "CONSTRAINT"
                    and artifact.role.startswith(follow_prefix)
                ):
                    continue
                pose_bone = armature.pose.bones.get(artifact.bone_name)
                constraint = (
                    pose_bone.constraints.get(artifact.constraint_name)
                    if pose_bone is not None
                    else None
                )
                if constraint is not None:
                    constraint.mute = False
            stage.secondary_baked = False
            if hasattr(stage, "secondary_source_signature"):
                stage.secondary_source_signature = ""
            action_role = f"semantic:{stage_uuid}:secondary_action"
            nla_role = f"semantic:{stage_uuid}:secondary_nla_track"
            for index in range(len(component.artifacts) - 1, -1, -1):
                artifact = component.artifacts[index]
                if artifact.role in {action_role, nla_role} and artifact.data_type in {
                    "ACTION",
                    "NLA_TRACK",
                }:
                    component.artifacts.remove(index)
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
    if component.component_type != "SEMANTIC" and (
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
        "space_object",
        "space_subtarget",
        "head_tail",
        "use_x",
        "use_y",
        "use_z",
        "use_offset",
        "mix_mode",
        "remove_target_shear",
        "keep_axis",
        "volume",
        "rest_length",
        "use_chain_offset",
        "use_even_divisions",
        "use_curve_radius",
        "y_scale_mode",
        "xz_scale_mode",
        "use_original_scale",
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


def _curve_object_snapshot(obj):
    """Capture generated Curve geometry and managed Hook state for rollback."""

    data = obj.data
    splines = []
    for spline in data.splines:
        if spline.type == "BEZIER":
            # Semantic Spline currently emits NURBS, but preserving Bezier data
            # here keeps the transaction helper safe for later curve presets.
            points = tuple(
                {
                    "co": point.co.copy(),
                    "handle_left": point.handle_left.copy(),
                    "handle_right": point.handle_right.copy(),
                    "handle_left_type": point.handle_left_type,
                    "handle_right_type": point.handle_right_type,
                    "radius": point.radius,
                    "tilt": point.tilt,
                }
                for point in spline.bezier_points
            )
        else:
            points = tuple(
                {
                    "co": point.co.copy(),
                    "radius": point.radius,
                    "tilt": point.tilt,
                    "weight": getattr(point, "weight", None),
                    "weight_softbody": getattr(point, "weight_softbody", None),
                }
                for point in spline.points
            )
        splines.append(
            {
                "type": spline.type,
                "points": points,
                "order_u": getattr(spline, "order_u", 2),
                "use_endpoint_u": getattr(spline, "use_endpoint_u", False),
                "use_cyclic_u": getattr(spline, "use_cyclic_u", False),
            }
        )

    hooks = {}
    for modifier_index, modifier in enumerate(obj.modifiers):
        if modifier.type != "HOOK":
            continue
        indices = tuple(getattr(modifier, "vertex_indices", ()) or ())
        hooks[modifier.name] = {
            "index": modifier_index,
            "object": modifier.object,
            "subtarget": modifier.subtarget,
            "strength": modifier.strength,
            "falloff_type": modifier.falloff_type,
            "center": modifier.center.copy(),
            "matrix_inverse": modifier.matrix_inverse.copy(),
            "vertex_indices": indices,
        }
    return {
        "dimensions": data.dimensions,
        "resolution_u": data.resolution_u,
        "render_resolution_u": data.render_resolution_u,
        "twist_mode": data.twist_mode,
        "splines": tuple(splines),
        "hooks": hooks,
    }


def _matches_owned_tags(owner, instance_id, component_uuid, role=None):
    owner_role = str(owner.get("coa_rig_component_role", "") or "")
    return (
        bool(owner.get("coa_rig_managed"))
        and owner.get("coa_rig_instance_id") == instance_id
        and owner.get("coa_rig_component_uuid") == component_uuid
        and bool(owner_role)
        and (role is None or owner_role == role)
    )


def _restore_curve_object(obj, state):
    data = obj.data
    data.dimensions = state["dimensions"]
    data.resolution_u = state["resolution_u"]
    data.render_resolution_u = state["render_resolution_u"]
    data.twist_mode = state["twist_mode"]
    for spline in tuple(data.splines):
        data.splines.remove(spline)
    for saved in state["splines"]:
        spline = data.splines.new(saved["type"])
        points = saved["points"]
        collection = (
            spline.bezier_points if saved["type"] == "BEZIER" else spline.points
        )
        if len(points) > 1:
            collection.add(len(points) - 1)
        for point, values in zip(collection, points):
            point.co = values["co"]
            point.radius = values["radius"]
            point.tilt = values["tilt"]
            if saved["type"] == "BEZIER":
                point.handle_left = values["handle_left"]
                point.handle_right = values["handle_right"]
                point.handle_left_type = values["handle_left_type"]
                point.handle_right_type = values["handle_right_type"]
            else:
                for name in ("weight", "weight_softbody"):
                    saved_value = values[name]
                    # Blender 5.1 clamps an explicit weight_softbody=0 assignment
                    # to 0.01, while a newly created point legitimately keeps
                    # its implicit 0.0 default.  Do not disturb that default.
                    if (
                        saved_value is not None
                        and hasattr(point, name)
                        and not (name == "weight_softbody" and saved_value <= 0.0)
                    ):
                        setattr(point, name, saved_value)
        if hasattr(spline, "order_u"):
            spline.order_u = min(saved["order_u"], max(2, len(points)))
        if hasattr(spline, "use_endpoint_u"):
            spline.use_endpoint_u = saved["use_endpoint_u"]
        if hasattr(spline, "use_cyclic_u"):
            spline.use_cyclic_u = saved["use_cyclic_u"]

    saved_hooks = state["hooks"]
    # The build transaction is synchronous, so the names captured at its start
    # are authoritative within this rollback.  Unlike RNA pointers they cannot
    # be accidentally reused after Blender frees and reallocates a Modifier.
    for modifier in tuple(obj.modifiers):
        if modifier.type == "HOOK" and modifier.name not in saved_hooks:
            obj.modifiers.remove(modifier)
    restored_names = {}
    for name, values in sorted(
        saved_hooks.items(), key=lambda item: item[1]["index"]
    ):
        modifier = obj.modifiers.get(name)
        if modifier is not None and modifier.type != "HOOK":
            modifier = None
        if modifier is None:
            modifier = obj.modifiers.new(name, "HOOK")
        modifier.object = values["object"]
        modifier.subtarget = values["subtarget"]
        modifier.strength = values["strength"]
        modifier.falloff_type = values["falloff_type"]
        modifier.center = values["center"]
        modifier.matrix_inverse = values["matrix_inverse"]
        modifier.vertex_indices_set(values["vertex_indices"])
        current_index = obj.modifiers.find(modifier.name)
        desired_index = min(values["index"], len(obj.modifiers) - 1)
        if current_index != desired_index:
            obj.modifiers.move(current_index, desired_index)
        restored_names[name] = modifier.name
    return restored_names


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
    instance_id = ensure_rig_instance_id(armature)
    widget_geometry = {}
    for obj in bpy.data.objects:
        if (
            obj.type == "MESH"
            and obj.get("coa_rig_component_uuid") == component.component_uuid
            and obj.get("coa_rig_instance_id") == instance_id
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
    object_states = {}
    curve_states = {}
    for obj in bpy.data.objects:
        if (
            obj.get("coa_rig_instance_id") == instance_id
            and obj.get("coa_rig_component_uuid") == component.component_uuid
        ):
            object_states[obj.name] = {
                "matrix_world": obj.matrix_world.copy(),
                "parent": obj.parent,
                "parent_type": obj.parent_type,
                "parent_bone": obj.parent_bone,
                "hide_viewport": obj.hide_viewport,
                "hide_render": obj.hide_render,
                "hide_select": obj.hide_select,
                "display_type": obj.display_type,
                "show_in_front": obj.show_in_front,
            }
            if obj.type == "CURVE":
                curve_states[obj.name] = _curve_object_snapshot(obj)
    return {
        "instance_id": instance_id,
        "object_names": frozenset(obj.name for obj in bpy.data.objects),
        "bone_names": frozenset(bone.name for bone in armature.data.bones),
        "constraints": constraints,
        "pose_states": pose_states,
        "bone_states": bone_states,
        "widget_geometry": widget_geometry,
        "object_states": object_states,
        "curve_states": curve_states,
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
    return constraint


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
    instance_id = snapshot.get("instance_id") or ensure_rig_instance_id(armature)
    component_uuid = component.component_uuid
    previous_constraint_names = {
        bone_name: {item["name"] for item in items}
        for bone_name, items in previous_constraints.items()
    }
    # Snapshot names are authoritative only inside this synchronous
    # transaction.  They avoid RNA pointer reuse while never serving as
    # persistent artifact ownership outside rollback.
    for pose_bone in armature.pose.bones:
        for constraint in tuple(pose_bone.constraints):
            if constraint.name not in previous_constraint_names.get(
                pose_bone.name,
                set(),
            ):
                pose_bone.constraints.remove(constraint)

    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.mode_set(mode="EDIT")
    for edit_bone in tuple(armature.data.edit_bones):
        if edit_bone.name in snapshot["bone_names"]:
            continue
        if _matches_owned_tags(edit_bone, instance_id, component_uuid):
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
    restored_constraints = {}
    for bone_name, items in previous_constraints.items():
        pose_bone = armature.pose.bones.get(bone_name)
        if pose_bone is None:
            continue
        for item in items:
            constraint = _restore_constraint(pose_bone, item)
            restored_constraints[(bone_name, item["name"])] = constraint.name

    for obj in tuple(bpy.data.objects):
        if obj.name in snapshot["object_names"]:
            continue
        if _matches_owned_tags(obj, instance_id, component_uuid):
            bpy.data.objects.remove(obj, do_unlink=True)
    for object_name, geometry in snapshot["widget_geometry"].items():
        obj = bpy.data.objects.get(object_name)
        if obj is None or obj.type != "MESH":
            continue
        obj.data.clear_geometry()
        obj.data.from_pydata(geometry["vertices"], geometry["edges"], ())
        obj.data.update()
    for object_name, state in snapshot.get("object_states", {}).items():
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            continue
        obj.parent = state["parent"]
        obj.parent_type = state["parent_type"]
        obj.parent_bone = state["parent_bone"]
        obj.matrix_world = state["matrix_world"]
        obj.hide_viewport = state["hide_viewport"]
        obj.hide_render = state["hide_render"]
        obj.hide_select = state.get("hide_select", obj.hide_select)
        obj.display_type = state.get("display_type", obj.display_type)
        obj.show_in_front = state.get("show_in_front", obj.show_in_front)
    restored_modifiers = {}
    for object_name, state in snapshot.get("curve_states", {}).items():
        obj = bpy.data.objects.get(object_name)
        if obj is not None and obj.type == "CURVE":
            for saved_name, modifier_name in _restore_curve_object(
                obj,
                state,
            ).items():
                restored_modifiers[(object_name, saved_name)] = modifier_name

    component.artifacts.clear()
    for values in snapshot["artifacts"]:
        artifact = component.artifacts.add()
        for name, value in values.items():
            setattr(artifact, name, value)
        constraint_key = (artifact.bone_name, artifact.constraint_name)
        modifier_key = (artifact.object_name, artifact.constraint_name)
        if artifact.data_type == "CONSTRAINT" and constraint_key in restored_constraints:
            artifact.constraint_name = restored_constraints[constraint_key]
        elif artifact.data_type == "MODIFIER" and modifier_key in restored_modifiers:
            artifact.constraint_name = restored_modifiers[modifier_key]
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
