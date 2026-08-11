#!/usr/bin/env python3
"""Blender integration test for semantic Contact / Pin transitions."""

from __future__ import annotations

from pathlib import Path
import sys

import bpy


def main():
    import coa_tools2
    from coa_tools2 import functions
    from coa_tools2.rig_control.blender.selection import select_pose_bone
    from coa_tools2.rig_control.blender.semantic_artifacts import semantic_stage_role

    coa_tools2.register()
    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object
    bpy.ops.object.mode_set(mode="EDIT")
    bone = armature.data.edit_bones.new("hand")
    bone.head = (0.0, 0.0, 0.0)
    bone.tail = (0.0, 0.0, 1.0)
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

    # Overlapping support ranges on the same driven control are rejected
    # before Blender artifacts are changed.
    assert bpy.ops.coa_tools2.add_semantic_stage(
        "EXEC_DEFAULT", stage_type="CONTACT_PIN", label="Overlapping Pin"
    ) == {"FINISHED"}
    overlap = component.semantic_stages[-1]
    overlap.pin_start = 9
    overlap.pin_end = 15
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
    print("PHASE7C_PIN_OK", keys)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
