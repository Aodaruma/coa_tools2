#!/usr/bin/env python3
"""Blender headless integration test for semantic FK/IK and Contact switches."""

from __future__ import annotations

from pathlib import Path
import sys

import bpy
from mathutils import Vector


def _bone(edit_bones, name, head, tail, parent=None):
    bone = edit_bones.new(name)
    bone.head = head
    bone.tail = tail
    bone.parent = parent
    bone.use_connect = parent is not None
    return bone


def _matrices(armature, names):
    bpy.context.view_layer.update()
    return tuple(armature.pose.bones[name].matrix.copy() for name in names)


def _world_head(armature, pose_bone):
    return armature.matrix_world @ pose_bone.head


def _world_tail(armature, pose_bone):
    return armature.matrix_world @ pose_bone.tail


def _matrix_error(before, after):
    return max(
        abs(float(left) - float(right))
        for left_matrix, right_matrix in zip(before, after)
        for left_row, right_row in zip(left_matrix, right_matrix)
        for left, right in zip(left_row, right_row)
    )


def _matrix_errors(before, after):
    return tuple(
        max(
            abs(float(left) - float(right))
            for left_row, right_row in zip(left_matrix, right_matrix)
            for left, right in zip(left_row, right_row)
        )
        for left_matrix, right_matrix in zip(before, after)
    )


def _transform_errors(before, after):
    result = []
    for left, right in zip(before, after):
        location = (left.translation - right.translation).length
        rotation = left.to_quaternion().rotation_difference(
            right.to_quaternion()
        ).angle
        left_scale = left.to_scale()
        right_scale = right.to_scale()
        scale = (left_scale - right_scale).length
        result.append(
            (
                round(float(location), 9),
                round(float(rotation), 9),
                round(float(scale), 9),
            )
        )
    return tuple(result)


def _curve(armature, data_path):
    from coa_tools2 import functions

    action = armature.animation_data.action if armature.animation_data else None
    return next(
        item
        for item in functions.iter_action_fcurves(action)
        if item.data_path == data_path
    )


def _curves(armature, data_path):
    from coa_tools2 import functions

    action = armature.animation_data.action if armature.animation_data else None
    return tuple(
        item
        for item in functions.iter_action_fcurves(action)
        if item.data_path == data_path
    )


def _curve_signature(curve):
    return tuple(
        (
            round(float(point.co.x), 6),
            round(float(point.co.y), 6),
            point.interpolation,
            point.handle_left_type,
            point.handle_right_type,
        )
        for point in curve.keyframe_points
    )


def _driver_signature(armature, data_paths):
    paths = set(data_paths)
    drivers = armature.animation_data.drivers if armature.animation_data else ()
    return tuple(
        sorted(
            (
                curve.data_path,
                int(curve.array_index),
                curve.driver.type,
                curve.driver.expression,
                tuple(
                    (
                        variable.name,
                        variable.type,
                        tuple(
                            (
                                getattr(target.id, "name_full", "")
                                if target.id is not None
                                else "",
                                target.data_path,
                            )
                            for target in variable.targets
                        ),
                    )
                    for variable in curve.driver.variables
                ),
            )
            for curve in drivers
            if curve.data_path in paths
        )
    )


def _structure_signature(armature, component):
    return (
        len(armature.data.bones),
        sum(len(pose_bone.constraints) for pose_bone in armature.pose.bones),
        len(armature.animation_data.drivers) if armature.animation_data else 0,
        len(component.artifacts),
    )


def _object_bounds(obj):
    coordinates = tuple(tuple(vertex.co) for vertex in obj.data.vertices)
    return tuple(
        max(vertex[axis] for vertex in coordinates)
        - min(vertex[axis] for vertex in coordinates)
        for axis in range(3)
    )


def _owned_widget_pair(armature, component, stage, target_role):
    from coa_tools2.rig_control.blender.semantic_presentations import (
        semantic_widget_object_role,
    )
    from coa_tools2.rig_control.blender.semantic_widgets import (
        find_semantic_widget_modifier,
    )

    objects = []
    for artifact_role in ("source", "cache"):
        role = semantic_widget_object_role(
            stage.stage_uuid,
            target_role,
            artifact_role,
        )
        records = tuple(
            artifact
            for artifact in component.artifacts
            if artifact.role == role and artifact.data_type == "OBJECT"
        )
        assert len(records) == 1 and records[0].owned, role
        obj = bpy.data.objects[records[0].object_name]
        assert obj.get("coa_semantic_widget_target_role") == target_role
        assert obj.get("coa_semantic_widget_shape") == "ELLIPSE"
        objects.append(obj)
    source, cache = objects
    modifier = find_semantic_widget_modifier(source)
    assert modifier is not None and modifier.type == "NODES"
    assert modifier.node_group.get("coa_semantic_widget_managed")
    assert cache.data.vertices and cache.data.edges and not cache.data.polygons
    return source, cache, modifier


def main():
    import coa_tools2
    from coa_tools2.rig_control.blender import (
        semantic_compiler,
        semantic_contact,
        semantic_fk,
    )
    from coa_tools2.rig_control.blender.selection import select_pose_bones
    from coa_tools2.rig_control.blender.semantic_artifacts import semantic_stage_role
    from coa_tools2.rig_control.blender.semantic_fk import resolve_fk_solver_layer
    from coa_tools2.rig_control.blender.semantic_presentations import (
        compile_component_presentations,
    )

    coa_tools2.register()
    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object
    armature.name = "SemanticSwitchValidation"
    bpy.ops.object.mode_set(mode="EDIT")
    bones = armature.data.edit_bones
    upper = _bone(bones, "upper", (0, 0, 0), (1, 0.15, 0))
    lower = _bone(bones, "lower", upper.tail, (2, -0.10, 0), upper)
    hand = _bone(bones, "hand", lower.tail, (2.65, -0.10, 0), lower)
    bpy.ops.object.mode_set(mode="POSE")
    select_pose_bones(armature, {"upper", "lower", "hand"}, "hand")
    assert bpy.ops.coa_tools2.add_semantic_rig(
        "EXEC_DEFAULT",
        label="FK IK Contact",
        initial_dimensions=3,
    ) == {"FINISHED"}
    component = armature.coa_tools2_rig.rig_components[0]
    assert bpy.ops.coa_tools2.add_semantic_stage(
        "EXEC_DEFAULT",
        stage_type="CHAIN_IK",
        label="Arm FK IK",
    ) == {"FINISHED"}
    ik_stage = component.semantic_stages[-1]
    ik_stage.use_pole = True
    ik_stage.chain_length = 2
    ik_stage.allow_stretch = False
    component.semantic_stages_index = len(component.semantic_stages) - 1
    select_pose_bones(armature, {"upper", "lower", "hand"}, "hand")
    assert bpy.ops.coa_tools2.assign_semantic_stage_chain("EXEC_DEFAULT") == {
        "FINISHED"
    }
    assert bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT") == {"FINISHED"}

    layer = resolve_fk_solver_layer(armature, component, ik_stage)
    assert len(layer.fk_control_bones) == len(layer.mechanism_bones) == 3
    stage_prefix = f"semantic:{ik_stage.stage_uuid}:"
    roles = {artifact.role for artifact in component.artifacts}
    assert stage_prefix + "ik_orientation" in roles
    assert stage_prefix + "ik_end_rotation" in roles
    for index in range(3):
        assert stage_prefix + f"fk_control:{index}" in roles
        assert stage_prefix + f"fk_follow:{index}" in roles

    # Embedded FK controls receive one production GN edge-only presentation.
    fk_source, fk_cache, _fk_modifier = _owned_widget_pair(
        armature, component, ik_stage, "FK_CONTROL"
    )
    assert all(
        armature.pose.bones[name].custom_shape == fk_cache
        for name in layer.fk_control_bones
    )
    fk_structure = _structure_signature(armature, component)
    fk_bounds = _object_bounds(fk_cache)
    fk_objects = (fk_source.as_pointer(), fk_cache.as_pointer())
    ik_stage.fk_presentation.width *= 1.5
    compile_component_presentations(
        armature,
        component,
        only_target=(ik_stage.stage_uuid, "FK_CONTROL"),
    )
    fk_source, fk_cache, _fk_modifier = _owned_widget_pair(
        armature, component, ik_stage, "FK_CONTROL"
    )
    assert _object_bounds(fk_cache)[0] > fk_bounds[0] + 0.1
    assert fk_structure == _structure_signature(armature, component)
    assert fk_objects == (fk_source.as_pointer(), fk_cache.as_pointer())

    ik_control = armature.pose.bones[layer.ik_control_bone]
    display = armature.pose.bones[ik_stage.display_frame_bone]
    assert ik_control.custom_shape_transform == display
    follows, ik_constraint, end_rotation, contact_end_rotation = semantic_fk._layer_constraints(
        armature,
        layer,
    )
    assert ik_stage.rig_mode == "IK"
    assert all(abs(item.influence) < 1.0e-6 for item in follows)
    assert abs(ik_constraint.influence - 1.0) < 1.0e-6
    assert abs(end_rotation.influence - 1.0) < 1.0e-6
    assert abs(contact_end_rotation.influence) < 1.0e-6
    solver_constraints = follows + (
        ik_constraint,
        end_rotation,
        contact_end_rotation,
    )
    solver_driver_paths = {
        item.path_from_id("influence") for item in solver_constraints
    }
    assert solver_driver_paths.issubset(
        {item.data_path for item in armature.animation_data.drivers}
    )

    # Establish FK, author a pose, then verify FK -> IK Pose Match.
    bpy.context.scene.frame_set(1)
    component.semantic_stages_index = list(component.semantic_stages).index(ik_stage)
    operator = bpy.ops.coa_tools2.switch_semantic_ik_fk
    assert operator("EXEC_DEFAULT", mode="FK") == {"FINISHED"}
    assert all(abs(item.influence - 1.0) < 1.0e-6 for item in follows)
    assert abs(ik_constraint.influence) < 1.0e-6
    assert abs(end_rotation.influence) < 1.0e-6
    fk_controls = tuple(
        armature.pose.bones[name] for name in layer.fk_control_bones
    )
    bpy.context.scene.frame_set(10)
    fk_controls[0].rotation_euler.z = 0.28
    fk_controls[1].rotation_euler.z = -0.42
    fk_controls[2].rotation_euler.z = 0.18
    bpy.context.view_layer.update()
    before = _matrices(armature, layer.mechanism_bones)

    assert operator("EXEC_DEFAULT", mode="IK") == {"FINISHED"}
    after = _matrices(armature, layer.mechanism_bones)
    fk_to_ik_error = _matrix_error(before, after)
    assert fk_to_ik_error < 5.0e-3, (
        fk_to_ik_error,
        _matrix_errors(before, after),
        {
            "public_mode": ik_stage.rig_mode,
            "constraint_influences": tuple(
                (round(float(item.influence), 6), bool(item.mute))
                for item in follows + (ik_constraint, end_rotation)
            ),
            "final(location,rotation,scale)": _transform_errors(before, after),
        },
    )

    # Author an IK pose, then verify IK -> FK Pose Match.
    bpy.context.scene.frame_set(20)
    ik_control.location += Vector((0.08, -0.12, 0.18))
    pole = armature.pose.bones[layer.pole_bone]
    pole.location += Vector((0.10, 0.05, 0.12))
    bpy.context.view_layer.update()
    before = _matrices(armature, layer.mechanism_bones)
    assert operator("EXEC_DEFAULT", mode="FK") == {"FINISHED"}
    after = _matrices(armature, layer.mechanism_bones)
    ik_to_fk_error = _matrix_error(before, after)
    assert ik_to_fk_error < 5.0e-3, (
        ik_to_fk_error,
        _matrix_errors(before, after),
    )

    mode_curve = _curve(armature, ik_stage.path_from_id("rig_mode"))
    assert all(point.interpolation == "CONSTANT" for point in mode_curve.keyframe_points)
    action = armature.animation_data.action
    from coa_tools2 import functions

    assert not any(
        curve.data_path in solver_driver_paths
        for curve in functions.iter_action_fcurves(action)
    )

    # Contact is a hidden IK override even while the public Mode remains FK.
    bpy.context.scene.frame_set(30)
    assert operator("EXEC_DEFAULT", mode="FK") == {"FINISHED"}
    assert bpy.ops.coa_tools2.add_semantic_stage(
        "EXEC_DEFAULT",
        stage_type="CONTACT_PIN",
        label="Hand Contact",
    ) == {"FINISHED"}
    contact = component.semantic_stages[-1]
    contact.pin_space = "WORLD"
    contact.pin_position = True
    contact.pin_orientation = False
    contact.contact_transition_frames = 3
    component.semantic_stages_index = len(component.semantic_stages) - 1
    assert bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT") == {"FINISHED"}
    assert contact.pin_driven_stage_uuid == ik_stage.stage_uuid
    assert contact.pin_driven_bone == layer.ik_control_bone
    ik_stage_uuid = ik_stage.stage_uuid
    contact_stage_uuid = contact.stage_uuid

    # Add Stage may retain a CHAIN_IK dependency when the author then chooses
    # an explicit generic Driven Bone.  Durable provider identity—not the stale
    # dependency alone—keeps this legacy range Pin out of IK solver drivers and
    # the discrete Contact switch.
    automatic_solver_signature = _driver_signature(
        armature,
        solver_driver_paths,
    )
    assert bpy.ops.coa_tools2.add_semantic_stage(
        "EXEC_DEFAULT",
        stage_type="CONTACT_PIN",
        label="Generic Range Pin",
    ) == {"FINISHED"}
    generic_contact = component.semantic_stages[-1]
    generic_contact.depends_on = ik_stage.stage_uuid
    generic_contact.pin_driven_bone = layer.fk_control_bones[0]
    assert not generic_contact.pin_driven_stage_uuid
    assert not semantic_contact.contact_uses_ik_override(generic_contact)
    assert bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT") == {"FINISHED"}
    assert _driver_signature(
        armature,
        solver_driver_paths,
    ) == automatic_solver_signature
    # CollectionProperty.add/remove may invalidate a previously retained Python
    # PropertyGroup wrapper even though the durable stage item is unchanged.
    # Resolve both stages by UUID before checking compiler identity.
    ik_stage = next(
        stage
        for stage in component.semantic_stages
        if stage.stage_uuid == ik_stage_uuid
    )
    contact = next(
        stage
        for stage in component.semantic_stages
        if stage.stage_uuid == contact_stage_uuid
    )
    selected_contact = semantic_fk._solver_contact_stage(component, ik_stage)
    contact_identity_diagnostics = {
        "automatic": (
            contact.pin_driven_bone,
            contact.pin_driven_stage_uuid,
            contact.depends_on,
            semantic_contact.contact_uses_ik_override(contact),
        ),
        "generic": (
            generic_contact.pin_driven_bone,
            generic_contact.pin_driven_stage_uuid,
            generic_contact.depends_on,
            semantic_contact.contact_uses_ik_override(generic_contact),
        ),
        "selected_uuid": (
            selected_contact.stage_uuid if selected_contact is not None else ""
        ),
    }
    assert contact.pin_driven_stage_uuid == ik_stage_uuid, contact_identity_diagnostics
    assert semantic_contact.contact_uses_ik_override(contact), contact_identity_diagnostics
    assert selected_contact is not None, contact_identity_diagnostics
    assert selected_contact.stage_uuid == contact_stage_uuid, contact_identity_diagnostics
    generic_role_prefix = f"semantic:{generic_contact.stage_uuid}:"
    generic_constraint = next(
        artifact
        for artifact in component.artifacts
        if artifact.role == generic_role_prefix + "pin_constraint"
    )
    assert generic_constraint.bone_name == layer.fk_control_bones[0]
    generic_stage_uuid = generic_contact.stage_uuid
    component.semantic_stages.remove(len(component.semantic_stages) - 1)
    contact = next(
        stage
        for stage in component.semantic_stages
        if stage.stage_uuid == contact_stage_uuid
    )
    component.semantic_stages_index = next(
        index
        for index, stage in enumerate(component.semantic_stages)
        if stage.stage_uuid == contact_stage_uuid
    )
    assert bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT") == {"FINISHED"}
    assert not any(
        artifact.role.startswith(f"semantic:{generic_stage_uuid}:")
        for artifact in component.artifacts
    )
    assert _driver_signature(
        armature,
        solver_driver_paths,
    ) == automatic_solver_signature
    driven = armature.pose.bones[contact.pin_driven_bone]
    visible_endpoint = armature.pose.bones["hand"]
    source_output_record = next(
        artifact
        for artifact in component.artifacts
        if artifact.role == stage_prefix + "source_presentation:2"
    )
    source_output_constraint = visible_endpoint.constraints[
        source_output_record.constraint_name
    ]
    presentation_output_record = next(
        artifact
        for artifact in component.artifacts
        if artifact.role == stage_prefix + "presentation_bone:2"
    )
    projected_endpoint_record = next(
        artifact
        for artifact in component.artifacts
        if artifact.role == stage_prefix + "projected_joint:2"
    )
    ik_owner = armature.pose.bones[layer.ik_constraint_owner]
    mechanism_endpoint = armature.pose.bones[layer.mechanism_bones[-1]]
    projected_endpoint = armature.pose.bones[projected_endpoint_record.bone_name]
    presentation_endpoint = armature.pose.bones[
        presentation_output_record.bone_name
    ]
    assert layer.contact_end_rotation_owner == presentation_endpoint.name
    assert contact_end_rotation in tuple(presentation_endpoint.constraints)
    assert contact_end_rotation.owner_space == "CUSTOM"
    assert contact_end_rotation.target_space == "CUSTOM"
    assert contact_end_rotation.space_object == armature
    assert contact_end_rotation.space_subtarget == ik_stage.art_frame_bone
    assert not contact_end_rotation.use_x
    assert not contact_end_rotation.use_y
    assert contact_end_rotation.use_z
    assert layer.ik_constraint_owner == layer.mechanism_bones[-2]
    assert armature.data.bones[layer.mechanism_bones[-1]].use_connect
    assert source_output_constraint.target == armature
    assert source_output_constraint.subtarget == presentation_output_record.bone_name
    pin_constraint_record = next(
        artifact
        for artifact in component.artifacts
        if artifact.role == f"semantic:{contact.stage_uuid}:pin_constraint"
    )
    pin_anchor_record = next(
        artifact
        for artifact in component.artifacts
        if artifact.role == f"semantic:{contact.stage_uuid}:pin_anchor"
    )
    pin_anchor = bpy.data.objects[pin_anchor_record.object_name]
    assert pin_constraint_record.bone_name == driven.name
    assert driven.constraints[-1].name == pin_constraint_record.constraint_name
    property_path = driven.path_from_id(f'["{contact.pin_property}"]')
    prior_ik_controls = (
        armature.pose.bones[layer.ik_control_bone],
        armature.pose.bones[layer.orientation_bone],
        armature.pose.bones[layer.pole_bone],
    )
    prior_ik_paths = tuple(
        pose_bone.path_from_id(path)
        for pose_bone in prior_ik_controls
        for path in (
            "location",
            semantic_fk._rotation_path(pose_bone),
            "scale",
        )
    )
    assert all(_curves(armature, path) for path in prior_ik_paths)

    bpy.context.scene.frame_set(40)
    captured = (
        armature.matrix_world @ visible_endpoint.matrix
    ).translation.copy()
    captured_points = {
        "ik_owner_tail": _world_tail(armature, ik_owner).copy(),
        "mechanism_final_head": _world_head(armature, mechanism_endpoint).copy(),
        "projected_head": _world_head(armature, projected_endpoint).copy(),
        "presentation_head": _world_head(armature, presentation_endpoint).copy(),
        "source_head": _world_head(armature, visible_endpoint).copy(),
        "source_tail": _world_tail(armature, visible_endpoint).copy(),
    }
    assert bpy.ops.coa_tools2.switch_semantic_contact(
        "EXEC_DEFAULT",
        mode="ON",
    ) == {"FINISHED"}
    assert contact.contact_mode == "ON"
    contact_mode_curve = _curve(armature, contact.path_from_id("contact_mode"))
    assert all(
        point.interpolation == "CONSTANT"
        for point in contact_mode_curve.keyframe_points
    )
    pin_curve = _curve(armature, property_path)
    on_keys = {
        round(float(point.co.x)): point
        for point in pin_curve.keyframe_points
        if round(float(point.co.x)) in {40, 43}
    }
    assert set(on_keys) == {40, 43}
    assert all(point.interpolation == "BEZIER" for point in on_keys.values())
    assert all(
        point.handle_left_type == point.handle_right_type == "AUTO_CLAMPED"
        for point in on_keys.values()
    )
    bpy.context.scene.frame_set(43)
    component.semantic_stages_index = list(component.semantic_stages).index(ik_stage)
    ramp_points = {
        "ik_owner_tail": _world_tail(armature, ik_owner).copy(),
        "mechanism_final_head": _world_head(armature, mechanism_endpoint).copy(),
        "projected_head": _world_head(armature, projected_endpoint).copy(),
        "presentation_head": _world_head(armature, presentation_endpoint).copy(),
        "source_head": _world_head(armature, visible_endpoint).copy(),
        "source_tail": _world_tail(armature, visible_endpoint).copy(),
    }
    ramp_diagnostics = {
        "captured": tuple(round(float(value), 6) for value in captured),
        "points": {
            name: tuple(round(float(value), 6) for value in point)
            for name, point in ramp_points.items()
        },
        "deltas_from_frame40": {
            name: round((point - captured_points[name]).length, 9)
            for name, point in ramp_points.items()
        },
        "source_head_to_captured": round(
            (ramp_points["source_head"] - captured).length,
            9,
        ),
        "solver_influences": tuple(
            round(float(item.influence), 6)
            for item in follows
            + (ik_constraint, end_rotation, contact_end_rotation)
        ),
        "public_mode": ik_stage.rig_mode,
        "contact_mode": contact.contact_mode,
        "contact_weight": round(float(driven[contact.pin_property]), 6),
        "ik_control": tuple(
            round(float(value), 6)
            for value in (armature.matrix_world @ ik_control.matrix).translation
        ),
        "anchor": tuple(
            round(float(value), 6) for value in pin_anchor.matrix_world.translation
        ),
    }
    # Separate Contact acquisition/ramp evaluation from the redundant public
    # FK switch below.  The first failing payload identifies whether the shift
    # precedes Pose Match.
    assert (ramp_points["source_head"] - captured).length < 1.0e-4, (
        "after_contact_ramp",
        ramp_diagnostics,
    )
    assert operator("EXEC_DEFAULT", mode="FK") == {"FINISHED"}
    # Author the animator's wrist change on a new frame.  These controls
    # already have Pose Match curves, so an unkeyed RNA edit would correctly
    # be replaced by Action evaluation and would not exercise the rig.
    bpy.context.scene.frame_set(44)
    before_mode_switch = (
        armature.matrix_world @ visible_endpoint.matrix
    ).translation.copy()
    before_points = {
        "ik_owner_tail": _world_tail(armature, ik_owner).copy(),
        "mechanism_final_head": _world_head(armature, mechanism_endpoint).copy(),
        "projected_head": _world_head(armature, projected_endpoint).copy(),
        "presentation_head": _world_head(armature, presentation_endpoint).copy(),
        "source_head": _world_head(armature, visible_endpoint).copy(),
        "source_tail": _world_tail(armature, visible_endpoint).copy(),
    }
    mode_diagnostics = {
        "captured": tuple(round(float(value), 6) for value in captured),
        "points": {
            name: tuple(round(float(value), 6) for value in point)
            for name, point in before_points.items()
        },
        "deltas_from_after_ramp": {
            name: round((point - ramp_points[name]).length, 9)
            for name, point in before_points.items()
        },
        "source_head_to_captured": round(
            (before_points["source_head"] - captured).length,
            9,
        ),
        "solver_influences": tuple(
            round(float(item.influence), 6)
            for item in follows
            + (ik_constraint, end_rotation, contact_end_rotation)
        ),
        "public_mode": ik_stage.rig_mode,
        "contact_mode": contact.contact_mode,
        "contact_weight": round(float(driven[contact.pin_property]), 6),
        "ik_control": tuple(
            round(float(value), 6)
            for value in (armature.matrix_world @ ik_control.matrix).translation
        ),
        "anchor": tuple(
            round(float(value), 6) for value in pin_anchor.matrix_world.translation
        ),
    }
    assert (before_points["source_head"] - captured).length < 1.0e-4, (
        "after_same_mode_fk_pose_match",
        mode_diagnostics,
    )
    before_free_rotation = visible_endpoint.matrix.to_quaternion()
    before_fk_rotations = tuple(
        pose_bone.matrix.to_quaternion().copy() for pose_bone in fk_controls
    )
    before_layer_rotations = {
        "mechanism": mechanism_endpoint.matrix.to_quaternion().copy(),
        "presentation": presentation_endpoint.matrix.to_quaternion().copy(),
        "source": visible_endpoint.matrix.to_quaternion().copy(),
    }
    fk_controls[0].rotation_euler.z += 0.31
    fk_controls[1].rotation_euler.z -= 0.19
    fk_controls[2].rotation_euler.z += 0.27
    for fk_control in fk_controls:
        assert fk_control.keyframe_insert(
            data_path="rotation_euler",
            frame=44,
            group=fk_control.name,
        )
    bpy.context.view_layer.update()
    pinned = (armature.matrix_world @ visible_endpoint.matrix).translation
    pin_error = (pinned - captured).length
    after_points = {
        "ik_owner_tail": _world_tail(armature, ik_owner).copy(),
        "mechanism_final_head": _world_head(armature, mechanism_endpoint).copy(),
        "projected_head": _world_head(armature, projected_endpoint).copy(),
        "presentation_head": _world_head(armature, presentation_endpoint).copy(),
        "source_head": _world_head(armature, visible_endpoint).copy(),
        "source_tail": _world_tail(armature, visible_endpoint).copy(),
    }
    point_deltas = {
        name: round((after_points[name] - before_points[name]).length, 9)
        for name in before_points
    }
    after_fk_rotations = tuple(
        pose_bone.matrix.to_quaternion().copy() for pose_bone in fk_controls
    )
    fk_rotation_deltas = tuple(
        round(before.rotation_difference(after).angle, 9)
        for before, after in zip(before_fk_rotations, after_fk_rotations)
    )
    after_layer_rotations = {
        "mechanism": mechanism_endpoint.matrix.to_quaternion().copy(),
        "presentation": presentation_endpoint.matrix.to_quaternion().copy(),
        "source": visible_endpoint.matrix.to_quaternion().copy(),
    }
    layer_rotation_deltas = {
        name: round(before_layer_rotations[name].rotation_difference(after).angle, 9)
        for name, after in after_layer_rotations.items()
    }
    final_rotation_path = fk_controls[-1].path_from_id("rotation_euler")
    final_z_curve = next(
        curve
        for curve in _curves(armature, final_rotation_path)
        if curve.array_index == 2
    )
    final_z_keys = tuple(
        (round(float(point.co.x), 6), round(float(point.co.y), 6))
        for point in final_z_curve.keyframe_points
        if abs(float(point.co.x) - 44.0) < 1.0e-5
    )
    contact_end_driver = next(
        curve
        for curve in armature.animation_data.drivers
        if curve.data_path == contact_end_rotation.path_from_id("influence")
    )
    rotation_diagnostics = {
        "fk_world_deltas": fk_rotation_deltas,
        "layer_world_deltas": layer_rotation_deltas,
        "final_fk_euler": tuple(
            round(float(value), 6) for value in fk_controls[-1].rotation_euler
        ),
        "final_fk_z_key": final_z_keys,
        "final_fk_parent": (
            fk_controls[-1].parent.name if fk_controls[-1].parent else ""
        ),
        "contact_end": {
            "name": contact_end_rotation.name,
            "target": (
                contact_end_rotation.target.name
                if contact_end_rotation.target is not None
                else ""
            ),
            "subtarget": contact_end_rotation.subtarget,
            "influence": round(float(contact_end_rotation.influence), 6),
            "owner_space": contact_end_rotation.owner_space,
            "target_space": contact_end_rotation.target_space,
            "mix_mode": contact_end_rotation.mix_mode,
            "driver_expression": contact_end_driver.driver.expression,
            "driver_variables": tuple(
                (
                    variable.name,
                    tuple(target.data_path for target in variable.targets),
                )
                for variable in contact_end_driver.driver.variables
            ),
        },
        "presentation_constraint_stack": tuple(
            (
                constraint.name,
                constraint.type,
                round(float(constraint.influence), 6),
                getattr(constraint, "subtarget", ""),
            )
            for constraint in presentation_endpoint.constraints
        ),
    }
    # The existing CHAIN_IK targets the preceding segment's tail, which is the
    # connected final hand/foot bone's head and the point beneath the IK
    # widget.  Position-only Contact must keep that wrist/ankle point fixed;
    # the final bone tail is intentionally free to arc as its rotation changes.
    assert point_deltas["ik_owner_tail"] < 1.0e-4, point_deltas
    assert point_deltas["mechanism_final_head"] < 1.0e-4, point_deltas
    assert fk_rotation_deltas[-1] > 0.05, rotation_diagnostics
    art_frame = armature.pose.bones[ik_stage.art_frame_bone]
    world_basis = armature.matrix_world.to_3x3()
    art_normal = (
        world_basis @ art_frame.matrix.to_3x3() @ Vector((0.0, 0.0, 1.0))
    ).normalized()
    presentation_normal = (
        world_basis
        @ presentation_endpoint.matrix.to_3x3()
        @ Vector((0.0, 0.0, 1.0))
    ).normalized()
    source_normal = (
        world_basis
        @ visible_endpoint.matrix.to_3x3()
        @ Vector((0.0, 0.0, 1.0))
    ).normalized()
    assert abs(art_normal.dot(presentation_normal)) > 1.0 - 1.0e-4
    assert abs(art_normal.dot(source_normal)) > 1.0 - 1.0e-4
    assert point_deltas["source_tail"] > 0.05, (
        point_deltas,
        rotation_diagnostics,
    )
    assert pin_error < 1.0e-4, (pin_error, point_deltas)
    assert (pinned - before_mode_switch).length < 1.0e-4
    free_rotation_delta = before_free_rotation.rotation_difference(
        visible_endpoint.matrix.to_quaternion()
    ).angle
    assert free_rotation_delta > 0.05, (free_rotation_delta, rotation_diagnostics)
    assert all(abs(item.influence) < 1.0e-5 for item in follows)
    assert abs(ik_constraint.influence - 1.0) < 1.0e-5
    assert abs(end_rotation.influence) < 1.0e-5
    assert abs(contact_end_rotation.influence - 1.0) < 1.0e-5

    # Mode switching while contact is ON pose-matches the mechanism but never
    # releases the source endpoint from the captured world contact.
    assert operator("EXEC_DEFAULT", mode="IK") == {"FINISHED"}
    after_mode_switch = (
        armature.matrix_world @ visible_endpoint.matrix
    ).translation
    assert (after_mode_switch - captured).length < 1.0e-4
    bpy.context.scene.frame_set(45)
    ik_control.location += Vector((0.7, -0.2, 0.1))
    assert ik_control.keyframe_insert(
        data_path="location",
        frame=45,
        group=ik_control.name,
    )
    bpy.context.view_layer.update()
    assert (
        (armature.matrix_world @ visible_endpoint.matrix).translation - captured
    ).length < 1.0e-4
    assert operator("EXEC_DEFAULT", mode="FK") == {"FINISHED"}
    assert (
        (armature.matrix_world @ visible_endpoint.matrix).translation - captured
    ).length < 1.0e-4

    bpy.context.scene.frame_set(50)
    component.semantic_stages_index = list(component.semantic_stages).index(contact)
    before_release = (
        armature.matrix_world @ visible_endpoint.matrix
    ).translation.copy()

    def fk_animation_signature():
        return tuple(
            (path, curve.array_index, _curve_signature(curve))
            for path in semantic_fk._pose_transform_paths(fk_controls)
            for curve in _curves(armature, path)
        )

    before_release_fk_matrices = _matrices(
        armature,
        layer.fk_control_bones,
    )
    before_release_fk_animation = fk_animation_signature()
    assert bpy.ops.coa_tools2.switch_semantic_contact(
        "EXEC_DEFAULT",
        mode="OFF",
    ) == {"FINISHED"}
    after_release = (
        armature.matrix_world @ visible_endpoint.matrix
    ).translation.copy()
    assert (after_release - before_release).length < 1.0e-4
    assert _matrix_error(
        before_release_fk_matrices,
        _matrices(armature, layer.fk_control_bones),
    ) < 1.0e-6
    assert fk_animation_signature() == before_release_fk_animation
    pin_curve = _curve(armature, property_path)
    off_keys = {
        round(float(point.co.x)): point
        for point in pin_curve.keyframe_points
        if round(float(point.co.x)) in {50, 53}
    }
    assert set(off_keys) == {50, 53}
    assert all(point.interpolation == "BEZIER" for point in off_keys.values())
    assert all(
        point.interpolation == "CONSTANT"
        for point in contact_mode_curve.keyframe_points
    )
    bpy.context.scene.frame_set(53)
    assert abs(float(driven[contact.pin_property])) < 1.0e-5
    assert all(abs(item.influence - 1.0) < 1.0e-5 for item in follows)
    assert abs(ik_constraint.influence) < 1.0e-5
    assert abs(end_rotation.influence) < 1.0e-5
    assert abs(contact_end_rotation.influence) < 1.0e-5

    # Enabling orientation adds an independent carrier/anchor.  The same
    # public Contact weight now fixes both endpoint position and wrist
    # rotation without conflating the IK handle's rest axes.
    contact.pin_orientation = True
    assert bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT") == {"FINISHED"}
    orientation_anchor_record = next(
        artifact
        for artifact in component.artifacts
        if artifact.role
        == f"semantic:{contact.stage_uuid}:pin_orientation_anchor"
    )
    orientation_constraint_record = next(
        artifact
        for artifact in component.artifacts
        if artifact.role
        == f"semantic:{contact.stage_uuid}:pin_orientation_constraint"
    )
    assert orientation_anchor_record.object_name in bpy.data.objects
    assert orientation_constraint_record.bone_name == layer.orientation_bone
    bpy.context.scene.frame_set(56)
    orientation_position = (
        armature.matrix_world @ visible_endpoint.matrix
    ).translation.copy()
    orientation_rotation = visible_endpoint.matrix.to_quaternion().copy()
    assert bpy.ops.coa_tools2.switch_semantic_contact(
        "EXEC_DEFAULT", mode="ON"
    ) == {"FINISHED"}
    bpy.context.scene.frame_set(59)
    fk_controls[2].rotation_euler.z += 0.41
    bpy.context.view_layer.update()
    assert (
        (armature.matrix_world @ visible_endpoint.matrix).translation
        - orientation_position
    ).length < 1.0e-4
    assert orientation_rotation.rotation_difference(
        visible_endpoint.matrix.to_quaternion()
    ).angle < 1.0e-4
    assert abs(end_rotation.influence - 1.0) < 1.0e-5
    assert abs(contact_end_rotation.influence) < 1.0e-5
    bpy.context.scene.frame_set(62)
    assert bpy.ops.coa_tools2.switch_semantic_contact(
        "EXEC_DEFAULT", mode="OFF"
    ) == {"FINISHED"}
    bpy.context.scene.frame_set(65)
    assert abs(float(driven[contact.pin_property])) < 1.0e-5

    # Reversing acquisition starts at the evaluated mid-ramp influence and
    # removes the superseded future ON endpoint even when the new release uses
    # a shorter duration.
    contact.contact_transition_frames = 10
    bpy.context.scene.frame_set(70)
    assert bpy.ops.coa_tools2.switch_semantic_contact(
        "EXEC_DEFAULT", mode="ON"
    ) == {"FINISHED"}
    bpy.context.scene.frame_set(72)
    mid_value = float(driven[contact.pin_property])
    assert 0.0 < mid_value < 1.0, mid_value
    before_reversal = (
        armature.matrix_world @ visible_endpoint.matrix
    ).translation.copy()
    before_reversal_fk_matrices = _matrices(
        armature,
        layer.fk_control_bones,
    )
    before_reversal_fk_animation = fk_animation_signature()
    reversal_position_anchor = semantic_contact.find_component_object(
        armature,
        component.component_uuid,
        semantic_stage_role(contact.stage_uuid, "pin_anchor"),
    )
    reversal_orientation_anchor = semantic_contact.find_component_object(
        armature,
        component.component_uuid,
        semantic_stage_role(contact.stage_uuid, "pin_orientation_anchor"),
    )
    assert reversal_position_anchor is not None
    assert reversal_orientation_anchor is not None
    reversal_control_names = tuple(
        layer.fk_control_bones
        + (layer.ik_control_bone, layer.orientation_bone)
        + ((layer.pole_bone,) if layer.pole_bone else ())
    )

    def reversal_snapshot():
        def matrix_payload(matrix):
            translation, rotation, scale = matrix.decompose()
            return {
                "translation": tuple(round(float(value), 9) for value in translation),
                "rotation": tuple(round(float(value), 9) for value in rotation),
                "scale": tuple(round(float(value), 9) for value in scale),
            }

        return {
            "source": matrix_payload(armature.matrix_world @ visible_endpoint.matrix),
            "mechanism": tuple(
                (name, matrix_payload(armature.matrix_world @ armature.pose.bones[name].matrix))
                for name in layer.mechanism_bones
            ),
            "controls": tuple(
                (name, matrix_payload(armature.matrix_world @ armature.pose.bones[name].matrix))
                for name in reversal_control_names
            ),
            "pin_weight": round(float(driven[contact.pin_property]), 9),
            "public_contact": contact.contact_mode,
            "public_mode": ik_stage.rig_mode,
            "position_anchor": matrix_payload(reversal_position_anchor.matrix_world),
            "orientation_anchor": matrix_payload(
                reversal_orientation_anchor.matrix_world
            ),
            "influences": {
                "follows": tuple(round(float(item.influence), 9) for item in follows),
                "ik": round(float(ik_constraint.influence), 9),
                "ik_end_rotation": round(float(end_rotation.influence), 9),
                "contact_end_rotation": round(
                    float(contact_end_rotation.influence), 9
                ),
            },
        }

    before_reversal_state = reversal_snapshot()
    contact.contact_transition_frames = 2
    assert bpy.ops.coa_tools2.switch_semantic_contact(
        "EXEC_DEFAULT", mode="OFF"
    ) == {"FINISHED"}
    after_reversal = (
        armature.matrix_world @ visible_endpoint.matrix
    ).translation.copy()
    after_reversal_state = reversal_snapshot()
    reversal_delta = (after_reversal - before_reversal).length
    assert reversal_delta < 1.0e-4, {
        "delta": round(float(reversal_delta), 9),
        "before": before_reversal_state,
        "after": after_reversal_state,
    }
    assert _matrix_error(
        before_reversal_fk_matrices,
        _matrices(armature, layer.fk_control_bones),
    ) < 1.0e-6
    assert fk_animation_signature() == before_reversal_fk_animation
    pin_curve = _curve(armature, property_path)
    reversal_keys = {
        round(float(point.co.x)): float(point.co.y)
        for point in pin_curve.keyframe_points
        if round(float(point.co.x)) in {72, 74, 80}
    }
    assert abs(reversal_keys[72] - mid_value) < 1.0e-5, reversal_keys
    assert abs(reversal_keys[74]) < 1.0e-6, reversal_keys
    assert 80 not in reversal_keys, reversal_keys
    bpy.context.scene.frame_set(73)
    assert float(driven[contact.pin_property]) <= mid_value + 1.0e-5
    bpy.context.scene.frame_set(80)
    assert abs(float(driven[contact.pin_property])) < 1.0e-5

    # Editing an earlier transition must stop at the next authored public
    # switch.  Later public states and their private ramps remain byte-for-byte
    # equivalent and evaluate to the same values.
    contact.contact_transition_frames = 4
    bpy.context.scene.frame_set(100)
    assert bpy.ops.coa_tools2.switch_semantic_contact(
        "EXEC_DEFAULT", mode="ON"
    ) == {"FINISHED"}
    bpy.context.scene.frame_set(110)
    assert bpy.ops.coa_tools2.switch_semantic_contact(
        "EXEC_DEFAULT", mode="OFF"
    ) == {"FINISHED"}
    pin_curve = _curve(armature, property_path)
    contact_mode_curve = _curve(armature, contact.path_from_id("contact_mode"))

    def future_signature(curve):
        return tuple(
            item
            for item in _curve_signature(curve)
            if item[0] >= 100.0
        )

    future_pin_signature = future_signature(pin_curve)
    future_mode_signature = future_signature(contact_mode_curve)
    future_frames = (100.0, 102.0, 104.0, 110.0, 112.0, 114.0)
    future_values = tuple(
        round(float(pin_curve.evaluate(frame)), 7) for frame in future_frames
    )

    bpy.context.scene.frame_set(80)
    contact.contact_transition_frames = 10
    assert bpy.ops.coa_tools2.switch_semantic_contact(
        "EXEC_DEFAULT", mode="ON"
    ) == {"FINISHED"}
    bpy.context.scene.frame_set(82)
    assert 0.0 < float(driven[contact.pin_property]) < 1.0
    contact.contact_transition_frames = 2
    assert bpy.ops.coa_tools2.switch_semantic_contact(
        "EXEC_DEFAULT", mode="OFF"
    ) == {"FINISHED"}
    pin_curve = _curve(armature, property_path)
    contact_mode_curve = _curve(armature, contact.path_from_id("contact_mode"))
    assert future_signature(pin_curve) == future_pin_signature
    assert future_signature(contact_mode_curve) == future_mode_signature
    assert tuple(
        round(float(pin_curve.evaluate(frame)), 7) for frame in future_frames
    ) == future_values
    bpy.context.scene.frame_set(114)
    assert contact.contact_mode == "OFF"
    assert abs(float(driven[contact.pin_property])) < 1.0e-5

    # A past edit may not create a new private ramp that reaches the next
    # public switch.  Reject it transactionally instead of mixing two events.
    bpy.context.scene.frame_set(82)
    contact.contact_transition_frames = 30
    blocked_mode = contact.contact_mode
    blocked_property = float(driven[contact.pin_property])
    blocked_public_curve = _curve_signature(contact_mode_curve)
    blocked_private_curve = _curve_signature(pin_curve)
    blocked_anchor_role = semantic_stage_role(contact.stage_uuid, "pin_anchor")
    blocked_anchor = next(
        obj
        for obj in bpy.data.objects
        if obj.get("coa_rig_component_role") == blocked_anchor_role
    )
    blocked_anchor_matrix = blocked_anchor.matrix_world.copy()
    blocked_orientation_anchor_matrix = (
        reversal_orientation_anchor.matrix_world.copy()
    )
    blocked_control_matrices = _matrices(armature, reversal_control_names)
    blocked_rig_mode = ik_stage.rig_mode

    def assert_contact_boundary_rejected():
        expected = "would reach or cross the next authored Contact/Mode switch"
        try:
            result = bpy.ops.coa_tools2.switch_semantic_contact(
                "EXEC_DEFAULT",
                mode="ON",
            )
        except RuntimeError as exc:
            assert expected in str(exc), str(exc)
        else:
            assert result == {"CANCELLED"}, result

    assert_contact_boundary_rejected()
    assert contact.contact_mode == blocked_mode
    assert abs(float(driven[contact.pin_property]) - blocked_property) < 1.0e-6
    assert _curve_signature(contact_mode_curve) == blocked_public_curve
    assert _curve_signature(pin_curve) == blocked_private_curve
    assert _matrix_error(
        (blocked_anchor_matrix,),
        (blocked_anchor.matrix_world,),
    ) < 1.0e-6
    assert _matrix_error(
        (blocked_orientation_anchor_matrix,),
        (reversal_orientation_anchor.matrix_world,),
    ) < 1.0e-6
    assert _matrix_error(
        blocked_control_matrices,
        _matrices(armature, reversal_control_names),
    ) < 1.0e-6
    assert ik_stage.rig_mode == blocked_rig_mode
    contact.contact_transition_frames = 2

    # A Contact ramp also cannot cross a future public FK/IK Pose Match.  The
    # direct Enum curve and private Contact curve both remain unchanged.
    component.semantic_stages_index = list(component.semantic_stages).index(ik_stage)
    bpy.context.scene.frame_set(140)
    assert operator("EXEC_DEFAULT", mode="IK") == {"FINISHED"}
    future_mode_curve_signature = _curve_signature(mode_curve)
    component.semantic_stages_index = list(component.semantic_stages).index(contact)
    bpy.context.scene.frame_set(130)
    mode_boundary_public = _curve_signature(contact_mode_curve)
    mode_boundary_private = _curve_signature(pin_curve)
    mode_boundary_anchor = blocked_anchor.matrix_world.copy()
    mode_boundary_orientation_anchor = (
        reversal_orientation_anchor.matrix_world.copy()
    )
    mode_boundary_controls = _matrices(armature, reversal_control_names)
    mode_boundary_mode = contact.contact_mode
    mode_boundary_property = float(driven[contact.pin_property])
    mode_boundary_rig_mode = ik_stage.rig_mode
    contact.contact_transition_frames = 12
    assert_contact_boundary_rejected()
    assert _curve_signature(mode_curve) == future_mode_curve_signature
    assert _curve_signature(contact_mode_curve) == mode_boundary_public
    assert _curve_signature(pin_curve) == mode_boundary_private
    assert _matrix_error(
        (mode_boundary_anchor,),
        (blocked_anchor.matrix_world,),
    ) < 1.0e-6
    assert _matrix_error(
        (mode_boundary_orientation_anchor,),
        (reversal_orientation_anchor.matrix_world,),
    ) < 1.0e-6
    assert _matrix_error(
        mode_boundary_controls,
        _matrices(armature, reversal_control_names),
    ) < 1.0e-6
    assert contact.contact_mode == mode_boundary_mode
    assert abs(
        float(driven[contact.pin_property]) - mode_boundary_property
    ) < 1.0e-6
    assert ik_stage.rig_mode == mode_boundary_rig_mode
    contact.contact_transition_frames = 2

    # Recompile is idempotent and preserves the display-frame custom shape
    # transform that visually tilts the primary IK widget.
    structural = _structure_signature(armature, component)
    assert bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT") == {"FINISHED"}
    assert structural == _structure_signature(armature, component)
    assert armature.pose.bones[layer.ik_control_bone].custom_shape_transform == display

    # FK/IK failure injection restores state, transforms, influences and keys.
    component.semantic_stages_index = list(component.semantic_stages).index(ik_stage)
    bpy.context.scene.frame_set(60)
    previous_mode = ik_stage.rig_mode
    previous_controls = _matrices(
        armature,
        layer.fk_control_bones + (layer.ik_control_bone, layer.pole_bone),
    )
    previous_influences = tuple(
        item.influence
        for item in follows
        + (ik_constraint, end_rotation, contact_end_rotation)
    )
    previous_mode_curve = _curve_signature(mode_curve)
    original_key_pose = semantic_fk._key_pose

    def fail_pose_key(*_args, **_kwargs):
        raise RuntimeError("injected FK Pose Match failure")

    semantic_fk._key_pose = fail_pose_key
    try:
        semantic_fk.switch_ik_fk_mode(
            armature,
            component,
            ik_stage,
            "FK" if previous_mode == "IK" else "IK",
        )
    except RuntimeError as exc:
        assert "injected FK Pose Match failure" in str(exc)
    else:
        raise AssertionError("Injected FK/IK failure did not propagate.")
    finally:
        semantic_fk._key_pose = original_key_pose
    assert ik_stage.rig_mode == previous_mode
    assert previous_influences == tuple(
        item.influence
        for item in follows
        + (ik_constraint, end_rotation, contact_end_rotation)
    )
    restored_controls = _matrices(
        armature,
        layer.fk_control_bones + (layer.ik_control_bone, layer.pole_bone),
    )
    assert _matrix_error(previous_controls, restored_controls) < 1.0e-5
    assert _curve_signature(mode_curve) == previous_mode_curve

    # Contact failure injection runs after the last authored public event so
    # the transition-boundary guard does not mask the injected write failure.
    # It restores both public/private curves, all matched controls and anchors.
    component.semantic_stages_index = list(component.semantic_stages).index(contact)
    bpy.context.scene.frame_set(160)
    pin_curve = _curve(armature, property_path)
    contact_mode_curve = _curve(armature, contact.path_from_id("contact_mode"))
    mode_curve = _curve(armature, ik_stage.path_from_id("rig_mode"))
    previous_contact_mode = contact.contact_mode
    previous_rig_mode = ik_stage.rig_mode
    previous_pin_curve = _curve_signature(pin_curve)
    previous_contact_mode_curve = _curve_signature(contact_mode_curve)
    previous_public_mode_curve = _curve_signature(mode_curve)
    previous_action = armature.animation_data.action
    anchor_role = semantic_stage_role(contact.stage_uuid, "pin_anchor")
    anchor = next(
        obj
        for obj in bpy.data.objects
        if obj.get("coa_rig_component_role") == anchor_role
    )
    previous_anchor = anchor.matrix_world.copy()
    previous_orientation_anchor = reversal_orientation_anchor.matrix_world.copy()
    previous_contact_controls = _matrices(armature, reversal_control_names)
    previous_control_curves = tuple(
        (path, curve.array_index, _curve_signature(curve))
        for path in semantic_fk._pose_transform_paths(
            tuple(armature.pose.bones[name] for name in reversal_control_names)
        )
        for curve in _curves(armature, path)
    )
    previous_property = float(driven[contact.pin_property])
    original_insert = semantic_contact._insert_pin_key
    calls = 0

    def fail_second_pin_key(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected Contact transition failure")
        return original_insert(*args, **kwargs)

    semantic_contact._insert_pin_key = fail_second_pin_key
    try:
        semantic_contact.switch_contact_pin(
            armature,
            component,
            contact,
            "ON" if previous_contact_mode == "OFF" else "OFF",
        )
    except RuntimeError as exc:
        assert "injected Contact transition failure" in str(exc)
    else:
        raise AssertionError("Injected Contact failure did not propagate.")
    finally:
        semantic_contact._insert_pin_key = original_insert
    assert contact.contact_mode == previous_contact_mode
    assert abs(float(driven[contact.pin_property]) - previous_property) < 1.0e-6
    assert _matrix_error((previous_anchor,), (anchor.matrix_world,)) < 1.0e-6
    assert _matrix_error(
        (previous_orientation_anchor,),
        (reversal_orientation_anchor.matrix_world,),
    ) < 1.0e-6
    assert _matrix_error(
        previous_contact_controls,
        _matrices(armature, reversal_control_names),
    ) < 1.0e-5
    assert armature.animation_data.action == previous_action
    pin_curve = _curve(armature, property_path)
    contact_mode_curve = _curve(armature, contact.path_from_id("contact_mode"))
    mode_curve = _curve(armature, ik_stage.path_from_id("rig_mode"))
    assert _curve_signature(pin_curve) == previous_pin_curve
    assert _curve_signature(contact_mode_curve) == previous_contact_mode_curve
    assert _curve_signature(mode_curve) == previous_public_mode_curve
    assert tuple(
        (path, curve.array_index, _curve_signature(curve))
        for path in semantic_fk._pose_transform_paths(
            tuple(armature.pose.bones[name] for name in reversal_control_names)
        )
        for curve in _curves(armature, path)
    ) == previous_control_curves
    assert ik_stage.rig_mode == previous_rig_mode

    # Migrating a legacy direct influence curve is transactional.  A compile
    # failure restores the original no-driver state and exact animator keys;
    # only a fully successful retry commits removal and installs the composed
    # public Mode / private Contact driver.
    legacy_constraint = follows[0]
    legacy_path = legacy_constraint.path_from_id("influence")
    assert legacy_constraint.driver_remove("influence")
    legacy_constraint.influence = 0.25
    assert legacy_constraint.keyframe_insert(data_path="influence", frame=150)
    legacy_constraint.influence = 0.75
    assert legacy_constraint.keyframe_insert(data_path="influence", frame=152)
    legacy_curve = _curve(armature, legacy_path)
    for point in legacy_curve.keyframe_points:
        point.interpolation = "CONSTANT"
    legacy_curve.update()
    legacy_signature = _curve_signature(legacy_curve)
    original_outputs = semantic_compiler.reconcile_semantic_outputs

    def fail_legacy_migration(*_args, **_kwargs):
        raise RuntimeError("injected solver migration failure")

    semantic_compiler.reconcile_semantic_outputs = fail_legacy_migration
    try:
        try:
            semantic_compiler.compile_semantic_component(armature, component)
        except RuntimeError as exc:
            assert "injected solver migration failure" in str(exc)
        else:
            raise AssertionError("Injected solver migration failure did not propagate.")
    finally:
        semantic_compiler.reconcile_semantic_outputs = original_outputs
    assert _curve_signature(_curve(armature, legacy_path)) == legacy_signature
    assert legacy_path not in {
        item.data_path for item in armature.animation_data.drivers
    }

    semantic_compiler.compile_semantic_component(armature, component)
    assert not _curves(armature, legacy_path)
    assert legacy_path in {
        item.data_path for item in armature.animation_data.drivers
    }

    # Save/reload keeps the authored public modes, their evaluation at the
    # persisted frame, and the public-Mode/private-Contact solver drivers.
    persistence_frame = int(bpy.context.scene.frame_current)
    persistence_mode = ik_stage.rig_mode
    persistence_contact_mode = contact.contact_mode
    persistence_mode_path = ik_stage.path_from_id("rig_mode")
    persistence_contact_mode_path = contact.path_from_id("contact_mode")
    persistence_pin_path = armature.pose.bones[contact.pin_driven_bone].path_from_id(
        f'["{contact.pin_property}"]'
    )
    persistence_mode_curve = _curve(armature, persistence_mode_path)
    persistence_contact_curve = _curve(armature, persistence_contact_mode_path)
    persistence_pin_curve = _curve(armature, persistence_pin_path)
    persistence_mode_curve_signature = _curve_signature(persistence_mode_curve)
    persistence_contact_curve_signature = _curve_signature(persistence_contact_curve)
    persistence_pin_curve_signature = _curve_signature(persistence_pin_curve)
    persistence_mode_evaluation = round(
        float(persistence_mode_curve.evaluate(persistence_frame)),
        7,
    )
    persistence_contact_evaluation = round(
        float(persistence_contact_curve.evaluate(persistence_frame)),
        7,
    )
    persistence_driver_signature = _driver_signature(
        armature,
        solver_driver_paths,
    )
    persistence = Path(bpy.app.tempdir) / "coa_phase10_fk_contact_validation.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(persistence), check_existing=False)
    bpy.ops.wm.open_mainfile(filepath=str(persistence), load_ui=False)
    armature = bpy.data.objects["SemanticSwitchValidation"]
    component = armature.coa_tools2_rig.rig_components[0]
    ik_stage = next(
        stage for stage in component.semantic_stages if stage.stage_type == "CHAIN_IK"
    )
    contact = next(
        stage for stage in component.semantic_stages if stage.stage_type == "CONTACT_PIN"
    )
    assert int(bpy.context.scene.frame_current) == persistence_frame
    bpy.context.scene.frame_set(persistence_frame)
    bpy.context.view_layer.update()
    reloaded_mode_path = ik_stage.path_from_id("rig_mode")
    reloaded_contact_mode_path = contact.path_from_id("contact_mode")
    reloaded_pin_path = armature.pose.bones[contact.pin_driven_bone].path_from_id(
        f'["{contact.pin_property}"]'
    )
    reloaded_mode_curve = _curve(armature, reloaded_mode_path)
    reloaded_contact_curve = _curve(armature, reloaded_contact_mode_path)
    reloaded_pin_curve = _curve(armature, reloaded_pin_path)
    persistence_diagnostics = {
        "frame": persistence_frame,
        "before_mode": persistence_mode,
        "after_mode": ik_stage.rig_mode,
        "before_contact": persistence_contact_mode,
        "after_contact": contact.contact_mode,
        "before_mode_curve_value": persistence_mode_evaluation,
        "after_mode_curve_value": round(
            float(reloaded_mode_curve.evaluate(persistence_frame)),
            7,
        ),
        "before_contact_curve_value": persistence_contact_evaluation,
        "after_contact_curve_value": round(
            float(reloaded_contact_curve.evaluate(persistence_frame)),
            7,
        ),
    }
    assert ik_stage.rig_mode == persistence_mode, persistence_diagnostics
    assert contact.contact_mode == persistence_contact_mode, persistence_diagnostics
    assert _curve_signature(
        reloaded_mode_curve
    ) == persistence_mode_curve_signature, persistence_diagnostics
    assert _curve_signature(
        reloaded_contact_curve
    ) == persistence_contact_curve_signature, persistence_diagnostics
    assert _curve_signature(
        reloaded_pin_curve
    ) == persistence_pin_curve_signature, persistence_diagnostics
    assert _driver_signature(
        armature,
        solver_driver_paths,
    ) == persistence_driver_signature, persistence_diagnostics
    reloaded_roles = {artifact.role for artifact in component.artifacts}
    assert f"semantic:{ik_stage.stage_uuid}:fk_control:0" in reloaded_roles
    assert f"semantic:{ik_stage.stage_uuid}:ik_end_rotation" in reloaded_roles
    assert f"semantic:{contact.stage_uuid}:pin_constraint" in reloaded_roles
    try:
        persistence.unlink()
    except OSError:
        pass

    print(
        "PHASE10_FK_CONTACT_SWITCH_OK",
        round(fk_to_ik_error, 6),
        round(ik_to_fk_error, 6),
        round(pin_error, 6),
        structural,
    )


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
