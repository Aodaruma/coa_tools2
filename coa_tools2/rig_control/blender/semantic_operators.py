"""Authoring operators for composable semantic character rigs."""

from __future__ import annotations

import re
import traceback
import uuid

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty

from ... import functions
from .component_compiler import compile_component
from .properties import get_rig_data
from .selection import select_pose_bone
from .semantic_outputs import (
    SemanticOutputError,
    capture_semantic_input_value,
    capture_semantic_output_value,
    remove_semantic_output_drivers,
)
from .semantic_runtime import clear_pose_field_cache


def _armature(context):
    obj = functions.get_sprite_object(context.active_object)
    return obj if obj is not None and obj.type == "ARMATURE" else None


def _active_component(context):
    armature = _armature(context)
    if armature is None:
        return None, None
    rig_data = get_rig_data(armature)
    if not rig_data.rig_components:
        return armature, None
    index = min(rig_data.rig_components_index, len(rig_data.rig_components) - 1)
    return armature, rig_data.rig_components[index]


def _active_stage(context, *, stage_type=None):
    armature, component = _active_component(context)
    if component is None or component.component_type != "SEMANTIC":
        return armature, component, None
    if not component.semantic_stages:
        return armature, component, None
    index = min(component.semantic_stages_index, len(component.semantic_stages) - 1)
    stage = component.semantic_stages[index]
    if stage_type is not None and stage.stage_type != stage_type:
        return armature, component, None
    return armature, component, stage


def _slug(value):
    value = re.sub(r"[^0-9A-Za-z_]+", "_", value.strip().lower()).strip("_")
    return value or "semantic_rig"


def _selected_chain(context):
    active = context.active_pose_bone
    if active is None:
        return []
    selected = {bone.name for bone in context.selected_pose_bones or ()}
    selected.add(active.name)
    chain = [active]
    cursor = active.parent
    while cursor is not None and cursor.name in selected:
        chain.append(cursor)
        cursor = cursor.parent
    chain.reverse()
    return [bone.name for bone in chain]


def _new_stage(component, stage_type, label, order):
    stage = component.semantic_stages.add()
    stage.stage_uuid = str(uuid.uuid4())
    stage.semantic_id = _slug(label)
    stage.label = label
    stage.stage_type = stage_type
    stage.order = order
    return stage


def _new_input(stage, channel_id, label, transform_type, control_bone=""):
    channel = stage.inputs.add()
    channel.channel_uuid = str(uuid.uuid4())
    channel.channel_id = channel_id
    channel.label = label
    term = channel.terms.add()
    term.term_uuid = str(uuid.uuid4())
    term.source_kind = "TRANSFORM"
    term.source_bone = control_bone
    term.transform_type = transform_type
    term.transform_space = "LOCAL_SPACE"
    return channel


def _shape_key_items(self, _context):
    obj = bpy.data.objects.get(getattr(self, "target_object_name", ""))
    shape_keys = getattr(getattr(obj, "data", None), "shape_keys", None)
    if shape_keys is None:
        return (("", "No Shape Keys", ""),)
    items = [
        (block.name, block.name, "")
        for block in shape_keys.key_blocks
        if block != shape_keys.reference_key
    ]
    return tuple(items) or (("", "No Shape Keys", ""),)


def _bone_items(self, _context):
    obj = bpy.data.objects.get(getattr(self, "target_object_name", ""))
    if obj is None or obj.type != "ARMATURE":
        return (("", "No Bones", ""),)
    return tuple((bone.name, bone.name, "") for bone in obj.data.bones)


def _constraint_items(self, _context):
    obj = bpy.data.objects.get(getattr(self, "target_object_name", ""))
    bone_name = getattr(self, "target_bone", "")
    pose_bone = obj.pose.bones.get(bone_name) if obj and obj.type == "ARMATURE" else None
    if pose_bone is None:
        return (("", "No Constraints", ""),)
    return tuple((item.name, item.name, "") for item in pose_bone.constraints) or (
        ("", "No Constraints", ""),
    )


class COATOOLS2_OT_AddSemanticRig(bpy.types.Operator):
    bl_idname = "coa_tools2.add_semantic_rig"
    bl_label = "Add Semantic Character Rig"
    bl_description = "Create a composable Projected Transform and N-D Recorded Pose Map"
    bl_options = {"REGISTER", "UNDO"}

    label: StringProperty(default="Semantic Motion")
    initial_dimensions: IntProperty(default=3, min=1, max=12)

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None and context.mode == "POSE" and context.active_pose_bone

    def invoke(self, context, _event):
        if context.active_pose_bone:
            self.label = context.active_pose_bone.name
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, _context):
        self.layout.prop(self, "label")
        self.layout.prop(self, "initial_dimensions")
        self.layout.label(text="Dimensions remain extensible after creation.", icon="INFO")

    def execute(self, context):
        armature = _armature(context)
        chain = _selected_chain(context)
        if armature is None or not chain:
            self.report({"ERROR"}, "Select one connected bone chain in Pose Mode.")
            return {"CANCELLED"}
        rig_data = get_rig_data(armature)
        component = rig_data.rig_components.add()
        component.component_uuid = str(uuid.uuid4())
        component.semantic_id = _slug(self.label)
        component.label = self.label
        component.component_type = "SEMANTIC"
        component.deformation_mode = "PARAMETRIC"
        component.build_mode = "GENERATED"
        component.orientation_reference = chain[-1]
        component.orientation_mode = "SOURCE_BONE"
        component.depth_mode = "LOCKED"
        component.widget = "SQUARE"
        for name in chain:
            reference = component.source_bones.add()
            reference.bone_name = name

        projected = _new_stage(component, "PROJECTED_TRANSFORM", "Projected Transform", 0)
        for name in chain:
            reference = projected.source_bones.add()
            reference.bone_name = name
        pose_map = _new_stage(component, "POSE_MAP", "Recorded Pose Map", 1)
        pose_map.depends_on = projected.stage_uuid
        channels = (
            ("move_x", "Move X", "LOC_X"),
            ("move_y", "Move Y", "LOC_Y"),
            ("apparent_depth", "Apparent Depth", "LOC_Z"),
            ("turn_x", "Turn X", "ROT_X"),
            ("turn_y", "Turn Y", "ROT_Y"),
            ("turn_z", "Turn Z", "ROT_Z"),
        )
        for channel_id, label, transform in channels[: self.initial_dimensions]:
            _new_input(pose_map, channel_id, label, transform)
        component.semantic_stages_index = 1
        try:
            result = compile_component(armature, component)
        except Exception as exc:
            traceback.print_exc()
            rig_data.rig_components.remove(len(rig_data.rig_components) - 1)
            self.report({"ERROR"}, f"Semantic rig build failed: {exc}")
            return {"CANCELLED"}
        rig_data.rig_components_index = len(rig_data.rig_components) - 1
        if result.get("primary_control_bone"):
            select_pose_bone(armature, result["primary_control_bone"], exclusive=True)
        self.report({"INFO"}, "Created composable semantic character rig.")
        return {"FINISHED"}


class COATOOLS2_OT_AddSemanticStage(bpy.types.Operator):
    bl_idname = "coa_tools2.add_semantic_stage"
    bl_label = "Add Semantic Stage"
    bl_options = {"REGISTER", "UNDO"}

    stage_type: EnumProperty(
        items=(
            ("PROJECTED_TRANSFORM", "Projected Transform", ""),
            ("POSE_MAP", "Recorded Pose Map", ""),
            ("CHAIN_IK", "Kinematic Chain", ""),
            ("CONTACT_PIN", "Contact / Pin", ""),
            ("SPLINE", "Spline Chain", ""),
            ("SECONDARY_MOTION", "Secondary Motion", ""),
        ),
        default="POSE_MAP",
    )
    label: StringProperty(default="Semantic Stage")

    @classmethod
    def poll(cls, context):
        _arm, component = _active_component(context)
        return component is not None and component.component_type == "SEMANTIC"

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, _context):
        self.layout.prop(self, "stage_type")
        self.layout.prop(self, "label")

    def execute(self, context):
        armature, component = _active_component(context)
        stage = _new_stage(component, self.stage_type, self.label, len(component.semantic_stages))
        for source in component.source_bones:
            reference = stage.source_bones.add()
            reference.bone_name = source.bone_name
        if component.semantic_stages:
            predecessors = [item for item in component.semantic_stages if item != stage]
            if predecessors:
                stage.depends_on = max(predecessors, key=lambda item: item.order).stage_uuid
        component.semantic_stages_index = len(component.semantic_stages) - 1
        component.needs_rebuild = True
        clear_pose_field_cache()
        self.report({"INFO"}, "Stage added; configure it, then Apply Changes.")
        return {"FINISHED"}


class COATOOLS2_OT_AddSemanticInput(bpy.types.Operator):
    bl_idname = "coa_tools2.add_semantic_input"
    bl_label = "Add Pose Input Dimension"
    bl_options = {"REGISTER", "UNDO"}

    channel_id: StringProperty(default="input")
    label: StringProperty(default="Input")
    transform_type: EnumProperty(
        items=tuple((kind, kind.replace("_", " ").title(), "") for kind in (
            "LOC_X", "LOC_Y", "LOC_Z", "ROT_X", "ROT_Y", "ROT_Z",
            "SCALE_X", "SCALE_Y", "SCALE_Z",
        )),
        default="LOC_X",
    )
    scale: FloatProperty(default=1.0, min=1.0e-8)

    @classmethod
    def poll(cls, context):
        return _active_stage(context, stage_type="POSE_MAP")[2] is not None

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, _context):
        self.layout.prop(self, "channel_id")
        self.layout.prop(self, "label")
        self.layout.prop(self, "transform_type")
        self.layout.prop(self, "scale")

    def execute(self, context):
        _armature, component, stage = _active_stage(context, stage_type="POSE_MAP")
        if any(item.channel_id == self.channel_id for item in stage.inputs):
            self.report({"ERROR"}, "Input id must be unique in this Pose Map.")
            return {"CANCELLED"}
        channel = _new_input(stage, self.channel_id, self.label, self.transform_type, component.control_bone)
        channel.scale = self.scale
        stage.inputs_index = len(stage.inputs) - 1
        component.needs_rebuild = True
        clear_pose_field_cache()
        return {"FINISHED"}


class COATOOLS2_OT_AddSemanticOutput(bpy.types.Operator):
    bl_idname = "coa_tools2.add_semantic_output"
    bl_label = "Add Recorded Output"
    bl_options = {"REGISTER", "UNDO"}

    label: StringProperty(default="Output")
    target_kind: EnumProperty(
        items=(
            ("SHAPE_KEY", "Shape Key", ""),
            ("CONSTRAINT_INFLUENCE", "Constraint Influence", ""),
            ("BONE_LOCATION", "Bone Location", ""),
            ("BONE_ROTATION", "Bone Rotation", ""),
            ("CUSTOM_PROPERTY", "Custom Property", ""),
            ("SLOT_INDEX", "Sprite Slot", ""),
            ("Z_VALUE", "Draw Order", ""),
        ),
        default="SHAPE_KEY",
    )
    target_object_name: StringProperty()
    target_bone: EnumProperty(items=_bone_items)
    target_name: EnumProperty(items=_shape_key_items)
    target_constraint: EnumProperty(items=_constraint_items)
    data_path: StringProperty()
    array_index: IntProperty(default=0, min=-1, max=3)
    discrete: BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        return _active_stage(context, stage_type="POSE_MAP")[2] is not None

    def invoke(self, context, _event):
        armature, _component, _stage = _active_stage(context, stage_type="POSE_MAP")
        target = next(
            (
                obj for obj in context.selected_objects
                if obj.type == "MESH" and getattr(obj.data, "shape_keys", None)
            ),
            None,
        )
        self.target_object_name = (target or armature).name
        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "label")
        layout.prop(self, "target_kind")
        layout.prop_search(self, "target_object_name", bpy.data, "objects", text="Target")
        if self.target_kind == "SHAPE_KEY":
            layout.prop(self, "target_name", text="Shape Key")
        elif self.target_kind in {"CONSTRAINT_INFLUENCE", "BONE_LOCATION", "BONE_ROTATION"}:
            layout.prop(self, "target_bone", text="Bone")
            if self.target_kind == "CONSTRAINT_INFLUENCE":
                layout.prop(self, "target_constraint", text="Constraint")
            else:
                layout.prop(self, "array_index", text="Axis")
        elif self.target_kind == "CUSTOM_PROPERTY":
            layout.prop(self, "data_path")
            layout.prop(self, "array_index")
        layout.prop(self, "discrete")

    def execute(self, context):
        armature, component, stage = _active_stage(context, stage_type="POSE_MAP")
        target = bpy.data.objects.get(self.target_object_name)
        if target is None:
            self.report({"ERROR"}, "Target object is required.")
            return {"CANCELLED"}
        output = stage.outputs.add()
        output.output_uuid = str(uuid.uuid4())
        output.output_id = _slug(self.label)
        output.label = self.label
        output.target_kind = self.target_kind
        output.target_object = target
        output.target_bone = self.target_bone
        output.target_name = self.target_constraint if self.target_kind == "CONSTRAINT_INFLUENCE" else self.target_name
        output.data_path = self.data_path
        output.array_index = self.array_index
        output.discrete = self.discrete or self.target_kind in {"SLOT_INDEX", "Z_VALUE"}
        try:
            compile_component(armature, component)
        except Exception as exc:
            traceback.print_exc()
            stage.outputs.remove(len(stage.outputs) - 1)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        stage.outputs_index = len(stage.outputs) - 1
        self.report({"INFO"}, "Output added. Begin a sample to author its value.")
        return {"FINISHED"}


class COATOOLS2_OT_BeginSemanticSample(bpy.types.Operator):
    bl_idname = "coa_tools2.begin_semantic_sample"
    bl_label = "Begin Pose Sample"
    bl_description = "Capture N-D inputs and temporarily release outputs for authoring"
    bl_options = {"REGISTER", "UNDO"}

    label: StringProperty(default="Pose Sample")

    @classmethod
    def poll(cls, context):
        _arm, component, stage = _active_stage(context, stage_type="POSE_MAP")
        return stage is not None and bool(stage.outputs) and not component.semantic_edit_sample_uuid

    def execute(self, context):
        armature, component, stage = _active_stage(context, stage_type="POSE_MAP")
        sample = stage.samples.add()
        sample.sample_uuid = str(uuid.uuid4())
        sample.label = f"Pose {len(stage.samples)}"
        try:
            for channel in stage.inputs:
                value = sample.inputs.add()
                value.channel_id = channel.channel_uuid or channel.channel_id
                value.value = capture_semantic_input_value(armature, channel)
            for output in stage.outputs:
                remove_semantic_output_drivers(armature, output.output_uuid)
        except Exception as exc:
            stage.samples.remove(len(stage.samples) - 1)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        stage.samples_index = len(stage.samples) - 1
        component.semantic_edit_sample_uuid = sample.sample_uuid
        clear_pose_field_cache()
        self.report({"INFO"}, "Inputs captured. Edit target Shape Keys/properties, then Commit Pose Sample.")
        return {"FINISHED"}


class COATOOLS2_OT_CommitSemanticSample(bpy.types.Operator):
    bl_idname = "coa_tools2.commit_semantic_sample"
    bl_label = "Commit Pose Sample"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        _arm, component, stage = _active_stage(context, stage_type="POSE_MAP")
        return stage is not None and bool(component.semantic_edit_sample_uuid)

    def execute(self, context):
        armature, component, stage = _active_stage(context, stage_type="POSE_MAP")
        sample = next((item for item in stage.samples if item.sample_uuid == component.semantic_edit_sample_uuid), None)
        if sample is None:
            component.semantic_edit_sample_uuid = ""
            self.report({"ERROR"}, "The editable sample no longer exists.")
            return {"CANCELLED"}
        sample.outputs.clear()
        try:
            for output in stage.outputs:
                value = sample.outputs.add()
                value.output_uuid = output.output_uuid
                captured = capture_semantic_output_value(armature, output)
                value.value = (captured, 0.0, 0.0, 0.0)
                value.value_arity = 1
                value.discrete_value = str(int(round(captured))) if output.discrete else ""
            component.semantic_edit_sample_uuid = ""
            compile_component(armature, component)
        except Exception as exc:
            traceback.print_exc()
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Recorded {len(stage.inputs)}D pose sample.")
        return {"FINISHED"}


class COATOOLS2_OT_CancelSemanticSample(bpy.types.Operator):
    bl_idname = "coa_tools2.cancel_semantic_sample"
    bl_label = "Cancel Pose Sample"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        _arm, component, stage = _active_stage(context, stage_type="POSE_MAP")
        return stage is not None and bool(component.semantic_edit_sample_uuid)

    def execute(self, context):
        armature, component, stage = _active_stage(context, stage_type="POSE_MAP")
        for index in range(len(stage.samples) - 1, -1, -1):
            if stage.samples[index].sample_uuid == component.semantic_edit_sample_uuid:
                stage.samples.remove(index)
                break
        component.semantic_edit_sample_uuid = ""
        try:
            compile_component(armature, component)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


CLASSES = (
    COATOOLS2_OT_AddSemanticRig,
    COATOOLS2_OT_AddSemanticStage,
    COATOOLS2_OT_AddSemanticInput,
    COATOOLS2_OT_AddSemanticOutput,
    COATOOLS2_OT_BeginSemanticSample,
    COATOOLS2_OT_CommitSemanticSample,
    COATOOLS2_OT_CancelSemanticSample,
)
