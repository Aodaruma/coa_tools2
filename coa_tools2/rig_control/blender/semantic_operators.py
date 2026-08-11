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
    capture_semantic_output_state,
    remove_semantic_output_drivers,
    restore_semantic_output_state,
    set_semantic_output_value,
)
from .semantic_runtime import clear_pose_field_cache
from .semantic_contact import key_pin_range
from .semantic_secondary import bake_secondary_motion
from .semantic_spline import retarget_spline_hooks


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


def _editing_pose_stage(component):
    if component is None or not component.semantic_edit_stage_uuid:
        return None
    return next(
        (
            stage
            for stage in component.semantic_stages
            if stage.stage_uuid == component.semantic_edit_stage_uuid
            and stage.stage_type == "POSE_MAP"
        ),
        None,
    )


def _sample_snapshot(sample):
    return {
        "sample_uuid": sample.sample_uuid,
        "label": sample.label,
        "enabled": sample.enabled,
        "inputs": tuple(
            (value.channel_id, value.value) for value in sample.inputs
        ),
        "outputs": tuple(
            (
                value.output_uuid,
                tuple(value.value),
                value.value_arity,
                value.discrete_value,
            )
            for value in sample.outputs
        ),
    }


def _restore_sample(stage, snapshot, index):
    sample = stage.samples.add()
    sample.sample_uuid = snapshot["sample_uuid"]
    sample.label = snapshot["label"]
    sample.enabled = snapshot["enabled"]
    for channel_id, captured in snapshot["inputs"]:
        value = sample.inputs.add()
        value.channel_id = channel_id
        value.value = captured
    for output_uuid, captured, value_arity, discrete_value in snapshot["outputs"]:
        value = sample.outputs.add()
        value.output_uuid = output_uuid
        value.value = captured
        value.value_arity = value_arity
        value.discrete_value = discrete_value
    restored_index = len(stage.samples) - 1
    if restored_index != index:
        stage.samples.move(restored_index, index)
    return stage.samples[index]


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


def _dependency_stage_items(self, context):
    _armature, component, stage = _active_stage(context, stage_type="POSE_MAP")
    items = [
        (
            "AUTO",
            "Automatic (single dependency)",
            "Use the only upstream stage",
        )
    ]
    if component is None or stage is None:
        return tuple(items)
    dependency_ids = {
        token.strip() for token in stage.depends_on.split(",") if token.strip()
    }
    items.extend(
        (
            candidate.stage_uuid,
            f"{candidate.label} [{candidate.stage_uuid[:8]}]",
            f"Read the control exported by {candidate.label}",
        )
        for candidate in component.semantic_stages
        if candidate.stage_uuid in dependency_ids
    )
    return tuple(items)


class COATOOLS2_OT_AddSemanticRig(bpy.types.Operator):
    bl_idname = "coa_tools2.add_semantic_rig"
    bl_label = "Add Character Rig"
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
        # Solver stages own an explicit source chain.  Mapping, contact and
        # secondary layers inherit their inputs through ``depends_on`` instead;
        # copying the component chain into those layers would silently bypass
        # the graph connection (notably Spline -> Secondary).
        if self.stage_type in {"PROJECTED_TRANSFORM", "CHAIN_IK", "SPLINE"}:
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


class COATOOLS2_OT_AssignSemanticStageChain(bpy.types.Operator):
    bl_idname = "coa_tools2.assign_semantic_stage_chain"
    bl_label = "Assign Selected Chain"
    bl_description = (
        "Assign the connected Pose Mode selection as this solver stage's "
        "source chain"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        _armature, _component, stage = _active_stage(context)
        return (
            context.mode == "POSE"
            and stage is not None
            and stage.stage_type
            in {"PROJECTED_TRANSFORM", "CHAIN_IK", "SPLINE"}
            and bool(_selected_chain(context))
        )

    def execute(self, context):
        _armature, component, stage = _active_stage(context)
        chain = _selected_chain(context)
        if component is None or stage is None or not chain:
            self.report({"ERROR"}, "Select one connected source chain in Pose Mode.")
            return {"CANCELLED"}
        stage.source_bones.clear()
        for bone_name in chain:
            reference = stage.source_bones.add()
            reference.bone_name = bone_name
        stage.source_bones_index = max(0, len(stage.source_bones) - 1)
        component.needs_rebuild = True
        clear_pose_field_cache()
        self.report({"INFO"}, f"Assigned {len(chain)} source bones to this stage.")
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
    source_stage_uuid: EnumProperty(
        name="Source Stage",
        description="Upstream stage whose exported control provides this dimension",
        items=_dependency_stage_items,
        default=0,
    )

    @classmethod
    def poll(cls, context):
        return _active_stage(context, stage_type="POSE_MAP")[2] is not None

    def invoke(self, context, _event):
        _armature, _component, stage = _active_stage(
            context, stage_type="POSE_MAP"
        )
        if stage is not None:
            dependency_ids = [
                token.strip()
                for token in stage.depends_on.split(",")
                if token.strip()
            ]
            if len(dependency_ids) == 1:
                self.source_stage_uuid = dependency_ids[0]
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, _context):
        self.layout.prop(self, "channel_id")
        self.layout.prop(self, "label")
        self.layout.prop(self, "transform_type")
        self.layout.prop(self, "scale")
        self.layout.prop(self, "source_stage_uuid")

    def execute(self, context):
        _armature, component, stage = _active_stage(context, stage_type="POSE_MAP")
        if any(item.channel_id == self.channel_id for item in stage.inputs):
            self.report({"ERROR"}, "Input id must be unique in this Pose Map.")
            return {"CANCELLED"}
        dependency_ids = {
            token.strip() for token in stage.depends_on.split(",") if token.strip()
        }
        selected_source = getattr(self, "source_stage_uuid", "AUTO")
        source_stage_uuid = "" if selected_source == "AUTO" else selected_source
        if not source_stage_uuid and len(dependency_ids) == 1:
            source_stage_uuid = next(iter(dependency_ids))
        if source_stage_uuid and source_stage_uuid not in dependency_ids:
            self.report({"ERROR"}, "Source Stage must be a direct dependency.")
            return {"CANCELLED"}
        if len(dependency_ids) > 1 and not source_stage_uuid:
            self.report({"ERROR"}, "Choose a Source Stage for this dimension.")
            return {"CANCELLED"}
        channel = _new_input(
            stage,
            self.channel_id,
            self.label,
            self.transform_type,
        )
        channel.terms[0].source_stage_uuid = source_stage_uuid
        channel.scale = self.scale
        stored_channel_id = channel.channel_uuid or channel.channel_id
        for sample in stage.samples:
            value = sample.inputs.add()
            value.channel_id = stored_channel_id
            value.value = channel.offset
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
    target_bone: StringProperty()
    target_name: StringProperty()
    target_constraint: StringProperty()
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
        if target is not None and target.data.shape_keys is not None:
            available = [
                block
                for block in target.data.shape_keys.key_blocks
                if block != target.data.shape_keys.reference_key
            ]
            if available:
                self.target_name = available[0].name
        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "label")
        layout.prop(self, "target_kind")
        layout.prop_search(self, "target_object_name", bpy.data, "objects", text="Target")
        target = bpy.data.objects.get(self.target_object_name)
        if self.target_kind == "SHAPE_KEY":
            shape_keys = getattr(getattr(target, "data", None), "shape_keys", None)
            if shape_keys is not None:
                layout.prop_search(self, "target_name", shape_keys, "key_blocks", text="Shape Key")
            else:
                layout.prop(self, "target_name", text="Shape Key")
        elif self.target_kind in {"CONSTRAINT_INFLUENCE", "BONE_LOCATION", "BONE_ROTATION"}:
            if target is not None and target.type == "ARMATURE":
                layout.prop_search(self, "target_bone", target.data, "bones", text="Bone")
            else:
                layout.prop(self, "target_bone", text="Bone")
            if self.target_kind == "CONSTRAINT_INFLUENCE":
                pose_bone = target.pose.bones.get(self.target_bone) if target and target.type == "ARMATURE" else None
                if pose_bone is not None:
                    layout.prop_search(self, "target_constraint", pose_bone, "constraints", text="Constraint")
                else:
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
            captured = capture_semantic_output_value(armature, output)
            for sample in stage.samples:
                value = sample.outputs.add()
                value.output_uuid = output.output_uuid
                value.value = (captured, 0.0, 0.0, 0.0)
                value.value_arity = 1
                value.discrete_value = (
                    str(int(round(captured))) if output.discrete else ""
                )
            compile_component(armature, component)
        except Exception as exc:
            traceback.print_exc()
            for sample in stage.samples:
                for index in range(len(sample.outputs) - 1, -1, -1):
                    if sample.outputs[index].output_uuid == output.output_uuid:
                        sample.outputs.remove(index)
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
        output_driver_state = ()
        sample_uuid = ""
        try:
            output_driver_state = capture_semantic_output_state(armature, component)
            captured_outputs = tuple(
                (output, capture_semantic_output_value(armature, output))
                for output in stage.outputs
            )
            sample = stage.samples.add()
            sample.sample_uuid = str(uuid.uuid4())
            sample_uuid = sample.sample_uuid
            sample.label = f"Pose {len(stage.samples)}"
            for channel in stage.inputs:
                value = sample.inputs.add()
                value.channel_id = channel.channel_uuid or channel.channel_id
                value.value = capture_semantic_input_value(armature, channel)
            for output, captured in captured_outputs:
                value = sample.outputs.add()
                value.output_uuid = output.output_uuid
                value.value = (captured, 0.0, 0.0, 0.0)
                value.value_arity = 1
                value.discrete_value = str(int(round(captured))) if output.discrete else ""
                remove_semantic_output_drivers(armature, output.output_uuid)
                set_semantic_output_value(armature, output, captured)
        except Exception as exc:
            for index in range(len(stage.samples) - 1, -1, -1):
                if stage.samples[index].sample_uuid == sample_uuid:
                    stage.samples.remove(index)
                    break
            try:
                restore_semantic_output_state(armature, output_driver_state)
            except Exception:
                traceback.print_exc()
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        stage.samples_index = len(stage.samples) - 1
        component.semantic_edit_sample_uuid = sample.sample_uuid
        component.semantic_edit_stage_uuid = stage.stage_uuid
        clear_pose_field_cache()
        self.report({"INFO"}, "Inputs captured. Edit target Shape Keys/properties, then Commit Pose Sample.")
        return {"FINISHED"}


class COATOOLS2_OT_CommitSemanticSample(bpy.types.Operator):
    bl_idname = "coa_tools2.commit_semantic_sample"
    bl_label = "Commit Pose Sample"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        _arm, component = _active_component(context)
        return (
            component is not None
            and bool(component.semantic_edit_sample_uuid)
            and _editing_pose_stage(component) is not None
        )

    def execute(self, context):
        armature, component = _active_component(context)
        stage = _editing_pose_stage(component)
        sample = next((item for item in stage.samples if item.sample_uuid == component.semantic_edit_sample_uuid), None)
        if sample is None:
            component.semantic_edit_sample_uuid = ""
            component.semantic_edit_stage_uuid = ""
            self.report({"ERROR"}, "The editable sample no longer exists.")
            return {"CANCELLED"}
        sample_index = next(
            index for index, item in enumerate(stage.samples)
            if item.sample_uuid == sample.sample_uuid
        )
        sample_state = _sample_snapshot(sample)
        captured_outputs = ()
        try:
            captured_outputs = tuple(
                (output, capture_semantic_output_value(armature, output))
                for output in stage.outputs
            )
            sample.outputs.clear()
            for output, captured in captured_outputs:
                value = sample.outputs.add()
                value.output_uuid = output.output_uuid
                value.value = (captured, 0.0, 0.0, 0.0)
                value.value_arity = 1
                value.discrete_value = str(int(round(captured))) if output.discrete else ""
            component.semantic_edit_sample_uuid = ""
            component.semantic_edit_stage_uuid = ""
            compile_component(armature, component)
        except Exception as exc:
            traceback.print_exc()
            current_index = next(
                (
                    index for index, item in enumerate(stage.samples)
                    if item.sample_uuid == sample_state["sample_uuid"]
                ),
                -1,
            )
            if current_index >= 0:
                stage.samples.remove(current_index)
            _restore_sample(stage, sample_state, sample_index)
            stage.samples_index = sample_index
            component.semantic_edit_sample_uuid = sample_state["sample_uuid"]
            component.semantic_edit_stage_uuid = stage.stage_uuid
            for output, captured in captured_outputs:
                try:
                    remove_semantic_output_drivers(armature, output.output_uuid)
                    set_semantic_output_value(armature, output, captured)
                except Exception:
                    traceback.print_exc()
            clear_pose_field_cache()
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
        _arm, component = _active_component(context)
        return (
            component is not None
            and bool(component.semantic_edit_sample_uuid)
            and _editing_pose_stage(component) is not None
        )

    def execute(self, context):
        armature, component = _active_component(context)
        stage = _editing_pose_stage(component)
        edit_sample_uuid = component.semantic_edit_sample_uuid
        edit_stage_uuid = component.semantic_edit_stage_uuid
        sample_index = next(
            (
                index
                for index, sample in enumerate(stage.samples)
                if sample.sample_uuid == edit_sample_uuid
            ),
            -1,
        )
        if sample_index < 0:
            component.semantic_edit_sample_uuid = ""
            component.semantic_edit_stage_uuid = ""
            self.report({"ERROR"}, "The editable sample no longer exists.")
            return {"CANCELLED"}
        sample_state = _sample_snapshot(stage.samples[sample_index])
        previous_index = stage.samples_index
        try:
            edited_outputs = tuple(
                (output, capture_semantic_output_value(armature, output))
                for output in stage.outputs
            )
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        try:
            restored_values = {
                output_uuid: float(captured[0])
                for output_uuid, captured, _arity, _discrete in sample_state["outputs"]
            }
            for output in stage.outputs:
                if output.output_uuid in restored_values:
                    set_semantic_output_value(
                        armature, output, restored_values[output.output_uuid]
                    )
            stage.samples.remove(sample_index)
            component.semantic_edit_sample_uuid = ""
            component.semantic_edit_stage_uuid = ""
            compile_component(armature, component)
        except Exception as exc:
            if not any(
                sample.sample_uuid == sample_state["sample_uuid"]
                for sample in stage.samples
            ):
                _restore_sample(stage, sample_state, sample_index)
            stage.samples_index = previous_index
            component.semantic_edit_sample_uuid = edit_sample_uuid
            component.semantic_edit_stage_uuid = edit_stage_uuid
            for output, captured in edited_outputs:
                try:
                    remove_semantic_output_drivers(armature, output.output_uuid)
                    set_semantic_output_value(armature, output, captured)
                except Exception:
                    traceback.print_exc()
            clear_pose_field_cache()
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        stage.samples_index = min(previous_index, max(len(stage.samples) - 1, 0))
        return {"FINISHED"}


class COATOOLS2_OT_ApplySemanticPinRange(bpy.types.Operator):
    bl_idname = "coa_tools2.apply_semantic_pin_range"
    bl_label = "Capture & Key Pin Range"
    bl_description = "Capture the contact at the start frame and key its smooth Pin/Release range"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_stage(context, stage_type="CONTACT_PIN")[2] is not None

    def execute(self, context):
        armature, component, stage = _active_stage(context, stage_type="CONTACT_PIN")
        try:
            compile_component(armature, component)
            key_pin_range(armature, component, stage)
        except Exception as exc:
            traceback.print_exc()
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, "Pin contact captured and transition range keyed.")
        return {"FINISHED"}


class COATOOLS2_OT_BakeSemanticSecondary(bpy.types.Operator):
    bl_idname = "coa_tools2.bake_semantic_secondary"
    bl_label = "Bake Secondary Motion"
    bl_description = (
        "Bake deterministic secondary motion and feed it into the preceding "
        "Spline Chain"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_stage(context, stage_type="SECONDARY_MOTION")[2] is not None

    def execute(self, context):
        armature, component, stage = _active_stage(
            context, stage_type="SECONDARY_MOTION"
        )
        try:
            compiled = compile_component(armature, component)
            stage_results = compiled["stage_results"]
            dependency_results = [
                stage_results[token.strip()]
                for token in stage.depends_on.split(",")
                if token.strip() in stage_results
            ]
            spline_results = [
                result.spline_info
                for result in dependency_results
                if result.spline_info is not None
            ]
            if len(spline_results) != 1:
                raise SemanticOutputError(
                    "Secondary Motion needs exactly one upstream Spline result."
                )
            spline = spline_results[0]
            result = bake_secondary_motion(
                armature,
                component,
                stage,
                default_source_bones=spline.control_bones,
            )
            if len(result.output_bones) != len(spline.hook_modifiers):
                raise SemanticOutputError(
                    "Secondary outputs must match the Spline control count."
                )
            hook_targets = tuple(
                binding.bone_name if binding.pinned else output_bone
                for binding, output_bone in zip(
                    spline.hook_bindings, result.output_bones
                )
            )
            retarget_spline_hooks(
                spline.curve_object,
                hook_targets,
                armature=armature,
                hook_names=spline.hook_modifiers,
            )
        except Exception as exc:
            traceback.print_exc()
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"Baked {result.sample_count} frames of Secondary Motion.",
        )
        return {"FINISHED"}


CLASSES = (
    COATOOLS2_OT_AddSemanticRig,
    COATOOLS2_OT_AddSemanticStage,
    COATOOLS2_OT_AssignSemanticStageChain,
    COATOOLS2_OT_AddSemanticInput,
    COATOOLS2_OT_AddSemanticOutput,
    COATOOLS2_OT_BeginSemanticSample,
    COATOOLS2_OT_CommitSemanticSample,
    COATOOLS2_OT_CancelSemanticSample,
    COATOOLS2_OT_ApplySemanticPinRange,
    COATOOLS2_OT_BakeSemanticSecondary,
)
