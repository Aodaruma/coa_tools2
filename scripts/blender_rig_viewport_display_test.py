#!/usr/bin/env python3
"""Headless regression for reversible, ownership-scoped animator display."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile

import bpy


def _color(color):
    return (
        color.palette,
        tuple(color.custom.normal),
        tuple(color.custom.select),
        tuple(color.custom.active),
    )


def _display(armature, name):
    bone = armature.data.bones[name]
    pose = armature.pose.bones[name]
    return (bone.hide, _color(bone.color), _color(pose.color))


def main():
    import coa_tools2
    from coa_tools2.rig_control.blender.viewport_display import (
        apply_animator_display,
        has_animator_display,
        restore_animator_display,
    )

    coa_tools2.register()
    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object
    armature.name = "AnimatorDisplayValidation"
    rig = armature.coa_tools2_rig
    rig.rig_instance_id = "display-validation-instance"
    component = rig.rig_components.add()
    component.component_uuid = "display-validation-component"
    control = rig.rig_controls.add()
    control.control_uuid = "display-validation-state"
    roles = {
        "primary": "semantic:stage:control_bone",
        "fk": "semantic:stage:fk_control:0",
        "spline": "semantic:stage:spline_control:0",
        "point": "semantic:stage:bbone_point:start",
        "handle": "semantic:stage:bbone_handle:out",
        "pole": "semantic:stage:pole_control",
        "mechanism": "semantic:stage:mechanism_bone:0",
        "source": "semantic:stage:source_bone:0",
    }
    names = (*roles, "state_tip", "state_base", "state_name", "user", "foreign")
    bpy.ops.object.mode_set(mode="EDIT")
    for index, name in enumerate(names):
        bone = armature.data.edit_bones.new(name)
        bone.head = (index, 0, 0)
        bone.tail = (index, 0, 1)
    bpy.ops.object.mode_set(mode="POSE")
    for name in names:
        bone = armature.data.bones[name]
        bone.color.palette = "THEME04"
        pose = armature.pose.bones[name]
        pose.color.palette = "CUSTOM"
        pose.color.custom.normal = (0.21, 0.34, 0.47)
        pose.location = (0.1, 0.2, 0.3)
        if name == "user":
            continue
        bone["coa_rig_instance_id"] = rig.rig_instance_id
        bone["coa_rig_managed"] = name != "source"
        if name in roles:
            bone["coa_rig_component_uuid"] = component.component_uuid
            bone["coa_rig_component_role"] = roles[name]
        else:
            bone["coa_rig_control_uuid"] = control.control_uuid
            bone["coa_rig_artifact_role"] = {
                "state_tip": "control_bone",
                "state_base": "display_bone",
                "state_name": "name_bone",
                "foreign": "control_bone",
            }[name]
        if name == "foreign":
            bone["coa_rig_instance_id"] = "another-rig"
    armature.data.bones["primary"].hide = True
    armature.data.show_names = True
    armature.data.show_bone_colors = False
    before = {name: _display(armature, name) for name in names}
    transforms = {
        name: tuple(armature.pose.bones[name].location) for name in names
    }
    assert apply_animator_display(armature) == 10
    assert has_animator_display(armature)
    assert not armature.data.show_names and armature.data.show_bone_colors
    for name in ("primary", "fk", "spline", "point", "handle", "pole", "state_tip", "state_base"):
        assert not armature.data.bones[name].hide, name
        assert armature.pose.bones[name].color.palette == "CUSTOM"
        assert max(armature.pose.bones[name].color.custom.normal) >= 0.79
    for name in ("mechanism", "state_name"):
        assert armature.data.bones[name].hide, name
    for name in ("source", "user", "foreign"):
        assert _display(armature, name) == before[name], name
    assert all(tuple(armature.pose.bones[name].location) == transforms[name] for name in names)
    assert _color(armature.pose.bones["point"].color) != _color(armature.pose.bones["handle"].color)

    # Applying again must retain the original display, including a hidden control.
    armature.data.bones["primary"].name = "renamed_primary"
    assert apply_animator_display(armature) == 10
    with tempfile.TemporaryDirectory(prefix="coa_display_validation_") as directory:
        blend_path = str(Path(directory) / "display_validation.blend")
        bpy.ops.wm.save_as_mainfile(filepath=blend_path)
        bpy.ops.wm.open_mainfile(filepath=blend_path)
        armature = bpy.data.objects["AnimatorDisplayValidation"]
        assert has_animator_display(armature)
        assert restore_animator_display(armature) == 10
    assert not has_animator_display(armature)
    assert armature.data.show_names and not armature.data.show_bone_colors
    for original_name in names:
        current_name = "renamed_primary" if original_name == "primary" else original_name
        assert _display(armature, current_name) == before[original_name], original_name
    assert restore_animator_display(armature) == 0

    # Shared armature data would affect another object; decline before mutation.
    other = armature.copy()
    try:
        apply_animator_display(armature)
    except ValueError as error:
        assert "single-user" in str(error)
    else:
        raise AssertionError("Shared armature data must not be modified")
    assert not has_animator_display(armature)
    bpy.data.objects.remove(other)
    assert bpy.ops.coa_tools2.apply_animator_display() == {"FINISHED"}
    assert bpy.ops.coa_tools2.restore_animator_display() == {"FINISHED"}
    print("RIG_VIEWPORT_DISPLAY_OK")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
