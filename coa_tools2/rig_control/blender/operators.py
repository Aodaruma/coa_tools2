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
from .compiler import RigCompileError, compile_control, restore_control_artifacts
from .control_safety import (
    RigControlForkError,
    preflight_isolated_rig_control_mutation,
)
from .drivers import (
    BindingConflictError,
    binding_target_key,
    driver_uses_control,
    ensure_binding_driver,
    find_driver,
    remove_binding_driver,
)
from .properties import get_rig_data
from .selection import select_pose_bone
from .states import (
    ensure_state_cells,
    ensure_state_driver,
    remove_state_driver,
    state_dimensions,
    state_point_local_position,
    summarize_state_mix_policy,
    state_target_key,
)
from .validation import store_validation_issues, validate_rig
from ..schema import LipSyncPreset, lip_sync_preset_points, state_grid_size


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


def _active_control(context, *, migrate=True):
    armature = _armature(context)
    if armature is None:
        return armature, None
    rig_data = get_rig_data(armature, migrate=migrate)
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
    _armature_object, control = _active_control(context, migrate=False)
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


def _active_state_point(context, *, migrate=True):
    armature, control = _active_control(context, migrate=migrate)
    if control is None or not control.state_points:
        return armature, control, None
    index = min(control.state_points_index, len(control.state_points) - 1)
    return armature, control, control.state_points[index]


def _fallback_state_items(_self, context):
    _armature_object, control, point = _active_state_point(
        context,
        migrate=False,
    )
    items = [("AUTO", "Automatic Nearest", "Generate a safe nearest fallback edge")]
    if control is None or point is None:
        return items
    items.extend(
        (
            candidate.state_uuid,
            candidate.label or f"State {index + 1}",
            f"Fallback edge to {candidate.label or candidate.state_uuid}",
        )
        for index, candidate in enumerate(control.state_points)
        if candidate.enabled
        and candidate.state_uuid
        and candidate.state_uuid != point.state_uuid
    )
    return items


def _state_point_snapshot(point):
    return {
        "state_uuid": point.state_uuid,
        "control_uuid": point.control_uuid,
        "label": point.label,
        "column": point.column,
        "row": point.row,
        "target_object": point.target_object,
        "target_name": point.target_name,
        "target_name_candidates": point.target_name_candidates,
        "phoneme_aliases": point.phoneme_aliases,
        "generated_data_path": point.generated_data_path,
        "graph_position": tuple(point.graph_position),
        "point_shape": point.point_shape,
        "custom_object": point.custom_object,
        "fallback_state_uuid": point.fallback_state_uuid,
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
            point.graph_position = (
                column / max(columns - 1, 1),
                0.0 if rows == 1 else row / max(rows - 1, 1),
            )
    control.state_points_index = min(
        previous_index,
        len(control.state_points) - 1,
    )


def _default_graph_positions(count):
    count = max(2, int(count))
    if count == 2:
        return ((0.0, 0.5), (1.0, 0.5))
    if count == 3:
        return ((0.5, 0.0), (0.0, 1.0), (1.0, 1.0))
    if count == 4:
        return ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    return tuple(
        (
            0.5 + 0.5 * math.sin(math.tau * index / count),
            0.5 - 0.5 * math.cos(math.tau * index / count),
        )
        for index in range(count)
    )


def _replace_graph_points(control, count, snapshots=None):
    snapshots = tuple(snapshots or ())
    previous_index = control.state_points_index
    positions = _default_graph_positions(count)
    control.state_points.clear()
    for index in range(max(2, int(count))):
        point = control.state_points.add()
        if index < len(snapshots):
            _restore_state_point(point, snapshots[index])
        else:
            point.state_uuid = str(uuid.uuid4())
            point.label = f"State {index + 1}"
            point.graph_position = positions[index]
        point.control_uuid = control.control_uuid
        point.column = index
        point.row = 0
    if control.state_points:
        valid_ids = {point.state_uuid for point in control.state_points}
        for index, point in enumerate(control.state_points):
            if (
                not point.fallback_state_uuid
                or point.fallback_state_uuid == point.state_uuid
                or point.fallback_state_uuid not in valid_ids
            ):
                point.fallback_state_uuid = control.state_points[index - 1].state_uuid
    control.state_points_index = min(
        previous_index,
        max(0, len(control.state_points) - 1),
    )


def _state_cell_snapshot(cell):
    return {
        "cell_uuid": cell.cell_uuid,
        "control_uuid": cell.control_uuid,
        "column": cell.column,
        "row": cell.row,
        "mix_enabled": cell.mix_enabled,
    }


def _state_definition_snapshot(control):
    return {
        "state_mode": control.state_mode,
        "state_columns": control.state_columns,
        "state_rows": control.state_rows,
        "state_mix_policy": control.state_mix_policy,
        "state_points_index": control.state_points_index,
        "state_cells_index": control.state_cells_index,
        "rectangle_mode": control.rectangle_mode,
        "grid_columns": control.grid_columns,
        "grid_rows": control.grid_rows,
        "input_min": control.input_min,
        "input_max": control.input_max,
        "live_preview": control.live_preview,
        "needs_rebuild": control.needs_rebuild,
        "auto_rebuild_error": control.auto_rebuild_error,
        "points": tuple(
            _state_point_snapshot(point) for point in control.state_points
        ),
        "cells": tuple(
            _state_cell_snapshot(cell) for cell in control.state_cells
        ),
    }


def _restore_state_definition(control, snapshot):
    control.live_preview = False
    for name in (
        "state_mode",
        "state_columns",
        "state_rows",
        "state_mix_policy",
        "rectangle_mode",
        "grid_columns",
        "grid_rows",
        "input_min",
        "input_max",
    ):
        setattr(control, name, snapshot[name])
    control.state_points.clear()
    for values in snapshot["points"]:
        _restore_state_point(control.state_points.add(), values)
    control.state_cells.clear()
    for values in snapshot["cells"]:
        cell = control.state_cells.add()
        for name, value in values.items():
            setattr(cell, name, value)
    control.state_points_index = snapshot["state_points_index"]
    control.state_cells_index = snapshot["state_cells_index"]


def _state_setup_target_preflight(armature, control, retained_points):
    """Reject duplicates and unmanaged FCurves before resizing collections."""

    reserved = set()
    rig_data = get_rig_data(armature)
    for candidate in rig_data.rig_controls:
        for binding in candidate.bindings:
            if binding.enabled:
                reserved.add(binding_target_key(binding))
        if candidate.as_pointer() == control.as_pointer():
            continue
        for point in candidate.state_points:
            if point.enabled and not point.is_empty:
                reserved.add(state_target_key(point))

    for values in retained_points:
        target = values["target_object"]
        name = values["target_name"]
        if (
            not values["enabled"]
            or values["is_empty"]
            or target is None
            or not name
        ):
            continue
        key = ("SHAPE_KEY_VALUE", target.name, "", name)
        if key in reserved:
            raise BindingConflictError(
                f"State target is assigned more than once: {target.name} / {name}"
            )
        reserved.add(key)
        shape_keys = getattr(target.data, "shape_keys", None)
        if shape_keys is None or name not in shape_keys.key_blocks:
            raise ValueError(f"Shape Key not found: {target.name} / {name}")
        data_path = shape_keys.key_blocks[name].path_from_id("value")
        fcurve = find_driver(shape_keys, data_path)
        if fcurve is not None and not driver_uses_control(
            fcurve,
            armature,
            control.control_bone,
        ):
            raise BindingConflictError(
                f"State target has an unmanaged driver: {target.name} / {name}"
            )


def _cleanup_state_setup_artifacts(control, transaction):
    """Drop artifacts created only by a failed State layout transition."""

    control_uuid = str(control.control_uuid)
    widget_uuids = {
        str(control.tip_widget_uuid),
        str(control.base_widget_uuid),
    } - {""}
    for obj in tuple(bpy.data.objects):
        if obj.as_pointer() in transaction["objects"]:
            continue
        if (
            obj.get("coa_rig_control_uuid") == control_uuid
            or obj.get("coa_rig_widget_uuid") in widget_uuids
        ):
            bpy.data.objects.remove(obj, do_unlink=True)
    _remove_new_unused_datablocks(bpy.data.meshes, transaction["meshes"])
    _remove_new_unused_datablocks(bpy.data.curves, transaction["curves"])
    _remove_new_unused_datablocks(
        bpy.data.node_groups,
        transaction["node_groups"],
    )
    for collection in tuple(bpy.data.collections):
        if (
            collection.as_pointer() not in transaction["collections"]
            and not collection.objects
            and not collection.children
        ):
            bpy.data.collections.remove(collection)


def _replace_state_cells(control, columns, rows, snapshots=None):
    snapshots = snapshots or {}
    previous_index = control.state_cells_index
    default_enabled = control.state_mix_policy == "FULL"
    control.state_cells.clear()
    for row in range(max(0, rows - 1)):
        for column in range(max(0, columns - 1)):
            cell = control.state_cells.add()
            values = snapshots.get((column, row))
            cell.cell_uuid = (
                values["cell_uuid"]
                if values and values.get("cell_uuid")
                else str(uuid.uuid4())
            )
            cell.control_uuid = control.control_uuid
            cell.column = column
            cell.row = row
            cell.mix_enabled = (
                bool(values["mix_enabled"]) if values else default_enabled
            )
    control.state_cells_index = min(
        previous_index,
        max(0, len(control.state_cells) - 1),
    )
    control.state_mix_policy = summarize_state_mix_policy(control)


class COATOOLS2_OT_AddRigControl(bpy.types.Operator):
    bl_idname = "coa_tools2.add_rig_control"
    bl_label = "Add State Rig"
    bl_description = "Create a Geometry Nodes control preset; bindings can be added later"
    bl_options = {"REGISTER", "UNDO"}

    label: StringProperty(default="State Rig")
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
            (
                "GRAPH",
                "State Graph",
                "Arbitrary named points with a manual 2D handle",
            ),
        ),
        default="FREE",
    )
    grid_columns: IntProperty(default=3, min=2, max=32)
    grid_rows: IntProperty(default=3, min=2, max=32)
    matrix_mix_policy: EnumProperty(
        name="Mix Domain",
        items=(
            ("FULL", "Full", "Allow mixing inside every matrix cell"),
            ("NO_MIX", "Grid Only", "Keep the handle on matrix rails"),
        ),
        default="FULL",
    )
    graph_interpolation: EnumProperty(
        name="Graph Behavior",
        items=(
            ("NAMED_GRAPH", "Named Graph", "Move along fallback edges"),
            ("MAP_2D", "2D Map", "Blend freely across the control"),
            ("HYBRID", "Hybrid", "Combine a 2D map with fallback edges"),
        ),
        default="MAP_2D",
    )
    graph_points: IntProperty(default=4, min=2, max=32)
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
            if self.rectangle_mode == "MATRIX":
                layout.prop(self, "matrix_mix_policy", expand=True)
            elif self.rectangle_mode == "GRAPH":
                layout.prop(self, "graph_interpolation", expand=True)
                layout.prop(self, "graph_points")
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
        is_state_graph = (
            self.control_type == "POINT_2D_RECT"
            and self.rectangle_mode == "GRAPH"
        )
        if not (is_state_matrix or is_state_graph):
            layout.separator()
            layout.prop(self, "create_initial_binding")
        if self.create_initial_binding and not (is_state_matrix or is_state_graph):
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
        is_state_graph = (
            self.control_type == "POINT_2D_RECT"
            and self.rectangle_mode == "GRAPH"
        )
        if is_state_matrix or is_state_graph:
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
        control.rectangle_mode = (
            "FREE" if is_state_matrix or is_state_graph else self.rectangle_mode
        )
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
            control.state_mix_policy = self.matrix_mix_policy
            _replace_state_points(
                control,
                self.grid_columns,
                self.grid_rows,
            )
            _replace_state_cells(
                control,
                self.grid_columns,
                self.grid_rows,
            )
        elif is_state_graph:
            control.state_mode = "GRAPH_2D"
            control.graph_interpolation = self.graph_interpolation
            control.state_columns = self.graph_points
            control.state_rows = 1
            _replace_graph_points(control, self.graph_points)

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
        select_pose_bone(armature, result["control_bone"], exclusive=True)
        self.report({"INFO"}, f"Created rig control: {self.label}")
        return {"FINISHED"}


def _selected_mesh_target(context):
    active = context.active_object
    if active is not None and active.type == "MESH":
        return active
    return next(
        (obj for obj in context.selected_objects if obj.type == "MESH"),
        None,
    )


def _matching_shape_key_name(target, candidates):
    shape_keys = getattr(getattr(target, "data", None), "shape_keys", None)
    if shape_keys is None:
        return ""
    by_casefold = {
        key.name.casefold(): key.name
        for key in shape_keys.key_blocks
        if key.name != "Basis"
    }
    return next(
        (
            by_casefold[candidate.casefold()]
            for candidate in candidates
            if candidate.casefold() in by_casefold
        ),
        "",
    )


def _lip_target_preflight(armature, target, templates, match_existing):
    """Resolve every matched slot before creating a persisted control."""

    if target is None or not match_existing:
        return tuple("" for _template in templates)
    names = tuple(
        _matching_shape_key_name(target, template.target_name_candidates)
        for template in templates
    )
    assigned = tuple(name for name in names if name)
    if len(assigned) != len(set(assigned)):
        raise BindingConflictError(
            "Lip Sync preset resolves multiple states to the same Shape Key."
        )
    existing_targets = set(_all_target_keys(armature))
    shape_keys = target.data.shape_keys
    for name in assigned:
        target_key = ("SHAPE_KEY_VALUE", target.name, "", name)
        if target_key in existing_targets:
            raise BindingConflictError(
                f"Shape Key is already assigned to a Rig Control: {target.name} / {name}"
            )
        key_block = shape_keys.key_blocks[name]
        if find_driver(shape_keys, key_block.path_from_id("value")) is not None:
            raise BindingConflictError(
                f"Shape Key already has an unmanaged driver: {target.name} / {name}"
            )
    return names


def _control_transaction_snapshot(armature, shape_key_targets=()):
    """Capture Blender datablocks that a new ordinary control may create."""

    shape_key_targets = tuple(shape_key_targets)
    return {
        "bones": {bone.name for bone in armature.data.bones},
        "bone_collections": {
            collection.name for collection in armature.data.collections
        },
        "objects": {obj.as_pointer() for obj in bpy.data.objects},
        "meshes": {mesh.as_pointer() for mesh in bpy.data.meshes},
        "curves": {curve.as_pointer() for curve in bpy.data.curves},
        "node_groups": {group.as_pointer() for group in bpy.data.node_groups},
        "collections": {
            collection.as_pointer() for collection in bpy.data.collections
        },
        "shape_key_values": tuple(
            (target, name, float(target.data.shape_keys.key_blocks[name].value))
            for target, name in shape_key_targets
            if target is not None and name
        ),
        "shape_key_animation": tuple(
            (target.data.shape_keys, target.data.shape_keys.animation_data is not None)
            for target, _name in shape_key_targets
            if target is not None
        ),
    }


def _remove_new_unused_datablocks(collection, previous_pointers):
    for datablock in tuple(collection):
        if datablock.as_pointer() not in previous_pointers and datablock.users == 0:
            collection.remove(datablock)


def _rollback_new_rig_control(armature, rig_data, control, control_index, snapshot):
    """Remove every artifact that can be emitted before a failed Add Lip."""

    errors = []
    control_uuid = str(control.control_uuid)
    widget_uuids = {
        str(control.tip_widget_uuid),
        str(control.base_widget_uuid),
    } - {""}

    for binding in tuple(control.bindings):
        try:
            remove_binding_driver(armature, control, binding)
        except Exception as exc:  # Continue restoring the structural state.
            errors.append(exc)
    for point in tuple(control.state_points):
        try:
            remove_state_driver(armature, control, point)
        except Exception as exc:
            errors.append(exc)
    for target, name, value in snapshot["shape_key_values"]:
        try:
            target.data.shape_keys.key_blocks[name].value = value
        except Exception as exc:
            errors.append(exc)
    for shape_keys, had_animation_data in snapshot["shape_key_animation"]:
        animation_data = shape_keys.animation_data
        if (
            not had_animation_data
            and animation_data is not None
            and animation_data.action is None
            and not animation_data.drivers
            and not animation_data.nla_tracks
        ):
            try:
                shape_keys.animation_data_clear()
            except Exception as exc:
                errors.append(exc)

    for obj in tuple(bpy.data.objects):
        if obj.as_pointer() in snapshot["objects"]:
            continue
        if not (
            obj.get("coa_rig_control_uuid") == control_uuid
            or obj.get("coa_rig_widget_uuid") in widget_uuids
        ):
            continue
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception as exc:
            errors.append(exc)

    try:
        if bpy.context.active_object != armature:
            if bpy.context.active_object and bpy.context.active_object.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            armature.select_set(True)
            bpy.context.view_layer.objects.active = armature
        if armature.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.mode_set(mode="EDIT")
        for edit_bone in tuple(armature.data.edit_bones):
            if edit_bone.name not in snapshot["bones"]:
                armature.data.edit_bones.remove(edit_bone)
        bpy.ops.object.mode_set(mode="POSE")
    except Exception as exc:
        errors.append(exc)

    for collection in tuple(armature.data.collections):
        if (
            collection.name not in snapshot["bone_collections"]
            and not collection.bones
        ):
            try:
                armature.data.collections.remove(collection)
            except Exception as exc:
                errors.append(exc)

    try:
        _remove_new_unused_datablocks(bpy.data.meshes, snapshot["meshes"])
        _remove_new_unused_datablocks(bpy.data.curves, snapshot["curves"])
        _remove_new_unused_datablocks(
            bpy.data.node_groups,
            snapshot["node_groups"],
        )
    except Exception as exc:
        errors.append(exc)
    for collection in tuple(bpy.data.collections):
        if (
            collection.as_pointer() not in snapshot["collections"]
            and not collection.objects
            and not collection.children
        ):
            try:
                bpy.data.collections.remove(collection)
            except Exception as exc:
                errors.append(exc)

    try:
        if 0 <= control_index < len(rig_data.rig_controls):
            rig_data.rig_controls.remove(control_index)
        rig_data.rig_controls_index = min(
            rig_data.rig_controls_index,
            max(0, len(rig_data.rig_controls) - 1),
        )
    except Exception as exc:
        errors.append(exc)
    if errors:
        raise RuntimeError(
            "Rig Control rollback failed: "
            + "; ".join(str(error) for error in errors)
        )


class COATOOLS2_OT_AddLipSyncStateRig(bpy.types.Operator):
    bl_idname = "coa_tools2.add_lip_sync_state_rig"
    bl_label = "Add Lip Sync State Rig"
    bl_description = "Create a manual Graph State mouth control and empty target slots"
    bl_options = {"REGISTER", "UNDO"}

    label: StringProperty(default="Lip Sync")
    preset: EnumProperty(
        name="Preset",
        items=(
            ("MINIMAL", "Minimal", "REST, A/E, I, U/O"),
            ("JP_VOWELS", "JP Vowels", "REST plus A, I, U, E, O"),
            ("JP_VOWELS_MBP", "JP Vowels + MBP", "Japanese vowels and closed lips"),
            (
                "STANDARD_2D",
                "Standard 2D",
                "REST, MBP, ETC, E, AI, O, and U",
            ),
            (
                "ADVANCED_PHONEME",
                "Advanced Phoneme",
                "Standard visemes plus FV, L, W/Q alias mapping",
            ),
        ),
        default="JP_VOWELS_MBP",
    )
    include_optional: BoolProperty(
        name="Add FV / L / WQ",
        description="Add optional Standard 2D named states",
        default=False,
    )
    graph_interpolation: EnumProperty(
        name="Control Layout",
        items=(
            ("MAP_2D", "2D Mouth Map", "Move freely and mix nearby mouth states"),
            ("NAMED_GRAPH", "Named Graph", "Move only on fallback edges"),
            ("HYBRID", "Hybrid", "Blend the mouth map with graph fallbacks"),
        ),
        default="HYBRID",
    )
    width: FloatProperty(default=4.0, min=0.1)
    height: FloatProperty(default=2.4, min=0.1)
    target_object_name: StringProperty()
    match_existing_shape_keys: BoolProperty(
        name="Match Existing Shape Keys",
        description=(
            "Assign only Shape Keys whose names match a preset candidate; "
            "never create or rename Shape Keys"
        ),
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None

    def invoke(self, context, _event):
        target = _selected_mesh_target(context)
        self.target_object_name = target.name if target else ""
        return context.window_manager.invoke_props_dialog(self, width=440)

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "label")
        layout.prop(self, "preset")
        if self.preset == "STANDARD_2D":
            layout.prop(self, "include_optional")
        layout.prop(self, "graph_interpolation", expand=True)
        row = layout.row(align=True)
        row.prop(self, "width")
        row.prop(self, "height")
        layout.separator()
        layout.prop_search(
            self,
            "target_object_name",
            bpy.data,
            "objects",
            text="Optional Mouth Mesh",
        )
        layout.prop(self, "match_existing_shape_keys")
        info = layout.box()
        info.label(text="A manual viewport control is always created.", icon="BONE_DATA")
        info.label(text="No audio analysis or Shape Key creation is performed.")
        info.label(text="Unmatched states remain editable target slots.")

    def execute(self, context):
        armature = _armature(context)
        if armature is None:
            return {"CANCELLED"}
        target = bpy.data.objects.get(self.target_object_name)
        if target is not None and target.type != "MESH":
            self.report({"ERROR"}, "Optional mouth target must be a Mesh.")
            return {"CANCELLED"}

        templates = lip_sync_preset_points(
            LipSyncPreset(self.preset),
            include_optional=(
                self.include_optional or self.preset == "ADVANCED_PHONEME"
            ),
        )
        if len(templates) < 2:
            self.report({"ERROR"}, "Lip Sync preset has no usable named states.")
            return {"CANCELLED"}

        rig_data = get_rig_data(armature)
        try:
            matched_names = _lip_target_preflight(
                armature,
                target,
                templates,
                self.match_existing_shape_keys,
            )
        except (BindingConflictError, ValueError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        transaction = _control_transaction_snapshot(
            armature,
            tuple((target, name) for name in matched_names if name),
        )
        control_index = len(rig_data.rig_controls)
        control = rig_data.rig_controls.add()
        control.control_uuid = str(uuid.uuid4())
        # Nested property updates must not enqueue a half-built live preview.
        control.live_preview = False
        control.semantic_id = _semantic_id(self.label)
        control.label = self.label
        control.control_type = "POINT_2D_RECT"
        control.axis = "X"
        control.width = self.width
        control.height = self.height
        control.rectangle_mode = "FREE"
        control.state_mode = "GRAPH_2D"
        control.graph_interpolation = self.graph_interpolation
        control.graph_radius = 0.72
        control.lip_sync_preset = self.preset
        control.state_columns = len(templates)
        control.state_rows = 1
        control.input_min = 0.0
        control.input_max = self.width

        state_uuid_by_name = {}
        for index, template in enumerate(templates):
            point = control.state_points.add()
            point.state_uuid = str(uuid.uuid4())
            point.control_uuid = control.control_uuid
            point.label = template.name
            point.column = index
            point.row = 0
            point.graph_position = template.position
            point.point_shape = template.point_shape.value
            point.target_object = target
            point.target_name_candidates = ", ".join(
                template.target_name_candidates
            )
            point.phoneme_aliases = ", ".join(template.phoneme_aliases)
            point.target_name = matched_names[index]
            point.is_empty = False
            point.enabled = True
            state_uuid_by_name[template.name] = point.state_uuid
        for template in templates:
            state_uuid = state_uuid_by_name[template.name]
            point = next(
                item
                for item in control.state_points
                if item.state_uuid == state_uuid
            )
            fallback_uuid = state_uuid_by_name.get(template.fallback_name, "")
            point.fallback_state_uuid = (
                fallback_uuid if fallback_uuid != state_uuid else ""
            )

        rest_uuid = state_uuid_by_name.get(
            "REST",
            control.state_points[0].state_uuid,
        )

        origin = armature.matrix_world.inverted() @ context.scene.cursor.location
        control.origin = origin
        try:
            result = compile_control(armature, control, origin=origin)
        except Exception as exc:
            traceback.print_exc()
            rollback_error = None
            try:
                _rollback_new_rig_control(
                    armature,
                    rig_data,
                    control,
                    control_index,
                    transaction,
                )
            except Exception as cleanup_exc:
                traceback.print_exc()
                rollback_error = cleanup_exc
            message = f"Lip Sync State Rig compile failed: {exc}"
            if rollback_error is not None:
                message += f"; rollback failed: {rollback_error}"
            self.report({"ERROR"}, message)
            return {"CANCELLED"}

        control.state_points_index = next(
            index
            for index, point in enumerate(control.state_points)
            if point.state_uuid == rest_uuid
        )
        handle = armature.pose.bones.get(result["control_bone"])
        if handle is not None:
            rest = control.state_points[control.state_points_index]
            x, y = state_point_local_position(control, rest)
            handle.location.x = x
            handle.location.y = y
        rig_data.rig_controls_index = len(rig_data.rig_controls) - 1
        control.live_preview = True
        if armature.mode != "POSE":
            bpy.context.view_layer.objects.active = armature
            armature.select_set(True)
            bpy.ops.object.mode_set(mode="POSE")
        select_pose_bone(armature, result["control_bone"], exclusive=True)
        context.view_layer.update()
        self.report(
            {"INFO"},
            f"Created {self.preset} Lip Sync Graph with {len(templates)} slots.",
        )
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
        _armature_object, control = _active_control(context, migrate=False)
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
        help_box = layout.box()
        help_box.label(text="Source Channel is read from this control.")
        help_box.label(text="Target is the property receiving the value.")
        layout.prop(self, "source_component", text="Source Channel", expand=True)
        layout.prop(self, "target_kind", text="Target Type")
        layout.prop_search(
            self,
            "target_object_name",
            bpy.data,
            "objects",
            text="Target Object",
        )
        if self.target_kind == "CONSTRAINT_INFLUENCE":
            layout.prop(self, "target_bone", text="Target Bone")
            layout.prop(self, "target_name", text="Constraint")
        else:
            layout.prop(self, "target_name", text="Shape Key")
        layout.label(text="Output Range")
        row = layout.row(align=True)
        row.prop(self, "output_min")
        row.prop(self, "output_max")
        layout.prop(
            self,
            "clamp",
            text="Clamp result to the output range",
        )

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
        _armature_object, control = _active_control(context, migrate=False)
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
            ("GRAPH_2D", "2D Graph", "Arbitrary named points and fallback edges"),
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
        _armature_object, control = _active_control(context, migrate=False)
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
            self.columns = (
                len(control.state_points)
                if self.mode == "GRAPH_2D"
                else control.state_columns
            )
            self.rows = (
                1
                if self.mode in {"LINEAR_1D", "GRAPH_2D"}
                else max(2, control.state_rows)
            )
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "mode", expand=True)
        row = layout.row(align=True)
        row.prop(self, "columns", text="Points" if self.mode == "GRAPH_2D" else "Columns")
        if self.mode == "MATRIX_2D":
            row.prop(self, "rows")
        _armature_object, control = _active_control(context, migrate=False)
        columns, rows = state_grid_size(self.mode, self.columns, self.rows)
        removed = [
            point
            for index, point in enumerate(control.state_points)
            if point.enabled
            and not point.is_empty
            and point.target_object is not None
            and point.target_name
            and (
                (self.mode == "GRAPH_2D" and index >= columns)
                or (
                    self.mode != "GRAPH_2D"
                    and (point.column >= columns or point.row >= rows)
                )
            )
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
        if self.mode == "GRAPH_2D" and control.control_type != "POINT_2D_RECT":
            self.report({"ERROR"}, "2D State Graph requires a 2D Rectangle control.")
            return {"CANCELLED"}

        try:
            preflight_isolated_rig_control_mutation(armature)
        except RigControlForkError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        definition_snapshot = _state_definition_snapshot(control)
        transaction = _control_transaction_snapshot(armature)
        columns, rows = state_grid_size(self.mode, self.columns, self.rows)
        cell_snapshots = {
            (cell.column, cell.row): _state_cell_snapshot(cell)
            for cell in control.state_cells
        }
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
            for index, point in enumerate(control.state_points)
            if (
                (self.mode == "GRAPH_2D" and index >= columns)
                or (
                    self.mode != "GRAPH_2D"
                    and (point.column, point.row) not in expected
                )
            )
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
        if self.mode == "GRAPH_2D":
            ordered_snapshots = tuple(
                _state_point_snapshot(point) for point in control.state_points
            )
            retained_snapshots = ordered_snapshots[:columns]
        else:
            retained_snapshots = tuple(
                values
                for coordinate, values in snapshots.items()
                if coordinate in expected
            )
        try:
            _state_setup_target_preflight(
                armature,
                control,
                retained_snapshots,
            )
        except (BindingConflictError, ValueError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        control.live_preview = False
        try:
            for point in removed_assigned:
                remove_state_driver(armature, control, point)

            control.state_mode = self.mode
            control.state_columns = columns
            control.state_rows = rows
            if self.mode == "GRAPH_2D":
                _replace_graph_points(control, columns, ordered_snapshots)
            else:
                _replace_state_points(control, columns, rows, snapshots)
            if self.mode == "MATRIX_2D":
                _replace_state_cells(control, columns, rows, cell_snapshots)
            else:
                control.state_cells.clear()
                control.state_mix_policy = "FULL"
            compile_control(armature, control)
        except Exception as exc:
            traceback.print_exc()
            rollback_error = None
            try:
                _restore_state_definition(control, definition_snapshot)
                restore_control_artifacts(armature, control)
                _cleanup_state_setup_artifacts(control, transaction)
            except Exception as cleanup_exc:
                traceback.print_exc()
                rollback_error = cleanup_exc
            finally:
                control.needs_rebuild = definition_snapshot["needs_rebuild"]
                control.auto_rebuild_error = definition_snapshot[
                    "auto_rebuild_error"
                ]
                control.live_preview = definition_snapshot["live_preview"]
            message = f"State grid compile failed: {exc}"
            if rollback_error is not None:
                message += f"; rollback failed: {rollback_error}"
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        control.live_preview = definition_snapshot["live_preview"]
        self.report(
            {"INFO"},
            (
                f"State graph ready: {columns} named points."
                if self.mode == "GRAPH_2D"
                else f"State grid ready: {columns} x {rows}."
            ),
        )
        return {"FINISHED"}


class COATOOLS2_OT_SetRigStateMixPolicy(bpy.types.Operator):
    bl_idname = "coa_tools2.set_rig_state_mix_policy"
    bl_label = "Set Matrix Mix Domain"
    bl_description = "Allow mixing in all cells or keep the handle on grid rails"
    bl_options = {"REGISTER", "UNDO"}

    policy: EnumProperty(
        items=(
            ("FULL", "Full", "Allow mixing inside every matrix cell"),
            ("NO_MIX", "Grid Only", "Disable mixing inside every matrix cell"),
        ),
        default="FULL",
        options={"HIDDEN"},
    )

    @classmethod
    def poll(cls, context):
        _armature_object, control = _active_control(context, migrate=False)
        return control is not None and control.state_mode == "MATRIX_2D"

    def execute(self, context):
        armature, control = _active_control(context)
        ensure_state_cells(control)
        enabled = self.policy == "FULL"
        for cell in control.state_cells:
            cell.mix_enabled = enabled
        control.state_mix_policy = self.policy
        try:
            compile_control(armature, control)
        except Exception as exc:
            traceback.print_exc()
            self.report({"ERROR"}, f"Matrix domain update failed: {exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


class COATOOLS2_OT_ToggleRigStateCell(bpy.types.Operator):
    bl_idname = "coa_tools2.toggle_rig_state_cell"
    bl_label = "Toggle Matrix Cell Mix"
    bl_description = "Toggle free bilinear mixing inside this four-point cell"
    bl_options = {"REGISTER", "UNDO"}

    cell_uuid: StringProperty(options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        _armature_object, control = _active_control(context, migrate=False)
        return control is not None and control.state_mode == "MATRIX_2D"

    def execute(self, context):
        armature, control = _active_control(context)
        ensure_state_cells(control)
        cell = next(
            (
                candidate
                for candidate in control.state_cells
                if candidate.cell_uuid == self.cell_uuid
            ),
            None,
        )
        if cell is None:
            self.report({"ERROR"}, "Matrix cell was not found.")
            return {"CANCELLED"}
        cell.mix_enabled = not cell.mix_enabled
        control.state_mix_policy = summarize_state_mix_policy(control)
        try:
            compile_control(armature, control)
        except Exception as exc:
            traceback.print_exc()
            self.report({"ERROR"}, f"Matrix cell update failed: {exc}")
            return {"CANCELLED"}
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
        _armature_object, _control, point = _active_state_point(
            context,
            migrate=False,
        )
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
        _armature_object, _control, point = _active_state_point(
            context,
            migrate=False,
        )
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


class COATOOLS2_OT_SetRigStateFallback(bpy.types.Operator):
    bl_idname = "coa_tools2.set_rig_state_fallback"
    bl_label = "Set State Fallback Edge"
    bl_description = "Connect the selected named state to a fallback state"
    bl_options = {"REGISTER", "UNDO"}

    fallback_state_uuid: EnumProperty(
        name="Fallback State",
        items=_fallback_state_items,
    )

    @classmethod
    def poll(cls, context):
        _armature_object, control, point = _active_state_point(
            context,
            migrate=False,
        )
        return (
            control is not None
            and point is not None
            and control.state_mode == "GRAPH_2D"
        )

    def invoke(self, context, _event):
        _armature_object, _control, point = _active_state_point(context)
        choices = {item[0] for item in _fallback_state_items(self, context)}
        self.fallback_state_uuid = (
            point.fallback_state_uuid
            if point.fallback_state_uuid in choices
            else "AUTO"
        )
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        armature, control, point = _active_state_point(context)
        point.fallback_state_uuid = (
            "" if self.fallback_state_uuid == "AUTO" else self.fallback_state_uuid
        )
        try:
            compile_control(armature, control)
        except Exception as exc:
            self.report({"ERROR"}, f"Graph fallback update failed: {exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


class COATOOLS2_OT_SnapRigStatePoint(bpy.types.Operator):
    bl_idname = "coa_tools2.snap_rig_state_point"
    bl_label = "Snap to State Point"
    bl_description = "Move the control handle to the selected state point"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        armature, control, point = _active_state_point(
            context,
            migrate=False,
        )
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
        _armature_object, control = _active_control(context, migrate=False)
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
    COATOOLS2_OT_AddLipSyncStateRig,
    COATOOLS2_OT_AddRigBinding,
    COATOOLS2_OT_RemoveRigBinding,
    COATOOLS2_OT_SetupRigStates,
    COATOOLS2_OT_SetRigStateMixPolicy,
    COATOOLS2_OT_ToggleRigStateCell,
    COATOOLS2_OT_AssignRigStatePoint,
    COATOOLS2_OT_ClearRigStatePoint,
    COATOOLS2_OT_SetRigStateFallback,
    COATOOLS2_OT_SnapRigStatePoint,
    COATOOLS2_OT_UpdateRigControl,
    COATOOLS2_OT_ValidateRig,
    COATOOLS2_OT_RepairRig,
)
