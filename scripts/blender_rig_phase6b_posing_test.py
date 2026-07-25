#!/usr/bin/env python3
"""Blender integration test for Phase 6B character posing components."""

from __future__ import annotations

import math
import os
import sys
import tempfile
import uuid

import addon_utils
import bpy
from mathutils import Vector


def _create_bone(edit_bones, name, head, tail, *, parent=None, roll=0.0):
    bone = edit_bones.new(name)
    bone.head = head
    bone.tail = tail
    bone.roll = roll
    bone.parent = parent
    bone.use_connect = parent is not None and bone.head == parent.tail
    return bone


def _select_pose_bones(armature, names, active_name):
    from coa_tools2.rig_control.blender.selection import select_pose_bones

    select_pose_bones(armature, names, active_name)
    bpy.context.view_layer.update()


def _add_component(**properties):
    result = bpy.ops.coa_tools2.add_rig_component("EXEC_DEFAULT", **properties)
    assert result == {"FINISHED"}, result


def _action_data_paths(action):
    from coa_tools2.functions import iter_action_fcurves

    return {curve.data_path for curve in iter_action_fcurves(action)}


def _action_signature(action):
    from coa_tools2.functions import iter_action_fcurves

    return tuple(
        sorted(
            (
                curve.data_path,
                curve.array_index,
                tuple(
                    (
                        tuple(point.co),
                        point.interpolation,
                    )
                    for point in curve.keyframe_points
                ),
            )
            for curve in iter_action_fcurves(action)
        )
    )


def _matrix_delta(left, right):
    return max(
        abs(left[row][column] - right[row][column])
        for row in range(4)
        for column in range(4)
    )


def main():
    if not addon_utils.check("coa_tools2")[1]:
        if addon_utils.enable("coa_tools2", default_set=False, persistent=False) is None:
            raise RuntimeError("Could not enable coa_tools2.")

    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object
    assert armature is not None and armature.type == "ARMATURE"

    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = armature.data.edit_bones
    root = _create_bone(edit_bones, "root", (0, 0, 0), (0, 0, 1))
    spine_1 = _create_bone(
        edit_bones,
        "spine_1",
        root.tail,
        (0, 0, 2.25),
        parent=root,
    )
    spine_2 = _create_bone(
        edit_bones,
        "spine_2",
        spine_1.tail,
        (0, 0, 3.5),
        parent=spine_1,
    )
    upper = _create_bone(
        edit_bones,
        "upper_arm.L",
        (0, 0, 3.15),
        (1.45, 0.10, 3.05),
        parent=spine_2,
        roll=0.25,
    )
    lower = _create_bone(
        edit_bones,
        "forearm.L",
        upper.tail,
        (2.65, 0.35, 2.75),
        parent=upper,
        roll=0.45,
    )
    _create_bone(
        edit_bones,
        "hand.L",
        lower.tail,
        (3.30, 0.62, 2.72),
        parent=lower,
        roll=0.80,
    )
    bpy.ops.object.mode_set(mode="POSE")

    # Preserve an existing animation path while converting the source spine
    # bones to in-place FK controls.
    spine_pose = armature.pose.bones["spine_1"]
    spine_pose.rotation_mode = "XYZ"
    spine_pose.rotation_euler.z = math.radians(8.0)
    spine_pose.keyframe_insert("rotation_euler", frame=1, index=2)
    action = armature.animation_data.action
    original_paths = _action_data_paths(action)
    original_action_signature = _action_signature(action)

    _select_pose_bones(armature, {"root"}, "root")
    _add_component(
        label="Body Root",
        component_type="ROOT",
        depth_mode="LIMITED",
        depth_min=-0.20,
        depth_max=0.35,
        widget="ROOT",
        widget_size=0.8,
    )

    spine_color = getattr(armature.data.bones["spine_1"], "color", None)
    if spine_color is not None:
        spine_color.palette = "THEME04"
    _select_pose_bones(armature, {"spine_1", "spine_2"}, "spine_2")
    _add_component(
        label="Spine FK",
        component_type="SPINE_FK",
        widget="FK",
        widget_size=0.55,
    )
    assert _action_data_paths(action) == original_paths
    assert _action_signature(action) == original_action_signature
    if spine_color is not None:
        assert armature.data.bones["spine_1"].color.palette == "THEME04"

    upper_pose = armature.pose.bones["upper_arm.L"]
    lower_pose = armature.pose.bones["forearm.L"]
    upper_pose.rotation_mode = "XYZ"
    lower_pose.rotation_mode = "XYZ"
    upper_pose.rotation_euler = (
        math.radians(18.0),
        math.radians(-11.0),
        math.radians(14.0),
    )
    lower_pose.rotation_euler = (
        math.radians(-9.0),
        math.radians(16.0),
        math.radians(-21.0),
    )
    bpy.context.view_layer.update()
    reference_z = (
        armature.data.bones["hand.L"].matrix_local.to_3x3()
        @ Vector((0.0, 0.0, 1.0))
    ).normalized()
    pre_ik_matrices = {
        name: armature.pose.bones[name].matrix.copy()
        for name in ("upper_arm.L", "forearm.L", "hand.L")
    }
    pre_ik_joint = armature.pose.bones["forearm.L"].head.copy()
    pre_ik_end = armature.pose.bones["hand.L"].head.copy()
    _select_pose_bones(
        armature,
        {"upper_arm.L", "forearm.L", "hand.L"},
        "hand.L",
    )
    _add_component(
        label="Hand IK.L",
        component_type="LIMB_IK",
        orientation_mode="SOURCE_BONE",
        depth_mode="LIMITED",
        depth_min=-0.30,
        depth_max=0.50,
        widget="HAND",
        widget_size=0.65,
        ik_solver_mode="SPATIAL",
        end_rotation_mode="COPY_WORLD",
        use_stretch=False,
    )

    rig_data = armature.coa_tools2_rig
    assert len(rig_data.rig_components) == 3
    root_component, fk_component, limb_component = rig_data.rig_components
    assert root_component.build_mode == "IN_PLACE"
    assert fk_component.build_mode == "IN_PLACE"
    assert limb_component.build_mode == "GENERATED"

    root_pose = armature.pose.bones["root"]
    assert tuple(root_pose.lock_location) == (False, False, False)
    assert tuple(root_pose.lock_rotation) == (False, False, False)
    assert root_pose.custom_shape is not None
    root_depth = root_pose.constraints.get(
        f"COA_COMP_{root_component.component_uuid[:8]}_Depth"
    )
    assert root_depth is not None
    assert math.isclose(root_depth.min_z, -0.20, abs_tol=1e-6)
    assert math.isclose(root_depth.max_z, 0.35, abs_tol=1e-6)

    for name in ("spine_1", "spine_2"):
        pose_bone = armature.pose.bones[name]
        assert tuple(pose_bone.lock_location) == (True, True, True)
        assert tuple(pose_bone.lock_rotation) == (False, False, False)
        assert pose_bone.custom_shape is not None

    frame_pose = armature.pose.bones[limb_component.frame_bone]
    control_pose = armature.pose.bones[limb_component.control_bone]
    pole_pose = armature.pose.bones[limb_component.pole_bone]
    control_z = (
        armature.data.bones[control_pose.name].matrix_local.to_3x3()
        @ Vector((0.0, 0.0, 1.0))
    ).normalized()
    assert control_z.dot(reference_z) > 0.9999, (
        tuple(control_z),
        tuple(reference_z),
        control_z.dot(reference_z),
    )
    assert tuple(control_pose.lock_location) == (False, False, False)
    assert tuple(control_pose.lock_rotation) == (False, False, False)
    assert len(control_pose.custom_shape.data.vertices) > 6
    assert pole_pose.custom_shape is not None
    assert tuple(pole_pose.lock_location) == (False, False, False)
    assert tuple(pole_pose.lock_rotation) == (True, True, True)

    owner = armature.pose.bones["forearm.L"]
    ik = owner.constraints.get(limb_component.constraint_name)
    assert ik is not None and ik.type == "IK"
    assert ik.target == armature
    assert ik.subtarget == control_pose.name
    assert ik.chain_count == 2
    assert not ik.use_stretch
    assert ik.pole_target == armature
    assert ik.pole_subtarget == pole_pose.name
    bpy.context.view_layer.update()
    joint_delta = (armature.pose.bones["forearm.L"].head - pre_ik_joint).length
    end_delta = (armature.pose.bones["hand.L"].head - pre_ik_end).length
    assert joint_delta < 1e-4, (joint_delta, ik.pole_angle)
    assert end_delta < 1e-4, (end_delta, ik.pole_angle)
    for name, expected_matrix in pre_ik_matrices.items():
        assert _matrix_delta(
            armature.pose.bones[name].matrix,
            expected_matrix,
        ) < 1e-4, name
    calibrated_pole_angle = ik.pole_angle
    calibrated_joint = armature.pose.bones["forearm.L"].head.copy()
    calibrated_upper_rotation = armature.pose.bones[
        "upper_arm.L"
    ].matrix.to_quaternion()
    assert limb_component.pole_angle_valid
    assert math.isclose(
        limb_component.pole_angle,
        calibrated_pole_angle,
        abs_tol=1e-8,
    )
    for name in ("upper_arm.L", "forearm.L"):
        pose_bone = armature.pose.bones[name]
        assert not pose_bone.lock_ik_x
        assert not pose_bone.lock_ik_y
        assert not pose_bone.lock_ik_z
        assert math.isclose(pose_bone.ik_stretch, 0.0, abs_tol=1e-6)

    end_rotation = armature.pose.bones["hand.L"].constraints.get(
        f"COA_COMP_{limb_component.component_uuid[:8]}_EndRotation"
    )
    assert end_rotation is not None and end_rotation.type == "COPY_ROTATION"

    # The input channel remains animatable, while the evaluated control is
    # constrained to the requested visual-normal slab.
    original_control_location = control_pose.location.copy()
    control_pose.location.z = 2.0
    bpy.context.view_layer.update()
    evaluated_armature = armature.evaluated_get(
        bpy.context.evaluated_depsgraph_get()
    )
    evaluated_control = evaluated_armature.pose.bones[control_pose.name]
    evaluated_frame = evaluated_armature.pose.bones[frame_pose.name]
    visual_normal = evaluated_frame.matrix.to_3x3().col[2].normalized()
    evaluated_delta = (
        evaluated_control.matrix.translation
        - evaluated_frame.matrix.translation
    )
    depth = evaluated_delta.dot(visual_normal)
    assert 0.4900 <= depth <= 0.5001, depth
    control_pose.location = original_control_location
    bpy.context.view_layer.update()

    from coa_tools2.rig_control.blender.component_compiler import compile_component
    from coa_tools2.rig_control.blender import component_artifacts

    bone_count = len(armature.data.bones)
    artifact_count = len(limb_component.artifacts)
    compile_component(armature, limb_component)
    assert len(armature.data.bones) == bone_count
    assert len(limb_component.artifacts) == artifact_count
    assert not limb_component.needs_rebuild
    bpy.context.view_layer.update()
    assert math.isclose(ik.pole_angle, calibrated_pole_angle, abs_tol=1e-8)
    assert (
        armature.pose.bones["forearm.L"].head - calibrated_joint
    ).length < 1e-5
    upper_rotation = armature.pose.bones["upper_arm.L"].matrix.to_quaternion()
    assert (
        upper_rotation.rotation_difference(calibrated_upper_rotation).angle
        < 1e-5
    )

    # Unsupported hidden IK settings remain guarded after the source bones
    # become component-owned; Update must not silently preserve them.
    owned_source_pose = armature.pose.bones["upper_arm.L"]
    owned_source_pose.use_ik_limit_x = True
    try:
        compile_component(armature, limb_component)
    except RuntimeError as exc:
        assert "unmanaged IK channel settings" in str(exc)
    else:
        raise AssertionError("Owned source IK limits were not rejected.")
    assert owned_source_pose.use_ik_limit_x
    assert len(armature.data.bones) == bone_count
    assert len(limb_component.artifacts) == artifact_count
    owned_source_pose.use_ik_limit_x = False

    # A failed structural Update restores existing generated rest frames.
    generated_matrices = {
        name: armature.data.bones[name].matrix_local.copy()
        for name in (
            limb_component.frame_bone,
            limb_component.control_bone,
            limb_component.pole_bone,
        )
    }
    original_limb_constraint_builder = (
        component_artifacts.ensure_limb_constraints
    )

    def _raise_after_limb_reconcile(*_args, **_kwargs):
        raise RuntimeError("injected limb rollback test")

    limb_component.orientation_mode = "CUSTOM"
    limb_component.orientation_euler = (
        math.radians(12.0),
        math.radians(-18.0),
        math.radians(25.0),
    )
    component_artifacts.ensure_limb_constraints = _raise_after_limb_reconcile
    try:
        try:
            compile_component(armature, limb_component)
        except RuntimeError as exc:
            assert "injected limb rollback test" in str(exc)
            assert "rollback also failed" not in str(exc), str(exc)
        else:
            raise AssertionError("Limb rollback failure did not propagate.")
    finally:
        component_artifacts.ensure_limb_constraints = (
            original_limb_constraint_builder
        )
    for name, expected_matrix in generated_matrices.items():
        assert name in armature.data.bones
        assert _matrix_delta(
            armature.data.bones[name].matrix_local,
            expected_matrix,
        ) < 1e-6, name
    limb_component.orientation_mode = "SOURCE_BONE"
    limb_component.orientation_euler = (0.0, 0.0, 0.0)
    compile_component(armature, limb_component)

    # Spatial -> Planar removes Pole artifacts only after the rest of the
    # reconcile succeeds; rollback recreates the Pole and its constraint links.
    previous_pole_name = limb_component.pole_bone
    previous_pole_matrix = armature.data.bones[
        previous_pole_name
    ].matrix_local.copy()
    previous_pole_widget = armature.pose.bones[
        previous_pole_name
    ].custom_shape
    previous_ik = armature.pose.bones["forearm.L"].constraints[
        limb_component.constraint_name
    ]
    previous_pole_angle = previous_ik.pole_angle
    limb_component.ik_solver_mode = "PLANAR"
    component_artifacts.ensure_limb_constraints = _raise_after_limb_reconcile
    try:
        try:
            compile_component(armature, limb_component)
        except RuntimeError as exc:
            assert "injected limb rollback test" in str(exc)
            assert "rollback also failed" not in str(exc), str(exc)
        else:
            raise AssertionError("Pole rollback failure did not propagate.")
    finally:
        component_artifacts.ensure_limb_constraints = (
            original_limb_constraint_builder
        )
    assert limb_component.pole_bone == previous_pole_name
    assert previous_pole_name in armature.data.bones
    restored_pole_matrix_delta = _matrix_delta(
        armature.data.bones[previous_pole_name].matrix_local,
        previous_pole_matrix,
    )
    assert restored_pole_matrix_delta < 1e-6, restored_pole_matrix_delta
    assert (
        armature.pose.bones[previous_pole_name].custom_shape
        == previous_pole_widget
    )
    restored_ik = armature.pose.bones["forearm.L"].constraints[
        limb_component.constraint_name
    ]
    assert restored_ik.pole_target == armature
    assert restored_ik.pole_subtarget == previous_pole_name
    assert math.isclose(
        restored_ik.pole_angle,
        previous_pole_angle,
        abs_tol=1e-8,
    )
    limb_component.ik_solver_mode = "SPATIAL"
    compile_component(armature, limb_component)

    # Switching desired artifacts must remove both the Blender constraints and
    # their ownership records, then recreate them safely.
    limb_component.depth_mode = "FREE"
    limb_component.end_rotation_mode = "NONE"
    limb_component.ik_solver_mode = "PLANAR"
    limb_component.bend_axis = "Y"
    compile_component(armature, limb_component)
    assert control_pose.constraints.get(
        f"COA_COMP_{limb_component.component_uuid[:8]}_Depth"
    ) is None
    assert armature.pose.bones["hand.L"].constraints.get(
        f"COA_COMP_{limb_component.component_uuid[:8]}_EndRotation"
    ) is None
    assert limb_component.pole_bone == ""
    assert not any(
        artifact.role
        in {"depth_constraint", "end_rotation_constraint", "bend_control", "bend_widget"}
        for artifact in limb_component.artifacts
    )
    for name in ("upper_arm.L", "forearm.L"):
        pose_bone = armature.pose.bones[name]
        assert pose_bone.lock_ik_x
        assert not pose_bone.lock_ik_y
        assert pose_bone.lock_ik_z

    limb_component.depth_mode = "LIMITED"
    limb_component.end_rotation_mode = "COPY_WORLD"
    limb_component.ik_solver_mode = "SPATIAL"
    compile_component(armature, limb_component)
    assert limb_component.pole_bone

    # A failure after source mutation must restore tags, locks, widgets,
    # collections, generated objects, and component ownership records.
    bpy.ops.object.mode_set(mode="EDIT")
    rollback_bone = _create_bone(
        armature.data.edit_bones,
        "rollback_root",
        (5.0, 0.0, 0.0),
        (5.0, 0.0, 1.0),
    )
    rollback_bone_name = rollback_bone.name
    bpy.ops.object.mode_set(mode="POSE")
    rollback_pose = armature.pose.bones[rollback_bone_name]
    rollback_component = rig_data.rig_components.add()
    rollback_component.component_uuid = str(uuid.uuid4())
    rollback_component.semantic_id = "pose.rollback"
    rollback_component.label = "Rollback"
    rollback_component.component_type = "ROOT"
    rollback_component.build_mode = "IN_PLACE"
    rollback_component.widget = "ROOT"
    rollback_reference = rollback_component.source_bones.add()
    rollback_reference.bone_name = rollback_bone_name
    user_constraint = rollback_pose.constraints.new("COPY_LOCATION")
    user_constraint.name = (
        f"COA_COMP_{rollback_component.component_uuid[:8]}_UserOffset"
    )
    before_object_names = {obj.name for obj in bpy.data.objects}
    before_bone_names = {bone.name for bone in armature.data.bones}
    before_collections = {
        collection.name for collection in rollback_pose.bone.collections
    }

    original_depth_builder = component_artifacts.ensure_depth_constraint

    def _raise_after_source_mutation(_pose_bone, _component):
        raise RuntimeError("injected rollback test")

    component_artifacts.ensure_depth_constraint = _raise_after_source_mutation
    try:
        try:
            compile_component(armature, rollback_component)
        except RuntimeError as exc:
            assert "injected rollback test" in str(exc)
            assert "rollback also failed" not in str(exc), str(exc)
        else:
            raise AssertionError("Injected build failure did not propagate.")
    finally:
        component_artifacts.ensure_depth_constraint = original_depth_builder
    after_object_names = {obj.name for obj in bpy.data.objects}
    assert after_object_names == before_object_names, (
        sorted(after_object_names - before_object_names),
        sorted(before_object_names - after_object_names),
    )
    assert {bone.name for bone in armature.data.bones} == before_bone_names
    assert rollback_pose.custom_shape is None
    assert tuple(rollback_pose.lock_location) == (False, False, False)
    assert tuple(rollback_pose.lock_rotation) == (False, False, False)
    assert not rollback_pose.bone.get("coa_rig_component_uuid")
    assert rollback_pose.constraints.get(user_constraint.name) is not None
    assert {
        collection.name for collection in rollback_pose.bone.collections
    } == before_collections
    assert len(rollback_component.artifacts) == 0
    rig_data.rig_components.remove(len(rig_data.rig_components) - 1)

    # Limb FK animation in an inactive NLA Action is rejected until Phase 6C
    # can convert and bake it without changing its evaluated poses.
    bpy.ops.object.mode_set(mode="EDIT")
    animated_upper = _create_bone(
        armature.data.edit_bones,
        "animated_upper.L",
        (5.5, 0.0, 3.0),
        (6.5, 0.1, 2.8),
        parent=armature.data.edit_bones["spine_2"],
    )
    animated_lower = _create_bone(
        armature.data.edit_bones,
        "animated_lower.L",
        animated_upper.tail,
        (7.4, 0.2, 2.5),
        parent=animated_upper,
    )
    _create_bone(
        armature.data.edit_bones,
        "animated_end.L",
        animated_lower.tail,
        (8.0, 0.3, 2.45),
        parent=animated_lower,
    )
    bpy.ops.object.mode_set(mode="POSE")
    from coa_tools2 import functions

    active_action = armature.animation_data.action
    nla_action = bpy.data.actions.new("COA_Phase6B_InactiveFK")
    functions.assign_action(armature, nla_action)
    animated_pose = armature.pose.bones["animated_upper.L"]
    animated_pose.rotation_mode = "XYZ"
    animated_pose.rotation_euler.z = math.radians(10.0)
    animated_pose.keyframe_insert("rotation_euler", frame=1, index=2)
    animated_pose.rotation_euler.z = math.radians(-15.0)
    animated_pose.keyframe_insert("rotation_euler", frame=8, index=2)
    functions.assign_action(armature, active_action)
    nla_track = armature.animation_data.nla_tracks.new()
    nla_track.name = "Inactive FK Guard"
    nla_track.strips.new("Inactive FK", 1, nla_action)
    nla_track.mute = True
    _select_pose_bones(
        armature,
        {"animated_upper.L", "animated_lower.L", "animated_end.L"},
        "animated_end.L",
    )
    component_count = len(rig_data.rig_components)
    guard_object_names = {obj.name for obj in bpy.data.objects}
    try:
        bpy.ops.coa_tools2.add_rig_component(
            "EXEC_DEFAULT",
            label="Animated Limb",
            component_type="LIMB_IK",
        )
    except RuntimeError as exc:
        assert "already has FK animation" in str(exc)
    else:
        raise AssertionError("Animated limb conversion was not rejected.")
    assert len(rig_data.rig_components) == component_count
    assert {obj.name for obj in bpy.data.objects} == guard_object_names
    armature.animation_data.nla_tracks.remove(nla_track)

    # Existing solver limits/stiffness are never silently adopted or cleared.
    animated_pose.use_ik_limit_x = True
    limit_object_names = {obj.name for obj in bpy.data.objects}
    try:
        bpy.ops.coa_tools2.add_rig_component(
            "EXEC_DEFAULT",
            label="Limited Limb",
            component_type="LIMB_IK",
        )
    except RuntimeError as exc:
        assert "unmanaged IK channel settings" in str(exc)
    else:
        raise AssertionError("Unmanaged IK limits were not rejected.")
    assert animated_pose.use_ik_limit_x
    assert len(rig_data.rig_components) == component_count
    assert {obj.name for obj in bpy.data.objects} == limit_object_names
    animated_pose.use_ik_limit_x = False

    # A known preflight conflict is rejected before copy-on-write isolation,
    # so a failed Update leaves a copied Armature and its widgets shared.
    bpy.ops.object.mode_set(mode="OBJECT")
    conflict_duplicate = armature.copy()
    bpy.context.collection.objects.link(conflict_duplicate)
    conflict_duplicate.name = "SpriteObject_ConflictDuplicate"
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    conflict_duplicate.select_set(True)
    bpy.context.view_layer.objects.active = conflict_duplicate
    bpy.ops.object.mode_set(mode="POSE")
    conflict_owner = conflict_duplicate.pose.bones["forearm.L"]
    conflict_constraint = conflict_owner.constraints.new("IK")
    conflict_constraint.name = "User IK Conflict"
    conflict_data = conflict_duplicate.data
    conflict_instance = conflict_duplicate.coa_tools2_rig.rig_instance_id
    conflict_object_names = {obj.name for obj in bpy.data.objects}
    try:
        compile_component(
            conflict_duplicate,
            conflict_duplicate.coa_tools2_rig.rig_components[2],
        )
    except RuntimeError as exc:
        assert "unmanaged IK constraint" in str(exc)
    else:
        raise AssertionError("Unmanaged IK conflict was not rejected.")
    assert conflict_duplicate.data == conflict_data
    assert (
        conflict_duplicate.coa_tools2_rig.rig_instance_id
        == conflict_instance
    )
    assert {obj.name for obj in bpy.data.objects} == conflict_object_names
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.data.objects.remove(conflict_duplicate, do_unlink=True)

    # A copied Armature receives a new instance id and private widget meshes
    # before an update can affect the original rig.
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    duplicate = armature.copy()
    bpy.context.collection.objects.link(duplicate)
    duplicate.name = "SpriteObject_Duplicate"
    original_instance = rig_data.rig_instance_id
    original_widget = control_pose.custom_shape
    original_vertices = tuple(tuple(vertex.co) for vertex in original_widget.data.vertices)
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    duplicate.select_set(True)
    bpy.context.view_layer.objects.active = duplicate
    bpy.ops.object.mode_set(mode="POSE")
    duplicate_component = duplicate.coa_tools2_rig.rig_components[2]
    duplicate_component.widget_size += 0.15
    compile_component(duplicate, duplicate_component)
    assert duplicate.coa_tools2_rig.rig_instance_id != original_instance
    duplicate_control = duplicate.pose.bones[duplicate_component.control_bone]
    assert duplicate_control.custom_shape != original_widget
    assert tuple(tuple(vertex.co) for vertex in original_widget.data.vertices) == (
        original_vertices
    )

    # Save/reload keeps component definitions, generated artifacts, and the
    # independent duplicate instance resolvable.
    file_descriptor, blend_path = tempfile.mkstemp(
        prefix="coa_phase6b_",
        suffix=".blend",
    )
    os.close(file_descriptor)
    try:
        bpy.ops.wm.save_as_mainfile(filepath=blend_path)
        bpy.ops.wm.open_mainfile(filepath=blend_path)
        restored = bpy.data.objects["SpriteObject"]
        restored_duplicate = bpy.data.objects["SpriteObject_Duplicate"]
        assert len(restored.coa_tools2_rig.rig_components) == 3
        restored_component = restored.coa_tools2_rig.rig_components[2]
        assert restored_component.pole_bone
        restored_ik = restored.pose.bones[
            restored_component.constraint_bone
        ].constraints[restored_component.constraint_name]
        assert restored_component.pole_angle_valid
        assert math.isclose(
            restored_ik.pole_angle,
            restored_component.pole_angle,
            abs_tol=1e-8,
        )
        assert math.isclose(
            restored_component.pole_angle,
            calibrated_pole_angle,
            abs_tol=1e-8,
        )
        assert (
            restored.coa_tools2_rig.rig_instance_id
            != restored_duplicate.coa_tools2_rig.rig_instance_id
        )
    finally:
        if os.path.exists(blend_path):
            os.unlink(blend_path)

    print("COA rig Phase 6B posing component test OK.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"Rig Phase 6B test failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise
