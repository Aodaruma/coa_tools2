#!/usr/bin/env python3
"""Build the distributable COA Tools 2 State/Character Rig demo scene.

Run from the repository root with Blender 5.1 or newer::

    blender --factory-startup --python scripts/blender_rig_semantic_character_sample.py

The file is saved to ``samples/semantic_character_rig_demo.blend``.
This builder refuses to run without ``--factory-startup`` and must never be
executed inside an existing project.
"""

from __future__ import annotations

import math
from pathlib import Path
import sys
import uuid

import bpy
from mathutils import Vector


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPOSITORY_ROOT / "samples" / "semantic_character_rig_demo.blend"


def _require_factory_startup(argv, current_filepath="", is_dirty=False):
    if "--factory-startup" not in argv:
        raise RuntimeError(
            "This sample builder replaces the current scene. Run Blender with "
            "--factory-startup; do not execute it inside an existing project."
        )
    if current_filepath or is_dirty:
        raise RuntimeError(
            "This sample builder requires an untouched factory scene. Close "
            "the current project and run it from a new --factory-startup process."
        )


def _slug(value: str) -> str:
    return "_".join(value.lower().split())


def _collection(name: str, *, parent=None):
    collection = bpy.data.collections.new(name)
    (parent or bpy.context.scene.collection).children.link(collection)
    return collection


def _move_to_collection(obj, collection):
    for linked in tuple(obj.users_collection):
        linked.objects.unlink(obj)
    collection.objects.link(obj)


def _activate_armature(armature, *, pose=True):
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    armature.hide_set(False)
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    if pose:
        bpy.ops.object.mode_set(mode="POSE")


def _new_sprite_armature(name, location, collection):
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    result = bpy.ops.coa_tools2.create_sprite_object()
    assert result == {"FINISHED"}, result
    armature = bpy.context.active_object
    assert armature is not None and armature.type == "ARMATURE"
    armature.name = name
    armature.data.name = f"{name}_Rig"
    armature.location = location
    armature.show_in_front = True
    armature.show_name = False
    armature.data.display_type = "BBONE"
    armature.data.show_names = False
    armature.data.show_axes = False
    _move_to_collection(armature, collection)
    return armature


def _bone(edit_bones, name, head, tail, parent=None):
    bone = edit_bones.new(name)
    bone.head = head
    bone.tail = tail
    bone.parent = parent
    bone.use_connect = parent is not None and Vector(head) == Vector(parent.tail)
    try:
        bone.align_roll(Vector((0.0, 1.0, 0.0)))
    except ValueError:
        pass
    return bone


def _material(name, color):
    material = bpy.data.materials.new(name)
    material.diffuse_color = (*color, 1.0)
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    emission = tree.nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (*color, 1.0)
    emission.inputs["Strength"].default_value = 0.8
    tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return material


def _grid_mesh(name, width=1.7, height=1.7, columns=3, rows=3):
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    vertices = []
    for row in range(rows):
        z = -height * 0.5 + height * row / (rows - 1)
        for column in range(columns):
            x = -width * 0.5 + width * column / (columns - 1)
            vertices.append((x, 0.0, z))
    faces = []
    for row in range(rows - 1):
        for column in range(columns - 1):
            lower = row * columns + column
            faces.append(
                (lower, lower + 1, lower + columns + 1, lower + columns)
            )
    mesh.from_pydata(vertices, (), faces)
    mesh.update()
    return mesh


def _flat_target(name, collection, material, *, parent, location):
    obj = bpy.data.objects.new(name, _grid_mesh(name))
    collection.objects.link(obj)
    obj.data.materials.append(material)
    obj.parent = parent
    obj.location = location
    obj.show_in_front = True
    obj.shape_key_add(name="Basis")
    return obj


def _add_relative_shape(obj, name, transform):
    key = obj.shape_key_add(name=name)
    basis = obj.data.shape_keys.reference_key
    for index, (point, base) in enumerate(zip(key.data, basis.data)):
        point.co = transform(base.co.copy(), index)
    return key


def _ribbon_mesh(name, points, width):
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    points = tuple(Vector(point) for point in points)
    vertices = []
    for index, point in enumerate(points):
        if index == 0:
            direction = points[1] - point
        elif index == len(points) - 1:
            direction = point - points[index - 1]
        else:
            direction = points[index + 1] - points[index - 1]
        planar = Vector((direction.x, 0.0, direction.z))
        if planar.length < 1.0e-8:
            planar = Vector((1.0, 0.0, 0.0))
        planar.normalize()
        perpendicular = Vector((-planar.z, 0.0, planar.x)) * width * 0.5
        vertices.extend((point - perpendicular, point + perpendicular))
    faces = [
        (index * 2, index * 2 + 1, index * 2 + 3, index * 2 + 2)
        for index in range(len(points) - 1)
    ]
    mesh.from_pydata(vertices, (), faces)
    mesh.update()
    return mesh


def _flat_ribbon(
    name,
    collection,
    material,
    *,
    armature,
    points,
    source_bones,
    width=0.34,
):
    obj = bpy.data.objects.new(name, _ribbon_mesh(name, points, width))
    collection.objects.link(obj)
    obj.data.materials.append(material)
    obj.parent = armature
    modifier = obj.modifiers.new(f"{name}_Armature", "ARMATURE")
    modifier.object = armature
    for index, bone_name in enumerate(source_bones):
        group = obj.vertex_groups.new(name=bone_name)
        group.add((index * 2, index * 2 + 1), 1.0, "REPLACE")
        if index == len(source_bones) - 1:
            group.add((index * 2 + 2, index * 2 + 3), 1.0, "REPLACE")
    obj.show_in_front = True
    return obj


def _wire_shape(name, vertices, edges, collection):
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, edges, ())
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.hide_render = True
    obj.hide_set(True)
    return obj


def _demo_widgets(collection):
    segments = 32
    circle_vertices = [
        (
            math.cos(math.tau * index / segments),
            math.sin(math.tau * index / segments),
            0.0,
        )
        for index in range(segments)
    ]
    circle_edges = [(index, (index + 1) % segments) for index in range(segments)]
    circle = _wire_shape(
        "DEMO_WGT_Circle", circle_vertices, circle_edges, collection
    )
    diamond = _wire_shape(
        "DEMO_WGT_Diamond",
        ((-1.0, 0.0, 0.0), (0.0, -0.65, 0.0), (1.0, 0.0, 0.0), (0.0, 0.65, 0.0)),
        ((0, 1), (1, 2), (2, 3), (3, 0)),
        collection,
    )
    # A compact hand/foot-like outline.  It deliberately has no direction
    # arrow: translation and rotation come from the transform gizmo itself.
    hand = _wire_shape(
        "DEMO_WGT_HandIK",
        (
            (-1.05, -0.45, 0.0),
            (-0.55, -0.72, 0.0),
            (0.45, -0.66, 0.0),
            (1.08, -0.25, 0.0),
            (0.92, 0.34, 0.0),
            (0.30, 0.65, 0.0),
            (-0.58, 0.62, 0.0),
            (-1.08, 0.25, 0.0),
        ),
        tuple((index, (index + 1) % 8) for index in range(8)),
        collection,
    )
    return {"circle": circle, "diamond": diamond, "hand": hand}


def _set_custom_shape(pose_bone, shape, scale=0.45):
    pose_bone.custom_shape = shape
    pose_bone.use_custom_shape_bone_size = False
    pose_bone.custom_shape_scale_xyz = (scale, scale, scale)
    bone_color = getattr(pose_bone, "color", None)
    if bone_color is not None:
        bone_color.palette = "DEFAULT"


def _key_pose(pose_bone, frame, *, location=None, rotation=None):
    pose_bone.rotation_mode = "XYZ"
    if location is not None:
        pose_bone.location = location
        pose_bone.keyframe_insert("location", frame=frame, group=pose_bone.name)
    if rotation is not None:
        pose_bone.rotation_euler = rotation
        pose_bone.keyframe_insert(
            "rotation_euler", frame=frame, group=pose_bone.name
        )


def _new_semantic_component(armature, label, source_names):
    from coa_tools2.rig_control.blender.artifacts import ensure_rig_instance_id

    rig_data = armature.coa_tools2_rig
    ensure_rig_instance_id(armature)
    component = rig_data.rig_components.add()
    component.component_uuid = str(uuid.uuid4())
    component.semantic_id = _slug(label)
    component.label = label
    component.component_type = "SEMANTIC"
    component.deformation_mode = "PARAMETRIC"
    component.build_mode = "GENERATED"
    component.orientation_reference = source_names[-1]
    component.orientation_mode = "SOURCE_BONE"
    component.depth_mode = "LIMITED"
    component.depth_min = -1.0
    component.depth_max = 1.0
    component.widget = "SQUARE"
    for bone_name in source_names:
        reference = component.source_bones.add()
        reference.bone_name = bone_name
    rig_data.rig_components_index = len(rig_data.rig_components) - 1
    return component


def _new_semantic_stage(component, stage_type, label, order, source_names=()):
    stage = component.semantic_stages.add()
    stage.stage_uuid = str(uuid.uuid4())
    stage.semantic_id = _slug(label)
    stage.label = label
    stage.stage_type = stage_type
    stage.order = order
    for bone_name in source_names:
        reference = stage.source_bones.add()
        reference.bone_name = bone_name
    return stage


def _create_state_demo(collection, material):
    armature = _new_sprite_armature(
        "DEMO_A_StateRig", (-8.2, 0.0, 2.8), collection
    )
    target = _flat_target(
        "DEMO_A_StateOutput",
        collection,
        material,
        parent=armature,
        location=(4.9, 0.05, 1.15),
    )
    for column, row in ((0, 0), (1, 0), (0, 1), (1, 1)):
        x_sign = -1.0 if column == 0 else 1.0
        z_sign = -1.0 if row == 0 else 1.0

        def transform(point, index, x_sign=x_sign, z_sign=z_sign):
            falloff = 0.35 + 0.10 * (index % 3)
            point.x += x_sign * falloff
            point.z += z_sign * (0.18 + 0.05 * (index // 3))
            return point

        _add_relative_shape(target, f"State_{column}_{row}", transform)

    _activate_armature(armature)
    # State Rig creation interprets the scene cursor in armature-local space.
    # Put it at this demo armature so the Widget and its name stay inside the
    # A section instead of appearing at the world origin.
    bpy.context.scene.cursor.location = armature.matrix_world.translation
    result = bpy.ops.coa_tools2.add_rig_control(
        "EXEC_DEFAULT",
        label="2 x 2 State Matrix",
        control_type="POINT_2D_RECT",
        width=3.6,
        height=2.4,
        rectangle_mode="MATRIX",
        grid_columns=2,
        grid_rows=2,
        matrix_mix_policy="FULL",
        create_initial_binding=False,
    )
    assert result == {"FINISHED"}, result
    control = armature.coa_tools2_rig.rig_controls[-1]
    assert control.state_mode == "MATRIX_2D"
    assert len(control.state_points) == 4
    for index, point in enumerate(control.state_points):
        control.state_points_index = index
        result = bpy.ops.coa_tools2.assign_rig_state_point(
            "EXEC_DEFAULT",
            target_object_name=target.name,
            shape_key=f"State_{point.column}_{point.row}",
        )
        assert result == {"FINISHED"}, (index, result)

    handle = armature.pose.bones[control.control_bone]
    _key_pose(handle, 1, location=(0.0, 0.0, 0.0))
    _key_pose(handle, 24, location=(1.8, 1.2, 0.0))
    _key_pose(handle, 48, location=(3.6, 2.4, 0.0))
    assert target.data.shape_keys.animation_data is not None
    assert len(target.data.shape_keys.animation_data.drivers) == 4
    return armature, control, target


def _create_pose_map_demo(collection, material, widgets):
    from coa_tools2.rig_control.blender.semantic_compiler import (
        compile_semantic_component,
    )
    from coa_tools2.rig_control.blender.selection import select_pose_bone

    armature = _new_sprite_armature(
        "DEMO_B_4D_PoseMap", (-0.9, 0.0, 3.25), collection
    )
    bpy.ops.object.mode_set(mode="EDIT")
    source = _bone(
        armature.data.edit_bones,
        "face_source",
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 1.0),
    )
    # EditBone RNA proxies become invalid as soon as Edit Mode ends.
    source_name = source.name
    bpy.ops.object.mode_set(mode="POSE")
    _activate_armature(armature)
    select_pose_bone(armature, source_name, exclusive=True)
    assert bpy.context.object == armature
    assert bpy.context.mode == "POSE"
    assert bpy.context.active_pose_bone is not None
    assert bpy.context.active_pose_bone.name == source_name
    result = bpy.ops.coa_tools2.add_semantic_rig(
        "EXEC_DEFAULT", label="4D Recorded Pose Map", initial_dimensions=4
    )
    assert result == {"FINISHED"}, result
    component = armature.coa_tools2_rig.rig_components[-1]
    projected, pose_map = component.semantic_stages
    component.depth_mode = "LIMITED"
    component.depth_min = -1.0
    component.depth_max = 1.0
    projected.visual_axis = (0.18, 0.94, 0.28)
    compile_semantic_component(armature, component)

    # A projected apparent-depth axis is intentionally kept inside the art
    # plane.  Combining that proxy with both screen translation axes would
    # therefore make a nominal four-dimensional field linearly dependent.
    # This demo uses four genuinely independent control channels instead.
    channel_specs = (
        ("move_x", "Move X", "LOC_X"),
        ("move_y", "Move Y", "LOC_Y"),
        ("turn_x", "Turn X", "ROT_X"),
        ("turn_z", "Turn Z", "ROT_Z"),
    )
    for channel, (channel_id, label, transform_type) in zip(
        pose_map.inputs, channel_specs
    ):
        channel.channel_id = channel_id
        channel.label = label
        channel.terms.clear()
        term = channel.terms.add()
        term.term_uuid = str(uuid.uuid4())
        term.source_stage_uuid = projected.stage_uuid
        term.source_object = armature
        term.source_bone = projected.control_bone
        term.source_kind = "TRANSFORM"
        term.transform_type = transform_type
        term.transform_space = "LOCAL_SPACE"
    compile_semantic_component(armature, component)

    target = _flat_target(
        "DEMO_B_FlatShapeKeyArt",
        collection,
        material,
        parent=armature,
        location=(2.4, 0.05, 0.55),
    )
    target.show_wire = True
    target.show_all_edges = True

    def expression(point, index):
        column = index % 3
        row = index // 3
        point.x *= 0.78 + 0.08 * row
        point.x += (row - 1) * 0.18
        point.z += math.sin(column * math.pi * 0.5) * 0.28
        if index == 4:
            point.z += 0.32
        return point

    key = _add_relative_shape(target, "Expression", expression)
    component.semantic_stages_index = 1
    result = bpy.ops.coa_tools2.add_semantic_output(
        "EXEC_DEFAULT",
        label="Flat Shape Expression",
        target_kind="SHAPE_KEY",
        target_object_name=target.name,
        target_name=key.name,
    )
    assert result == {"FINISHED"}, result

    control = armature.pose.bones[projected.control_bone]
    _set_custom_shape(control, widgets["diamond"], 0.55)
    sample_poses = (
        ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), 0.10),
        ((1.0, 0.0, 0.0), (0.0, 0.0, 0.0), 0.95),
        ((-1.0, 0.0, 0.0), (0.0, 0.0, 0.0), 0.30),
        ((0.0, 1.0, 0.0), (0.0, 0.0, 0.0), 0.72),
        ((0.0, -1.0, 0.0), (0.0, 0.0, 0.0), 0.42),
        ((0.0, 0.0, 0.0), (0.65, 0.0, 0.0), 0.84),
        ((0.0, 0.0, 0.0), (-0.65, 0.0, 0.0), 0.22),
        ((0.0, 0.0, 0.0), (0.0, 0.0, 0.65), 0.78),
        ((0.0, 0.0, 0.0), (0.0, 0.0, -0.65), 0.36),
    )
    for location, rotation, output_value in sample_poses:
        control.location = location
        control.rotation_euler = rotation
        bpy.context.view_layer.update()
        result = bpy.ops.coa_tools2.begin_semantic_sample("EXEC_DEFAULT")
        assert result == {"FINISHED"}, result
        key.value = output_value
        result = bpy.ops.coa_tools2.commit_semantic_sample("EXEC_DEFAULT")
        assert result == {"FINISHED"}, result

    assert len(pose_map.inputs) == 4
    assert len(pose_map.samples) == len(sample_poses)
    assert tuple(
        channel.terms[0].transform_type for channel in pose_map.inputs
    ) == ("LOC_X", "LOC_Y", "ROT_X", "ROT_Z")
    assert len(
        {
            tuple(round(value.value, 6) for value in sample.inputs)
            for sample in pose_map.samples
        }
    ) == len(sample_poses)
    assert all(abs(point.co.y) < 1.0e-8 for block in target.data.shape_keys.key_blocks for point in block.data)
    control.location = (0.0, 0.0, 0.0)
    control.rotation_euler = (0.0, 0.0, 0.0)
    _key_pose(control, 1, location=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 0.0))
    _key_pose(
        control,
        24,
        location=(0.62, 0.30, 0.0),
        rotation=(0.30, 0.0, 0.24),
    )
    _key_pose(
        control,
        48,
        location=(-0.62, -0.24, 0.0),
        rotation=(-0.28, 0.0, -0.22),
    )
    assert target.data.shape_keys.animation_data is not None
    assert target.data.shape_keys.animation_data.drivers
    return armature, component, projected, pose_map, target


def _create_projected_ik_demo(collection, material, widgets):
    from coa_tools2.rig_control.blender.semantic_compiler import (
        compile_semantic_component,
    )

    armature = _new_sprite_armature(
        "DEMO_C_ProjectedIK", (-8.0, 0.0, -4.1), collection
    )
    points = (
        (0.0, 0.0, 0.0),
        (1.35, 0.0, 0.62),
        (2.62, 0.0, 0.12),
        (3.35, 0.0, 0.12),
    )
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = armature.data.edit_bones
    bones = []
    for index in range(len(points) - 1):
        bones.append(
            _bone(
                edit_bones,
                ("upper", "lower", "hand")[index],
                points[index],
                points[index + 1],
                bones[-1] if bones else None,
            )
        )
    # Resolve names while the EditBone proxies are still valid.
    source_names = tuple(bone.name for bone in bones)
    bpy.ops.object.mode_set(mode="POSE")
    _activate_armature(armature)
    ribbon = _flat_ribbon(
        "DEMO_C_FlatIKArt",
        collection,
        material,
        armature=armature,
        points=points,
        source_bones=source_names,
        width=0.48,
    )
    component = _new_semantic_component(
        armature, "Projected IK and Circular Pole", source_names
    )
    stage = _new_semantic_stage(
        component, "CHAIN_IK", "Projected IK", 0, source_names
    )
    stage.chain_length = 2
    stage.use_pole = True
    stage.allow_stretch = False
    stage.visual_axis = (0.18, 0.94, 0.28)
    result = compile_semantic_component(armature, component)
    info = result["stage_results"][stage.stage_uuid]
    control = armature.pose.bones[stage.control_bone]
    pole = armature.pose.bones[stage.pole_bone]
    _set_custom_shape(control, widgets["hand"], 0.72)
    _set_custom_shape(pole, widgets["circle"], 0.44)

    _key_pose(control, 1, location=(0.0, 0.0, 0.0))
    _key_pose(control, 24, location=(0.42, -0.36, 0.72))
    _key_pose(control, 48, location=(-0.25, 0.44, -0.50))
    pole.keyframe_insert("location", frame=1, group=pole.name)
    pole.keyframe_insert("location", frame=24, group=pole.name)
    pole.keyframe_insert("location", frame=48, group=pole.name)

    stage_role = f"semantic:{stage.stage_uuid}:"
    mechanism = tuple(
        artifact.bone_name
        for artifact in component.artifacts
        if artifact.role.startswith(stage_role + "mechanism_bone:")
    )
    projected = tuple(
        artifact.bone_name
        for artifact in component.artifacts
        if artifact.role.startswith(stage_role + "projected_joint:")
    )
    presentation = tuple(
        artifact.bone_name
        for artifact in component.artifacts
        if artifact.role.startswith(stage_role + "presentation_bone:")
    )
    pole_constraint = next(
        constraint for constraint in pole.constraints if constraint.type == "LIMIT_DISTANCE"
    )
    assert len(mechanism) == len(presentation) == 3
    assert len(projected) == 4
    assert pole_constraint.limit_mode == "LIMITDIST_ONSURFACE"
    assert info.primary_control_bone == stage.control_bone
    return armature, component, stage, ribbon


def _create_spline_secondary_demo(collection, internal_collection, material, widgets):
    from coa_tools2.rig_control.blender.semantic_compiler import (
        compile_semantic_component,
    )
    from coa_tools2.rig_control.blender.semantic_secondary import (
        bake_secondary_motion,
    )

    armature = _new_sprite_armature(
        "DEMO_D_SplineSecondary", (3.3, 0.0, -5.2), collection
    )
    points = (
        (0.0, 0.0, 0.0),
        (0.10, 0.0, 0.95),
        (-0.08, 0.0, 1.90),
        (0.16, 0.0, 2.85),
        (0.02, 0.0, 3.80),
    )
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = armature.data.edit_bones
    bones = []
    for index in range(len(points) - 1):
        bones.append(
            _bone(
                edit_bones,
                f"strand.{index:03d}",
                points[index],
                points[index + 1],
                bones[-1] if bones else None,
            )
        )
    # Resolve names while the EditBone proxies are still valid.
    source_names = tuple(bone.name for bone in bones)
    bpy.ops.object.mode_set(mode="POSE")
    _activate_armature(armature)
    ribbon = _flat_ribbon(
        "DEMO_D_FlatSplineArt",
        collection,
        material,
        armature=armature,
        points=points,
        source_bones=source_names,
        width=0.42,
    )
    component = _new_semantic_component(
        armature, "Spline Chain plus Secondary Motion", source_names
    )
    spline_stage = _new_semantic_stage(
        component, "SPLINE", "Spline Chain", 0, source_names
    )
    spline_stage.spline_control_count = 4
    spline_stage.root_pin = True
    spline_stage.tip_pin = False
    secondary_stage = _new_semantic_stage(
        component, "SECONDARY_MOTION", "Secondary Motion", 1
    )
    secondary_stage.depends_on = spline_stage.stage_uuid
    secondary_stage.frequency_hz = 1.8
    secondary_stage.damping_ratio = 0.42
    secondary_stage.substeps = 3
    secondary_stage.pre_roll = 4
    secondary_stage.bake_start = 1
    secondary_stage.bake_end = 48

    compiled = compile_semantic_component(armature, component)
    spline = compiled["stage_results"][spline_stage.stage_uuid].spline_info
    assert spline is not None
    curve_object = bpy.data.objects[spline.curve_object]
    _move_to_collection(curve_object, internal_collection)
    controls = tuple(armature.pose.bones[name] for name in spline.control_bones)
    for control in controls:
        _set_custom_shape(control, widgets["circle"], 0.28)
        _key_pose(control, -3, location=(0.0, 0.0, 0.0))
        _key_pose(control, 1, location=(0.0, 0.0, 0.0))
        _key_pose(control, 24, location=(0.0, 0.0, 0.0))
        _key_pose(control, 48, location=(0.0, 0.0, 0.0))
    _key_pose(controls[1], 15, location=(0.85, 0.0, 0.18))
    _key_pose(controls[1], 32, location=(-0.42, 0.0, 0.02))
    _key_pose(controls[2], 20, location=(-0.72, 0.0, 0.22))
    _key_pose(controls[2], 39, location=(0.68, 0.0, -0.08))

    baked = bake_secondary_motion(
        armature,
        component,
        secondary_stage,
        default_source_bones=spline.control_bones,
    )
    assert secondary_stage.secondary_baked
    assert baked.sample_count == 48
    action = bpy.data.actions.get(baked.action_name)
    assert action is not None
    assert action.get("coa_semantic_stage_uuid") == secondary_stage.stage_uuid
    return armature, component, spline_stage, secondary_stage, spline, ribbon


def _evaluated_world_vertices(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        return tuple(evaluated.matrix_world @ vertex.co for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def _maximum_art_depth(armature, art_frame_bone, obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated_armature = armature.evaluated_get(depsgraph)
    art_world = (
        evaluated_armature.matrix_world
        @ evaluated_armature.pose.bones[art_frame_bone].matrix
    )
    inverse = art_world.inverted()
    return max(abs((inverse @ point).z) for point in _evaluated_world_vertices(obj))


def _text_object(name, body, location, collection, material, *, size=0.42):
    data = bpy.data.curves.new(f"{name}_Font", "FONT")
    data.body = body
    data.align_x = "CENTER"
    data.align_y = "CENTER"
    data.size = size
    data.extrude = 0.0
    data.materials.append(material)
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler.x = math.pi * 0.5
    obj.hide_render = False
    return obj


def _create_readme(scene):
    readme = bpy.data.texts.new("README_SemanticCharacterRig.txt")
    readme.write(
        "COA Tools 2 — State Rig / Character Rig Sample\n"
        "====================================================\n\n"
        "This file is generated by scripts/blender_rig_semantic_character_sample.py.\n"
        "Animation samples are keyed at frames 1, 24 and 48.\n\n"
        "Open / driver runtime\n"
        "  Recommended: .\\scripts\\launch_blender_rig_manual_test.ps1 -OpenSemanticSample\n"
        "  The current development add-on must be enabled before this file is opened.\n"
        "  If B is static after opening with an older/disabled add-on, enable the development\n"
        "  add-on and reopen this file so coa_pose_field_scalar is registered first.\n"
        "  All four Armatures are saved in multi-object Pose Mode for direct CTRL selection.\n\n"
        "A / State Rig — 2 x 2 State Matrix\n"
        "  A Geometry Nodes matrix widget drives four Shape Key states.\n"
        "  Drag its circular handle in the visible matrix.\n\n"
        "B / Character Rig — 4D Recorded Pose Map\n"
        "  Click the diamond CTRL at the left of the amber mesh.\n"
        "  G in the screen plane supplies Move X/Y; R X X and R Z Z supply local Turn X/Z.\n"
        "  Nine recorded samples interpolate the flat mesh Shape Key with a local RBF.\n"
        "  The four channels are independent and the artwork remains a flat X/Z mesh.\n"
        "  Changing frame restores the keyed demo pose after a temporary manual edit.\n\n"
        "C / Character Rig — Projected IK\n"
        "  The hand-shaped CTRL is active on open; move it with G to drive real IK.\n"
        "  Move the circular bend CTRL around its Limit Distance rail to change the bend.\n"
        "  Projected joints and presentation bones return the source ribbon to the Art Plane.\n\n"
        "D / Character Rig — Spline + Secondary Motion\n"
        "  Four circle CTRLs Hook a generated NURBS curve feeding Spline IK.\n"
        "  A deterministic spring layer is baked to a managed NLA Action.\n"
        "  Edit the Spline controls, then use Bake Secondary Motion to rebuild the layer.\n\n"
        "UI\n"
        "  N-panel > COA Tools2 > State Rig shows A.\n"
        "  N-panel > COA Tools2 > Character Rig shows B/C/D.\n"
        "  Generated mechanism bones live in the hidden COA Rig MCH bone collection.\n"
        "  The DEMO_Internal collection contains the generated Spline curve.\n\n"
        "Notes\n"
        "  Semantic custom-shape Geometry Nodes are intentionally a later presentation phase.\n"
        "  The simple diamond/hand/circle shapes in this sample only make controls easy to find.\n"
        "  All generated Character Rig artifacts are tagged by instance/component/stage identity.\n"
    )
    scene["coa_demo_readme"] = readme.name
    scene["coa_demo_frames"] = "1,24,48"
    scene["coa_demo_sections"] = "A State Rig; B 4D Pose Map; C Projected IK; D Spline Secondary"
    return readme


def _camera(scene):
    data = bpy.data.cameras.new("DEMO_FrontCamera")
    camera = bpy.data.objects.new("DEMO_FrontCamera", data)
    scene.collection.objects.link(camera)
    camera.location = (0.0, -30.0, 0.65)
    target = Vector((0.0, 0.0, 0.65))
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    data.type = "ORTHO"
    # Blender's orthographic scale is the horizontal span here.  Keep enough
    # width that the resulting 16:9 vertical span also contains both rows,
    # the title and every section label.
    data.ortho_scale = 25.5
    scene.camera = camera
    return camera


def _hide_source_bone_collection(armature):
    source = armature.data.collections_all.get("Bones")
    if source is not None:
        source.is_visible = False


def _prepare_saved_view(scene, armatures, active_armature, active_bone):
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    for armature in armatures:
        armature.hide_set(False)
        armature.select_set(True)
    bpy.context.view_layer.objects.active = active_armature
    # Blender 5.x moved pose selection away from Bone RNA.  Multi-object Edit
    # Mode remains a stable way to author the saved active/selected PoseBone.
    bpy.ops.object.mode_set(mode="EDIT")
    for armature in armatures:
        for edit_bone in armature.data.edit_bones:
            selected = armature == active_armature and edit_bone.name == active_bone
            edit_bone.select = selected
            edit_bone.select_head = selected
            edit_bone.select_tail = selected
        if armature == active_armature:
            active = armature.data.edit_bones[active_bone]
            armature.data.edit_bones.active = active
    bpy.ops.object.mode_set(mode="POSE")
    assert all(armature.mode == "POSE" for armature in armatures)
    assert bpy.context.active_pose_bone.name == active_bone
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            space = area.spaces.active
            space.shading.type = "MATERIAL"
            space.overlay.show_bones = True
            space.overlay.show_relationship_lines = False
            if space.region_3d is not None:
                space.region_3d.view_perspective = "CAMERA"


def _validate_reloaded_sample(output, armature_names, active_armature_name, active_bone):
    """Reopen the distributable file and verify its interactive saved state."""

    bpy.ops.wm.open_mainfile(filepath=str(output))
    armatures = tuple(bpy.data.objects[name] for name in armature_names)
    assert bpy.context.mode == "POSE"
    assert all(armature.mode == "POSE" and armature.select_get() for armature in armatures)
    assert bpy.context.active_object.name == active_armature_name
    assert bpy.context.active_pose_bone.name == active_bone
    for armature in armatures[1:]:
        source = armature.data.collections_all.get("Bones")
        assert source is None or not source.is_visible

    pose_armature = bpy.data.objects["DEMO_B_4D_PoseMap"]
    component = pose_armature.coa_tools2_rig.rig_components[0]
    projected, pose_map = component.semantic_stages
    assert tuple(
        channel.terms[0].transform_type for channel in pose_map.inputs
    ) == ("LOC_X", "LOC_Y", "ROT_X", "ROT_Z")
    assert len(
        {
            tuple(round(value.value, 6) for value in sample.inputs)
            for sample in pose_map.samples
        }
    ) == 9
    target = bpy.data.objects["DEMO_B_FlatShapeKeyArt"]
    assert target.show_wire and target.show_all_edges
    key = target.data.shape_keys.key_blocks["Expression"]
    values = []
    for frame in (1, 24, 48):
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        values.append(round(key.value, 6))
    assert len(set(values)) == 3, values

    control = pose_armature.pose.bones[projected.control_bone]
    bpy.context.scene.frame_set(24)
    bpy.context.view_layer.update()
    before = key.value
    control.location.x = 1.0
    bpy.context.view_layer.update()
    assert abs(key.value - before) > 1.0e-4, (before, key.value)


def main():
    _require_factory_startup(
        sys.argv,
        current_filepath=bpy.data.filepath,
        is_dirty=bpy.data.is_dirty,
    )
    # ``--factory-startup`` is the supported way to run this builder.  Import
    # from this checkout explicitly so an installed Extension cannot shadow it.
    if str(REPOSITORY_ROOT) not in sys.path:
        sys.path.insert(0, str(REPOSITORY_ROOT))
    import coa_tools2

    # This is a file builder, not an in-place scene utility.  It is expected to
    # run in a disposable ``--factory-startup`` process.
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in tuple(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for collection in tuple(bpy.data.collections):
        bpy.data.collections.remove(collection)
    coa_tools2.register()
    scene = bpy.context.scene
    scene.name = "COA Semantic Character Rig Demo"
    scene.frame_start = 1
    scene.frame_end = 48
    scene.render.fps = 24
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.world.color = (0.025, 0.032, 0.045)

    root = _collection("DEMO_COA_Rigs")
    state_collection = _collection("A_State_Rig", parent=root)
    pose_map_collection = _collection("B_4D_Pose_Map", parent=root)
    ik_collection = _collection("C_Projected_IK", parent=root)
    spline_collection = _collection("D_Spline_Secondary", parent=root)
    guide_collection = _collection("DEMO_Guides", parent=root)
    widget_collection = _collection("DEMO_Widgets", parent=root)
    widget_collection.hide_render = True
    internal_collection = _collection("DEMO_Internal", parent=root)
    internal_collection.hide_render = True

    blue = _material("DEMO_Blue", (0.16, 0.48, 0.92))
    amber = _material("DEMO_Amber", (0.96, 0.52, 0.16))
    green = _material("DEMO_Green", (0.23, 0.76, 0.48))
    rose = _material("DEMO_Rose", (0.92, 0.28, 0.47))
    text_material = _material("DEMO_Text", (0.90, 0.93, 1.0))
    widgets = _demo_widgets(widget_collection)

    state_armature, state_control, state_target = _create_state_demo(
        state_collection, blue
    )
    pose_map = _create_pose_map_demo(pose_map_collection, amber, widgets)
    pose_armature, pose_component, projected_stage, pose_stage, pose_target = pose_map
    ik_demo = _create_projected_ik_demo(ik_collection, green, widgets)
    ik_armature, ik_component, ik_stage, ik_ribbon = ik_demo
    spline_demo = _create_spline_secondary_demo(
        spline_collection,
        internal_collection,
        rose,
        widgets,
    )
    (
        spline_armature,
        spline_component,
        spline_stage,
        secondary_stage,
        spline_info,
        spline_ribbon,
    ) = spline_demo

    _text_object(
        "DEMO_Title",
        "COA Tools 2 | State Rig + Character Rig",
        (0.0, -0.30, 7.0),
        guide_collection,
        text_material,
        size=0.66,
    )
    _text_object(
        "DEMO_Subtitle",
        "Frames 1 / 24 / 48  |  See README_SemanticCharacterRig.txt",
        (0.0, -0.30, 6.35),
        guide_collection,
        text_material,
        size=0.30,
    )
    for name, body, location in (
        ("DEMO_Label_A", "A  STATE RIG | 2 x 2 MATRIX", (-6.25, -0.28, 5.75)),
        ("DEMO_Label_B", "B  CHARACTER RIG | 4D POSE MAP", (1.30, -0.28, 5.75)),
        ("DEMO_Label_C", "C  CHARACTER RIG | PROJECTED IK", (-6.20, -0.28, -2.20)),
        ("DEMO_Label_D", "D  CHARACTER RIG | SPLINE + SECONDARY", (3.45, -0.28, -0.70)),
    ):
        _text_object(
            name,
            body,
            location,
            guide_collection,
            text_material,
            size=0.34,
        )
    for name, body, location in (
        (
            "DEMO_Guide_B",
            "B  CLICK DIAMOND | G: MOVE X/Y | R X X / R Z Z: TURN",
            (1.30, -0.28, 2.45),
        ),
        (
            "DEMO_Guide_C",
            "C  HAND: IK TARGET (ACTIVE) | CIRCLE: BEND RAIL",
            (-6.20, -0.28, -5.25),
        ),
    ):
        _text_object(
            name,
            body,
            location,
            guide_collection,
            text_material,
            size=0.22,
        )
    _create_readme(scene)
    _camera(scene)

    # Validate the core promises again at the authored sample frames.  These
    # checks make the .blend a tested deliverable rather than a static mock-up.
    assert len(state_armature.coa_tools2_rig.rig_controls) == 1
    assert len(pose_stage.inputs) == 4 and len(pose_stage.samples) >= 9
    assert ik_stage.control_bone and ik_stage.pole_bone
    assert secondary_stage.secondary_baked
    assert spline_info.curve_object in bpy.data.objects
    for frame in (1, 24, 48):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        ik_depth = _maximum_art_depth(
            ik_armature, ik_stage.art_frame_bone, ik_ribbon
        )
        spline_depth = _maximum_art_depth(
            spline_armature, spline_info.art_frame_bone, spline_ribbon
        )
        assert ik_depth < 2.0e-4, (frame, ik_depth)
        assert spline_depth < 2.0e-4, (frame, spline_depth)
    assert all(abs(vertex.co.y) < 1.0e-8 for vertex in pose_target.data.vertices)
    assert bpy.data.texts.get("README_SemanticCharacterRig.txt") is not None

    armatures = (state_armature, pose_armature, ik_armature, spline_armature)
    for armature in armatures[1:]:
        _hide_source_bone_collection(armature)
    scene.frame_set(24)
    _prepare_saved_view(
        scene,
        armatures,
        ik_armature,
        ik_stage.control_bone,
    )
    output = DEFAULT_OUTPUT.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output), compress=True)
    assert output.is_file() and output.stat().st_size > 0
    summary = (
        len(pose_stage.inputs),
        len(pose_stage.samples),
        len(spline_info.control_bones),
    )
    _validate_reloaded_sample(
        output,
        tuple(armature.name for armature in armatures),
        ik_armature.name,
        ik_stage.control_bone,
    )
    print(
        "SEMANTIC_CHARACTER_SAMPLE_OK",
        output,
        *summary,
    )


if __name__ == "__main__":
    main()
