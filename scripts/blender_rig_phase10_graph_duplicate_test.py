#!/usr/bin/env python3
"""Blender regression for copied Graph State ownership and save/reload."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import addon_utils
import bpy


def update_scene():
    bpy.context.view_layer.update()
    bpy.context.scene.frame_set(bpy.context.scene.frame_current)
    bpy.context.view_layer.update()


def activate_armature(armature):
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="POSE")


def create_target(name, shape_names):
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.mesh.primitive_plane_add(size=2.0)
    target = bpy.context.active_object
    target.name = name
    target.shape_key_add(name="Basis")
    for shape_name in shape_names:
        target.shape_key_add(name=shape_name)
    return target


def driver_snapshot(target):
    animation_data = target.data.shape_keys.animation_data
    return {
        fcurve.data_path: (
            fcurve.driver.expression,
            tuple(
                (
                    variable.name,
                    variable.targets[0].id.name if variable.targets[0].id else "",
                    variable.targets[0].bone_target,
                )
                for variable in fcurve.driver.variables
            ),
        )
        for fcurve in animation_data.drivers
    }


def widget_objects(widget_uuid):
    return tuple(
        obj
        for obj in bpy.data.objects
        if obj.get("coa_rig_widget_uuid") == widget_uuid
    )


def rail_object(control_uuid):
    return next(
        obj
        for obj in bpy.data.objects
        if obj.get("coa_rig_control_uuid") == control_uuid
        and obj.get("coa_rig_artifact_role") == "rail_target"
    )


def name_object(control_uuid):
    return next(
        obj
        for obj in bpy.data.objects
        if obj.get("coa_rig_control_uuid") == control_uuid
        and obj.get("coa_rig_artifact_role") == "name_text"
    )


def build_graph(armature, target, names):
    activate_armature(armature)
    result = bpy.ops.coa_tools2.add_rig_control(
        "EXEC_DEFAULT",
        label="Copy-safe Graph",
        control_type="POINT_2D_RECT",
        rectangle_mode="GRAPH",
        graph_interpolation="NAMED_GRAPH",
        graph_points=len(names),
        width=4.0,
        height=2.5,
        create_initial_binding=False,
    )
    assert result == {"FINISHED"}, result
    control = armature.coa_tools2_rig.rig_controls[-1]
    control.live_preview = False
    positions = ((0.08, 0.12), (0.86, 0.18), (0.72, 0.88))
    for index, point in enumerate(control.state_points):
        point.label = names[index]
        point.graph_position = positions[index]
        point.target_object = target
        point.target_name = names[index]
        point.is_empty = False
        point.enabled = True
    control.state_points[0].fallback_state_uuid = control.state_points[1].state_uuid
    control.state_points[1].fallback_state_uuid = control.state_points[2].state_uuid
    control.state_points[2].fallback_state_uuid = control.state_points[1].state_uuid
    result = bpy.ops.coa_tools2.update_rig_control()
    assert result == {"FINISHED"}, result
    return control, positions


def duplicate_character(armature, target):
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    duplicate = armature.copy()
    duplicate.data = armature.data.copy()
    duplicate.name = "Phase10GraphRigCopy"
    bpy.context.scene.collection.objects.link(duplicate)

    duplicate_target = target.copy()
    duplicate_target.data = target.data.copy()
    duplicate_target.name = "Phase10GraphTargetCopy"
    bpy.context.scene.collection.objects.link(duplicate_target)
    duplicate_target.parent = duplicate
    assert duplicate_target.data.shape_keys != target.data.shape_keys

    duplicate_control = duplicate.coa_tools2_rig.rig_controls[0]
    duplicate_control.live_preview = False
    for point in duplicate_control.state_points:
        point.target_object = duplicate_target
    return duplicate, duplicate_target


def assert_fork(armature, duplicate, target, duplicate_target, original):
    control = armature.coa_tools2_rig.rig_controls[0]
    copied = duplicate.coa_tools2_rig.rig_controls[0]
    assert armature.coa_tools2_rig.rig_instance_id == original["instance"]
    assert control.control_uuid == original["control"]
    assert tuple(point.state_uuid for point in control.state_points) == original["states"]
    assert control.base_widget_uuid == original["base_widget"]
    assert control.tip_widget_uuid == original["tip_widget"]
    assert driver_snapshot(target) == original["drivers"]

    assert duplicate.coa_tools2_rig.rig_instance_id != original["instance"]
    assert copied.control_uuid != original["control"]
    assert set(point.state_uuid for point in copied.state_points).isdisjoint(original["states"])
    assert copied.base_widget_uuid != original["base_widget"]
    assert copied.tip_widget_uuid != original["tip_widget"]
    assert widget_objects(copied.base_widget_uuid)
    assert widget_objects(copied.tip_widget_uuid)
    assert {obj.name for obj in widget_objects(copied.base_widget_uuid)}.isdisjoint(
        obj.name for obj in widget_objects(original["base_widget"])
    )
    assert {obj.name for obj in widget_objects(copied.tip_widget_uuid)}.isdisjoint(
        obj.name for obj in widget_objects(original["tip_widget"])
    )
    assert duplicate.data != armature.data

    for bone_name in (copied.display_bone, copied.control_bone, copied.name_bone):
        bone = duplicate.data.bones[bone_name]
        assert bone.get("coa_rig_instance_id") == duplicate.coa_tools2_rig.rig_instance_id
        assert bone.get("coa_rig_control_uuid") == copied.control_uuid
    assert name_object(original["control"]).parent == armature
    assert name_object(copied.control_uuid).parent == duplicate
    assert name_object(copied.control_uuid) != name_object(original["control"])
    assert rail_object(original["control"]).parent == armature
    assert rail_object(copied.control_uuid).parent == duplicate
    assert rail_object(copied.control_uuid) != rail_object(original["control"])

    from coa_tools2.rig_control.blender.artifacts import (
        limit_location_name,
        rail_constraint_name,
    )

    control_pose = duplicate.pose.bones[copied.control_bone]
    assert control_pose.custom_shape.get("coa_rig_widget_uuid") == copied.tip_widget_uuid
    assert duplicate.pose.bones[copied.display_bone].custom_shape.get(
        "coa_rig_widget_uuid"
    ) == copied.base_widget_uuid
    assert control_pose.constraints.get(limit_location_name(original["control"])) is None
    assert control_pose.constraints.get(rail_constraint_name(original["control"])) is None
    assert control_pose.constraints.get(limit_location_name(copied.control_uuid)) is not None
    assert control_pose.constraints.get(rail_constraint_name(copied.control_uuid)) is not None

    copied_drivers = driver_snapshot(duplicate_target)
    assert copied_drivers
    for expression, variables in copied_drivers.values():
        assert duplicate.coa_tools2_rig.rig_instance_id in expression
        assert copied.control_uuid in expression
        assert all(variable[1] == duplicate.name for variable in variables)
        assert all(variable[2] == copied.control_bone for variable in variables)


def main():
    if addon_utils.enable("coa_tools2", default_set=False, persistent=False) is None:
        raise RuntimeError("Could not enable coa_tools2.")
    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object
    armature.name = "Phase10GraphRigSource"
    names = ("Rest", "Smile", "Round")
    target = create_target("Phase10GraphTargetSource", names)
    target.parent = armature
    control, positions = build_graph(armature, target, names)
    original = {
        "instance": str(armature.coa_tools2_rig.rig_instance_id),
        "control": str(control.control_uuid),
        "states": tuple(str(point.state_uuid) for point in control.state_points),
        "base_widget": str(control.base_widget_uuid),
        "tip_widget": str(control.tip_widget_uuid),
        "drivers": driver_snapshot(target),
        "values": tuple(
            float(target.data.shape_keys.key_blocks[name].value) for name in names
        ),
    }

    duplicate, duplicate_target = duplicate_character(armature, target)
    activate_armature(duplicate)
    duplicate.coa_tools2_rig.rig_controls_index = 0
    result = bpy.ops.coa_tools2.update_rig_control()
    assert result == {"FINISHED"}, result
    assert_fork(armature, duplicate, target, duplicate_target, original)

    copied = duplicate.coa_tools2_rig.rig_controls[0]
    copied_uuid = str(copied.control_uuid)
    copied_states = tuple(str(point.state_uuid) for point in copied.state_points)
    copied_instance = str(duplicate.coa_tools2_rig.rig_instance_id)
    handle = duplicate.pose.bones[copied.control_bone]
    handle.location.x = positions[1][0] * copied.width
    handle.location.y = positions[1][1] * copied.height
    update_scene()
    copied_keys = duplicate_target.data.shape_keys.key_blocks
    source_keys = target.data.shape_keys.key_blocks
    assert copied_keys["Smile"].value > 0.99
    assert tuple(float(source_keys[name].value) for name in names) == original["values"]

    temporary = tempfile.TemporaryDirectory(prefix="coa-rig-graph-copy-")
    blend_path = Path(temporary.name) / "graph-copy.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    armature = bpy.data.objects["Phase10GraphRigSource"]
    duplicate = bpy.data.objects["Phase10GraphRigCopy"]
    target = bpy.data.objects["Phase10GraphTargetSource"]
    duplicate_target = bpy.data.objects["Phase10GraphTargetCopy"]
    copied = duplicate.coa_tools2_rig.rig_controls[0]
    assert duplicate.coa_tools2_rig.rig_instance_id == copied_instance
    assert copied.control_uuid == copied_uuid
    assert tuple(point.state_uuid for point in copied.state_points) == copied_states
    assert_fork(armature, duplicate, target, duplicate_target, original)

    handle = duplicate.pose.bones[copied.control_bone]
    handle.location.x = positions[2][0] * copied.width
    handle.location.y = positions[2][1] * copied.height
    update_scene()
    assert duplicate_target.data.shape_keys.key_blocks["Round"].value > 0.99
    assert tuple(
        float(target.data.shape_keys.key_blocks[name].value) for name in names
    ) == original["values"]

    addon_utils.disable("coa_tools2", default_set=False)
    temporary.cleanup()
    print("COA rig Phase 10 Graph duplicate isolation test OK.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"Rig Phase 10 Graph duplicate test failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise
