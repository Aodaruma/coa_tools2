"""UI for composable semantic character rig stages."""

from __future__ import annotations

import bpy

from ... import functions
from .component_ui import draw_widget_presentation
from .properties import get_rig_data
from .semantic_contact import contact_uses_ik_override


def _active(context):
    armature = functions.get_sprite_object(context.active_object)
    if armature is None or armature.type != "ARMATURE":
        return None, None, None
    # Panel poll/draw callbacks must not perform lazy RNA migration; operator
    # execute paths migrate before making authoring changes.
    rig_data = get_rig_data(armature, migrate=False)
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
        suffix = f" · Vec{item.value_arity}" if item.value_arity > 1 else ""
        row.label(text=f"{item.label} · {item.target_kind}{suffix}", icon="OUTPUT")


class COATOOLS2_UL_SemanticSamples(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active, _prop, _index):
        row = layout.row(align=True)
        row.prop(item, "enabled", text="")
        row.label(text=item.label, icon="KEY_HLT")


class COATOOLS2_PT_SemanticRig(bpy.types.Panel):
    bl_idname = "COATOOLS2_PT_semantic_rig"
    bl_label = "Character Rig Layers"
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
        dependencies = {value.strip() for value in stage.depends_on.split(",") if value.strip()}
        dependency_names = [candidate.label for candidate in component.semantic_stages
                            if candidate.stage_uuid in dependencies]
        inputs = box.row(align=True)
        inputs.label(text="Input: " + (", ".join(dependency_names) or "None"))
        operator = inputs.operator("coa_tools2.edit_rig_dependencies", text="Choose")
        operator.stage_uuid = stage.stage_uuid

        if stage.stage_type in {"PROJECTED_TRANSFORM", "CHAIN_FK", "SPLINE"}:
            draw_widget_presentation(
                box,
                stage.presentation,
                panel_id="coa_tools2_semantic_stage_presentation",
                title=(
                    "Spline Controls Presentation"
                    if stage.stage_type == "SPLINE"
                    else (
                        "FK Controls Presentation"
                        if stage.stage_type == "CHAIN_FK"
                        else "Control Presentation"
                    )
                ),
                stage_uuid=stage.stage_uuid,
                target_role=(
                    "SPLINE_CONTROL"
                    if stage.stage_type == "SPLINE"
                    else (
                        "FK_CONTROL"
                        if stage.stage_type == "CHAIN_FK"
                        else "PRIMARY"
                    )
                ),
            )
        elif stage.stage_type == "BBONE_BEZIER":
            draw_widget_presentation(
                box,
                stage.presentation,
                panel_id="coa_tools2_semantic_bbone_point_presentation",
                title="Point Controls Presentation",
                stage_uuid=stage.stage_uuid,
                target_role="BBONE_POINT",
            )
            draw_widget_presentation(
                box,
                stage.handle_presentation,
                panel_id="coa_tools2_semantic_bbone_handle_presentation",
                title="Tangent Handles Presentation",
                stage_uuid=stage.stage_uuid,
                target_role="BBONE_HANDLE",
            )

        if stage.stage_type in {
            "PROJECTED_TRANSFORM",
            "CHAIN_FK",
            "SPLINE",
            "BBONE_BEZIER",
        }:
            chain = box.box()
            chain.label(text="Stage Source Chain", icon="BONE_DATA")
            if stage.source_bones:
                chain.label(
                    text=" → ".join(ref.bone_name for ref in stage.source_bones)
                )
            else:
                chain.label(text="No source chain assigned", icon="ERROR")
            chain.operator(
                "coa_tools2.assign_semantic_stage_chain",
                icon="RESTRICT_SELECT_OFF",
            )

        if stage.stage_type == "PROJECTED_TRANSFORM":
            box.prop(stage, "projection_mode")
            box.prop(stage, "preserve_art_plane")
            box.prop(stage, "art_plane_normal")
            box.prop(stage, "visual_axis")
            box.label(text=f"Input control: {stage.control_bone or 'build pending'}")
            box.label(text=f"Display frame: {stage.display_frame_bone or 'build pending'}")
        elif stage.stage_type == "POSE_MAP":
            self._draw_pose_map(box, component, stage)
        elif stage.stage_type == "CHAIN_FK":
            box.label(
                text="Independent FK controls → source chain",
                icon="CON_ROTLIKE",
            )
            box.label(text=f"Tip control: {stage.control_bone or 'build pending'}")
        elif stage.stage_type == "CHAIN_IK":
            mode = box.row(align=True)
            mode.label(text="Mode")
            operator = mode.operator(
                "coa_tools2.switch_semantic_ik_fk",
                text="FK",
                depress=stage.rig_mode == "FK",
            )
            operator.mode = "FK"
            operator = mode.operator(
                "coa_tools2.switch_semantic_ik_fk",
                text="IK",
                depress=stage.rig_mode == "IK",
            )
            operator.mode = "IK"
            advanced = box.row(align=True)
            advanced.prop(
                stage,
                "switch_advanced_expanded",
                text="Advanced",
                icon=(
                    "DISCLOSURE_TRI_DOWN"
                    if stage.switch_advanced_expanded
                    else "DISCLOSURE_TRI_RIGHT"
                ),
                emboss=False,
            )
            if stage.switch_advanced_expanded:
                details = box.box()
                draw_widget_presentation(
                    details,
                    stage.presentation,
                    panel_id="coa_tools2_semantic_ik_presentation",
                    title="IK Handle Presentation",
                    stage_uuid=stage.stage_uuid,
                    target_role="PRIMARY",
                    align_to_hand=True,
                )
                draw_widget_presentation(
                    details,
                    stage.fk_presentation,
                    panel_id="coa_tools2_semantic_ik_fk_presentation",
                    title="FK Controls Presentation",
                    stage_uuid=stage.stage_uuid,
                    target_role="FK_CONTROL",
                )
                if stage.use_pole:
                    draw_widget_presentation(
                        details,
                        stage.pole_presentation,
                        panel_id="coa_tools2_semantic_pole_presentation",
                        title="Pole Presentation",
                        stage_uuid=stage.stage_uuid,
                        target_role="POLE",
                    )
                chain = details.box()
                chain.label(text="Stage Source Chain", icon="BONE_DATA")
                if stage.source_bones:
                    chain.label(
                        text=" → ".join(
                            ref.bone_name for ref in stage.source_bones
                        )
                    )
                else:
                    chain.label(text="No source chain assigned", icon="ERROR")
                chain.operator(
                    "coa_tools2.assign_semantic_stage_chain",
                    icon="RESTRICT_SELECT_OFF",
                )
                details.prop(stage, "chain_length")
                details.prop(stage, "use_pole")
                details.prop(stage, "allow_stretch")
            box.label(text="Real 3D mechanism → flat presentation projection")
        elif stage.stage_type == "CONTACT_PIN":
            automatic_contact = contact_uses_ik_override(stage)
            if automatic_contact:
                contact = box.row(align=True)
                contact.label(text="Contact Pin")
                operator = contact.operator(
                    "coa_tools2.switch_semantic_contact",
                    text="Off",
                    depress=stage.contact_mode == "OFF",
                )
                operator.mode = "OFF"
                operator = contact.operator(
                    "coa_tools2.switch_semantic_contact",
                    text="On",
                    depress=stage.contact_mode == "ON",
                )
                operator.mode = "ON"
            else:
                box.label(text="Generic Pin Range", icon="KEY_HLT")
            advanced = box.row(align=True)
            advanced.prop(
                stage,
                "switch_advanced_expanded",
                text="Advanced",
                icon=(
                    "DISCLOSURE_TRI_DOWN"
                    if stage.switch_advanced_expanded
                    else "DISCLOSURE_TRI_RIGHT"
                ),
                emboss=False,
            )
            if stage.switch_advanced_expanded:
                details = box.box()
                if automatic_contact:
                    details.prop(stage, "contact_transition_frames")
                details.prop(stage, "pin_driven_bone")
                details.prop(stage, "pin_target_object")
                details.prop(stage, "pin_space")
                details.prop(stage, "pin_position")
                details.prop(stage, "pin_orientation")
                legacy = details.box()
                legacy.label(
                    text=(
                        "Legacy Range Workflow"
                        if automatic_contact
                        else "Pin Range Workflow"
                    ),
                    icon="KEY_HLT",
                )
                row = legacy.row(align=True)
                row.prop(stage, "pin_start")
                row.prop(stage, "pin_end")
                row = legacy.row(align=True)
                row.prop(stage, "blend_in")
                row.prop(stage, "blend_out")
                legacy.operator(
                    "coa_tools2.apply_semantic_pin_range",
                    icon="KEY_HLT",
                )
        elif stage.stage_type == "SPLINE":
            box.prop(stage, "spline_control_count")
            box.prop(stage, "root_pin")
            box.prop(stage, "tip_pin")
            box.label(text=f"Curve: {stage.curve_object.name if stage.curve_object else 'build pending'}")
        elif stage.stage_type == "BBONE_BEZIER":
            box.prop(stage, "bbone_use_mid_control", text="Midpoint Control")
            if stage.bbone_use_mid_control:
                box.prop(stage, "bbone_mid_influence", text="Midpoint Pull")
            advanced = box.row(align=True)
            advanced.prop(
                stage,
                "bbone_show_advanced",
                text="Advanced",
                icon=(
                    "DISCLOSURE_TRI_DOWN"
                    if stage.bbone_show_advanced
                    else "DISCLOSURE_TRI_RIGHT"
                ),
                emboss=False,
            )
            if stage.bbone_show_advanced:
                details = box.box()
                details.prop(stage, "bbone_segments", text="Segments")
                details.prop(stage, "bbone_handle_length", text="Handle Length")
                row = details.row(align=True)
                row.prop(stage, "bbone_ease_in", text="Ease In")
                row.prop(stage, "bbone_ease_out", text="Ease Out")
                row = details.row(align=True)
                row.prop(stage, "bbone_roll_in", text="Roll In")
                row.prop(stage, "bbone_roll_out", text="Roll Out")
                details.prop(stage, "bbone_use_scale", text="Endpoint Scale")
                if stage.bbone_use_scale:
                    details.prop(stage, "bbone_scale_in", text="Scale In")
                    details.prop(stage, "bbone_scale_out", text="Scale Out")
            box.label(
                text=f"B-Bone: {stage.source_bones[0].bone_name if stage.source_bones else 'build pending'}"
            )
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
        if stage.inputs:
            channel = stage.inputs[
                min(stage.inputs_index, len(stage.inputs) - 1)
            ]
            details = box.box()
            details.label(text=f"Input Source · {channel.label}", icon="LINKED")
            dependencies = {
                item.stage_uuid: item.label
                for item in component.semantic_stages
                if item.stage_uuid in {
                    value.strip()
                    for value in stage.depends_on.split(",")
                    if value.strip()
                }
            }
            if dependencies:
                details.label(
                    text="Dependencies: "
                    + ", ".join(
                        f"{label} [{stage_uuid[:8]}]"
                        for stage_uuid, label in dependencies.items()
                    ),
                    icon="INFO",
                )
            for index, term in enumerate(channel.terms):
                term_box = details.box()
                term_box.label(text=f"Term {index + 1}")
                term_box.prop(term, "source_stage_uuid")
                row = term_box.row(align=True)
                row.prop(term, "source_object", text="Object")
                row.prop(term, "source_bone", text="Bone")
                term_box.label(
                    text="Stage UUID auto-wires a dependency; empty keeps Object/Bone explicit."
                )
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
        if (
            component.semantic_edit_sample_uuid
            and component.semantic_edit_stage_uuid == stage.stage_uuid
        ):
            warning = box.box()
            warning.label(text="Sample authoring: outputs are temporarily released.", icon="GREASEPENCIL")
            row = warning.row(align=True)
            row.operator("coa_tools2.commit_semantic_sample", icon="CHECKMARK")
            row.operator("coa_tools2.cancel_semantic_sample", icon="CANCEL")
        else:
            if component.semantic_edit_sample_uuid:
                box.label(text="Another Pose Map is being authored.", icon="INFO")
            box.operator("coa_tools2.begin_semantic_sample", icon="ADD")


CLASSES = (
    COATOOLS2_UL_SemanticStages,
    COATOOLS2_UL_SemanticInputs,
    COATOOLS2_UL_SemanticOutputs,
    COATOOLS2_UL_SemanticSamples,
    COATOOLS2_PT_SemanticRig,
)
