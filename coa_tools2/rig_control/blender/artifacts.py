"""Creation and lookup of Blender rig-control artifacts."""

from __future__ import annotations

import math
import re
import uuid

import bpy
from mathutils import Matrix, Vector

from ... import functions
from ..schema import (
    WidgetBackend,
    WidgetLayout,
    WidgetSpec,
    dial_point,
    dial_rest_angle,
)
from .properties import get_rig_data
from .rail_targets import ensure_rail_target
from .states import state_mix_mask
from .widgets import ensure_widget


GLOBAL_CONTROL_BONE = "GLOBAL_CTRL"
CONTROL_COLLECTION = "COA Rig Controls"
DISPLAY_COLLECTION = "COA Rig Display"
NAME_COLLECTION = "COA Rig Names"
NAME_TEXT_COLLECTION = "COA Rig Labels"


def slugify(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z_]+", "_", value.strip()).strip("_")
    return slug or "control"


def ensure_rig_instance_id(armature: bpy.types.Object) -> str:
    rig_data = get_rig_data(armature)
    instance_id = rig_data.rig_instance_id
    if not instance_id:
        instance_id = str(uuid.uuid4())
        rig_data.rig_instance_id = instance_id
    return instance_id


def _set_bone_palette(pose_bone, palette: str):
    """Apply presentation color to data and pose-level color overrides."""

    for owner in (pose_bone.bone, pose_bone):
        color = getattr(owner, "color", None)
        if color is not None and hasattr(color, "palette"):
            color.palette = palette


def find_bone_by_role(armature, control_uuid: str, role: str):
    for bone in armature.data.bones:
        if (
            bone.get("coa_rig_control_uuid") == control_uuid
            and bone.get("coa_rig_artifact_role") == role
        ):
            return bone
    return None


def find_object_by_role(control_uuid: str, role: str):
    return next(
        (
            obj
            for obj in bpy.data.objects
            if obj.get("coa_rig_control_uuid") == control_uuid
            and obj.get("coa_rig_artifact_role") == role
        ),
        None,
    )


def _ensure_name_text_collection():
    collection = bpy.data.collections.get(NAME_TEXT_COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(NAME_TEXT_COLLECTION)
    scene = bpy.context.scene
    if collection.name not in {
        child.name for child in scene.collection.children
    }:
        scene.collection.children.link(collection)
    collection.hide_render = True
    return collection


def _control_bottom_extent(control) -> float:
    handle_extent = max(control.node_radius, control.tip_radius)
    if control.control_type == "SLIDER_1D":
        return (
            control.width * 0.5 + handle_extent
            if control.axis == "Y"
            else handle_extent
        )
    if control.control_type == "POINT_2D_RECT":
        return control.height * 0.5 + handle_extent
    return control.radius + max(handle_extent, control.bar_width * 0.5)


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
    existing_name = find_bone_by_role(armature, control.control_uuid, "name_bone")
    existing_display_name = existing_display.name if existing_display else ""
    existing_control_name = existing_control.name if existing_control else ""
    existing_name_name = existing_name.name if existing_name else ""

    _switch_to_edit_mode(armature)
    _ensure_global_bone(armature)
    global_bone = armature.data.edit_bones[GLOBAL_CONTROL_BONE]

    slug = slugify(control.semantic_id or control.label)
    display_name = existing_display_name or control.display_bone or f"DISP_{slug}"
    control_name = existing_control_name or control.control_bone or f"CTRL_{slug}"
    name_name = existing_name_name or control.name_bone or f"NAME_{slug}"

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
    elif control.control_type == "DIAL":
        angle = dial_rest_angle(control.angle_min, control.angle_max)
        dial_x, dial_y = dial_point(control.radius, angle)
        handle_origin.x += dial_x
        handle_origin.z += dial_y

    handle = armature.data.edit_bones.get(control_name)
    if handle is None:
        handle = armature.data.edit_bones.new(control_name)
    handle.head = handle_origin
    handle.tail = handle_origin + Vector((0.0, 0.0, 1.0))
    handle.parent = global_bone
    handle.use_connect = False
    handle.use_deform = False

    name_position = origin.copy()
    name_position.z -= _control_bottom_extent(control) + control.name_offset
    name_bone_length = max(control.name_size, 0.1)
    name_bone = armature.data.edit_bones.get(name_name)
    if name_bone is None:
        name_bone = armature.data.edit_bones.new(name_name)
    # Bone-parented objects use the bone tail as their local origin.
    # Place that tail at the requested text center.
    name_bone.head = name_position - Vector((0.0, 0.0, name_bone_length))
    name_bone.tail = name_position
    name_bone.parent = global_bone
    name_bone.use_connect = False
    name_bone.use_deform = False

    display_name = display.name
    handle_name = handle.name
    name_name = name_bone.name
    bpy.ops.object.mode_set(mode="POSE")
    display_pose = armature.pose.bones[display_name]
    control_pose = armature.pose.bones[handle_name]
    name_pose = armature.pose.bones[name_name]

    for pose_bone, role in (
        (display_pose, "display_bone"),
        (control_pose, "control_bone"),
        (name_pose, "name_bone"),
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
        theme="DEFAULT",
        visible=True,
        exclusive=True,
    )
    functions.set_bone_group(
        None,
        armature,
        control_pose,
        group=CONTROL_COLLECTION,
        theme="DEFAULT",
        visible=True,
        exclusive=True,
    )
    functions.set_bone_group(
        None,
        armature,
        name_pose,
        group=NAME_COLLECTION,
        theme="DEFAULT",
        visible=True,
        exclusive=True,
    )
    _set_bone_palette(display_pose, "DEFAULT")
    _set_bone_palette(control_pose, "DEFAULT")
    _set_bone_palette(name_pose, "DEFAULT")

    control.display_bone = display_pose.name
    control.control_bone = control_pose.name
    control.name_bone = name_pose.name
    return display_pose, control_pose, name_pose


def ensure_control_name_text(armature, name_pose, control):
    """Create a viewport-only text layer parented to the control's name bone."""

    text_object = find_object_by_role(control.control_uuid, "name_text")
    if text_object is not None and text_object.type != "FONT":
        text_object = None
    if text_object is None:
        text_curve = bpy.data.curves.new(
            f"TXT_{slugify(control.semantic_id or control.label)}_Curve",
            "FONT",
        )
        text_object = bpy.data.objects.new(
            f"TXT_{slugify(control.semantic_id or control.label)}",
            text_curve,
        )
        _ensure_name_text_collection().objects.link(text_object)

    text_curve = text_object.data
    text_curve.body = control.label
    text_curve.align_x = "CENTER"
    text_curve.align_y = "CENTER"
    text_curve.size = control.name_size
    text_curve.extrude = 0.0
    text_curve.bevel_depth = 0.0

    text_object["coa_rig_managed"] = True
    text_object["coa_rig_instance_id"] = ensure_rig_instance_id(armature)
    text_object["coa_rig_control_uuid"] = control.control_uuid
    text_object["coa_rig_artifact_role"] = "name_text"
    text_object.parent = armature
    text_object.parent_type = "BONE"
    text_object.parent_bone = name_pose.name
    text_object.matrix_parent_inverse = Matrix.Identity(4)
    text_object.location = (0.0, 0.0, 0.0)
    text_object.rotation_mode = "XYZ"
    # Bone parenting already rotates the local XY text plane into the
    # armature's XZ control plane.
    text_object.rotation_euler = (0.0, 0.0, 0.0)
    text_object.scale = (1.0, 1.0, 1.0)
    text_object.show_in_front = True
    text_object.hide_render = True
    text_object.hide_set(not control.show_name)
    name_pose.bone.hide = not control.show_name
    control.name_text_object = text_object.name
    return text_object


def limit_location_name(control_uuid: str) -> str:
    return f"COA_{control_uuid[:8]}_LimitLocation"


def limit_distance_name(control_uuid: str) -> str:
    return f"COA_{control_uuid[:8]}_LimitDistance"


def limit_rotation_name(control_uuid: str) -> str:
    return f"COA_{control_uuid[:8]}_LimitRotation"


def rail_constraint_name(control_uuid: str) -> str:
    return f"COA_{control_uuid[:8]}_Rail"


def ensure_limit_location(control_pose, control):
    constraint_name = limit_location_name(control.control_uuid)
    constraint = control_pose.constraints.get(constraint_name)
    if constraint is None:
        constraint = control_pose.constraints.new("LIMIT_LOCATION")
    constraint.name = constraint_name
    constraint.owner_space = "LOCAL"
    constraint.use_transform_limit = True

    for axis in "xyz":
        setattr(constraint, f"use_min_{axis}", True)
        setattr(constraint, f"use_max_{axis}", True)
        setattr(constraint, f"min_{axis}", 0.0)
        setattr(constraint, f"max_{axis}", 0.0)

    if control.control_type == "SLIDER_1D":
        axis = "y" if control.axis == "Y" else "x"
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
        constraint.use_min_x = False
        constraint.use_max_x = False
        constraint.use_min_y = False
        constraint.use_max_y = False
        control.input_min = -control.radius
        control.input_max = control.radius
    elif control.control_type == "DIAL":
        constraint.use_min_x = False
        constraint.use_max_x = False
        constraint.use_min_y = False
        constraint.use_max_y = False
        control.input_min = control.angle_min
        control.input_max = control.angle_max
    return constraint


def ensure_rail_constraint(armature, control_pose, control):
    name = rail_constraint_name(control.control_uuid)
    constraint = control_pose.constraints.get(name)
    if constraint is None or constraint.type != "SHRINKWRAP":
        if constraint is not None:
            control_pose.constraints.remove(constraint)
        constraint = control_pose.constraints.new("SHRINKWRAP")
    constraint.name = name
    constraint.target = ensure_rail_target(armature, control)
    constraint.shrinkwrap_type = "NEAREST_SURFACE"
    constraint.wrap_mode = "ON_SURFACE"
    constraint.distance = 0.0
    constraint.owner_space = "WORLD"
    constraint.target_space = "WORLD"
    return constraint


def ensure_control_constraints(armature, display_pose, control_pose, control):
    expected = {limit_location_name(control.control_uuid)}
    if control.control_type == "POINT_2D_CIRCLE":
        expected.add(limit_distance_name(control.control_uuid))
    elif control.control_type == "DIAL" or (
        control.control_type == "POINT_2D_RECT"
        and (
            control.rectangle_mode == "GRID"
            or control.state_mode == "MATRIX_2D"
        )
    ):
        expected.add(rail_constraint_name(control.control_uuid))

    managed_names = {
        limit_location_name(control.control_uuid),
        limit_distance_name(control.control_uuid),
        limit_rotation_name(control.control_uuid),
        rail_constraint_name(control.control_uuid),
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
    elif control.control_type == "DIAL" or (
        control.control_type == "POINT_2D_RECT"
        and (
            control.rectangle_mode == "GRID"
            or control.state_mode == "MATRIX_2D"
        )
    ):
        ensure_rail_constraint(armature, control_pose, control)


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
        "POINT_2D_CIRCLE": WidgetLayout.CIRCLE,
        "DIAL": WidgetLayout.DIAL,
    }
    base_layout = (
        WidgetLayout.MATRIX
        if control.state_mode == "MATRIX_2D"
        else WidgetLayout.RECTANGLE_GRID
        if control.control_type == "POINT_2D_RECT"
        and control.rectangle_mode == "GRID"
        else WidgetLayout.RECTANGLE
        if control.control_type == "POINT_2D_RECT"
        else layout_by_type[control.control_type]
    )
    base_spec = WidgetSpec(
        widget_uuid=control.base_widget_uuid,
        layout=base_layout,
        width=control.width,
        height=control.height,
        radius=control.radius,
        tip_radius=control.tip_radius,
        node_radius=control.node_radius,
        bar_width=control.bar_width,
        stroke_radius=control.stroke_radius,
        columns=(
            control.state_columns
            if control.state_mode in {"LINEAR_1D", "MATRIX_2D"}
            else 2
            if control.control_type == "SLIDER_1D"
            else control.grid_columns
        ),
        rows=(
            control.state_rows
            if control.state_mode == "MATRIX_2D"
            else control.grid_rows
        ),
        mix_cells=(
            state_mix_mask(control)
            if control.state_mode == "MATRIX_2D"
            else None
        ),
        arc_start=control.angle_min,
        arc_end=control.angle_max,
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
    for pose_bone in (control_pose, display_pose):
        if hasattr(pose_bone, "custom_shape_translation"):
            pose_bone.custom_shape_translation = (0.0, 0.0, 0.0)
        if hasattr(pose_bone, "custom_shape_rotation_euler"):
            pose_bone.custom_shape_rotation_euler = (0.0, 0.0, 0.0)
    if (
        control.control_type == "SLIDER_1D"
        and control.axis == "Y"
        and hasattr(display_pose, "custom_shape_rotation_euler")
    ):
        display_pose.custom_shape_rotation_euler[2] = math.pi * 0.5
    return tip, base
