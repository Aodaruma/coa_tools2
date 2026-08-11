#!/usr/bin/env python3
"""Blender integration test for semantic Contact / Pin transitions."""

from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import bpy


def curve_signature(curve):
    return tuple(
        (
            tuple(round(value, 6) for value in point.co),
            tuple(round(value, 6) for value in point.handle_left),
            tuple(round(value, 6) for value in point.handle_right),
            point.interpolation,
            point.handle_left_type,
            point.handle_right_type,
        )
        for point in curve.keyframe_points
    )


def matrix_signature(matrix):
    return tuple(round(value, 6) for row in matrix for value in row)


def main():
    import coa_tools2
    from coa_tools2 import functions
    from coa_tools2.rig_control.blender.selection import select_pose_bone
    from coa_tools2.rig_control.blender.semantic_artifacts import semantic_stage_role
    from coa_tools2.rig_control.blender.semantic_contact import (
        SemanticContactError,
        validate_pin_ranges,
    )

    coa_tools2.register()
    pin_defaults = dict(
        enabled=True,
        stage_type="CONTACT_PIN",
        pin_start=5,
        pin_end=10,
        blend_in=2,
        blend_out=2,
        pin_driven_bone="stale_shared_name",
    )
    branch_a = SimpleNamespace(
        **pin_defaults,
        label="Branch A",
        depends_on="projected-a",
        pin_driven_stage_uuid="projected-a",
    )
    branch_b = SimpleNamespace(
        **pin_defaults,
        label="Branch B",
        depends_on="projected-b",
        pin_driven_stage_uuid="projected-b",
    )
    # Preflight compares the DAG provider, not stale compiled bone names.
    validate_pin_ranges(SimpleNamespace(semantic_stages=(branch_a, branch_b)))
    try:
        validate_pin_ranges(
            SimpleNamespace(semantic_stages=(branch_a, branch_b)),
            resolved=True,
        )
    except SemanticContactError as exc:
        assert "Pin ranges overlap" in str(exc)
    else:
        raise AssertionError("Resolved overlapping Pin destinations were accepted.")

    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object
    bpy.ops.object.mode_set(mode="EDIT")
    bone = armature.data.edit_bones.new("hand")
    bone.head = (0.0, 0.0, 0.0)
    bone.tail = (0.0, 0.0, 1.0)
    alternate = armature.data.edit_bones.new("hand_alt")
    alternate.head = (2.0, 0.0, 0.0)
    alternate.tail = (2.0, 0.0, 1.0)
    bpy.ops.object.mode_set(mode="POSE")
    select_pose_bone(armature, "hand", exclusive=True)
    assert bpy.ops.coa_tools2.add_semantic_rig(
        "EXEC_DEFAULT", label="Hand Contact", initial_dimensions=3
    ) == {"FINISHED"}
    component = armature.coa_tools2_rig.rig_components[0]
    assert bpy.ops.coa_tools2.add_semantic_stage(
        "EXEC_DEFAULT", stage_type="CONTACT_PIN", label="World Pin"
    ) == {"FINISHED"}
    pin = component.semantic_stages[-1]
    pin.pin_start = 5
    pin.pin_end = 10
    pin.blend_in = 2
    pin.blend_out = 2
    pin.pin_space = "WORLD"
    pin.pin_position = True
    pin.pin_orientation = False
    assert bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT") == {"FINISHED"}
    control = armature.pose.bones[pin.pin_driven_bone]
    constraint = control.constraints.get(
        f"COA_PIN_{component.component_uuid.replace('-', '')[:8]}_{pin.stage_uuid.replace('-', '')[:8]}"
    )
    assert constraint is not None and constraint.type == "COPY_LOCATION"
    managed_constraint_name = constraint.name
    influence_path = constraint.path_from_id("influence")
    assert any(
        curve.data_path == influence_path
        for curve in armature.animation_data.drivers
    )

    control.location.x = 0.0
    control.keyframe_insert("location", frame=1, index=0)
    control.location.x = 3.0
    control.keyframe_insert("location", frame=20, index=0)
    component.semantic_stages_index = len(component.semantic_stages) - 1
    assert bpy.ops.coa_tools2.apply_semantic_pin_range("EXEC_DEFAULT") == {"FINISHED"}

    action = armature.animation_data.action
    property_path = control.path_from_id(f'["{pin.pin_property}"]')
    curve = next(
        item for item in functions.iter_action_fcurves(action)
        if item.data_path == property_path
    )
    keys = tuple((round(point.co.x), round(point.co.y, 4)) for point in curve.keyframe_points)
    assert keys == ((3, 0.0), (5, 1.0), (10, 1.0), (12, 0.0)), keys
    assert all(point.interpolation == "LINEAR" for point in curve.keyframe_points)
    detached_action = action.copy()
    detached_curve = next(
        item for item in functions.iter_action_fcurves(detached_action)
        if item.data_path == property_path
    )
    detached_signature = curve_signature(detached_curve)

    role = semantic_stage_role(pin.stage_uuid, "pin_anchor")
    anchor = next(
        obj for obj in bpy.data.objects
        if obj.get("coa_rig_component_role") == role
    )
    pinned_location = anchor.matrix_world.translation.copy()
    bpy.context.scene.frame_set(7)
    bpy.context.view_layer.update()
    control_world = (armature.matrix_world @ control.matrix).translation
    assert (control_world - pinned_location).length < 1.0e-5
    bpy.context.scene.frame_set(12)
    bpy.context.view_layer.update()
    assert abs(constraint.influence) < 1.0e-6

    before = (len(component.artifacts), len(control.constraints), len(bpy.data.objects))
    assert bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT") == {"FINISHED"}
    after = (len(component.artifacts), len(control.constraints), len(bpy.data.objects))
    assert before == after, (before, after)

    # A stale artifact name is never authority for deletion.  The live Pin
    # driver identifies a renamed generated Constraint even when a user
    # Constraint reuses its old name; both remain untouched.
    renamed_owned_name = f"{managed_constraint_name}_RENAMED"
    constraint.name = renamed_owned_name
    user_constraint = control.constraints.new("COPY_LOCATION")
    user_constraint.name = managed_constraint_name
    assert bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT") == {"FINISHED"}
    assert control.constraints.get(renamed_owned_name) is not None
    assert control.constraints.get(managed_constraint_name) == user_constraint
    control.constraints.remove(user_constraint)
    constraint.name = managed_constraint_name
    assert bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT") == {"FINISHED"}
    constraint = control.constraints.get(managed_constraint_name)
    influence_path = constraint.path_from_id("influence")

    # Reapplying this stage at a new range replaces its old support keys.
    pin.pin_start = 30
    pin.pin_end = 34
    pin.blend_in = 1
    pin.blend_out = 2
    assert bpy.ops.coa_tools2.apply_semantic_pin_range("EXEC_DEFAULT") == {"FINISHED"}
    keys = tuple(
        (round(point.co.x), round(point.co.y, 4))
        for point in curve.keyframe_points
    )
    assert keys == ((29, 0.0), (30, 1.0), (34, 1.0), (36, 0.0)), keys

    # Overlapping support ranges on the same driven control are rejected
    # before Blender artifacts are changed.
    assert bpy.ops.coa_tools2.add_semantic_stage(
        "EXEC_DEFAULT", stage_type="CONTACT_PIN", label="Overlapping Pin"
    ) == {"FINISHED"}
    overlap = component.semantic_stages[-1]
    overlap.pin_start = 34
    overlap.pin_end = 40
    overlap.blend_in = overlap.blend_out = 2
    structural_before = (
        len(armature.data.bones), len(component.artifacts), len(bpy.data.objects)
    )
    try:
        result = bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT")
    except RuntimeError as exc:
        assert "Pin ranges overlap" in str(exc)
    else:
        assert result == {"CANCELLED"}
    assert structural_before == (
        len(armature.data.bones), len(component.artifacts), len(bpy.data.objects)
    )
    component.semantic_stages.remove(len(component.semantic_stages) - 1)

    # A user property at the requested destination is rejected before the
    # existing Pin identity is destructively moved.
    alternate_control = armature.pose.bones["hand_alt"]
    alternate_control[pin.pin_property] = 0.42
    pin.pin_driven_bone = "hand_alt"
    try:
        result = bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT")
    except RuntimeError as exc:
        assert "not owned by this Pin stage" in str(exc)
    else:
        assert result == {"CANCELLED"}
    assert abs(alternate_control[pin.pin_property] - 0.42) < 1.0e-6
    assert control.constraints.get(managed_constraint_name) is not None
    del alternate_control[pin.pin_property]

    # Retargeting the same Pin stage moves its complete managed identity.
    old_control = control
    old_constraint_path = influence_path
    component.semantic_stages_index = len(component.semantic_stages) - 1
    assert bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT") == {"FINISHED"}
    new_control = armature.pose.bones["hand_alt"]
    new_constraint = new_control.constraints.get(managed_constraint_name)
    assert new_constraint is not None
    assert old_control.constraints.get(managed_constraint_name) is None
    driver_paths = {
        item.data_path for item in armature.animation_data.drivers
    }
    assert old_constraint_path not in driver_paths, driver_paths
    assert new_constraint.path_from_id("influence") in driver_paths, driver_paths
    constraint_role = semantic_stage_role(pin.stage_uuid, "pin_constraint")
    driver_role = semantic_stage_role(pin.stage_uuid, "pin_influence_driver")
    constraint_artifacts = [
        item for item in component.artifacts if item.role == constraint_role
    ]
    driver_artifacts = [
        item for item in component.artifacts if item.role == driver_role
    ]
    assert len(constraint_artifacts) == len(driver_artifacts) == 1
    assert constraint_artifacts[0].bone_name == "hand_alt"
    assert driver_artifacts[0].bone_name == "hand_alt"

    # Only the active Armature Action is edited during retarget cleanup.  A
    # detached Action with the same RNA path may belong to another use and is
    # intentionally preserved.
    assert pin.pin_property not in old_control
    assert not any(
        item.data_path == property_path
        for item in functions.iter_action_fcurves(action)
    )
    assert curve_signature(detached_curve) == detached_signature

    # A partial keying failure restores keys, property value, anchor, active
    # Action, and frame as one transaction.
    from coa_tools2.rig_control.blender import semantic_contact

    pin.pin_start = 50
    pin.pin_end = 54
    pin.blend_in = 2
    pin.blend_out = 3
    assert bpy.ops.coa_tools2.apply_semantic_pin_range("EXEC_DEFAULT") == {"FINISHED"}
    new_property_path = new_control.path_from_id(f'["{pin.pin_property}"]')
    new_curve = next(
        item for item in functions.iter_action_fcurves(action)
        if item.data_path == new_property_path
    )
    previous_curve = curve_signature(new_curve)
    bpy.context.scene.frame_set(17)
    new_control[pin.pin_property] = 0.37
    previous_property = new_control.get(pin.pin_property)
    previous_anchor = anchor.matrix_world.copy()
    previous_action = armature.animation_data.action
    original_insert = semantic_contact._insert_pin_key
    calls = 0

    def fail_third_key(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("injected Pin key failure")
        return original_insert(*args, **kwargs)

    semantic_contact._insert_pin_key = fail_third_key
    try:
        semantic_contact.key_pin_range(armature, component, pin)
    except RuntimeError as exc:
        assert "injected Pin key failure" in str(exc)
    else:
        raise AssertionError("Injected Pin failure did not propagate.")
    finally:
        semantic_contact._insert_pin_key = original_insert
    assert bpy.context.scene.frame_current == 17
    assert armature.animation_data.action == previous_action
    assert abs(new_control.get(pin.pin_property) - previous_property) < 1.0e-6
    assert matrix_signature(anchor.matrix_world) == matrix_signature(previous_anchor)
    assert curve_signature(new_curve) == previous_curve

    # Disabling the stage removes only its live property/key/driver/constraint.
    # The detached Action remains byte-for-byte equivalent at its curve level.
    pin.enabled = False
    assert bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT") == {"FINISHED"}
    assert pin.pin_property not in new_control
    assert new_control.constraints.get(managed_constraint_name) is None
    assert not any(
        item.data_path == new_property_path
        for item in functions.iter_action_fcurves(action)
    )
    assert curve_signature(detached_curve) == detached_signature
    print("PHASE7C_PIN_OK", keys)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
