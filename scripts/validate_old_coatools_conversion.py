#!/usr/bin/env python3
"""Blender validation for old COA Tools data migration."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import bpy


ROOT = Path(__file__).resolve().parents[1]


def reset_scene() -> None:
    bpy.ops.object.mode_set(mode="OBJECT") if bpy.ops.object.mode_set.poll() else None
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh)
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action)


def register_addon():
    sys.path.insert(0, str(ROOT))
    addon = importlib.import_module("coa_tools2")
    addon.register()
    return addon


def unregister_addon(addon) -> None:
    try:
        addon.unregister()
    except Exception:
        pass


def iter_action_fcurves(action):
    legacy_fcurves = getattr(action, "fcurves", None)
    if legacy_fcurves is not None:
        yield from legacy_fcurves
        return

    action_slots = list(getattr(action, "slots", []))
    for layer in getattr(action, "layers", []):
        for strip in getattr(layer, "strips", []):
            for action_slot in action_slots:
                try:
                    channelbag = strip.channelbag(action_slot)
                except Exception:
                    continue
                if channelbag is not None:
                    yield from getattr(channelbag, "fcurves", [])


def make_mesh(name: str, x_offset: float) -> bpy.types.Mesh:
    mesh = bpy.data.meshes.new(name)
    verts = [
        (x_offset - 0.5, 0.0, -0.5),
        (x_offset + 0.5, 0.0, -0.5),
        (x_offset + 0.5, 0.0, 0.5),
        (x_offset - 0.5, 0.0, 0.5),
    ]
    mesh.from_pydata(verts, [], [(0, 1, 2, 3)])
    mesh.update()
    return mesh


def build_old_scene(addon):
    bpy.ops.object.armature_add()
    armature = bpy.context.object
    armature.name = "SpriteArmature"
    armature["coa_tools"] = {
        "sprite_object": True,
        "show_children": True,
    }
    armature.data.bones[0]["coa_tools"] = {"favorite": True}

    mesh_a = make_mesh("Slot_A", 0.0)
    mesh_b = make_mesh("Slot_B", 1.0)
    mesh_a["coa_tools"] = {"hide_base_sprite": True}
    mesh_b["coa_tools"] = {"hide_base_sprite": False}

    slot_obj = bpy.data.objects.new("SlotSprite", mesh_a)
    bpy.context.collection.objects.link(slot_obj)
    slot_obj.parent = armature
    slot_obj["coa_tools"] = {
        "type": 2,
        "slot_index": 1,
        "slot_reset_index": 1,
        "slot_show": True,
        "alpha": 0.5,
        "edit_mesh": True,
        "edit_armature": True,
        "edit_weights": True,
        "edit_shapekey": True,
        "edit_mode": 3,
        "slot": [
            {"mesh": "Slot_A", "name": "Slot_A", "index": 0, "active": False},
            {"mesh": "Slot_B", "name": "Slot_B", "index": 1, "active": True},
        ],
    }

    slot_obj.vertex_groups.new(name="Bone")
    slot_obj.vertex_groups.new(name="coa_base_sprite")
    modifier = slot_obj.modifiers.new("Armature", "ARMATURE")
    modifier.object = armature

    bpy.context.scene["coa_tools"] = {"view": 1}
    slot_obj.keyframe_insert(data_path='["coa_tools"]["slot_index"]', frame=1)
    driver = slot_obj.driver_add('["coa_tools"]["alpha"]').driver
    driver.expression = "0.75"

    return armature, slot_obj, mesh_a, mesh_b


def assert_no_old_data(armature, slot_obj, mesh_a, mesh_b) -> None:
    assert "coa_tools" not in armature
    assert "coa_tools" not in slot_obj
    assert "coa_tools" not in mesh_a
    assert "coa_tools" not in mesh_b
    assert "coa_tools" not in bpy.context.scene
    assert "coa_tools" not in armature.data.bones[0]


def validate_conversion(armature, slot_obj, mesh_a, mesh_b) -> None:
    assert slot_obj.parent == armature
    assert slot_obj.coa_tools2.type == "SLOT"
    assert len(slot_obj.coa_tools2.slot) == 2
    assert slot_obj.coa_tools2.slot_index == 1
    assert slot_obj.coa_tools2.slot_reset_index == 1
    assert slot_obj.coa_tools2.slot[0].mesh == mesh_a
    assert slot_obj.coa_tools2.slot[1].mesh == mesh_b
    assert not slot_obj.coa_tools2.slot[0].active
    assert slot_obj.coa_tools2.slot[1].active
    assert slot_obj.data == mesh_b
    assert slot_obj.modifiers["Armature"].object == armature
    assert "Bone" in slot_obj.vertex_groups
    assert "coa_base_sprite" in slot_obj.vertex_groups

    assert mesh_a.coa_tools2.hide_base_sprite
    assert not mesh_b.coa_tools2.hide_base_sprite
    assert armature.coa_tools2.show_children
    assert "sprite_object" in armature.coa_tools2
    assert armature.data.bones[0].coa_tools2.favorite
    assert bpy.context.scene.coa_tools2.view == "2D"

    for action in bpy.data.actions:
        for fcurve in iter_action_fcurves(action):
            assert "coa_tools." not in fcurve.data_path
            assert "coa_tools2." in fcurve.data_path

    for fcurve in slot_obj.animation_data.drivers:
        assert "coa_tools." not in fcurve.data_path
        assert "coa_tools2." in fcurve.data_path

    slot_obj.coa_tools2.slot_index = 0
    addon = sys.modules["coa_tools2"]
    addon.functions.change_slot_mesh_data(bpy.context, slot_obj)
    assert slot_obj.data == mesh_a
    assert slot_obj.parent == armature
    assert slot_obj.modifiers["Armature"].object == armature
    assert "coa_base_sprite" in slot_obj.vertex_groups

    bpy.context.view_layer.objects.active = slot_obj
    slot_obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    import bmesh

    bm = bmesh.from_edit_mesh(slot_obj.data)
    assert len(bm.verts) > 0
    bpy.ops.object.mode_set(mode="OBJECT")


def main() -> int:
    reset_scene()
    addon = register_addon()
    try:
        armature, slot_obj, mesh_a, mesh_b = build_old_scene(addon)

        addon.check_for_old_coatools(None)
        assert bpy.context.scene.coa_tools2.old_coatools_found

        result = bpy.ops.coa_tools2.convert_old_version_coatools()
        assert result == {"FINISHED"}
        validate_conversion(armature, slot_obj, mesh_a, mesh_b)
        assert_no_old_data(armature, slot_obj, mesh_a, mesh_b)
        print("Old COA Tools conversion validation OK.")
        return 0
    finally:
        unregister_addon(addon)


if __name__ == "__main__":
    raise SystemExit(main())
