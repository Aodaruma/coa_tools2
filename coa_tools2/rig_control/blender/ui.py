"""Viewport UI for rig controls."""

from __future__ import annotations

import bpy

from ... import functions


class COATOOLS2_UL_RigControls(bpy.types.UIList):
    def draw_item(
        self,
        _context,
        layout,
        _data,
        item,
        _icon,
        _active_data,
        _active_propname,
        _index,
    ):
        layout.label(text=item.label, icon="BONE_DATA")


class COATOOLS2_PT_RigControls(bpy.types.Panel):
    bl_idname = "COATOOLS2_PT_rig_controls"
    bl_label = "Rig Controls"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "COA Tools2"

    @classmethod
    def poll(cls, context):
        sprite_object = functions.get_sprite_object(context.active_object)
        return sprite_object is not None and sprite_object.type == "ARMATURE"

    def draw(self, context):
        layout = self.layout
        armature = functions.get_sprite_object(context.active_object)
        row = layout.row()
        row.operator("coa_tools2.add_rig_control", icon="ADD")

        controls = armature.coa_tools2.rig_controls
        if not controls:
            layout.label(text="No rig controls yet.", icon="INFO")
            return

        layout.template_list(
            "COATOOLS2_UL_RigControls",
            "",
            armature.coa_tools2,
            "rig_controls",
            armature.coa_tools2,
            "rig_controls_index",
            rows=min(5, max(2, len(controls))),
        )
        index = min(armature.coa_tools2.rig_controls_index, len(controls) - 1)
        control = controls[index]
        box = layout.box()
        box.prop(control, "label")
        box.prop(control, "axis")
        box.prop(control, "width")
        box.label(text=f"Control Bone: {control.control_bone}")
        if control.bindings:
            binding = control.bindings[0]
            target = binding.target_object.name if binding.target_object else "Missing"
            box.label(text=f"Target: {target} / {binding.target_name}")
        if control.needs_rebuild:
            box.label(text="Definition changed; rebuild required.", icon="ERROR")


CLASSES = (
    COATOOLS2_UL_RigControls,
    COATOOLS2_PT_RigControls,
)
