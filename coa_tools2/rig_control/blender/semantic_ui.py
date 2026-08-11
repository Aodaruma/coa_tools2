"""UI for composable semantic character rig stages."""

from __future__ import annotations

import bpy

from ... import functions
from .properties import get_rig_data


def _active(context):
    armature = functions.get_sprite_object(context.active_object)
    if armature is None or armature.type != "ARMATURE":
        return None, None, None
    rig_data = get_rig_data(armature)
    if not rig_data.rig_components:
        return armature, None, None
    component = rig_data.rig_components[
        min(rig_data.rig_components_index, len(rig_data.rig_components) - 1)
    ]
    stage = None
    if component.semantic_stages:
        stage = component.semantic_stages[
            min(component.semantic_stages_index, len(component.semantic_stages) - 1)
        ]
    return armature, component, stage


class COATOOLS2_UL_SemanticStages(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active, _prop, _index):
        row = layout.row(align=True)
        row.prop(item, "enabled", text="")
        row.label(text=f"{item.order}: {item.label}", icon="NODETREE")


class COATOOLS2_UL_SemanticInputs(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active, _prop, _index):
        layout.label(text=f"{item.label} · {item.channel_id}", icon="DRIVER")


class COATOOLS2_UL_SemanticOutputs(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active, _prop, _index):
        row = layout.row(align=True)
        row.prop(item, "enabled", text="")
        row.label(text=f"{item.label} · {item.target_kind}", icon="OUTPUT")


class COATOOLS2_UL_SemanticSamples(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active, _prop, _index):
        row = layout.row(align=True)
        row.prop(item, "enabled", text="")
        row.label(text=item.label, icon="KEY_HLT")


class COATOOLS2_PT_SemanticRig(bpy.types.Panel):
    bl_idname = "COATOOLS2_PT_semantic_rig"
    bl_label = "Semantic Rig Layers"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "COA Tools2"
    bl_parent_id = "COATOOLS2_PT_rig_components"

    @classmethod
    def poll(cls, context):
        _armature, component, _stage = _active(context)
        return component is not None and component.component_type == "SEMANTIC"

    def draw(self, context):
        layout = self.layout
        armature, component, stage = _active(context)
        header = layout.box()
        header.label(text="One rig = composable meaning + solver layers", icon="NODETREE")
        header.label(text="State Rig remains the parameter/state controller system.")

        row = layout.row()
        row.template_list(
            "COATOOLS2_UL_SemanticStages", "", component, "semantic_stages",
            component, "semantic_stages_index", rows=min(6, max(2, len(component.semantic_stages))),
        )
        column = row.column(align=True)
        column.operator("coa_tools2.add_semantic_stage", text="", icon="ADD")
        if stage is None:
            return
        box = layout.box()
        box.prop(stage, "label")
        box.prop(stage, "stage_type")
        box.prop(stage, "order")
        box.prop(stage, "depends_on", text="After UUIDs")

        if stage.stage_type == "PROJECTED_TRANSFORM":
            box.prop(stage, "projection_mode")
            box.prop(stage, "preserve_art_plane")
            box.prop(stage, "art_plane_normal")
            box.prop(stage, "visual_axis")
            box.label(text=f"Input control: {stage.control_bone or 'build pending'}")
            box.label(text=f"Display frame: {stage.display_frame_bone or 'build pending'}")
        elif stage.stage_type == "POSE_MAP":
            self._draw_pose_map(box, component, stage)
        elif stage.stage_type == "CHAIN_IK":
            box.prop(stage, "chain_length")
            box.prop(stage, "use_pole")
            box.prop(stage, "allow_stretch")
            box.label(text="Real 3D mechanism → flat presentation projection")
        elif stage.stage_type == "CONTACT_PIN":
            box.prop(stage, "pin_driven_bone")
            box.prop(stage, "pin_target_object")
            box.prop(stage, "pin_space")
            row = box.row(align=True)
            row.prop(stage, "pin_start")
            row.prop(stage, "pin_end")
            row = box.row(align=True)
            row.prop(stage, "blend_in")
            row.prop(stage, "blend_out")
            box.prop(stage, "pin_position")
            box.prop(stage, "pin_orientation")
        elif stage.stage_type == "SPLINE":
            box.prop(stage, "spline_control_count")
            box.prop(stage, "root_pin")
            box.prop(stage, "tip_pin")
            box.label(text=f"Curve: {stage.curve_object.name if stage.curve_object else 'build pending'}")
        elif stage.stage_type == "SECONDARY_MOTION":
            box.prop(stage, "frequency_hz")
            box.prop(stage, "damping_ratio")
            box.prop(stage, "substeps")
            box.prop(stage, "pre_roll")
            row = box.row(align=True)
            row.prop(stage, "bake_start")
            row.prop(stage, "bake_end")
            box.operator("coa_tools2.bake_semantic_secondary", icon="REC")

    def _draw_pose_map(self, box, component, stage):
        box.label(text=f"{len(stage.inputs)}D Recorded Pose Field", icon="ORIENTATION_GIMBAL")
        box.prop(stage, "kernel_radius")
        box.prop(stage, "neighborhood_size")
        row = box.row()
        row.template_list(
            "COATOOLS2_UL_SemanticInputs", "", stage, "inputs", stage,
            "inputs_index", rows=min(5, max(2, len(stage.inputs))),
        )
        row.column(align=True).operator("coa_tools2.add_semantic_input", text="", icon="ADD")
        row = box.row()
        row.template_list(
            "COATOOLS2_UL_SemanticOutputs", "", stage, "outputs", stage,
            "outputs_index", rows=min(5, max(2, len(stage.outputs))),
        )
        row.column(align=True).operator("coa_tools2.add_semantic_output", text="", icon="ADD")
        box.template_list(
            "COATOOLS2_UL_SemanticSamples", "", stage, "samples", stage,
            "samples_index", rows=min(5, max(2, len(stage.samples))),
        )
        if component.semantic_edit_sample_uuid:
            warning = box.box()
            warning.label(text="Sample authoring: outputs are temporarily released.", icon="GREASEPENCIL")
            row = warning.row(align=True)
            row.operator("coa_tools2.commit_semantic_sample", icon="CHECKMARK")
            row.operator("coa_tools2.cancel_semantic_sample", icon="CANCEL")
        else:
            box.operator("coa_tools2.begin_semantic_sample", icon="ADD")


CLASSES = (
    COATOOLS2_UL_SemanticStages,
    COATOOLS2_UL_SemanticInputs,
    COATOOLS2_UL_SemanticOutputs,
    COATOOLS2_UL_SemanticSamples,
    COATOOLS2_PT_SemanticRig,
)
