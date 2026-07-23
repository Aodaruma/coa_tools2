"""Operators for creating, binding, validating, and repairing rig controls."""

from __future__ import annotations

import math
import re
import traceback
import uuid

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty

from ... import functions
from .compiler import RigCompileError, compile_control
from .drivers import (
    BindingConflictError,
    binding_target_key,
    ensure_binding_driver,
    remove_binding_driver,
)
from .validation import store_validation_issues, validate_rig


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


def _armature(context):
    sprite_object = functions.get_sprite_object(context.active_object)
    if sprite_object is not None and sprite_object.type == "ARMATURE":
        return sprite_object
    return None


def _active_control(context):
    armature = _armature(context)
    if armature is None or not armature.coa_tools2.rig_controls:
        return armature, None
    index = min(
        armature.coa_tools2.rig_controls_index,
        len(armature.coa_tools2.rig_controls) - 1,
    )
    return armature, armature.coa_tools2.rig_controls[index]


def _binding_target_items(self, _context):
    target = bpy.data.objects.get(self.target_object_name)
    if target is None:
        return [("", "Missing Target", "Select a target object")]
    if self.target_kind == "SHAPE_KEY_VALUE":
        shape_keys = getattr(getattr(target, "data", None), "shape_keys", None)
        if shape_keys is None:
            return [("", "No Shape Keys", "Target has no Shape Keys")]
        items = [
            (key.name, key.name, f"Drive {key.name}")
            for key in shape_keys.key_blocks
            if key.name != "Basis"
        ]
        return items or [("", "No Shape Keys", "No non-Basis Shape Keys")]
    if target.type != "ARMATURE":
        return [("", "Not an Armature", "Constraint target must be an Armature")]
    pose_bone = target.pose.bones.get(self.target_bone)
    if pose_bone is None:
        return [("", "Choose Bone", "Select a pose bone")]
    items = [
        (constraint.name, constraint.name, f"Drive {constraint.name} influence")
        for constraint in pose_bone.constraints
    ]
    return items or [("", "No Constraints", "Bone has no constraints")]


def _target_bone_items(self, _context):
    target = bpy.data.objects.get(self.target_object_name)
    if target is None or target.type != "ARMATURE":
        return [("", "No Bones", "Select an Armature target")]
    return [(bone.name, bone.name, bone.name) for bone in target.pose.bones]


def _all_target_keys(armature):
    for control in armature.coa_tools2.rig_controls:
        for binding in control.bindings:
            yield binding_target_key(binding)


def _control_input_range(control, component):
    if control.control_type == "SLIDER_1D":
        return 0.0, control.width
    if control.control_type == "POINT_2D_RECT":
        return (0.0, control.height) if component == "Y" else (0.0, control.width)
    if control.control_type == "POINT_2D_CIRCLE":
        return -control.radius, control.radius
    if control.control_type == "DIAL":
        return control.angle_min, control.angle_max
    raise ValueError(f"Unsupported control type: {control.control_type}")


def _allowed_source_components(control):
    if control.control_type == "SLIDER_1D":
        return (control.axis,)
    if control.control_type in {"POINT_2D_RECT", "POINT_2D_CIRCLE"}:
        return ("X", "Y")
    if control.control_type == "DIAL":
        return ("ROTATION",)
    return ()


def _binding_source_items(_self, context):
    _armature_object, control = _active_control(context)
    allowed = _allowed_source_components(control) if control is not None else ()
    labels = {
        "X": ("X", "Control local X"),
        "Y": ("Y", "Control local Y"),
        "ROTATION": ("Rotation", "Control local Z rotation"),
    }
    return [
        (component, labels[component][0], labels[component][1])
        for component in allowed
    ] or [("X", "X", "Control local X")]


class COATOOLS2_OT_AddRigControl(bpy.types.Operator):
    bl_idname = "coa_tools2.add_rig_control"
    bl_label = "Add Rig Control"
    bl_description = "Create a Geometry Nodes control preset; bindings can be added later"
    bl_options = {"REGISTER", "UNDO"}

    label: StringProperty(default="Rig Control")
    control_type: EnumProperty(
        items=(
            ("SLIDER_1D", "1D Slider", "Linear slider"),
            ("POINT_2D_RECT", "2D Rectangle", "Rectangular 2D control"),
            ("POINT_2D_CIRCLE", "2D Circle", "Circular 2D control"),
            ("DIAL", "Dial", "Rotational dial"),
        ),
        default="SLIDER_1D",
    )
    axis: EnumProperty(
        items=(
            ("X", "Horizontal", "Horizontal 1D slider"),
            ("Y", "Vertical", "Vertical 1D slider"),
        ),
        default="X",
    )
    width: FloatProperty(default=4.0, min=0.1)
    height: FloatProperty(default=3.0, min=0.1)
    radius: FloatProperty(default=2.0, min=0.1)
    angle_min: FloatProperty(default=-math.pi * 0.5, subtype="ANGLE")
    angle_max: FloatProperty(default=math.pi * 0.5, subtype="ANGLE")
    source_component: EnumProperty(
        items=(
            ("X", "X", "Use local X as the initial binding source"),
            ("Y", "Y", "Use local Y as the initial binding source"),
        ),
        default="X",
    )
    create_initial_binding: BoolProperty(
        name="Create Initial Shape Key Binding",
        description="Optionally bind one Shape Key while creating the control",
        default=False,
    )
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
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "label")
        layout.prop(self, "control_type")
        if self.control_type == "SLIDER_1D":
            layout.prop(self, "axis", expand=True)
            layout.prop(self, "width")
        elif self.control_type == "POINT_2D_RECT":
            row = layout.row(align=True)
            row.prop(self, "width")
            row.prop(self, "height")
        elif self.control_type == "POINT_2D_CIRCLE":
            layout.prop(self, "radius")
        else:
            layout.prop(self, "radius")
            row = layout.row(align=True)
            row.prop(self, "angle_min")
            row.prop(self, "angle_max")
        layout.separator()
        layout.prop(self, "create_initial_binding")
        if self.create_initial_binding:
            if self.control_type in {"POINT_2D_RECT", "POINT_2D_CIRCLE"}:
                layout.prop(self, "source_component", expand=True)
            layout.prop_search(
                self,
                "target_object_name",
                bpy.data,
                "objects",
                text="Target",
            )
            layout.prop(self, "shape_key")

    def execute(self, context):
        armature = functions.get_sprite_object(context.active_object)
        if armature is None or armature.type != "ARMATURE":
            self.report({"ERROR"}, "No SpriteObject Armature found.")
            return {"CANCELLED"}

        target_object = None
        shape_key = ""
        if self.create_initial_binding:
            target_object = bpy.data.objects.get(
                self.target_object_name
            ) or _default_target(context)
            self.target_object_name = target_object.name if target_object else ""
            shape_key = self.shape_key
            if target_object is not None and not shape_key:
                items = _shape_key_items(self, context)
                shape_key = items[0][0] if items else ""
            if target_object is None or not shape_key:
                self.report({"ERROR"}, "Select a Mesh with a non-Basis Shape Key.")
                return {"CANCELLED"}

        control_uuid = str(uuid.uuid4())
        control = armature.coa_tools2.rig_controls.add()
        control.control_uuid = control_uuid
        control.semantic_id = _semantic_id(self.label)
        control.label = self.label
        control.control_type = self.control_type
        source_component = (
            "ROTATION"
            if self.control_type == "DIAL"
            else self.axis
            if self.control_type == "SLIDER_1D"
            else self.source_component
        )
        control.axis = source_component
        control.width = self.width
        control.height = self.height
        control.radius = self.radius
        control.angle_min = self.angle_min
        control.angle_max = self.angle_max
        control.input_min, control.input_max = _control_input_range(
            control,
            source_component,
        )

        if self.create_initial_binding:
            binding = control.bindings.add()
            binding.binding_uuid = str(uuid.uuid4())
            binding.control_uuid = control_uuid
            binding.source_component = source_component
            binding.target_kind = "SHAPE_KEY_VALUE"
            binding.target_object = target_object
            binding.target_name = shape_key
            binding.input_min = control.input_min
            binding.input_max = control.input_max
            binding.output_min = 0.0
            binding.output_max = 1.0

        origin = armature.matrix_world.inverted() @ context.scene.cursor.location
        control.origin = origin
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


class COATOOLS2_OT_AddRigBinding(bpy.types.Operator):
    bl_idname = "coa_tools2.add_rig_binding"
    bl_label = "Add Rig Binding"
    bl_description = "Bind the active control to another Shape Key or constraint"
    bl_options = {"REGISTER", "UNDO"}

    source_component: EnumProperty(items=_binding_source_items)
    target_kind: EnumProperty(
        items=(
            ("SHAPE_KEY_VALUE", "Shape Key", "Drive a Shape Key value"),
            (
                "CONSTRAINT_INFLUENCE",
                "Constraint Influence",
                "Drive a pose-bone constraint influence",
            ),
        ),
        default="SHAPE_KEY_VALUE",
    )
    target_object_name: StringProperty()
    target_bone: EnumProperty(items=_target_bone_items)
    target_name: EnumProperty(items=_binding_target_items)
    output_min: FloatProperty(default=0.0)
    output_max: FloatProperty(default=1.0)
    clamp: BoolProperty(default=True)

    @classmethod
    def poll(cls, context):
        _armature_object, control = _active_control(context)
        return control is not None

    def invoke(self, context, _event):
        _armature_object, control = _active_control(context)
        self.source_component = (
            "ROTATION"
            if control.control_type == "DIAL"
            else "Y"
            if control.axis == "Y"
            else "X"
        )
        target = _default_target(context)
        self.target_object_name = target.name if target else ""
        if target:
            items = _binding_target_items(self, context)
            if items and items[0][0]:
                self.target_name = items[0][0]
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "source_component", expand=True)
        layout.prop(self, "target_kind")
        layout.prop_search(self, "target_object_name", bpy.data, "objects", text="Target")
        if self.target_kind == "CONSTRAINT_INFLUENCE":
            layout.prop(self, "target_bone")
        layout.prop(self, "target_name")
        row = layout.row(align=True)
        row.prop(self, "output_min")
        row.prop(self, "output_max")
        layout.prop(self, "clamp")

    def execute(self, context):
        armature, control = _active_control(context)
        target = bpy.data.objects.get(self.target_object_name)
        if armature is None or control is None or target is None or not self.target_name:
            self.report({"ERROR"}, "Control and binding target are required.")
            return {"CANCELLED"}
        if self.source_component not in _allowed_source_components(control):
            self.report(
                {"ERROR"},
                f"{self.source_component} is not valid for {control.control_type}.",
            )
            return {"CANCELLED"}

        key = (
            self.target_kind,
            target.name,
            self.target_bone if self.target_kind == "CONSTRAINT_INFLUENCE" else "",
            self.target_name,
        )
        if key in set(_all_target_keys(armature)):
            self.report({"ERROR"}, "This target already has a rig binding.")
            return {"CANCELLED"}

        binding = control.bindings.add()
        binding.binding_uuid = str(uuid.uuid4())
        binding.control_uuid = control.control_uuid
        binding.source_component = self.source_component
        binding.target_kind = self.target_kind
        binding.target_object = target
        binding.target_bone = key[2]
        binding.target_name = self.target_name
        binding.input_min, binding.input_max = _control_input_range(
            control,
            self.source_component,
        )
        binding.output_min = self.output_min
        binding.output_max = self.output_max
        binding.clamp = self.clamp
        try:
            ensure_binding_driver(armature, control, binding)
        except (BindingConflictError, ValueError) as exc:
            control.bindings.remove(len(control.bindings) - 1)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        control.bindings_index = len(control.bindings) - 1
        self.report({"INFO"}, "Rig binding added.")
        return {"FINISHED"}


class COATOOLS2_OT_RemoveRigBinding(bpy.types.Operator):
    bl_idname = "coa_tools2.remove_rig_binding"
    bl_label = "Remove Rig Binding"
    bl_description = "Remove the selected binding and its managed driver"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        _armature_object, control = _active_control(context)
        return control is not None and bool(control.bindings)

    def execute(self, context):
        armature, control = _active_control(context)
        index = min(control.bindings_index, len(control.bindings) - 1)
        binding = control.bindings[index]
        remove_binding_driver(armature, control, binding)
        control.bindings.remove(index)
        control.bindings_index = max(0, min(index, len(control.bindings) - 1))
        return {"FINISHED"}


class COATOOLS2_OT_UpdateRigControl(bpy.types.Operator):
    bl_idname = "coa_tools2.update_rig_control"
    bl_label = "Update Rig Control"
    bl_description = "Recompile the active definition into managed Blender artifacts"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        _armature_object, control = _active_control(context)
        return control is not None

    def execute(self, context):
        armature, control = _active_control(context)
        try:
            compile_control(armature, control)
        except Exception as exc:
            traceback.print_exc()
            self.report({"ERROR"}, f"Rig update failed: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Updated {control.label}.")
        return {"FINISHED"}


class COATOOLS2_OT_ValidateRig(bpy.types.Operator):
    bl_idname = "coa_tools2.validate_rig"
    bl_label = "Validate Rig"
    bl_description = "Check definitions, generated artifacts, and drivers"

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None

    def execute(self, context):
        armature = _armature(context)
        issues = validate_rig(armature)
        store_validation_issues(armature, issues)
        if issues:
            self.report({"WARNING"}, f"Rig validation found {len(issues)} issue(s).")
        else:
            self.report({"INFO"}, "Rig validation passed.")
        return {"FINISHED"}


class COATOOLS2_OT_RepairRig(bpy.types.Operator):
    bl_idname = "coa_tools2.repair_rig"
    bl_label = "Repair Rig"
    bl_description = "Recreate missing managed artifacts without deleting user data"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None

    def execute(self, context):
        armature = _armature(context)
        failures = 0
        for control in armature.coa_tools2.rig_controls:
            try:
                compile_control(armature, control)
            except Exception:
                failures += 1
                traceback.print_exc()
        issues = validate_rig(armature)
        store_validation_issues(armature, issues)
        if failures or issues:
            self.report(
                {"WARNING"},
                f"Repair completed with {failures} compile failure(s) and {len(issues)} issue(s).",
            )
        else:
            self.report({"INFO"}, "Rig repaired and validated.")
        return {"FINISHED"}


CLASSES = (
    COATOOLS2_OT_AddRigControl,
    COATOOLS2_OT_AddRigBinding,
    COATOOLS2_OT_RemoveRigBinding,
    COATOOLS2_OT_UpdateRigControl,
    COATOOLS2_OT_ValidateRig,
    COATOOLS2_OT_RepairRig,
)
