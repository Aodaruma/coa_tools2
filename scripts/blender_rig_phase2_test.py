#!/usr/bin/env python3
"""Background Blender integration test for Phase 2 bindings and repair."""

from __future__ import annotations

import sys

import addon_utils
import bpy


def update_scene():
    bpy.context.view_layer.update()
    bpy.context.scene.frame_set(bpy.context.scene.frame_current)
    bpy.context.view_layer.update()


def main():
    if addon_utils.enable("coa_tools2", default_set=False, persistent=False) is None:
        raise RuntimeError("Could not enable coa_tools2.")

    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object

    bpy.ops.mesh.primitive_plane_add(size=2.0)
    mesh_object = bpy.context.active_object
    mesh_object.name = "Phase2Face"
    mesh_object.parent = armature
    mesh_object.shape_key_add(name="Basis")
    smile = mesh_object.shape_key_add(name="Smile")
    blink = mesh_object.shape_key_add(name="Blink")

    result = bpy.ops.coa_tools2.add_rig_control(
        "EXEC_DEFAULT",
        label="Face",
        axis="X",
        width=4.0,
        create_initial_binding=True,
        target_object_name=mesh_object.name,
        shape_key="Smile",
    )
    assert result == {"FINISHED"}, result
    control = armature.coa_tools2_rig.rig_controls[0]

    result = bpy.ops.coa_tools2.add_rig_binding(
        "EXEC_DEFAULT",
        source_component="X",
        target_kind="SHAPE_KEY_VALUE",
        target_object_name=mesh_object.name,
        target_name="Blink",
        output_min=1.0,
        output_max=0.0,
    )
    assert result == {"FINISHED"}, result

    target_bone = armature.pose.bones[control.display_bone]
    constraint = target_bone.constraints.new("LIMIT_SCALE")
    constraint.name = "Phase2 Influence"
    result = bpy.ops.coa_tools2.add_rig_binding(
        "EXEC_DEFAULT",
        source_component="X",
        target_kind="CONSTRAINT_INFLUENCE",
        target_object_name=armature.name,
        target_bone=target_bone.name,
        target_name=constraint.name,
    )
    assert result == {"FINISHED"}, result
    assert len(control.bindings) == 3

    try:
        bpy.ops.coa_tools2.add_rig_binding(
            "EXEC_DEFAULT",
            source_component="X",
            target_kind="SHAPE_KEY_VALUE",
            target_object_name=mesh_object.name,
            target_name="Blink",
        )
    except RuntimeError as exc:
        assert "already has a rig binding" in str(exc)
    else:
        raise AssertionError("Duplicate binding was not rejected.")
    assert len(control.bindings) == 3

    handle = armature.pose.bones[control.control_bone]
    handle.location.x = 0.0
    update_scene()
    assert abs(smile.value - 0.0) < 1e-5
    assert abs(blink.value - 1.0) < 1e-5
    assert abs(constraint.influence - 0.0) < 1e-5
    handle.location.x = 4.0
    update_scene()
    assert abs(smile.value - 1.0) < 1e-5
    assert abs(blink.value - 0.0) < 1e-5
    assert abs(constraint.influence - 1.0) < 1e-5

    result = bpy.ops.coa_tools2.validate_rig()
    assert result == {"FINISHED"}
    assert len(armature.coa_tools2_rig.rig_validation_issues) == 0

    base_widget = armature.pose.bones[control.display_bone].custom_shape
    bpy.data.objects.remove(base_widget, do_unlink=True)
    bpy.ops.coa_tools2.validate_rig()
    codes = {issue.code for issue in armature.coa_tools2_rig.rig_validation_issues}
    assert "artifact.missing_base_widget" in codes, codes

    result = bpy.ops.coa_tools2.repair_rig()
    assert result == {"FINISHED"}
    assert len(armature.coa_tools2_rig.rig_validation_issues) == 0
    assert armature.pose.bones[control.display_bone].custom_shape is not None

    counts_before = (len(armature.data.bones), len(bpy.data.objects))
    bpy.ops.coa_tools2.repair_rig()
    counts_after = (len(armature.data.bones), len(bpy.data.objects))
    assert counts_after == counts_before, (counts_before, counts_after)

    addon_utils.disable("coa_tools2", default_set=False)
    print("COA rig Phase 2 test OK.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Rig Phase 2 test failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
