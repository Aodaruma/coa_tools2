"""Operators for creating, binding, validating, and repairing rig controls."""

from __future__ import annotations

import math
import re
import traceback
import uuid

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)

from ... import functions
from .compiler import RigCompileError, compile_control
from .drivers import (
    BindingConflictError,
    binding_target_key,
    ensure_binding_driver,
    remove_binding_driver,
)
from .properties import get_rig_data
from .states import (
    ensure_state_driver,
    remove_state_driver,
    state_dimensions,
    state_point_local_position,
    state_target_key,
)
from .validation import store_validation_issues, validate_rig
from ..schema import state_grid_size


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
    if armature is None:
        return armature, None
    rig_data = get_rig_data(armature)
    if not rig_data.rig_controls:
        return armature, None
    index = min(
        rig_data.rig_controls_index,
        len(rig_data.rig_controls) - 1,
    )
    return armature, rig_data.rig_controls[index]


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


def _all_target_keys(armature, exclude_state_uuid=""):
    for control in get_rig_data(armature).rig_controls:
        for binding in control.bindings:
            yield binding_target_key(binding)
        for point in control.state_points:
            if point.state_uuid != exclude_state_uuid:
                yield state_target_key(point)


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
        "ROTATION": ("Angle", "Position along the dial rail"),
    }
    return [
        (component, labels[component][0], labels[component][1])
        for component in allowed
    ] or [("X", "X", "Control local X")]


def _active_state_point(context):
    armature, control = _active_control(context)
    if control is None or not control.state_points:
        return armature, control, None
    index = min(control.state_points_index, len(control.state_points) - 1)
    return armature, control, control.state_points[index]


def _state_point_snapshot(point):
    return {
        "state_uuid": point.state_uuid,
        "label": point.label,
        "target_object": point.target_object,
        "target_name": point.target_name,
        "generated_data_path": point.generated_data_path,
        "is_empty": point.is_empty,
        "enabled": point.enabled,
    }


def _restore_state_point(point, values):
    for name, value in values.items():
        setattr(point, name, value)


def _replace_state_points(control, columns, rows, snapshots=None):
    snapshots = snapshots or {}
    previous_index = control.state_points_index
    control.state_points.clear()
    for row in range(rows):
        for column in range(columns):
            point = control.state_points.add()
            values = snapshots.get((column, row))
            if values is not None:
                _restore_state_point(point, values)
            else:
                point.state_uuid = str(uuid.uuid4())
                point.label = (
                    f"State {column + 1}"
                    if rows == 1
                    else f"State {column + 1}, {row + 1}"
                )
            point.control_uuid = control.control_uuid
            point.column = column
            point.row = row
    control.state_points_index = min(
        previous_index,
        len(control.state_points) - 1,
    )


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
            ("DIAL", "Dial", "Angular control constrained to a visible rail"),
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
    rectangle_mode: EnumProperty(
        items=(
            ("FREE", "Free Interior", "Move freely inside the rectangular area"),
            ("GRID", "Grid Rails", "Move only along the displayed grid rails"),
            (
                "MATRIX",
                "State Matrix",
                "Continuously interpolate states inside the rectangle",
            ),
        ),
        default="FREE",
    )
    grid_columns: IntProperty(default=3, min=2, max=32)
    grid_rows: IntProperty(default=3, min=2, max=32)
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
            layout.prop(self, "rectangle_mode", expand=True)
            if self.rectangle_mode in {"GRID", "MATRIX"}:
                row = layout.row(align=True)
                row.prop(self, "grid_columns")
                row.prop(self, "grid_rows")
        elif self.control_type == "POINT_2D_CIRCLE":
            layout.prop(self, "radius")
        else:
            layout.prop(self, "radius")
            row = layout.row(align=True)
            row.prop(self, "angle_min")
            row.prop(self, "angle_max")
        is_state_matrix = (
            self.control_type == "POINT_2D_RECT"
            and self.rectangle_mode == "MATRIX"
        )
        if not is_state_matrix:
            layout.separator()
            layout.prop(self, "create_initial_binding")
        if self.create_initial_binding and not is_state_matrix:
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
        rig_data = get_rig_data(armature)

        is_state_matrix = (
            self.control_type == "POINT_2D_RECT"
            and self.rectangle_mode == "MATRIX"
        )
        if is_state_matrix:
            self.create_initial_binding = False

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
        control = rig_data.rig_controls.add()
        control.control_uuid = control_uuid
        control.semantic_id = _semantic_id(self.label)
        control.label = self.label
        control.control_type = self.control_type
        source_component = (
            "ROTATION"
            if control.control_type == "DIAL"
            else self.axis
            if control.control_type == "SLIDER_1D"
            else self.source_component
        )
        control.axis = source_component
        control.width = self.width
        control.height = self.height
        control.radius = self.radius
        control.rectangle_mode = "FREE" if is_state_matrix else self.rectangle_mode
        control.grid_columns = self.grid_columns
        control.grid_rows = self.grid_rows
        control.angle_min = self.angle_min
        control.angle_max = self.angle_max
        control.input_min, control.input_max = _control_input_range(
            control,
            source_component,
        )
        if is_state_matrix:
            control.state_mode = "MATRIX_2D"
            control.state_columns = self.grid_columns
            control.state_rows = self.grid_rows
            _replace_state_points(
                control,
                self.grid_columns,
                self.grid_rows,
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
            rig_data.rig_controls.remove(len(rig_data.rig_controls) - 1)
            self.report({"ERROR"}, f"Rig control compile failed: {exc}")
            return {"CANCELLED"}

        rig_data.rig_controls_index = len(rig_data.rig_controls) - 1
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


class COATOOLS2_OT_SetupRigStates(bpy.types.Operator):
    bl_idname = "coa_tools2.setup_rig_states"
    bl_label = "Set Up State Grid"
    bl_description = "Create or resize continuous Shape Key state points"
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(
        name="Mode",
        items=(
            ("LINEAR_1D", "1D States", "States along a 1D slider"),
            ("MATRIX_2D", "2D Matrix", "States on a rectangular grid"),
        ),
        default="MATRIX_2D",
    )
    columns: IntProperty(default=2, min=2, max=32)
    rows: IntProperty(default=2, min=1, max=32)
    confirm_remove_assigned: BoolProperty(
        name="Remove States Outside New Grid",
        description="Allow assigned points outside the resized grid to be removed",
        default=False,
    )
    preset: EnumProperty(
        items=(
            ("CUSTOM", "Custom", "Use the current dimensions"),
            ("2X2", "2 x 2", "Two columns and two rows"),
            ("3X2", "3 x 2", "Three columns and two rows"),
            ("2X4", "2 x 4", "Two columns and four rows"),
        ),
        default="CUSTOM",
        options={"HIDDEN"},
    )

    @classmethod
    def poll(cls, context):
        _armature_object, control = _active_control(context)
        return control is not None and control.control_type in {
            "SLIDER_1D",
            "POINT_2D_RECT",
        }

    def invoke(self, context, _event):
        _armature_object, control = _active_control(context)
        preset_dimensions = {
            "2X2": (2, 2),
            "3X2": (3, 2),
            "2X4": (2, 4),
        }
        if self.preset in preset_dimensions:
            self.mode = "MATRIX_2D"
            self.columns, self.rows = preset_dimensions[self.preset]
        else:
            self.mode = (
                control.state_mode
                if control.state_mode != "NONE"
                else "LINEAR_1D"
                if control.control_type == "SLIDER_1D"
                else "MATRIX_2D"
            )
            self.columns = control.state_columns
            self.rows = (
                1 if self.mode == "LINEAR_1D" else max(2, control.state_rows)
            )
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "mode", expand=True)
        row = layout.row(align=True)
        row.prop(self, "columns")
        if self.mode == "MATRIX_2D":
            row.prop(self, "rows")
        _armature_object, control = _active_control(context)
        columns, rows = state_grid_size(self.mode, self.columns, self.rows)
        removed = [
            point
            for point in control.state_points
            if point.enabled
            and not point.is_empty
            and point.target_object is not None
            and point.target_name
            and (point.column >= columns or point.row >= rows)
        ]
        if removed:
            box = layout.box()
            box.label(
                text=f"{len(removed)} assigned state(s) will be removed:",
                icon="ERROR",
            )
            for point in removed[:8]:
                box.label(
                    text=(
                        f"[{point.column + 1}, {point.row + 1}] "
                        f"{point.target_object.name} / {point.target_name}"
                    )
                )
            if len(removed) > 8:
                box.label(text=f"...and {len(removed) - 8} more")
            box.prop(self, "confirm_remove_assigned")

    def execute(self, context):
        armature, control = _active_control(context)
        if armature is None or control is None:
            return {"CANCELLED"}
        if self.mode == "LINEAR_1D" and control.control_type != "SLIDER_1D":
            self.report({"ERROR"}, "1D States require a 1D Slider control.")
            return {"CANCELLED"}
        if self.mode == "MATRIX_2D" and control.control_type != "POINT_2D_RECT":
            self.report({"ERROR"}, "2D State Matrix requires a 2D Rectangle control.")
            return {"CANCELLED"}

        columns, rows = state_grid_size(self.mode, self.columns, self.rows)
        expected = {
            (column, row)
            for row in range(rows)
            for column in range(columns)
        }
        snapshots = {
            (point.column, point.row): _state_point_snapshot(point)
            for point in control.state_points
        }
        removed_assigned = [
            point
            for point in control.state_points
            if (point.column, point.row) not in expected
            and point.enabled
            and not point.is_empty
            and point.target_object is not None
            and bool(point.target_name)
        ]
        if removed_assigned and not self.confirm_remove_assigned:
            self.report(
                {"ERROR"},
                f"Resize would remove {len(removed_assigned)} assigned state(s); "
                "enable the confirmation option.",
            )
            return {"CANCELLED"}
        for point in removed_assigned:
            remove_state_driver(armature, control, point)

        control.state_mode = self.mode
        control.state_columns = columns
        control.state_rows = rows
        _replace_state_points(control, columns, rows, snapshots)
        try:
            compile_control(armature, control)
        except Exception as exc:
            traceback.print_exc()
            self.report({"ERROR"}, f"State grid compile failed: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"State grid ready: {columns} x {rows}.")
        return {"FINISHED"}


class COATOOLS2_OT_AssignRigStatePoint(bpy.types.Operator):
    bl_idname = "coa_tools2.assign_rig_state_point"
    bl_label = "Assign State Point"
    bl_description = "Assign a Shape Key to the selected continuous state point"
    bl_options = {"REGISTER", "UNDO"}

    target_object_name: StringProperty()
    shape_key: EnumProperty(items=_shape_key_items)

    @classmethod
    def poll(cls, context):
        _armature_object, _control, point = _active_state_point(context)
        return point is not None

    def invoke(self, context, _event):
        _armature_object, _control, point = _active_state_point(context)
        target = point.target_object or _default_target(context)
        self.target_object_name = target.name if target else ""
        if target is not None:
            items = _shape_key_items(self, context)
            names = {item[0] for item in items}
            self.shape_key = (
                point.target_name
                if point.target_name in names
                else items[0][0]
                if items
                else ""
            )
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, _context):
        layout = self.layout
        layout.prop_search(
            self,
            "target_object_name",
            bpy.data,
            "objects",
            text="Target",
        )
        layout.prop(self, "shape_key")

    def execute(self, context):
        armature, control, point = _active_state_point(context)
        target = bpy.data.objects.get(self.target_object_name)
        if (
            armature is None
            or control is None
            or point is None
            or target is None
            or not self.shape_key
        ):
            self.report({"ERROR"}, "A Mesh and Shape Key are required.")
            return {"CANCELLED"}
        key = ("SHAPE_KEY_VALUE", target.name, "", self.shape_key)
        if key in set(_all_target_keys(armature, point.state_uuid)):
            self.report({"ERROR"}, "This target already has a rig binding or state.")
            return {"CANCELLED"}

        previous = _state_point_snapshot(point)
        remove_state_driver(armature, control, point)
        point.target_object = target
        point.target_name = self.shape_key
        point.generated_data_path = ""
        point.is_empty = False
        point.enabled = True
        try:
            ensure_state_driver(armature, control, point)
        except (BindingConflictError, ValueError) as exc:
            _restore_state_point(point, previous)
            try:
                ensure_state_driver(armature, control, point)
            except Exception:
                traceback.print_exc()
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"Assigned {target.name} / {self.shape_key}.",
        )
        return {"FINISHED"}


class COATOOLS2_OT_ClearRigStatePoint(bpy.types.Operator):
    bl_idname = "coa_tools2.clear_rig_state_point"
    bl_label = "Set Empty State"
    bl_description = "Remove the assigned driver and keep an intentional empty state"
    bl_options = {"REGISTER", "UNDO"}

    intentional: BoolProperty(default=True, options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        _armature_object, _control, point = _active_state_point(context)
        return point is not None

    def execute(self, context):
        armature, control, point = _active_state_point(context)
        remove_state_driver(armature, control, point)
        point.target_object = None
        point.target_name = ""
        point.generated_data_path = ""
        point.is_empty = self.intentional
        point.enabled = True
        return {"FINISHED"}


class COATOOLS2_OT_SnapRigStatePoint(bpy.types.Operator):
    bl_idname = "coa_tools2.snap_rig_state_point"
    bl_label = "Snap to State Point"
    bl_description = "Move the control handle to the selected state point"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        armature, control, point = _active_state_point(context)
        return (
            armature is not None
            and control is not None
            and point is not None
            and armature.pose.bones.get(control.control_bone) is not None
        )

    def execute(self, context):
        armature, control, point = _active_state_point(context)
        pose_bone = armature.pose.bones[control.control_bone]
        x, y = state_point_local_position(control, point)
        pose_bone.location.x = x
        pose_bone.location.y = y
        context.view_layer.update()
        self.report({"INFO"}, f"Snapped to [{point.column + 1}, {point.row + 1}].")
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
        for control in get_rig_data(armature).rig_controls:
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
    COATOOLS2_OT_SetupRigStates,
    COATOOLS2_OT_AssignRigStatePoint,
    COATOOLS2_OT_ClearRigStatePoint,
    COATOOLS2_OT_SnapRigStatePoint,
    COATOOLS2_OT_UpdateRigControl,
    COATOOLS2_OT_ValidateRig,
    COATOOLS2_OT_RepairRig,
)
