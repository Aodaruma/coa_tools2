"""Operators for creating the first rig-control vertical slice."""

from __future__ import annotations

import re
import traceback
import uuid

import bpy
from bpy.props import EnumProperty, FloatProperty, StringProperty

from ... import functions
from .compiler import RigCompileError, compile_control


def _shape_key_items(self, _context):
    target = bpy.data.objects.get(self.target_object_name)
    shape_keys = getattr(getattr(target, "data", None), "shape_keys", None)
    if shape_keys is None:
        return [("", "No Shape Keys", "Target mesh has no Shape Keys")]
    items = [
        (key.name, key.name, f"Drive {key.name}")
        for key in shape_keys.key_blocks
        if key.name != "Basis"
    ]
    return items or [("", "No Shape Keys", "Target mesh has no non-Basis Shape Keys")]


def _default_target(context):
    active = context.active_object
    if active is not None and active.type == "MESH" and active.data.shape_keys:
        return active
    return next(
        (
            obj
            for obj in context.selected_objects
            if obj.type == "MESH" and obj.data.shape_keys is not None
        ),
        None,
    )


def _semantic_id(label: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z_]+", "_", label.strip()).strip("_").lower()
    return f"control.{slug or 'slider'}"


class COATOOLS2_OT_AddRigControl(bpy.types.Operator):
    bl_idname = "coa_tools2.add_rig_control"
    bl_label = "Add Rig Control"
    bl_description = "Create a Geometry Nodes 1D slider and Shape Key binding"
    bl_options = {"REGISTER", "UNDO"}

    label: StringProperty(default="Shape Key Slider")
    axis: EnumProperty(
        items=(
            ("X", "Horizontal", "Horizontal 1D slider"),
            ("Y", "Vertical", "Vertical 1D slider"),
        ),
        default="X",
    )
    width: FloatProperty(default=4.0, min=0.1)
    target_object_name: StringProperty()
    shape_key: EnumProperty(items=_shape_key_items)

    @classmethod
    def poll(cls, context):
        sprite_object = functions.get_sprite_object(context.active_object)
        return sprite_object is not None and sprite_object.type == "ARMATURE"

    def invoke(self, context, _event):
        target_object = _default_target(context)
        self.target_object_name = target_object.name if target_object else ""
        if target_object is not None:
            items = _shape_key_items(self, context)
            if items and items[0][0]:
                self.shape_key = items[0][0]
                self.label = items[0][0]
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "label")
        layout.prop(self, "axis", expand=True)
        layout.prop(self, "width")
        layout.prop_search(self, "target_object_name", bpy.data, "objects", text="Target")
        layout.prop(self, "shape_key")

    def execute(self, context):
        target_object = bpy.data.objects.get(self.target_object_name) or _default_target(
            context
        )
        self.target_object_name = target_object.name if target_object else ""
        shape_key = self.shape_key
        if target_object is not None and not shape_key:
            items = _shape_key_items(self, context)
            shape_key = items[0][0] if items else ""
        if target_object is None or not shape_key:
            self.report({"ERROR"}, "Select a Mesh with a non-Basis Shape Key.")
            return {"CANCELLED"}

        armature = functions.get_sprite_object(context.active_object)
        if armature is None or armature.type != "ARMATURE":
            self.report({"ERROR"}, "No SpriteObject Armature found.")
            return {"CANCELLED"}

        control_uuid = str(uuid.uuid4())
        control = armature.coa_tools2.rig_controls.add()
        control.control_uuid = control_uuid
        control.semantic_id = _semantic_id(self.label)
        control.label = self.label
        control.control_type = "SLIDER_1D"
        control.axis = self.axis
        control.width = self.width
        control.input_min = 0.0
        control.input_max = self.width

        binding = control.bindings.add()
        binding.binding_uuid = str(uuid.uuid4())
        binding.control_uuid = control_uuid
        binding.source_component = self.axis
        binding.target_kind = "SHAPE_KEY_VALUE"
        binding.target_object = target_object
        binding.target_name = shape_key
        binding.input_min = 0.0
        binding.input_max = self.width
        binding.output_min = 0.0
        binding.output_max = 1.0

        origin = armature.matrix_world.inverted() @ context.scene.cursor.location
        try:
            result = compile_control(armature, control, origin=origin)
        except Exception as exc:
            traceback.print_exc()
            armature.coa_tools2.rig_controls.remove(
                len(armature.coa_tools2.rig_controls) - 1
            )
            self.report({"ERROR"}, f"Rig control compile failed: {exc}")
            return {"CANCELLED"}

        armature.coa_tools2.rig_controls_index = len(
            armature.coa_tools2.rig_controls
        ) - 1
        if armature.mode != "POSE":
            bpy.context.view_layer.objects.active = armature
            armature.select_set(True)
            bpy.ops.object.mode_set(mode="POSE")
        for pose_bone in armature.pose.bones:
            if hasattr(pose_bone.bone, "select"):
                pose_bone.bone.select = pose_bone.name == result["control_bone"]
        armature.data.bones.active = armature.data.bones[result["control_bone"]]
        self.report({"INFO"}, f"Created rig control: {self.label}")
        return {"FINISHED"}


CLASSES = (COATOOLS2_OT_AddRigControl,)
