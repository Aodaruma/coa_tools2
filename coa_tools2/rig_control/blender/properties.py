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
            ("DIAL", "Dial", "Angular slider constrained to a visible rail"),
        ),
        default="SLIDER_1D",
        update=_mark_control_dirty,
    )
    axis: EnumProperty(
        items=(
            ("X", "Horizontal", "Move along local X"),
            ("Y", "Vertical", "Move along local Y"),
            ("ROTATION", "Angle", "Position along the dial rail"),
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
    rectangle_mode: EnumProperty(
        items=(
            (
                "FREE",
                "Free Interior",
                "Move freely anywhere inside the rectangular area",
            ),
            (
                "GRID",
                "Grid Rails",
                "Draw internal rails and keep the tip on the grid",
            ),
        ),
        default="FREE",
        update=_mark_control_dirty,
    )
    grid_columns: IntProperty(default=3, min=2, max=32, update=_mark_control_dirty)
    grid_rows: IntProperty(default=3, min=2, max=32, update=_mark_control_dirty)
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


class COATOOLS2_PG_RigObjectProperties(bpy.types.PropertyGroup):
    """Rig-only object data kept outside the shared COA ObjectProperties."""

    rig_instance_id: StringProperty()
    rig_controls: CollectionProperty(type=COATOOLS2_PG_RigControl)
    rig_controls_index: IntProperty(default=0, min=0)
    rig_validation_issues: CollectionProperty(type=COATOOLS2_PG_RigValidationIssue)
    rig_validation_issues_index: IntProperty(default=0, min=0)
    legacy_migration_checked: BoolProperty(default=False, options={"HIDDEN"})


_CONTROL_FIELDS = (
    "schema_version",
    "control_uuid",
    "semantic_id",
    "label",
    "control_type",
    "axis",
    "control_bone",
    "display_bone",
    "tip_widget_uuid",
    "base_widget_uuid",
    "width",
    "height",
    "radius",
    "rectangle_mode",
    "grid_columns",
    "grid_rows",
    "angle_min",
    "angle_max",
    "tip_radius",
    "node_radius",
    "bar_width",
    "stroke_radius",
    "input_min",
    "input_max",
    "widget_backend",
    "bindings_index",
    "origin",
    "needs_rebuild",
)
_BINDING_FIELDS = (
    "schema_version",
    "binding_uuid",
    "control_uuid",
    "source_component",
    "target_kind",
    "target_object",
    "target_bone",
    "target_name",
    "generated_data_path",
    "input_min",
    "input_max",
    "output_min",
    "output_max",
    "clamp",
    "enabled",
)
_ISSUE_FIELDS = (
    "severity",
    "code",
    "message",
    "control_uuid",
    "binding_uuid",
)
_MISSING = object()


def _copy_fields(source, target, field_names):
    for field_name in field_names:
        value = getattr(source, field_name, _MISSING)
        if value is _MISSING and hasattr(source, "get"):
            value = source.get(field_name, _MISSING)
        if value is _MISSING:
            continue
        rna_property = target.bl_rna.properties.get(field_name)
        if (
            rna_property is not None
            and rna_property.type == "ENUM"
            and isinstance(value, int)
        ):
            value = next(
                (
                    item.identifier
                    for item in rna_property.enum_items
                    if item.value == value
                ),
                _MISSING,
            )
            if value is _MISSING:
                continue
        setattr(target, field_name, value)


def _legacy_collection(owner, field_name):
    collection = getattr(owner, field_name, _MISSING)
    if collection is _MISSING and hasattr(owner, "get"):
        collection = owner.get(field_name, _MISSING)
    return None if collection is _MISSING else collection


def _legacy_value(owner, field_name, default=None):
    value = getattr(owner, field_name, _MISSING)
    if value is _MISSING and hasattr(owner, "get"):
        value = owner.get(field_name, _MISSING)
    return default if value is _MISSING else value


def _migrate_legacy_rig_data(obj, rig_data):
    """Copy definitions stored by commits before the dedicated RNA namespace."""

    if rig_data.legacy_migration_checked:
        return

    legacy = getattr(obj, "coa_tools2", None)
    legacy_controls = (
        _legacy_collection(legacy, "rig_controls") if legacy is not None else None
    )
    if legacy is None or legacy_controls is None:
        rig_data.legacy_migration_checked = True
        return
    if not rig_data.rig_instance_id:
        rig_data.rig_instance_id = _legacy_value(legacy, "rig_instance_id", "")

    if not rig_data.rig_controls:
        for legacy_control in legacy_controls:
            control = rig_data.rig_controls.add()
            _copy_fields(legacy_control, control, _CONTROL_FIELDS)
            for legacy_binding in _legacy_collection(
                legacy_control, "bindings"
            ) or ():
                binding = control.bindings.add()
                _copy_fields(legacy_binding, binding, _BINDING_FIELDS)
        if rig_data.rig_controls:
            rig_data.rig_controls_index = min(
                _legacy_value(legacy, "rig_controls_index", 0),
                len(rig_data.rig_controls) - 1,
            )

    legacy_issues = _legacy_collection(legacy, "rig_validation_issues")
    if not rig_data.rig_validation_issues and legacy_issues is not None:
        for legacy_issue in legacy_issues:
            issue = rig_data.rig_validation_issues.add()
            _copy_fields(legacy_issue, issue, _ISSUE_FIELDS)
    rig_data.legacy_migration_checked = True


def get_rig_data(obj):
    """Return collision-free rig data and lazily migrate the legacy layout."""

    rig_data = getattr(obj, "coa_tools2_rig", None)
    if rig_data is None:
        raise RuntimeError(
            "COA Tools 2 rig properties are not registered. "
            "Disable duplicate add-on installations and reload the add-on."
        )
    _migrate_legacy_rig_data(obj, rig_data)
    return rig_data


CLASSES = (
    COATOOLS2_PG_RigBinding,
    COATOOLS2_PG_RigValidationIssue,
    COATOOLS2_PG_RigControl,
    COATOOLS2_PG_RigObjectProperties,
)
