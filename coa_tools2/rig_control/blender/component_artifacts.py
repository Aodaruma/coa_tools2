"""Blender artifacts for character posing rig components."""

from __future__ import annotations

import math
import uuid

import bpy
from mathutils import Euler, Matrix, Vector

from ... import functions
from .artifacts import ensure_rig_instance_id, slugify
from .properties import get_rig_data
from .widgets import ensure_widget_collection


COMPONENT_CONTROL_COLLECTION = "COA Controls"
COMPONENT_MECHANISM_COLLECTION = "COA Mechanism"
COMPONENT_DEFORM_COLLECTION = "COA Deform"
COMPONENT_UI_COLLECTION = "COA UI"


class ComponentArtifactConflict(RuntimeError):
    pass


def _matches_component(owner, instance_id: str, component_uuid: str, role: str) -> bool:
    return (
        owner.get("coa_rig_instance_id") == instance_id
        and owner.get("coa_rig_component_uuid") == component_uuid
        and owner.get("coa_rig_component_role") == role
    )


def find_component_bone(armature, component_uuid: str, role: str):
    instance_id = ensure_rig_instance_id(armature)
    return next(
        (
            bone
            for bone in armature.data.bones
            if _matches_component(bone, instance_id, component_uuid, role)
        ),
        None,
    )


def find_component_object(armature, component_uuid: str, role: str):
    instance_id = ensure_rig_instance_id(armature)
    return next(
        (
            obj
            for obj in bpy.data.objects
            if _matches_component(obj, instance_id, component_uuid, role)
        ),
        None,
    )


def _record_artifact(
    component,
    role: str,
    data_type: str,
    *,
    object_name: str = "",
    bone_name: str = "",
    constraint_name: str = "",
    owned: bool = True,
):
    artifact = next(
        (
            item
            for item in component.artifacts
            if item.role == role
            and item.data_type == data_type
            and item.object_name == object_name
            and item.bone_name == bone_name
            and item.constraint_name == constraint_name
        ),
        None,
    )
    if artifact is None:
        artifact = component.artifacts.add()
        artifact.artifact_uuid = str(uuid.uuid4())
    artifact.role = role
    artifact.data_type = data_type
    artifact.object_name = object_name
    artifact.bone_name = bone_name
    artifact.constraint_name = constraint_name
    artifact.owned = owned
    return artifact


def _remove_artifacts(
    component,
    *,
    role: str | None = None,
    data_type: str | None = None,
    bone_name: str | None = None,
    constraint_name: str | None = None,
):
    for index in range(len(component.artifacts) - 1, -1, -1):
        artifact = component.artifacts[index]
        if role is not None and artifact.role != role:
            continue
        if data_type is not None and artifact.data_type != data_type:
            continue
        if bone_name is not None and artifact.bone_name != bone_name:
            continue
        if constraint_name is not None and artifact.constraint_name != constraint_name:
            continue
        component.artifacts.remove(index)


def _owns_constraint(component, bone_name: str, constraint_name: str) -> bool:
    return any(
        artifact.data_type == "CONSTRAINT"
        and artifact.bone_name == bone_name
        and artifact.constraint_name == constraint_name
        and artifact.owned
        for artifact in component.artifacts
    )


def _tag_bone(armature, data_bone, component, role: str):
    instance_id = ensure_rig_instance_id(armature)
    existing_uuid = data_bone.get("coa_rig_component_uuid")
    if existing_uuid not in {None, "", component.component_uuid}:
        raise ComponentArtifactConflict(
            f"Bone '{data_bone.name}' already belongs to another pose component."
        )
    data_bone["coa_rig_instance_id"] = instance_id
    data_bone["coa_rig_component_uuid"] = component.component_uuid
    data_bone["coa_rig_component_role"] = role


def _tag_owned_bone(armature, data_bone, component, role: str):
    _tag_bone(armature, data_bone, component, role)
    data_bone["coa_rig_managed"] = True
    data_bone.use_deform = False


def _switch_to_edit_mode(armature):
    if bpy.context.active_object != armature:
        for selected in tuple(bpy.context.selected_objects):
            selected.select_set(False)
        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature
    if armature.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.mode_set(mode="EDIT")


def _ring(vertices, edges, axis_a: int, axis_b: int, radius: float, segments=32):
    start = len(vertices)
    for index in range(segments):
        angle = math.tau * index / segments
        point = [0.0, 0.0, 0.0]
        point[axis_a] = math.cos(angle) * radius
        point[axis_b] = math.sin(angle) * radius
        vertices.append(tuple(point))
        edges.append((start + index, start + ((index + 1) % segments)))


def _outline(vertices, edges, points):
    start = len(vertices)
    vertices.extend(points)
    for index in range(len(points)):
        edges.append((start + index, start + ((index + 1) % len(points))))


def _normal_marker(vertices, edges, size):
    start = len(vertices)
    vertices.extend(
        (
            (0.0, 0.0, 0.0),
            (0.0, 0.0, size * 0.65),
            (-size * 0.10, 0.0, size * 0.50),
            (size * 0.10, 0.0, size * 0.50),
        )
    )
    edges.extend(((start, start + 1), (start + 1, start + 2), (start + 1, start + 3)))


def _component_widget_geometry(widget: str, size: float):
    vertices: list[tuple[float, float, float]] = []
    edges: list[tuple[int, int]] = []
    size = max(float(size), 0.01)

    if widget == "ROOT":
        half = size * 0.5
        vertices.extend(
            (
                (-half, -half, -half),
                (half, -half, -half),
                (half, half, -half),
                (-half, half, -half),
                (-half, -half, half),
                (half, -half, half),
                (half, half, half),
                (-half, half, half),
            )
        )
        edges.extend(
            (
                (0, 1),
                (1, 2),
                (2, 3),
                (3, 0),
                (4, 5),
                (5, 6),
                (6, 7),
                (7, 4),
                (0, 4),
                (1, 5),
                (2, 6),
                (3, 7),
            )
        )
        _ring(vertices, edges, 0, 1, size * 0.72)
    elif widget == "FK":
        _ring(vertices, edges, 0, 1, size * 0.5)
        _ring(vertices, edges, 0, 2, size * 0.5)
        _ring(vertices, edges, 1, 2, size * 0.5)
    elif widget == "HAND":
        _outline(
            vertices,
            edges,
            tuple(
                (x * size, y * size, 0.0)
                for x, y in (
                    (-0.48, -0.58),
                    (0.48, -0.58),
                    (0.60, 0.08),
                    (0.28, 0.62),
                    (-0.28, 0.62),
                    (-0.60, 0.08),
                )
            ),
        )
        _normal_marker(vertices, edges, size)
    elif widget == "FOOT":
        _outline(
            vertices,
            edges,
            tuple(
                (x * size, y * size, 0.0)
                for x, y in (
                    (-0.38, -0.65),
                    (0.38, -0.65),
                    (0.52, 0.30),
                    (0.30, 0.68),
                    (-0.18, 0.62),
                    (-0.48, 0.18),
                )
            ),
        )
        _normal_marker(vertices, edges, size)
    elif widget == "DIAMOND":
        _outline(
            vertices,
            edges,
            (
                (0.0, -size * 0.55, 0.0),
                (size * 0.45, 0.0, 0.0),
                (0.0, size * 0.55, 0.0),
                (-size * 0.45, 0.0, 0.0),
            ),
        )
        _normal_marker(vertices, edges, size * 0.7)
    else:
        _outline(
            vertices,
            edges,
            tuple(
                (x * size, y * size, 0.0)
                for x, y in (
                    (-0.40, -0.55),
                    (0.40, -0.55),
                    (0.55, -0.40),
                    (0.55, 0.40),
                    (0.40, 0.55),
                    (-0.40, 0.55),
                    (-0.55, 0.40),
                    (-0.55, -0.40),
                )
            ),
        )
        _normal_marker(vertices, edges, size)
    return vertices, edges


def ensure_component_widget(
    armature,
    component,
    *,
    role="component_widget",
    widget=None,
    size=None,
):
    widget = widget or component.widget
    size = component.widget_size if size is None else size
    widget_object = find_component_object(armature, component.component_uuid, role)
    if widget_object is not None and widget_object.type != "MESH":
        raise ComponentArtifactConflict(
            f"Managed widget '{widget_object.name}' is not a Mesh object."
        )
    if widget_object is None:
        suffix = "" if role == "component_widget" else f"_{slugify(role)}"
        mesh = bpy.data.meshes.new(
            f"WGT_{slugify(component.semantic_id or component.label)}{suffix}_Mesh"
        )
        widget_object = bpy.data.objects.new(
            f"WGT_{slugify(component.semantic_id or component.label)}{suffix}",
            mesh,
        )
        ensure_widget_collection().objects.link(widget_object)
    vertices, edges = _component_widget_geometry(widget, size)
    widget_object.data.clear_geometry()
    widget_object.data.from_pydata(vertices, edges, ())
    widget_object.data.update()
    widget_object["coa_rig_managed"] = True
    widget_object["coa_rig_instance_id"] = ensure_rig_instance_id(armature)
    widget_object["coa_rig_component_uuid"] = component.component_uuid
    widget_object["coa_rig_component_role"] = role
    widget_object.hide_render = True
    widget_object.hide_set(True)
    _record_artifact(
        component,
        role,
        "OBJECT",
        object_name=widget_object.name,
        owned=True,
    )
    return widget_object


def _ensure_source_is_available(armature, data_bone, component, role):
    existing_uuid = data_bone.get("coa_rig_component_uuid")
    if existing_uuid not in {None, "", component.component_uuid}:
        raise ComponentArtifactConflict(
            f"Bone '{data_bone.name}' already belongs to another pose component."
        )
    _tag_bone(armature, data_bone, component, role)
    _record_artifact(
        component,
        role,
        "BONE",
        bone_name=data_bone.name,
        owned=False,
    )


def _component_depth_constraint_name(component) -> str:
    return f"COA_COMP_{component.component_uuid[:8]}_Depth"


def ensure_depth_constraint(pose_bone, component):
    name = _component_depth_constraint_name(component)
    constraint = pose_bone.constraints.get(name)
    if component.depth_mode == "FREE" or not component.allow_translation[2]:
        if constraint is not None and _owns_constraint(
            component,
            pose_bone.name,
            name,
        ):
            pose_bone.constraints.remove(constraint)
        _remove_artifacts(
            component,
            role="depth_constraint",
            data_type="CONSTRAINT",
            bone_name=pose_bone.name,
            constraint_name=name,
        )
        return None
    if constraint is not None and constraint.type != "LIMIT_LOCATION":
        if not _owns_constraint(component, pose_bone.name, name):
            raise ComponentArtifactConflict(
                f"Constraint '{name}' is not owned by this pose component."
            )
        pose_bone.constraints.remove(constraint)
        constraint = None
    elif constraint is not None and not _owns_constraint(
        component,
        pose_bone.name,
        name,
    ):
        raise ComponentArtifactConflict(
            f"Constraint '{name}' is not owned by this pose component."
        )
    if constraint is None:
        constraint = pose_bone.constraints.new("LIMIT_LOCATION")
        constraint.name = name
    constraint.owner_space = "LOCAL"
    constraint.use_transform_limit = True
    for axis in "xy":
        setattr(constraint, f"use_min_{axis}", False)
        setattr(constraint, f"use_max_{axis}", False)
    constraint.use_min_z = True
    constraint.use_max_z = True
    if component.depth_mode == "LOCKED":
        constraint.min_z = 0.0
        constraint.max_z = 0.0
    else:
        constraint.min_z = component.depth_min
        constraint.max_z = component.depth_max
    _record_artifact(
        component,
        "depth_constraint",
        "CONSTRAINT",
        bone_name=pose_bone.name,
        constraint_name=constraint.name,
        owned=True,
    )
    return constraint


def apply_component_channels(pose_bone, component, *, translation=True):
    translation_axes = (
        tuple(component.allow_translation) if translation else (False, False, False)
    )
    pose_bone.lock_location = tuple(not value for value in translation_axes)
    if component.depth_mode != "FREE":
        pose_bone.lock_location[2] = not component.allow_translation[2]
    pose_bone.lock_rotation = tuple(
        not value for value in tuple(component.allow_rotation)
    )
    if pose_bone.rotation_mode == "QUATERNION":
        pose_bone.lock_rotations_4d = True
        pose_bone.lock_rotation_w = not any(component.allow_rotation)
    else:
        pose_bone.lock_rotation_w = False


def ensure_in_place_component(armature, component):
    widget = ensure_component_widget(armature, component)
    pose_bones = []
    for index, reference in enumerate(component.source_bones):
        pose_bone = armature.pose.bones.get(reference.bone_name)
        if pose_bone is None:
            raise ComponentArtifactConflict(
                f"Source bone '{reference.bone_name}' is missing."
            )
        existing_shape = pose_bone.custom_shape
        if (
            existing_shape is not None
            and existing_shape != widget
            and existing_shape.get("coa_rig_component_uuid") != component.component_uuid
        ):
            raise ComponentArtifactConflict(
                f"Source bone '{pose_bone.name}' already has a custom shape."
            )
        role = f"source_bone_{index}"
        _ensure_source_is_available(armature, pose_bone.bone, component, role)
        pose_bone.custom_shape = widget
        pose_bone.use_custom_shape_bone_size = False
        if hasattr(pose_bone, "custom_shape_wire_width"):
            pose_bone.custom_shape_wire_width = 1.5
        apply_component_channels(
            pose_bone,
            component,
            translation=component.component_type == "ROOT",
        )
        if component.component_type == "ROOT":
            ensure_depth_constraint(pose_bone, component)
        functions.set_bone_group(
            None,
            armature,
            pose_bone,
            group=COMPONENT_CONTROL_COLLECTION,
            theme=None,
            visible=True,
            exclusive=False,
        )
        functions.set_bone_group(
            None,
            armature,
            pose_bone,
            group=COMPONENT_DEFORM_COLLECTION,
            theme=None,
            visible=True,
            exclusive=False,
        )
        pose_bones.append(pose_bone)
    component.control_bone = pose_bones[-1].name
    component.frame_bone = ""
    return pose_bones


def _orientation_matrix(reference, component):
    if component.orientation_mode == "WORLD_VIEW":
        matrix = Matrix.Identity(4)
        # Local X -> armature X, local Y -> armature Z, local Z -> -armature Y.
        matrix[0][0], matrix[1][0], matrix[2][0] = 1.0, 0.0, 0.0
        matrix[0][1], matrix[1][1], matrix[2][1] = 0.0, 0.0, 1.0
        matrix[0][2], matrix[1][2], matrix[2][2] = 0.0, -1.0, 0.0
        matrix.translation = reference.head
    else:
        matrix = reference.matrix.copy()
    if component.orientation_mode == "CUSTOM":
        offset = Euler(tuple(component.orientation_euler), "XYZ").to_matrix()
        rotation = matrix.to_3x3() @ offset
        custom = rotation.to_4x4()
        custom.translation = matrix.translation
        matrix = custom
    return matrix


def _set_edit_bone_matrix(edit_bone, matrix, length: float):
    """Set a new zero-length EditBone to an exact visual frame."""

    axis_y = (matrix.to_3x3() @ Vector((0.0, 1.0, 0.0))).normalized()
    edit_bone.head = matrix.translation
    edit_bone.tail = matrix.translation + axis_y * length
    edit_bone.matrix = matrix
    edit_bone.length = length


def _bend_hint_position(upper, lower, frame_matrix, pole_distance):
    start = upper.head.copy()
    joint = upper.tail.copy()
    end = lower.tail.copy()
    chain = end - start
    if chain.length < 1e-6:
        return joint + frame_matrix.to_3x3().col[2] * pole_distance
    chain_direction = chain.normalized()
    projected = start + chain_direction * (joint - start).dot(chain_direction)
    bend_direction = joint - projected
    if bend_direction.length < 1e-5:
        bend_direction = frame_matrix.to_3x3().col[2].copy()
        bend_direction -= chain_direction * bend_direction.dot(chain_direction)
    if bend_direction.length < 1e-5:
        bend_direction = frame_matrix.to_3x3().col[0].copy()
        bend_direction -= chain_direction * bend_direction.dot(chain_direction)
    distance = max(upper.length + lower.length, 0.1) * pole_distance
    return joint + bend_direction.normalized() * distance


def ensure_limb_control_bones(armature, component):
    reference_name = component.orientation_reference or component.source_bones[-1].bone_name
    existing_frame = find_component_bone(
        armature,
        component.component_uuid,
        "control_frame",
    )
    existing_control = find_component_bone(
        armature,
        component.component_uuid,
        "control_bone",
    )
    existing_pole = find_component_bone(
        armature,
        component.component_uuid,
        "bend_control",
    )
    frame_name = existing_frame.name if existing_frame else component.frame_bone
    control_name = existing_control.name if existing_control else component.control_bone
    pole_name = existing_pole.name if existing_pole else component.pole_bone
    needs_pole = component.use_bend_hint and component.ik_solver_mode == "SPATIAL"

    # Detach managed references before deleting their target EditBone.  Blender
    # 5.x otherwise rebuilds the dependency graph against a missing pose
    # channel while switching Spatial IK to Planar.
    if not needs_pole and existing_pole is not None:
        owner_name = (
            component.constraint_bone
            or component.source_bones[-2].bone_name
        )
        constraint_name = (
            component.constraint_name
            or f"COA_COMP_{component.component_uuid[:8]}_IK"
        )
        owner = armature.pose.bones.get(owner_name)
        constraint = (
            owner.constraints.get(constraint_name)
            if owner is not None
            else None
        )
        if (
            constraint is not None
            and constraint.type == "IK"
            and _owns_constraint(component, owner_name, constraint_name)
        ):
            constraint.pole_target = None
            constraint.pole_subtarget = ""
            constraint.pole_angle = 0.0
            bpy.context.view_layer.update()

    _switch_to_edit_mode(armature)
    reference = armature.data.edit_bones.get(reference_name)
    if reference is None:
        bpy.ops.object.mode_set(mode="POSE")
        raise ComponentArtifactConflict(
            f"Orientation reference bone '{reference_name}' is missing."
        )
    source_root = armature.data.edit_bones.get(component.source_bones[0].bone_name)
    if source_root is None:
        bpy.ops.object.mode_set(mode="POSE")
        raise ComponentArtifactConflict("Limb source root is missing.")

    slug = slugify(component.semantic_id or component.label)
    frame_name = frame_name or f"MCH_{slug}_FRAME"
    control_name = control_name or f"CTRL_{slug}"
    pole_name = pole_name or f"CTRL_{slug}_BEND"
    frame = armature.data.edit_bones.get(frame_name)
    if frame is not None and existing_frame is None:
        bpy.ops.object.mode_set(mode="POSE")
        raise ComponentArtifactConflict(
            f"Bone '{frame_name}' already exists and is not owned by this component."
        )
    if frame is None:
        frame = armature.data.edit_bones.new(frame_name)
    control = armature.data.edit_bones.get(control_name)
    if control is not None and existing_control is None:
        bpy.ops.object.mode_set(mode="POSE")
        raise ComponentArtifactConflict(
            f"Bone '{control_name}' already exists and is not owned by this component."
        )
    if control is None:
        control = armature.data.edit_bones.new(control_name)
    pole = armature.data.edit_bones.get(pole_name)
    if needs_pole and pole is not None and existing_pole is None:
        bpy.ops.object.mode_set(mode="POSE")
        raise ComponentArtifactConflict(
            f"Bone '{pole_name}' already exists and is not owned by this component."
        )
    if needs_pole and pole is None:
        pole = armature.data.edit_bones.new(pole_name)
    if not needs_pole and pole is not None and existing_pole is not None:
        armature.data.edit_bones.remove(pole)
        pole = None
    elif not needs_pole:
        pole = None

    matrix = _orientation_matrix(reference, component)
    length = max(reference.length, component.widget_size, 0.1)
    frame.parent = source_root.parent
    frame.use_connect = False
    _set_edit_bone_matrix(frame, matrix, length)
    control.parent = frame
    control.use_connect = False
    _set_edit_bone_matrix(control, matrix, length)
    if pole is not None:
        upper = armature.data.edit_bones[component.source_bones[-3].bone_name]
        lower = armature.data.edit_bones[component.source_bones[-2].bone_name]
        pole_matrix = matrix.copy()
        pole_matrix.translation = _bend_hint_position(
            upper,
            lower,
            matrix,
            component.pole_distance,
        )
        pole.parent = source_root.parent
        pole.use_connect = False
        _set_edit_bone_matrix(
            pole,
            pole_matrix,
            max(component.widget_size * 0.6, 0.1),
        )
    frame.use_deform = False
    control.use_deform = False
    _tag_owned_bone(armature, frame, component, "control_frame")
    _tag_owned_bone(armature, control, component, "control_bone")
    if pole is not None:
        pole.use_deform = False
        _tag_owned_bone(armature, pole, component, "bend_control")

    frame_name = frame.name
    control_name = control.name
    pole_name = pole.name if pole is not None else ""
    bpy.ops.object.mode_set(mode="POSE")
    frame_pose = armature.pose.bones[frame_name]
    control_pose = armature.pose.bones[control_name]
    pole_pose = armature.pose.bones.get(pole_name) if pole_name else None
    _tag_owned_bone(armature, frame_pose.bone, component, "control_frame")
    _tag_owned_bone(armature, control_pose.bone, component, "control_bone")
    _record_artifact(
        component,
        "control_frame",
        "BONE",
        bone_name=frame_name,
        owned=True,
    )
    if pole_pose is not None:
        _tag_owned_bone(
            armature,
            pole_pose.bone,
            component,
            "bend_control",
        )
        _record_artifact(
            component,
            "bend_control",
            "BONE",
            bone_name=pole_name,
            owned=True,
        )
    else:
        _remove_artifacts(
            component,
            role="bend_control",
            data_type="BONE",
        )
    _record_artifact(
        component,
        "control_bone",
        "BONE",
        bone_name=control_name,
        owned=True,
    )
    functions.set_bone_group(
        None,
        armature,
        frame_pose,
        group=COMPONENT_MECHANISM_COLLECTION,
        theme=None,
        visible=False,
        exclusive=True,
    )
    functions.set_bone_group(
        None,
        armature,
        control_pose,
        group=COMPONENT_CONTROL_COLLECTION,
        theme=None,
        visible=True,
        exclusive=True,
    )
    if pole_pose is not None:
        functions.set_bone_group(
            None,
            armature,
            pole_pose,
            group=COMPONENT_CONTROL_COLLECTION,
            theme=None,
            visible=True,
            exclusive=True,
        )
    frame_pose.bone.hide_select = True
    component.frame_bone = frame_name
    component.control_bone = control_name
    component.pole_bone = pole_name
    # Blender 5.x may otherwise evaluate a newly added IK relation before the
    # bend-control pose channel has entered the dependency graph.
    bpy.context.view_layer.update()
    return frame_pose, control_pose, pole_pose


def _managed_constraint(pose_bone, component, name: str, constraint_type: str):
    constraint = pose_bone.constraints.get(name)
    owned = _owns_constraint(component, pose_bone.name, name)
    if constraint is not None and not owned:
        raise ComponentArtifactConflict(
            f"Constraint '{name}' is not owned by this pose component."
        )
    if constraint is not None and constraint.type != constraint_type:
        pose_bone.constraints.remove(constraint)
        constraint = None
    if constraint is None:
        constraint = pose_bone.constraints.new(constraint_type)
        constraint.name = name
    return constraint


def _auto_bend_axis(armature, component):
    upper = armature.data.bones[component.source_bones[-3].bone_name]
    lower = armature.data.bones[component.source_bones[-2].bone_name]
    upper_direction = (upper.tail_local - upper.head_local).normalized()
    lower_direction = (lower.tail_local - lower.head_local).normalized()
    normal = upper_direction.cross(lower_direction)
    if normal.length < 1e-5:
        reference_name = component.frame_bone or component.orientation_reference
        reference = armature.data.bones.get(reference_name)
        if reference is not None:
            normal = (
                reference.matrix_local.to_3x3()
                @ Vector((0.0, 0.0, 1.0))
            ).normalized()
        else:
            normal = Vector((0.0, -1.0, 0.0))
    local_normal = upper.matrix_local.to_3x3().inverted() @ normal.normalized()
    axes = {"X": abs(local_normal.x), "Y": abs(local_normal.y), "Z": abs(local_normal.z)}
    return max(axes, key=axes.get)


def _compute_pole_angle(armature, component, pole_pose):
    """Return a geometric starting estimate for Blender's IK pole twist."""

    upper = armature.data.bones[component.source_bones[-3].bone_name]
    lower = armature.data.bones[component.source_bones[-2].bone_name]
    upper_vector = upper.tail_local - upper.head_local
    total_vector = lower.tail_local - upper.head_local
    pole_vector = pole_pose.bone.head_local - upper.head_local
    pole_normal = total_vector.cross(pole_vector)
    projected_pole_axis = pole_normal.cross(upper_vector)
    bone_x = upper.matrix_local.to_3x3() @ Vector((1.0, 0.0, 0.0))
    if projected_pole_axis.length < 1e-6 or bone_x.length < 1e-6:
        return 0.0
    projected_pole_axis.normalize()
    bone_x.normalize()
    angle = bone_x.angle(projected_pole_axis)
    if bone_x.cross(projected_pole_axis).dot(upper_vector) < 0.0:
        angle = -angle
    return angle


def _fit_pole_angle(armature, owner, ik, expected_joint, initial_angle):
    """Calibrate pole twist without changing the pose visible before build.

    Blender's pole angle also depends on bone roll and the currently evaluated
    parent pose.  A geometric rest-space formula is therefore only a useful
    initial estimate.  Searching the one periodic degree of freedom once at
    build time avoids a visible pose jump, while the persisted result keeps
    later updates deterministic.
    """

    two_pi = math.tau

    def wrapped(angle):
        return (angle + math.pi) % two_pi - math.pi

    def error(angle):
        ik.pole_angle = wrapped(angle)
        bpy.context.view_layer.update()
        return (owner.head - expected_joint).length

    # Include the geometric estimate, then sample the full periodic domain so
    # unusual rolls and mirrored limbs cannot trap the calibration locally.
    sample_count = 32
    step = two_pi / sample_count
    candidates = [initial_angle]
    candidates.extend(-math.pi + index * step for index in range(sample_count))
    best_angle = min(candidates, key=error)

    # Refine around the best coarse sample.  Seven rounds provide considerably
    # more precision than the integration test threshold without noticeable
    # build-time cost.
    radius = step
    for _round in range(7):
        candidates = (
            best_angle - radius,
            best_angle - radius * 0.5,
            best_angle,
            best_angle + radius * 0.5,
            best_angle + radius,
        )
        best_angle = min(candidates, key=error)
        radius *= 0.25

    best_angle = wrapped(best_angle)
    ik.pole_angle = best_angle
    bpy.context.view_layer.update()
    return best_angle


def ensure_limb_constraints(armature, component, control_pose, pole_pose=None):
    owner = armature.pose.bones.get(component.source_bones[-2].bone_name)
    end = armature.pose.bones.get(component.source_bones[-1].bone_name)
    if owner is None or end is None:
        raise ComponentArtifactConflict("Limb IK owner or end bone is missing.")
    name = f"COA_COMP_{component.component_uuid[:8]}_IK"
    expected_joint = (
        owner.head.copy()
        if pole_pose is not None and not component.pole_angle_valid
        else None
    )
    ik = _managed_constraint(owner, component, name, "IK")
    ik.target = armature
    ik.subtarget = control_pose.name
    ik.chain_count = component.ik_chain_length
    ik.use_stretch = component.use_stretch
    if pole_pose is not None:
        ik.pole_target = armature
        ik.pole_subtarget = pole_pose.name
        if component.pole_angle_valid:
            ik.pole_angle = component.pole_angle
        elif expected_joint is not None:
            component.pole_angle = _fit_pole_angle(
                armature,
                owner,
                ik,
                expected_joint,
                _compute_pole_angle(armature, component, pole_pose),
            )
            component.pole_angle_valid = True
        else:
            component.pole_angle = _compute_pole_angle(
                armature,
                component,
                pole_pose,
            )
            component.pole_angle_valid = True
            ik.pole_angle = component.pole_angle
    else:
        ik.pole_target = None
        ik.pole_subtarget = ""
        ik.pole_angle = 0.0
    component.constraint_bone = owner.name
    component.constraint_name = name
    _record_artifact(
        component,
        "ik_constraint",
        "CONSTRAINT",
        bone_name=owner.name,
        constraint_name=name,
        owned=True,
    )

    chain = []
    current = owner
    for _index in range(component.ik_chain_length):
        if current is None:
            break
        chain.append(current)
        current = current.parent
    if component.ik_solver_mode == "PLANAR":
        bend_axis = (
            _auto_bend_axis(armature, component)
            if component.bend_axis == "AUTO"
            else component.bend_axis
        )
        for pose_bone in chain:
            pose_bone.lock_ik_x = bend_axis != "X"
            pose_bone.lock_ik_y = bend_axis != "Y"
            pose_bone.lock_ik_z = bend_axis != "Z"
    else:
        for pose_bone in chain:
            pose_bone.lock_ik_x = False
            pose_bone.lock_ik_y = False
            pose_bone.lock_ik_z = False
    for pose_bone in chain:
        pose_bone.ik_stretch = 1.0 if component.use_stretch else 0.0

    rotation_name = f"COA_COMP_{component.component_uuid[:8]}_EndRotation"
    rotation = end.constraints.get(rotation_name)
    if component.end_rotation_mode == "NONE":
        if rotation is not None and _owns_constraint(
            component,
            end.name,
            rotation_name,
        ):
            end.constraints.remove(rotation)
        _remove_artifacts(
            component,
            role="end_rotation_constraint",
            data_type="CONSTRAINT",
            bone_name=end.name,
            constraint_name=rotation_name,
        )
    else:
        rotation = _managed_constraint(
            end,
            component,
            rotation_name,
            "COPY_ROTATION",
        )
        rotation.target = armature
        rotation.subtarget = control_pose.name
        if component.end_rotation_mode == "COPY_LOCAL":
            rotation.owner_space = "LOCAL"
            rotation.target_space = "LOCAL"
        else:
            rotation.owner_space = "WORLD"
            rotation.target_space = "WORLD"
        _record_artifact(
            component,
            "end_rotation_constraint",
            "CONSTRAINT",
            bone_name=end.name,
            constraint_name=rotation_name,
            owned=True,
        )
    return ik


def ensure_limb_component(armature, component):
    owner_name = component.source_bones[-2].bone_name
    constraint_name = f"COA_COMP_{component.component_uuid[:8]}_IK"
    owner = armature.pose.bones.get(owner_name)
    is_new_component = (
        owner is not None
        and owner.constraints.get(constraint_name) is None
    )
    initial_end_matrix = (
        armature.pose.bones[
            component.source_bones[-1].bone_name
        ].matrix.copy()
        if is_new_component
        else None
    )
    _frame_pose, control_pose, pole_pose = ensure_limb_control_bones(
        armature,
        component,
    )
    widget = ensure_component_widget(armature, component)
    control_pose.custom_shape = widget
    control_pose.rotation_mode = "XYZ"
    if initial_end_matrix is not None:
        # Match the generated target to the evaluated hand/foot pose before
        # enabling IK so adding a component does not snap a posed limb to rest.
        control_pose.matrix = initial_end_matrix
        bpy.context.view_layer.update()
    control_pose.use_custom_shape_bone_size = False
    if hasattr(control_pose, "custom_shape_wire_width"):
        control_pose.custom_shape_wire_width = 1.5
    apply_component_channels(control_pose, component, translation=True)
    ensure_depth_constraint(control_pose, component)
    if pole_pose is not None:
        pole_widget = ensure_component_widget(
            armature,
            component,
            role="bend_widget",
            widget="DIAMOND",
            size=component.widget_size * 0.65,
        )
        pole_pose.custom_shape = pole_widget
        pole_pose.use_custom_shape_bone_size = False
        pole_pose.rotation_mode = "XYZ"
        pole_pose.lock_location = (False, False, False)
        pole_pose.lock_rotation = (True, True, True)
        pole_pose.lock_scale = (True, True, True)
        if hasattr(pole_pose, "custom_shape_wire_width"):
            pole_pose.custom_shape_wire_width = 1.5
    ensure_limb_constraints(armature, component, control_pose, pole_pose)
    for index, reference in enumerate(component.source_bones):
        data_bone = armature.data.bones.get(reference.bone_name)
        if data_bone is None:
            raise ComponentArtifactConflict(
                f"Source bone '{reference.bone_name}' is missing."
            )
        _ensure_source_is_available(
            armature,
            data_bone,
            component,
            f"source_bone_{index}",
        )
        functions.set_bone_group(
            None,
            armature,
            armature.pose.bones[data_bone.name],
            group=COMPONENT_DEFORM_COLLECTION,
            theme=None,
            visible=True,
            exclusive=False,
        )
    if pole_pose is None:
        # Destructive cleanup is deliberately last. If any earlier reconcile
        # step fails, rollback still owns a valid custom-shape Object pointer.
        bend_widget = find_component_object(
            armature,
            component.component_uuid,
            "bend_widget",
        )
        if bend_widget is not None:
            bpy.data.objects.remove(bend_widget, do_unlink=True)
        _remove_artifacts(
            component,
            role="bend_widget",
            data_type="OBJECT",
        )
    return control_pose


def component_artifact_bones(armature, component):
    names = {reference.bone_name for reference in component.source_bones}
    names.update(
        name
        for name in (
            component.frame_bone,
            component.control_bone,
            component.pole_bone,
        )
        if name
    )
    return [armature.pose.bones[name] for name in names if name in armature.pose.bones]
