"""Viewport UI for character posing rig components."""

from __future__ import annotations

import bpy

from ... import functions
from .properties import get_rig_data
from .selection import active_data_bone


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
    bl_label = "Character Posing"
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
        row.operator("coa_tools2.add_rig_component", icon="ADD")
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
            visual_body.prop(component, "widget")
            visual_body.prop(component, "widget_size")

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

        if component.deformation_mode == "PARAMETRIC":
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
