"""Viewport UI for rig controls."""

from __future__ import annotations

import bpy

from ... import functions
from .properties import get_rig_data


def sync_control_index_from_active_bone(armature, rig_data):
    """Select the Rig Control owned by the active Tip, Base, or Name bone."""

    if rig_data is None:
        return False
    active_bone = armature.data.bones.active
    if active_bone is None:
        return False
    if active_bone.get("coa_rig_artifact_role") not in {
        "control_bone",
        "display_bone",
        "name_bone",
    }:
        return False
    control_uuid = active_bone.get("coa_rig_control_uuid", "")
    for index, control in enumerate(rig_data.rig_controls):
        if control.control_uuid == control_uuid:
            rig_data.rig_controls_index = index
            return True
    return False


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
        layout.label(
            text=f"{item.source_component} → {target} / {suffix}",
            icon="DRIVER",
        )


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


class COATOOLS2_UL_RigStateCells(bpy.types.UIList):
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
        operator = layout.operator(
            "coa_tools2.toggle_rig_state_cell",
            text=(
                f"Cell C{item.column + 1}-C{item.column + 2} / "
                f"R{item.row + 1}-R{item.row + 2}"
            ),
            depress=item.mix_enabled,
        )
        operator.cell_uuid = item.cell_uuid


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
        elif control.control_type == "POINT_2D_RECT":
            if control.state_mode == "MATRIX_2D":
                box.label(text="Rectangle Mode: State Matrix", icon="MESH_GRID")
            else:
                box.prop(control, "rectangle_mode")
        elif control.control_type == "DIAL":
            row = box.row(align=True)
            row.prop(control, "angle_min")
            row.prop(control, "angle_max")

        display_header, display_body = box.panel(
            "coa_tools2_rig_control_size_display",
            default_closed=True,
        )
        display_header.label(text="Size & Display", icon="PREFERENCES")
        if display_body:
            if control.control_type == "SLIDER_1D":
                display_body.prop(control, "width")
            elif control.control_type == "POINT_2D_RECT":
                # Equal-width fields keep Matrix dimensions easy to compare,
                # while still allowing the rectangular reference designs.
                row = display_body.row(align=True)
                row.prop(control, "width")
                row.prop(control, "height")
                if (
                    control.state_mode != "MATRIX_2D"
                    and control.rectangle_mode == "GRID"
                ):
                    row = display_body.row(align=True)
                    row.prop(control, "grid_columns")
                    row.prop(control, "grid_rows")
            else:
                display_body.prop(control, "radius")

            display_body.label(text="Widget")
            row = display_body.row(align=True)
            row.prop(control, "tip_radius")
            row.prop(control, "node_radius")
            display_body.prop(control, "bar_width")
            display_body.prop(control, "widget_backend")
            display_body.separator()
            display_body.prop(control, "show_name")
            if control.show_name:
                row = display_body.row(align=True)
                row.prop(control, "name_size")
                row.prop(control, "name_offset")

        preview_row = box.row(align=True)
        preview_row.prop(
            control,
            "live_preview",
            text="Live Preview",
            toggle=True,
            icon="HIDE_OFF" if control.live_preview else "HIDE_ON",
        )
        if control.auto_rebuild_error:
            box.label(text="Automatic update failed.", icon="ERROR")
            box.label(text=control.auto_rebuild_error)
            box.operator(
                "coa_tools2.update_rig_control",
                text="Rebuild Now",
                icon="FILE_REFRESH",
            )
        elif control.needs_rebuild:
            if control.live_preview:
                box.label(text="Updating automatically…", icon="FILE_REFRESH")
            else:
                box.label(text="Changes pending.", icon="INFO")
                box.operator(
                    "coa_tools2.update_rig_control",
                    text="Apply Changes",
                    icon="CHECKMARK",
                )

        advanced_header, advanced_body = box.panel(
            "coa_tools2_rig_control_advanced",
            default_closed=True,
        )
        advanced_header.label(text="Generated Rig", icon="BONE_DATA")
        if advanced_body:
            advanced_body.label(text=f"Control Bone: {control.control_bone}")
            advanced_body.label(text=f"Base Bone: {control.display_bone}")
            advanced_body.label(text=f"Name Bone: {control.name_bone or 'Pending'}")
            advanced_body.operator(
                "coa_tools2.update_rig_control",
                text="Rebuild Now",
                icon="FILE_REFRESH",
            )

        outputs_box = layout.box()
        outputs_box.label(text="Behavior & Outputs", icon="DRIVER")
        bindings_box = outputs_box.box()
        bindings_box.label(text="Direct Bindings (Optional)")
        bindings_box.label(text="Maps X / Y / Angle to one property.")
        if not control.bindings:
            bindings_box.label(
                text="No direct outputs. Add one with the + button.",
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
            states_box = outputs_box.box()
            states_box.label(text="State Targets", icon="SHAPEKEY_DATA")
            if control.state_mode == "NONE":
                states_box.label(
                    text="Interpolates assigned Shape Keys.",
                    icon="INFO",
                )
                states_box.label(
                    text="Optional; Direct Bindings still work.",
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
                if control.state_mode == "MATRIX_2D":
                    domain_box = states_box.box()
                    domain_box.label(text="Mix Domain", icon="MOD_SHRINKWRAP")
                    domain_box.label(
                        text="Controls where the handle may move."
                    )
                    domain_box.label(
                        text="Shape Key targets are assigned below."
                    )
                    preset_row = domain_box.row(align=True)
                    operator = preset_row.operator(
                        "coa_tools2.set_rig_state_mix_policy",
                        text="Full",
                        depress=control.state_mix_policy == "FULL",
                    )
                    operator.policy = "FULL"
                    operator = preset_row.operator(
                        "coa_tools2.set_rig_state_mix_policy",
                        text="Grid Only",
                        depress=control.state_mix_policy == "NO_MIX",
                    )
                    operator.policy = "NO_MIX"
                    if control.state_cells and len(control.state_cells) > 64:
                        domain_box.template_list(
                            "COATOOLS2_UL_RigStateCells",
                            "",
                            control,
                            "state_cells",
                            control,
                            "state_cells_index",
                            rows=8,
                        )
                    elif control.state_cells:
                        domain_box.label(
                            text="Allow Mix per four-point cell (top row first)"
                        )
                        cells_by_coordinate = {
                            (cell.column, cell.row): cell
                            for cell in control.state_cells
                        }
                        for row_index in reversed(
                            range(max(0, control.state_rows - 1))
                        ):
                            cell_row = domain_box.row(align=True)
                            cell_row.label(text=f"R{row_index + 1}")
                            for column_index in range(
                                max(0, control.state_columns - 1)
                            ):
                                cell = cells_by_coordinate.get(
                                    (column_index, row_index)
                                )
                                if cell is None:
                                    cell_row.label(text="?")
                                    continue
                                operator = cell_row.operator(
                                    "coa_tools2.toggle_rig_state_cell",
                                    text=f"C{column_index + 1}",
                                    depress=cell.mix_enabled,
                                )
                                operator.cell_uuid = cell.cell_uuid
                    else:
                        domain_box.label(
                            text="Update Rig Control to initialize matrix cells.",
                            icon="INFO",
                        )
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
    COATOOLS2_UL_RigStateCells,
    COATOOLS2_PT_RigControls,
)
