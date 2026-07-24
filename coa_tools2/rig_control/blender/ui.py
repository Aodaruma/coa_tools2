"""Viewport UI for rig controls."""

from __future__ import annotations

import bpy

from ... import functions
from .properties import get_rig_data


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


class COATOOLS2_UL_RigBindings(bpy.types.UIList):
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
        target = item.target_object.name if item.target_object else "Missing"
        suffix = item.target_name or "Missing"
        layout.label(text=f"{target} / {suffix}", icon="DRIVER")


class COATOOLS2_UL_RigStatePoints(bpy.types.UIList):
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
        coordinate = (
            f"{item.column + 1}"
            if item.row == 0 and getattr(_data, "state_rows", 1) == 1
            else f"{item.column + 1}, {item.row + 1}"
        )
        if item.is_empty:
            target = "Empty"
            icon = "RADIOBUT_OFF"
        elif item.target_object and item.target_name:
            target = f"{item.target_object.name} / {item.target_name}"
            icon = "SHAPEKEY_DATA"
        else:
            target = "Unassigned"
            icon = "QUESTION"
        layout.label(text=f"[{coordinate}] {target}", icon=icon)


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
        rig_data = get_rig_data(armature)
        row = layout.row(align=True)
        row.operator("coa_tools2.add_rig_control", icon="ADD")
        row.operator("coa_tools2.validate_rig", text="", icon="CHECKMARK")
        row.operator("coa_tools2.repair_rig", text="", icon="FILE_REFRESH")

        controls = rig_data.rig_controls
        if not controls:
            layout.label(text="No rig controls yet.", icon="INFO")
            return

        layout.template_list(
            "COATOOLS2_UL_RigControls",
            "",
            rig_data,
            "rig_controls",
            rig_data,
            "rig_controls_index",
            rows=min(5, max(2, len(controls))),
        )
        index = min(rig_data.rig_controls_index, len(controls) - 1)
        control = controls[index]
        box = layout.box()
        box.prop(control, "label")
        box.prop(control, "control_type")
        if control.control_type == "SLIDER_1D":
            box.prop(control, "axis")
            box.prop(control, "width")
        elif control.control_type == "POINT_2D_RECT":
            row = box.row(align=True)
            row.prop(control, "width")
            row.prop(control, "height")
            if control.state_mode == "MATRIX_2D":
                box.label(text="Rectangle Mode: State Matrix", icon="MESH_GRID")
            else:
                box.prop(control, "rectangle_mode")
            if (
                control.state_mode != "MATRIX_2D"
                and control.rectangle_mode == "GRID"
            ):
                row = box.row(align=True)
                row.prop(control, "grid_columns")
                row.prop(control, "grid_rows")
        elif control.control_type == "POINT_2D_CIRCLE":
            box.prop(control, "radius")
        elif control.control_type == "DIAL":
            box.prop(control, "radius")
            row = box.row(align=True)
            row.prop(control, "angle_min")
            row.prop(control, "angle_max")
        widget_box = box.box()
        widget_box.label(text="Widget Style")
        row = widget_box.row(align=True)
        row.prop(control, "tip_radius")
        row.prop(control, "node_radius")
        widget_box.prop(control, "bar_width")
        widget_box.prop(control, "widget_backend")
        box.label(text=f"Control Bone: {control.control_bone}")
        box.operator("coa_tools2.update_rig_control", icon="FILE_REFRESH")
        if control.needs_rebuild:
            box.label(text="Definition changed; rebuild required.", icon="ERROR")

        bindings_box = layout.box()
        bindings_box.label(text="Bindings")
        if not control.bindings:
            bindings_box.label(
                text="No bindings. Add targets with the + button.",
                icon="INFO",
            )
        row = bindings_box.row()
        row.template_list(
            "COATOOLS2_UL_RigBindings",
            "",
            control,
            "bindings",
            control,
            "bindings_index",
            rows=min(5, max(2, len(control.bindings))),
        )
        column = row.column(align=True)
        column.operator("coa_tools2.add_rig_binding", text="", icon="ADD")
        column.operator("coa_tools2.remove_rig_binding", text="", icon="REMOVE")

        if control.control_type in {"SLIDER_1D", "POINT_2D_RECT"}:
            states_box = layout.box()
            states_box.label(text="Continuous States", icon="SHAPEKEY_DATA")
            if control.state_mode == "NONE":
                states_box.label(
                    text="No state grid. Ordinary bindings still work.",
                    icon="INFO",
                )
                states_box.operator(
                    "coa_tools2.setup_rig_states",
                    text="Set Up State Grid",
                    icon="MESH_GRID",
                )
            else:
                dimensions = (
                    f"{control.state_columns} points"
                    if control.state_mode == "LINEAR_1D"
                    else f"{control.state_columns} x {control.state_rows}"
                )
                row = states_box.row(align=True)
                row.label(text=dimensions)
                row.operator(
                    "coa_tools2.setup_rig_states",
                    text="Resize",
                    icon="MESH_GRID",
                )
                if control.state_mode == "MATRIX_2D":
                    preset_row = states_box.row(align=True)
                    for label, preset in (
                        ("2x2", "2X2"),
                        ("3x2", "3X2"),
                        ("2x4", "2X4"),
                    ):
                        operator = preset_row.operator(
                            "coa_tools2.setup_rig_states",
                            text=label,
                        )
                        operator.preset = preset
                states_box.prop(control, "state_mix_policy")
                states_box.template_list(
                    "COATOOLS2_UL_RigStatePoints",
                    "",
                    control,
                    "state_points",
                    control,
                    "state_points_index",
                    rows=min(8, max(2, len(control.state_points))),
                )
                row = states_box.row(align=True)
                row.operator(
                    "coa_tools2.assign_rig_state_point",
                    text="Assign",
                    icon="ADD",
                )
                row.operator(
                    "coa_tools2.clear_rig_state_point",
                    text="Empty",
                    icon="X",
                )
                row.operator(
                    "coa_tools2.snap_rig_state_point",
                    text="Snap",
                    icon="SNAP_ON",
                )

        issues = rig_data.rig_validation_issues
        if issues:
            issue_box = layout.box()
            issue_box.label(text=f"Validation Issues ({len(issues)})", icon="ERROR")
            for issue in issues[:6]:
                icon = "ERROR" if issue.severity == "ERROR" else "INFO"
                issue_box.label(text=issue.message, icon=icon)


CLASSES = (
    COATOOLS2_UL_RigControls,
    COATOOLS2_UL_RigBindings,
    COATOOLS2_UL_RigStatePoints,
    COATOOLS2_PT_RigControls,
)
