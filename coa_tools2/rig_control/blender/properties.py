"""Blender PropertyGroups used to persist rig-control definitions."""

from __future__ import annotations

import math

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from ..schema import SCHEMA_VERSION


def _mark_control_dirty(self, _context):
    self.needs_rebuild = True


class COATOOLS2_PG_RigBinding(bpy.types.PropertyGroup):
    schema_version: IntProperty(default=SCHEMA_VERSION)
    binding_uuid: StringProperty()
    control_uuid: StringProperty()
    source_component: EnumProperty(
        items=(
            ("X", "X", "Control local X"),
            ("Y", "Y", "Control local Y"),
            ("ROTATION", "Rotation", "Control local rotation"),
        ),
        default="X",
    )
    target_kind: EnumProperty(
        items=(
            ("SHAPE_KEY_VALUE", "Shape Key", "Drive a shape key value"),
            (
                "CONSTRAINT_INFLUENCE",
                "Constraint Influence",
                "Drive a pose-bone constraint influence",
            ),
        ),
        default="SHAPE_KEY_VALUE",
    )
    target_object: PointerProperty(type=bpy.types.Object)
    target_bone: StringProperty()
    target_name: StringProperty()
    generated_data_path: StringProperty()
    input_min: FloatProperty(default=0.0)
    input_max: FloatProperty(default=1.0)
    output_min: FloatProperty(default=0.0)
    output_max: FloatProperty(default=1.0)
    clamp: BoolProperty(default=True)
    enabled: BoolProperty(default=True)


class COATOOLS2_PG_RigValidationIssue(bpy.types.PropertyGroup):
    severity: EnumProperty(
        items=(
            ("ERROR", "Error", "Rig error"),
            ("WARNING", "Warning", "Rig warning"),
        ),
        default="ERROR",
    )
    code: StringProperty()
    message: StringProperty()
    control_uuid: StringProperty()
    binding_uuid: StringProperty()


class COATOOLS2_PG_RigControl(bpy.types.PropertyGroup):
    schema_version: IntProperty(default=SCHEMA_VERSION)
    control_uuid: StringProperty()
    semantic_id: StringProperty()
    label: StringProperty(default="Rig Control", update=_mark_control_dirty)
    control_type: EnumProperty(
        items=(
            ("SLIDER_1D", "1D Slider", "One-dimensional slider"),
            ("POINT_2D_RECT", "2D Rectangle", "Rectangular 2D slider"),
            ("POINT_2D_CIRCLE", "2D Circle", "Circular 2D slider"),
            ("DIAL", "Dial", "Rotational slider"),
        ),
        default="SLIDER_1D",
        update=_mark_control_dirty,
    )
    axis: EnumProperty(
        items=(
            ("X", "Horizontal", "Move along local X"),
            ("Y", "Vertical", "Move along local Y"),
            ("ROTATION", "Rotation", "Rotate in the control plane"),
        ),
        default="X",
        update=_mark_control_dirty,
    )
    control_bone: StringProperty()
    display_bone: StringProperty()
    tip_widget_uuid: StringProperty()
    base_widget_uuid: StringProperty()
    width: FloatProperty(default=4.0, min=0.1, update=_mark_control_dirty)
    height: FloatProperty(default=2.0, min=0.1, update=_mark_control_dirty)
    radius: FloatProperty(default=2.0, min=0.1, update=_mark_control_dirty)
    angle_min: FloatProperty(
        default=-math.pi * 0.5,
        subtype="ANGLE",
        update=_mark_control_dirty,
    )
    angle_max: FloatProperty(
        default=math.pi * 0.5,
        subtype="ANGLE",
        update=_mark_control_dirty,
    )
    tip_radius: FloatProperty(default=0.28, min=0.01, update=_mark_control_dirty)
    node_radius: FloatProperty(default=0.34, min=0.01, update=_mark_control_dirty)
    bar_width: FloatProperty(default=0.28, min=0.01, update=_mark_control_dirty)
    stroke_radius: FloatProperty(
        default=0.035,
        min=0.001,
        update=_mark_control_dirty,
    )
    input_min: FloatProperty(default=0.0)
    input_max: FloatProperty(default=4.0)
    widget_backend: EnumProperty(
        items=(
            (
                "EVALUATED_MESH_CACHE",
                "Evaluated Mesh Cache",
                "Use a cached Mesh generated from Geometry Nodes",
            ),
            (
                "LIVE_MODIFIER",
                "Live Modifier",
                "Use the Geometry Nodes modifier object directly",
            ),
        ),
        default="EVALUATED_MESH_CACHE",
        update=_mark_control_dirty,
    )
    bindings: CollectionProperty(type=COATOOLS2_PG_RigBinding)
    bindings_index: IntProperty(default=0, min=0)
    origin: FloatVectorProperty(size=3, subtype="XYZ")
    needs_rebuild: BoolProperty(default=False)


CLASSES = (
    COATOOLS2_PG_RigBinding,
    COATOOLS2_PG_RigValidationIssue,
    COATOOLS2_PG_RigControl,
)
