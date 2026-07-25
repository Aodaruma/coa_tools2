"""Blender PropertyGroups used to persist rig-control definitions."""

from __future__ import annotations

import math
import time
import traceback

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


AUTO_REBUILD_DELAY = 0.35
_PENDING_REBUILDS: dict[tuple[str, str], float] = {}
_AUTO_REBUILD_ACTIVE = False
_LAST_ACTIVE_RIG_BONE: tuple[int, str] | None = None


def _find_control(armature, control_uuid):
    rig_data = getattr(armature, "coa_tools2_rig", None)
    if rig_data is None:
        return None
    return next(
        (
            control
            for control in rig_data.rig_controls
            if control.control_uuid == control_uuid
        ),
        None,
    )


def _flush_auto_rebuilds():
    global _AUTO_REBUILD_ACTIVE

    now = time.monotonic()
    due = [
        key
        for key, changed_at in _PENDING_REBUILDS.items()
        if now - changed_at >= AUTO_REBUILD_DELAY
    ]
    if not due:
        return 0.1 if _PENDING_REBUILDS else None

    from .compiler import compile_control

    for key in due:
        _PENDING_REBUILDS.pop(key, None)
        armature_name, control_uuid = key
        armature = bpy.data.objects.get(armature_name)
        if armature is None or armature.type != "ARMATURE":
            continue
        control = _find_control(armature, control_uuid)
        if control is None or not control.needs_rebuild:
            continue
        try:
            _AUTO_REBUILD_ACTIVE = True
            compile_control(armature, control)
        except Exception as exc:
            traceback.print_exc()
            control.auto_rebuild_error = str(exc)
            control.needs_rebuild = True
        finally:
            _AUTO_REBUILD_ACTIVE = False
    return 0.1 if _PENDING_REBUILDS else None


def _schedule_auto_rebuild(control):
    armature = getattr(control, "id_data", None)
    if (
        armature is None
        or not isinstance(armature, bpy.types.Object)
        or armature.type != "ARMATURE"
        or not control.control_uuid
        or not control.live_preview
    ):
        return
    _PENDING_REBUILDS[(armature.name, control.control_uuid)] = time.monotonic()
    if not bpy.app.timers.is_registered(_flush_auto_rebuilds):
        bpy.app.timers.register(
            _flush_auto_rebuilds,
            first_interval=AUTO_REBUILD_DELAY,
        )


def _mark_control_dirty(self, _context):
    if _AUTO_REBUILD_ACTIVE:
        return
    self.needs_rebuild = True
    self.auto_rebuild_error = ""
    _schedule_auto_rebuild(self)


def _update_live_preview(self, _context):
    armature = getattr(self, "id_data", None)
    key = (
        (armature.name, self.control_uuid)
        if isinstance(armature, bpy.types.Object) and self.control_uuid
        else None
    )
    if not self.live_preview:
        if key is not None:
            _PENDING_REBUILDS.pop(key, None)
        return
    if self.needs_rebuild:
        _schedule_auto_rebuild(self)


def cancel_auto_rebuild():
    _PENDING_REBUILDS.clear()
    if bpy.app.timers.is_registered(_flush_auto_rebuilds):
        bpy.app.timers.unregister(_flush_auto_rebuilds)


def flush_auto_rebuilds_now():
    """Compile pending definitions immediately; primarily useful for tests."""

    for key in tuple(_PENDING_REBUILDS):
        _PENDING_REBUILDS[key] = 0.0
    return _flush_auto_rebuilds()


def _poll_active_rig_bone():
    global _LAST_ACTIVE_RIG_BONE

    armature = bpy.context.active_object
    if armature is None or armature.type != "ARMATURE":
        _LAST_ACTIVE_RIG_BONE = None
        return 0.15
    active_bone = armature.data.bones.active
    if active_bone is None:
        _LAST_ACTIVE_RIG_BONE = None
        return 0.15
    token = (armature.as_pointer(), active_bone.name)
    if token == _LAST_ACTIVE_RIG_BONE:
        return 0.15
    _LAST_ACTIVE_RIG_BONE = token

    from .ui import sync_control_index_from_active_bone

    sync_control_index_from_active_bone(
        armature,
        getattr(armature, "coa_tools2_rig", None),
    )
    return 0.15


def start_selection_sync():
    if not bpy.app.timers.is_registered(_poll_active_rig_bone):
        bpy.app.timers.register(_poll_active_rig_bone, first_interval=0.15)


def cancel_selection_sync():
    global _LAST_ACTIVE_RIG_BONE

    _LAST_ACTIVE_RIG_BONE = None
    if bpy.app.timers.is_registered(_poll_active_rig_bone):
        bpy.app.timers.unregister(_poll_active_rig_bone)


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


class COATOOLS2_PG_RigStatePoint(bpy.types.PropertyGroup):
    schema_version: IntProperty(default=SCHEMA_VERSION)
    state_uuid: StringProperty()
    control_uuid: StringProperty()
    label: StringProperty()
    column: IntProperty(default=0, min=0)
    row: IntProperty(default=0, min=0)
    target_object: PointerProperty(type=bpy.types.Object)
    target_name: StringProperty()
    generated_data_path: StringProperty()
    is_empty: BoolProperty(
        name="Empty State",
        description="Keep this point intentionally empty without a validation warning",
        default=False,
    )
    enabled: BoolProperty(default=True)


class COATOOLS2_PG_RigStateCell(bpy.types.PropertyGroup):
    schema_version: IntProperty(default=SCHEMA_VERSION)
    cell_uuid: StringProperty()
    control_uuid: StringProperty()
    column: IntProperty(default=0, min=0)
    row: IntProperty(default=0, min=0)
    mix_enabled: BoolProperty(
        name="Allow Mix",
        description="Allow free bilinear mixing inside this four-point cell",
        default=True,
    )


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
    name_bone: StringProperty()
    name_text_object: StringProperty()
    show_name: BoolProperty(
        name="Show Rig Name",
        description="Show the control name below the widget",
        default=True,
        update=_mark_control_dirty,
    )
    name_offset: FloatProperty(
        name="Name Offset",
        description="Distance between the widget bottom and its name",
        default=0.75,
        min=0.0,
        update=_mark_control_dirty,
    )
    name_size: FloatProperty(
        name="Name Size",
        description="Viewport text size for the rig control name",
        default=0.4,
        min=0.05,
        update=_mark_control_dirty,
    )
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
    tip_radius: FloatProperty(default=0.68, min=0.01, update=_mark_control_dirty)
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
    live_preview: BoolProperty(
        name="Live Preview",
        description=(
            "Automatically rebuild shortly after a Rig Control parameter changes"
        ),
        default=True,
        update=_update_live_preview,
    )
    bindings: CollectionProperty(type=COATOOLS2_PG_RigBinding)
    bindings_index: IntProperty(default=0, min=0)
    state_mode: EnumProperty(
        name="State Mode",
        items=(
            ("NONE", "None", "Use ordinary bindings only"),
            (
                "LINEAR_1D",
                "1D States",
                "Interpolate Shape Key states along a 1D slider",
            ),
            (
                "MATRIX_2D",
                "2D State Matrix",
                "Interpolate Shape Key states on an arbitrary grid",
            ),
        ),
        default="NONE",
        update=_mark_control_dirty,
    )
    state_mix_policy: EnumProperty(
        name="Mix Domain",
        items=(
            ("FULL", "Full", "Allow continuous mixing in every cell"),
            ("NO_MIX", "Grid Only", "Keep the handle on state grid rails"),
            (
                "PARTIAL",
                "Per Cell",
                "Allow mixing only in selected four-point cells",
            ),
        ),
        default="FULL",
    )
    state_columns: IntProperty(default=2, min=2, max=32, update=_mark_control_dirty)
    state_rows: IntProperty(default=2, min=1, max=32, update=_mark_control_dirty)
    state_points: CollectionProperty(type=COATOOLS2_PG_RigStatePoint)
    state_points_index: IntProperty(default=0, min=0)
    state_cells: CollectionProperty(type=COATOOLS2_PG_RigStateCell)
    state_cells_index: IntProperty(default=0, min=0)
    origin: FloatVectorProperty(size=3, subtype="XYZ")
    needs_rebuild: BoolProperty(default=False)
    auto_rebuild_error: StringProperty()


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
    "name_bone",
    "name_text_object",
    "show_name",
    "name_offset",
    "name_size",
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
    "live_preview",
    "bindings_index",
    "state_mode",
    "state_mix_policy",
    "state_columns",
    "state_rows",
    "state_points_index",
    "state_cells_index",
    "origin",
    "needs_rebuild",
    "auto_rebuild_error",
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
_STATE_POINT_FIELDS = (
    "schema_version",
    "state_uuid",
    "control_uuid",
    "label",
    "column",
    "row",
    "target_object",
    "target_name",
    "generated_data_path",
    "is_empty",
    "enabled",
)
_STATE_CELL_FIELDS = (
    "schema_version",
    "cell_uuid",
    "control_uuid",
    "column",
    "row",
    "mix_enabled",
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
            for legacy_state in _legacy_collection(
                legacy_control, "state_points"
            ) or ():
                state = control.state_points.add()
                _copy_fields(legacy_state, state, _STATE_POINT_FIELDS)
            for legacy_cell in _legacy_collection(
                legacy_control, "state_cells"
            ) or ():
                cell = control.state_cells.add()
                _copy_fields(legacy_cell, cell, _STATE_CELL_FIELDS)
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
    COATOOLS2_PG_RigStatePoint,
    COATOOLS2_PG_RigStateCell,
    COATOOLS2_PG_RigControl,
    COATOOLS2_PG_RigObjectProperties,
)
