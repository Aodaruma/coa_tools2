"""Viewport UI for character posing rig components."""

from __future__ import annotations

import bpy

from ... import functions
from .properties import get_rig_data
from .selection import active_data_bone


_ARROW_SHAPES = {
    "ARROW_1D",
    "ARROW_2D",
    "CYLINDER_ARROW_1D",
    "SPHERE_ARROW_2D",
}
_SPATIAL_ARROW_SHAPES = {
    "CYLINDER_ARROW_1D",
    "SPHERE_ARROW_2D",
}
_WIDTH_HEIGHT_SHAPES = {
    "ARROW_1D",
    "ARROW_2D",
    "TOMBSTONE",
    "ELLIPSE",
    "TRIANGLE",
    "RECTANGLE",
    "DIAMOND",
}
_CORNER_SHAPES = {"TOMBSTONE", "TRIANGLE", "RECTANGLE", "DIAMOND"}
_RESOLUTION_SHAPES = {
    "CYLINDER_ARROW_1D",
    "SPHERE_ARROW_2D",
    "TOMBSTONE",
    "ELLIPSE",
    "TRIANGLE",
    "RECTANGLE",
    "DIAMOND",
    "SECTOR",
}


def _draw_presentation_status(
    layout,
    presentation,
    *,
    stage_uuid="",
    target_role="",
):
    if presentation.last_error:
        layout.label(text=presentation.last_error, icon="ERROR")
    if presentation.needs_rebuild:
        row = layout.row(align=True)
        row.label(text="Presentation changes pending.", icon="INFO")
        operator = row.operator(
            "coa_tools2.update_rig_presentation",
            text="Apply",
            icon="CHECKMARK",
        )
        operator.stage_uuid = stage_uuid
        operator.target_role = target_role


def draw_widget_presentation(
    layout,
    presentation,
    *,
    panel_id,
    title="Presentation Settings",
    default_closed=True,
    stage_uuid="",
    target_role="",
):
    """Draw one shape-aware, collapsible presentation editor."""

    header, body = layout.panel(panel_id, default_closed=default_closed)
    header.label(text=title, icon="BONE_DATA")
    header.prop(presentation, "live_preview", text="", icon="PLAY")
    if not body:
        return

    body.prop(presentation, "shape")
    shape = presentation.shape
    if shape == "NONE":
        body.label(text="No procedural custom shape is generated.", icon="INFO")
        _draw_presentation_status(
            body,
            presentation,
            stage_uuid=stage_uuid,
            target_role=target_role,
        )
        return
    body.prop(presentation, "wire_width")
    if shape == "CUSTOM_OBJECT":
        body.prop(presentation, "custom_object")
        if presentation.custom_object is None:
            body.label(text="Choose an existing custom-shape object.", icon="INFO")
        _draw_presentation_status(
            body,
            presentation,
            stage_uuid=stage_uuid,
            target_role=target_role,
        )
        return

    if shape in _WIDTH_HEIGHT_SHAPES:
        dimensions = body.row(align=True)
        dimensions.prop(presentation, "width")
        if shape != "ARROW_1D":
            dimensions.prop(presentation, "height")
    if shape in _CORNER_SHAPES:
        body.prop(presentation, "corner_radius")
    if shape in _ARROW_SHAPES:
        arrow = body.column(align=True)
        arrow.prop(presentation, "bar_width")
        row = arrow.row(align=True)
        row.prop(presentation, "head_length")
        row.prop(presentation, "head_width")
    if shape in _SPATIAL_ARROW_SHAPES:
        row = body.row(align=True)
        row.prop(presentation, "radius")
        row.prop(presentation, "arc_angle")
    if shape == "SECTOR":
        radii = body.row(align=True)
        radii.prop(presentation, "sector_inner_radius")
        radii.prop(presentation, "sector_outer_radius")
        angles = body.row(align=True)
        angles.prop(presentation, "sector_start_angle")
        angles.prop(presentation, "sector_sweep_angle")
    if shape in _RESOLUTION_SHAPES:
        body.prop(presentation, "segments")
    _draw_presentation_status(
        body,
        presentation,
        stage_uuid=stage_uuid,
        target_role=target_role,
    )


def sync_component_index_from_active_bone(armature, rig_data):
    if rig_data is None:
        return False
    active_bone = active_data_bone(armature)
    if active_bone is None:
        return False
    component_uuid = active_bone.get("coa_rig_component_uuid", "")
    if not component_uuid:
        return False
    for index, component in enumerate(rig_data.rig_components):
        if component.component_uuid == component_uuid:
            rig_data.rig_components_index = index
            if component.component_type == "SEMANTIC":
                role = str(active_bone.get("coa_rig_component_role", ""))
                parts = role.split(":", 2)
                if len(parts) >= 2 and parts[0] == "semantic":
                    stage_uuid = parts[1]
                    for stage_index, stage in enumerate(
                        component.semantic_stages
                    ):
                        if stage.stage_uuid == stage_uuid:
                            component.semantic_stages_index = stage_index
                            break
            return True
    return False


class COATOOLS2_UL_RigComponents(bpy.types.UIList):
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
        icon = "CONSTRAINT_BONE" if item.component_type == "LIMB_IK" else "BONE_DATA"
        layout.label(text=f"{item.label} · {item.component_type}", icon=icon)


class COATOOLS2_PT_RigComponents(bpy.types.Panel):
    bl_idname = "COATOOLS2_PT_rig_components"
    bl_label = "Character Rig"
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
        rig_data = get_rig_data(armature, migrate=False)
        row = layout.row(align=True)
        row.operator("coa_tools2.add_rig_component", icon="ADD")
        row.operator(
            "coa_tools2.add_semantic_rig",
            text="Character",
            icon="NODETREE",
        )
        row.operator(
            "coa_tools2.update_rig_component",
            text="",
            icon="FILE_REFRESH",
        )
        components = rig_data.rig_components
        if not components:
            layout.label(text="Select a bone chain in Pose Mode.", icon="INFO")
            layout.label(text="The active bone must be the chain end.")
            return
        layout.template_list(
            "COATOOLS2_UL_RigComponents",
            "",
            rig_data,
            "rig_components",
            rig_data,
            "rig_components_index",
            rows=min(5, max(2, len(components))),
        )
        index = min(rig_data.rig_components_index, len(components) - 1)
        component = components[index]
        box = layout.box()
        box.prop(component, "label")
        box.label(text=f"Type: {component.component_type}")
        mode_row = box.row()
        mode_row.enabled = not (
            component.compiled_deformation_mode or component.artifacts
        )
        mode_row.prop(component, "deformation_mode")
        box.label(text=f"Build: {component.build_mode}")
        if component.deformation_mode == "PARAMETRIC":
            info = box.box()
            info.label(text="Control Transform → Outputs", icon="SHAPEKEY_DATA")
            info.label(text="Source bones and flat artwork stay unchanged.")
        else:
            warning = box.box()
            warning.label(text="Legacy direct bone deformation", icon="ERROR")
            warning.label(text="Artwork rotates with source bones.")

        sources_header, sources_body = box.panel(
            "coa_tools2_component_sources",
            default_closed=True,
        )
        sources_header.label(text="Source Bones", icon="BONE_DATA")
        if sources_body:
            for source in component.source_bones:
                sources_body.label(text=source.bone_name)

        if (
            component.deformation_mode == "PARAMETRIC"
            or component.component_type == "LIMB_IK"
        ):
            orientation = box.box()
            orientation.label(text="Visual Control Frame", icon="ORIENTATION_LOCAL")
            orientation.prop(component, "orientation_mode")
            orientation.prop_search(
                component,
                "orientation_reference",
                armature.data,
                "bones",
                text="Reference",
            )
            if component.orientation_mode == "CUSTOM":
                orientation.prop(component, "orientation_euler")
            orientation.label(text="Local X/Y = art plane")
            orientation.label(text="Local Z = visual depth")

        if (
            component.deformation_mode == "DIRECT_BONES"
            and component.component_type == "LIMB_IK"
        ):
            solver = box.box()
            solver.label(text="IK")
            solver.prop(component, "ik_solver_mode")
            if component.ik_solver_mode == "PLANAR":
                solver.prop(component, "bend_axis")
            else:
                solver.prop(component, "use_bend_hint")
                if component.use_bend_hint:
                    solver.prop(component, "pole_distance")
            solver.prop(component, "end_rotation_mode")
            solver.prop(component, "use_stretch")

        if (
            component.deformation_mode == "PARAMETRIC"
            or component.component_type in {"ROOT", "LIMB_IK"}
        ):
            depth = box.box()
            depth.label(text="Movement")
            depth.prop(component, "allow_translation")
            depth.prop(component, "depth_mode")
            if component.depth_mode == "LIMITED":
                row = depth.row(align=True)
                row.prop(component, "depth_min")
                row.prop(component, "depth_max")
        box.prop(component, "allow_rotation")

        visual_header, visual_body = box.panel(
            "coa_tools2_component_visual",
            default_closed=True,
        )
        visual_header.label(text="Visual Settings", icon="HIDE_OFF")
        if visual_body:
            if component.component_type == "SEMANTIC":
                visual_body.label(
                    text="Select a stage below to edit its presentation.",
                    icon="INFO",
                )
            else:
                draw_widget_presentation(
                    visual_body,
                    component.presentation,
                    panel_id="coa_tools2_component_presentation",
                    default_closed=False,
                )
                if component.presentation.shape == "NONE":
                    visual_body.prop(
                        component,
                        "widget_size",
                        text="Legacy Size",
                    )
                    legacy = visual_body.row()
                    legacy.enabled = False
                    legacy.prop(component, "widget", text="Legacy Preset")

        if component.last_error:
            box.label(text=component.last_error, icon="ERROR")
        if component.needs_rebuild:
            box.label(text="Structural changes pending.", icon="INFO")
            box.operator(
                "coa_tools2.update_rig_component",
                text="Apply Changes",
                icon="CHECKMARK",
            )
        else:
            box.operator(
                "coa_tools2.update_rig_component",
                text="Rebuild Component",
                icon="FILE_REFRESH",
            )

        if (
            component.deformation_mode == "PARAMETRIC"
            and component.component_type != "SEMANTIC"
        ):
            outputs = layout.box()
            outputs.label(text="Shape Key & Property Outputs", icon="DRIVER")
            if not component.bindings:
                outputs.label(
                    text="The control is ready; add outputs when artwork is prepared.",
                    icon="INFO",
                )
            row = outputs.row()
            row.template_list(
                "COATOOLS2_UL_RigBindings",
                "",
                component,
                "bindings",
                component,
                "bindings_index",
                rows=min(5, max(2, len(component.bindings))),
            )
            column = row.column(align=True)
            column.operator(
                "coa_tools2.add_component_binding",
                text="",
                icon="ADD",
            )
            column.operator(
                "coa_tools2.remove_component_binding",
                text="",
                icon="REMOVE",
            )
            if component.bindings:
                binding = component.bindings[
                    min(component.bindings_index, len(component.bindings) - 1)
                ]
                details = outputs.box()
                details.label(text=f"Input: {binding.source_component}")
                details.label(
                    text=(
                        f"Range: {binding.input_min:.3f} … "
                        f"{binding.input_max:.3f}"
                    )
                )
                details.label(
                    text=(
                        f"Output: {binding.output_min:.3f} … "
                        f"{binding.output_max:.3f}"
                    )
                )
        elif component.component_type == "SEMANTIC" and component.bindings:
            outputs = layout.box()
            outputs.label(text="Legacy Outputs Need Removal", icon="ERROR")
            outputs.label(
                text="Use Recorded Pose Map outputs for Character Rigs."
            )
            row = outputs.row()
            row.template_list(
                "COATOOLS2_UL_RigBindings",
                "",
                component,
                "bindings",
                component,
                "bindings_index",
                rows=min(5, max(2, len(component.bindings))),
            )
            row.column(align=True).operator(
                "coa_tools2.remove_component_binding",
                text="",
                icon="REMOVE",
            )

        export = layout.box()
        if component.deformation_mode == "PARAMETRIC":
            export.label(
                text="3D depth/tilt is parameter input, not mesh rotation.",
                icon="INFO",
            )
        else:
            export.label(text="3D depth/tilt poses source bones.", icon="INFO")


CLASSES = (
    COATOOLS2_UL_RigComponents,
    COATOOLS2_PT_RigComponents,
)
