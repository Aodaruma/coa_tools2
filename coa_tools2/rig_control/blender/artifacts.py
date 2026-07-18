"""Creation and lookup of Blender rig-control artifacts."""

from __future__ import annotations

import re
import uuid

import bpy
from mathutils import Vector

from ... import functions
from ..schema import WidgetBackend, WidgetLayout, WidgetSpec
from .widgets import ensure_widget


GLOBAL_CONTROL_BONE = "GLOBAL_CTRL"
CONTROL_COLLECTION = "COA Rig Controls"
DISPLAY_COLLECTION = "COA Rig Display"


def slugify(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z_]+", "_", value.strip()).strip("_")
    return slug or "control"


def ensure_rig_instance_id(armature: bpy.types.Object) -> str:
    instance_id = armature.coa_tools2.rig_instance_id
    if not instance_id:
        instance_id = str(uuid.uuid4())
        armature.coa_tools2.rig_instance_id = instance_id
    return instance_id


def find_bone_by_role(armature, control_uuid: str, role: str):
    for bone in armature.data.bones:
        if (
            bone.get("coa_rig_control_uuid") == control_uuid
            and bone.get("coa_rig_artifact_role") == role
        ):
            return bone
    return None


def _switch_to_edit_mode(armature):
    if bpy.context.active_object != armature:
        for selected in list(bpy.context.selected_objects):
            selected.select_set(False)
        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature
    if armature.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.mode_set(mode="EDIT")


def _ensure_global_bone(armature):
    if GLOBAL_CONTROL_BONE in armature.data.bones:
        return
    bone = armature.data.edit_bones.new(GLOBAL_CONTROL_BONE)
    bone.head = (0.0, 0.0, 0.0)
    bone.tail = (0.0, 0.0, 1.0)
    bone.use_deform = False


def ensure_control_bones(
    armature: bpy.types.Object,
    control,
    origin: Vector | tuple[float, float, float],
):
    origin = Vector(origin)
    existing_display = find_bone_by_role(armature, control.control_uuid, "display_bone")
    existing_control = find_bone_by_role(armature, control.control_uuid, "control_bone")
    existing_display_name = existing_display.name if existing_display else ""
    existing_control_name = existing_control.name if existing_control else ""

    _switch_to_edit_mode(armature)
    _ensure_global_bone(armature)
    global_bone = armature.data.edit_bones[GLOBAL_CONTROL_BONE]

    slug = slugify(control.semantic_id or control.label)
    display_name = existing_display_name or control.display_bone or f"DISP_{slug}"
    control_name = existing_control_name or control.control_bone or f"CTRL_{slug}"

    display = armature.data.edit_bones.get(display_name)
    if display is None:
        display = armature.data.edit_bones.new(display_name)
    display.head = origin
    display.tail = origin + Vector((0.0, 0.0, 1.0))
    display.parent = global_bone
    display.use_connect = False
    display.use_deform = False

    handle_origin = origin.copy()
    if control.control_type == "SLIDER_1D":
        if control.axis == "Y":
            handle_origin.z -= control.width * 0.5
        else:
            handle_origin.x -= control.width * 0.5
    elif control.control_type == "POINT_2D_RECT":
        handle_origin.x -= control.width * 0.5
        handle_origin.z -= control.height * 0.5

    handle = armature.data.edit_bones.get(control_name)
    if handle is None:
        handle = armature.data.edit_bones.new(control_name)
    handle.head = handle_origin
    handle.tail = handle_origin + Vector((0.0, 0.0, 1.0))
    handle.parent = global_bone
    handle.use_connect = False
    handle.use_deform = False

    display_name = display.name
    handle_name = handle.name
    bpy.ops.object.mode_set(mode="POSE")
    display_pose = armature.pose.bones[display_name]
    control_pose = armature.pose.bones[handle_name]

    for pose_bone, role in (
        (display_pose, "display_bone"),
        (control_pose, "control_bone"),
    ):
        data_bone = pose_bone.bone
        data_bone["coa_rig_managed"] = True
        data_bone["coa_rig_instance_id"] = ensure_rig_instance_id(armature)
        data_bone["coa_rig_control_uuid"] = control.control_uuid
        data_bone["coa_rig_artifact_role"] = role
        data_bone.use_deform = False

    display_pose.bone.hide_select = True
    functions.set_bone_group(
        None,
        armature,
        display_pose,
        group=DISPLAY_COLLECTION,
        theme="THEME03",
        visible=True,
        exclusive=True,
    )
    functions.set_bone_group(
        None,
        armature,
        control_pose,
        group=CONTROL_COLLECTION,
        theme="THEME04",
        visible=True,
        exclusive=True,
    )

    control.display_bone = display_pose.name
    control.control_bone = control_pose.name
    return display_pose, control_pose


def limit_location_name(control_uuid: str) -> str:
    return f"COA_{control_uuid[:8]}_LimitLocation"


def limit_distance_name(control_uuid: str) -> str:
    return f"COA_{control_uuid[:8]}_LimitDistance"


def limit_rotation_name(control_uuid: str) -> str:
    return f"COA_{control_uuid[:8]}_LimitRotation"


def ensure_limit_location(control_pose, control):
    constraint_name = limit_location_name(control.control_uuid)
    constraint = control_pose.constraints.get(constraint_name)
    if constraint is None:
        constraint = control_pose.constraints.new("LIMIT_LOCATION")
    constraint.name = constraint_name
    constraint.owner_space = "LOCAL"
    constraint.use_transform_limit = True

    for axis in "xyz":
        setattr(constraint, f"use_min_{axis}", False)
        setattr(constraint, f"use_max_{axis}", False)
        setattr(constraint, f"min_{axis}", 0.0)
        setattr(constraint, f"max_{axis}", 0.0)
    constraint.use_min_z = True
    constraint.use_max_z = True

    if control.control_type == "SLIDER_1D":
        axis = "y" if control.axis == "Y" else "x"
        setattr(constraint, f"use_min_{axis}", True)
        setattr(constraint, f"use_max_{axis}", True)
        setattr(constraint, f"max_{axis}", control.width)
        control.input_min = 0.0
        control.input_max = control.width
    elif control.control_type == "POINT_2D_RECT":
        constraint.use_min_x = True
        constraint.use_max_x = True
        constraint.max_x = control.width
        constraint.use_min_y = True
        constraint.use_max_y = True
        constraint.max_y = control.height
        control.input_min = 0.0
        control.input_max = control.height if control.axis == "Y" else control.width
    elif control.control_type == "POINT_2D_CIRCLE":
        control.input_min = -control.radius
        control.input_max = control.radius
    elif control.control_type == "DIAL":
        constraint.use_min_x = True
        constraint.use_max_x = True
        constraint.use_min_y = True
        constraint.use_max_y = True
        control.input_min = control.angle_min
        control.input_max = control.angle_max
    return constraint


def ensure_control_constraints(armature, display_pose, control_pose, control):
    expected = {limit_location_name(control.control_uuid)}
    if control.control_type == "POINT_2D_CIRCLE":
        expected.add(limit_distance_name(control.control_uuid))
    elif control.control_type == "DIAL":
        expected.add(limit_rotation_name(control.control_uuid))

    managed_names = {
        limit_location_name(control.control_uuid),
        limit_distance_name(control.control_uuid),
        limit_rotation_name(control.control_uuid),
    }
    for constraint in list(control_pose.constraints):
        if constraint.name in managed_names and constraint.name not in expected:
            control_pose.constraints.remove(constraint)

    ensure_limit_location(control_pose, control)
    if control.control_type == "POINT_2D_CIRCLE":
        name = limit_distance_name(control.control_uuid)
        constraint = control_pose.constraints.get(name)
        if constraint is None or constraint.type != "LIMIT_DISTANCE":
            if constraint is not None:
                control_pose.constraints.remove(constraint)
            constraint = control_pose.constraints.new("LIMIT_DISTANCE")
        constraint.name = name
        constraint.target = armature
        constraint.subtarget = display_pose.name
        constraint.distance = control.radius
        constraint.limit_mode = "LIMITDIST_INSIDE"
        constraint.owner_space = "WORLD"
        constraint.target_space = "WORLD"
    elif control.control_type == "DIAL":
        name = limit_rotation_name(control.control_uuid)
        constraint = control_pose.constraints.get(name)
        if constraint is None or constraint.type != "LIMIT_ROTATION":
            if constraint is not None:
                control_pose.constraints.remove(constraint)
            constraint = control_pose.constraints.new("LIMIT_ROTATION")
        constraint.name = name
        constraint.owner_space = "LOCAL"
        constraint.use_transform_limit = True
        for axis in "xyz":
            setattr(constraint, f"use_limit_{axis}", True)
            setattr(constraint, f"min_{axis}", 0.0)
            setattr(constraint, f"max_{axis}", 0.0)
        constraint.min_z = control.angle_min
        constraint.max_z = control.angle_max
        control_pose.rotation_mode = "XYZ"


def ensure_control_widgets(display_pose, control_pose, control):
    if not control.tip_widget_uuid:
        control.tip_widget_uuid = str(uuid.uuid4())
    if not control.base_widget_uuid:
        control.base_widget_uuid = str(uuid.uuid4())
    backend = WidgetBackend(control.widget_backend)

    tip_spec = WidgetSpec(
        widget_uuid=control.tip_widget_uuid,
        layout=WidgetLayout.TIP,
        tip_radius=control.tip_radius,
        node_radius=control.node_radius,
        bar_width=control.bar_width,
        stroke_radius=control.stroke_radius,
    )
    layout_by_type = {
        "SLIDER_1D": WidgetLayout.LINEAR,
        "POINT_2D_RECT": WidgetLayout.RECTANGLE,
        "POINT_2D_CIRCLE": WidgetLayout.CIRCLE,
        "DIAL": WidgetLayout.DIAL,
    }
    base_spec = WidgetSpec(
        widget_uuid=control.base_widget_uuid,
        layout=layout_by_type[control.control_type],
        width=control.width,
        height=control.height,
        radius=control.radius,
        tip_radius=control.tip_radius,
        node_radius=control.node_radius,
        bar_width=control.bar_width,
        stroke_radius=control.stroke_radius,
    )
    tip = ensure_widget(tip_spec, name=f"WGT_{control.semantic_id}_TIP", backend=backend)
    base = ensure_widget(
        base_spec,
        name=f"WGT_{control.semantic_id}_BASE",
        backend=backend,
    )
    tip.hide_set(True)
    base.hide_set(True)
    control_pose.custom_shape = tip
    display_pose.custom_shape = base
    control_pose.use_custom_shape_bone_size = False
    display_pose.use_custom_shape_bone_size = False
    if hasattr(control_pose, "custom_shape_translation"):
        control_pose.custom_shape_translation = (
            (0.0, control.radius, 0.0)
            if control.control_type == "DIAL"
            else (0.0, 0.0, 0.0)
        )
    return tip, base
