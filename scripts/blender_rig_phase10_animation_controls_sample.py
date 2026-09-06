#!/usr/bin/env python3
"""Build the distributable COA Tools 2 Phase 10 animation-control sample.

Run from the repository root with Blender 5.1 or newer::

    blender --background --factory-startup --python \
        scripts/blender_rig_phase10_animation_controls_sample.py

The default output is ``samples/semantic_animation_controls_demo.blend``.
This builder is intentionally destructive and therefore refuses to run unless
Blender is both backgrounded and factory-started with no open project.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys
import uuid

import bpy
from mathutils import Vector


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPOSITORY_ROOT / "samples" / "semantic_animation_controls_demo.blend"
FRAMES = (1, 12, 24, 36, 48)


def _arguments():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else ()
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def _require_disposable_factory_process():
    if not bpy.app.background:
        raise RuntimeError("This builder must run with --background.")
    if "--factory-startup" not in sys.argv:
        raise RuntimeError("This builder must run with --factory-startup.")
    if bpy.data.filepath:
        raise RuntimeError(
            "An existing .blend is open. The sample builder only accepts an empty filepath."
        )


def _clear_factory_scene():
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in tuple(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for collection in tuple(bpy.data.collections):
        bpy.data.collections.remove(collection)


def _collection(name, *, parent=None):
    collection = bpy.data.collections.new(name)
    (parent or bpy.context.scene.collection).children.link(collection)
    return collection


def _move_to_collection(obj, collection):
    for current in tuple(obj.users_collection):
        current.objects.unlink(obj)
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


def _new_armature(name, location, collection):
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    assert bpy.ops.coa_tools2.create_sprite_object() == {"FINISHED"}
    armature = bpy.context.active_object
    armature.name = name
    armature.data.name = f"{name}_Rig"
    armature.location = location
    armature.show_in_front = True
    armature.data.display_type = "BBONE"
    armature.data.show_names = True
    armature.data.show_axes = False
    _move_to_collection(armature, collection)
    return armature


def _bone(edit_bones, name, head, tail, parent=None):
    bone = edit_bones.new(name)
    bone.head = head
    bone.tail = tail
    bone.parent = parent
    bone.use_connect = parent is not None and Vector(head) == Vector(parent.tail)
    return bone


def _material(name, color):
    material = bpy.data.materials.new(name)
    material.diffuse_color = (*color, 1.0)
    return material


def _grid_mesh(name, *, width=2.6, height=1.5, columns=4, rows=4):
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
            faces.append((lower, lower + 1, lower + columns + 1, lower + columns))
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, (), faces)
    mesh.update()
    return mesh


def _add_shape(obj, name, transform):
    key = obj.shape_key_add(name=name)
    basis = obj.data.shape_keys.reference_key
    for point, base in zip(key.data, basis.data):
        point.co = transform(base.co.copy())
    return key


def _mouth_target(name, collection, armature, material):
    target = bpy.data.objects.new(name, _grid_mesh(name))
    collection.objects.link(target)
    target.parent = armature
    target.location = (4.4, 0.05, 0.45)
    target.data.materials.append(material)
    target.show_wire = True
    target.show_all_edges = True
    target.shape_key_add(name="Basis")

    transforms = {
        "REST": lambda p: Vector((p.x, 0.0, p.z * 0.35)),
        "A": lambda p: Vector((p.x * 0.78, 0.0, p.z * 1.35)),
        "I": lambda p: Vector((p.x * 1.30, 0.0, p.z * 0.48)),
        "U": lambda p: Vector((p.x * 0.52, 0.0, p.z * 0.82)),
        "E": lambda p: Vector((p.x * 1.18, 0.0, p.z * 0.70 + 0.08)),
        "O": lambda p: Vector((p.x * 0.68, 0.0, p.z * 1.18)),
        "MBP": lambda p: Vector((p.x, 0.0, p.z * 0.12 - 0.06)),
    }
    for shape_name, transform in transforms.items():
        _add_shape(target, shape_name, transform)
    return target


def _ribbon_mesh(name, points, width):
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
        planar = planar.normalized() if planar.length > 1.0e-8 else Vector((1, 0, 0))
        offset = Vector((-planar.z, 0.0, planar.x)) * width * 0.5
        vertices.extend((point - offset, point + offset))
    faces = [
        (index * 2, index * 2 + 1, index * 2 + 3, index * 2 + 2)
        for index in range(len(points) - 1)
    ]
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, (), faces)
    mesh.update()
    return mesh


def _weighted_ribbon(name, collection, armature, material, points, bone_names, width):
    obj = bpy.data.objects.new(name, _ribbon_mesh(name, points, width))
    collection.objects.link(obj)
    obj.parent = armature
    obj.data.materials.append(material)
    modifier = obj.modifiers.new(f"{name}_Armature", "ARMATURE")
    modifier.object = armature
    if len(bone_names) == 1:
        group = obj.vertex_groups.new(name=bone_names[0])
        group.add(tuple(range(len(obj.data.vertices))), 1.0, "REPLACE")
    else:
        for index, bone_name in enumerate(bone_names):
            group = obj.vertex_groups.new(name=bone_name)
            group.add((index * 2, index * 2 + 1), 1.0, "REPLACE")
            if index == len(bone_names) - 1:
                group.add((index * 2 + 2, index * 2 + 3), 1.0, "REPLACE")
    return obj


def _weighted_marker(name, collection, armature, material, center, bone_name):
    x, _, z = center
    vertices = ((x - 0.45, 0, z), (x, 0, z + 0.45), (x + 0.45, 0, z), (x, 0, z - 0.45))
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, (), ((0, 1, 2, 3),))
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.parent = armature
    obj.data.materials.append(material)
    modifier = obj.modifiers.new(f"{name}_Armature", "ARMATURE")
    modifier.object = armature
    group = obj.vertex_groups.new(name=bone_name)
    group.add((0, 1, 2, 3), 1.0, "REPLACE")
    return obj


def _configure_presentation(presentation, shape, **values):
    presentation.live_preview = False
    presentation.shape = shape
    for name, value in values.items():
        setattr(presentation, name, value)


def _key_pose(pose_bone, frame, *, location=None, rotation=None, scale=None):
    pose_bone.rotation_mode = "XYZ"
    if location is not None:
        pose_bone.location = location
        pose_bone.keyframe_insert("location", frame=frame, group=pose_bone.name)
    if rotation is not None:
        pose_bone.rotation_euler = rotation
        pose_bone.keyframe_insert("rotation_euler", frame=frame, group=pose_bone.name)
    if scale is not None:
        pose_bone.scale = scale
        pose_bone.keyframe_insert("scale", frame=frame, group=pose_bone.name)


def _new_component(armature, label, source_names):
    from coa_tools2.rig_control.blender.artifacts import ensure_rig_instance_id

    ensure_rig_instance_id(armature)
    rig_data = armature.coa_tools2_rig
    component = rig_data.rig_components.add()
    component.component_uuid = str(uuid.uuid4())
    component.semantic_id = "_".join(label.lower().split())
    component.label = label
    component.component_type = "SEMANTIC"
    component.deformation_mode = "PARAMETRIC"
    component.build_mode = "GENERATED"
    component.orientation_reference = source_names[-1]
    for bone_name in source_names:
        reference = component.source_bones.add()
        reference.bone_name = bone_name
    rig_data.rig_components_index = len(rig_data.rig_components) - 1
    return component


def _new_stage(component, stage_type, label, order, source_names=()):
    stage = component.semantic_stages.add()
    stage.stage_uuid = str(uuid.uuid4())
    stage.semantic_id = "_".join(label.lower().split())
    stage.label = label
    stage.stage_type = stage_type
    stage.order = order
    for bone_name in source_names:
        reference = stage.source_bones.add()
        reference.bone_name = bone_name
    return stage


def _widget_source(widget):
    widget_uuid = widget.get("coa_rig_widget_uuid")
    if widget_uuid:
        return next(
            obj
            for obj in bpy.data.objects
            if obj.get("coa_rig_widget_uuid") == widget_uuid
            and obj.get("coa_rig_artifact_role") == "widget_source"
        )
    role = str(widget.get("coa_rig_component_role", ""))
    assert role.endswith(":cache"), role
    source_role = role[:-5] + "source"
    component_uuid = widget.get("coa_rig_component_uuid")
    return next(
        obj
        for obj in bpy.data.objects
        if obj.get("coa_rig_component_uuid") == component_uuid
        and obj.get("coa_rig_component_role") == source_role
    )


def _assert_production_widget(pose_bone, *, shape=None):
    widget = pose_bone.custom_shape
    assert widget is not None and widget.type == "MESH", pose_bone.name
    assert widget.data.vertices and widget.data.edges and not widget.data.polygons
    if shape is not None:
        assert widget.get("coa_semantic_widget_shape") == shape
    source = _widget_source(widget)
    modifiers = [item for item in source.modifiers if item.type == "NODES"]
    assert modifiers and modifiers[0].node_group is not None
    group = modifiers[0].node_group
    is_state_widget = bool(
        group.get("coa_rig_managed")
        and group.get("coa_rig_widget_family")
        and group.get("coa_rig_widget_version") is not None
    )
    is_semantic_widget = bool(
        group.get("coa_semantic_widget_managed")
        and group.get("coa_semantic_widget_schema")
        == "coa-tools2-semantic-widget-v1"
        and group.get("coa_semantic_widget_version") is not None
        and group.get("coa_semantic_widget_shape")
    )
    assert is_state_widget or is_semantic_widget, tuple(group.keys())
    return widget


def _create_graph_lipsync(collection, material):
    from coa_tools2.rig_control.blender.states import state_point_local_position

    armature = _new_armature("DEMO_A_GraphLipSync", (-8.0, 0.0, 3.6), collection)
    target = _mouth_target("DEMO_A_Mouth", collection, armature, material)
    _activate_armature(armature)
    bpy.context.scene.cursor.location = armature.matrix_world.translation
    result = bpy.ops.coa_tools2.add_lip_sync_state_rig(
        "EXEC_DEFAULT",
        label="JP Vowels + MBP",
        preset="JP_VOWELS_MBP",
        include_optional=False,
        graph_interpolation="HYBRID",
        width=3.7,
        height=2.35,
        target_object_name=target.name,
        match_existing_shape_keys=True,
    )
    assert result == {"FINISHED"}, result
    control = armature.coa_tools2_rig.rig_controls[-1]
    assert control.state_mode == "GRAPH_2D" and len(control.state_points) == 7
    assert all(point.target_object == target and point.target_name for point in control.state_points)
    handle = armature.pose.bones[control.control_bone]
    display = armature.pose.bones[control.display_bone]
    _assert_production_widget(display)
    assert handle.custom_shape is not None and not handle.custom_shape.data.polygons
    point_frames = {"REST": 1, "A": 9, "I": 17, "U": 25, "E": 33, "O": 41, "MBP": 48}
    for point in control.state_points:
        x, y = state_point_local_position(control, point)
        _key_pose(handle, point_frames[point.label], location=(x, y, 0.0))
    drivers = tuple(target.data.shape_keys.animation_data.drivers)
    assert len(drivers) == 7
    assert all(curve.driver.expression.startswith("coa_graph_state_weight(") for curve in drivers)
    return armature, control, target


def _create_fk_ik_contact(collection, material):
    from coa_tools2 import functions
    from coa_tools2.rig_control.blender.selection import select_pose_bones
    from coa_tools2.rig_control.blender.semantic_fk import resolve_fk_solver_layer

    armature = _new_armature("DEMO_B_FKIKContact", (0.6, 0.0, 3.8), collection)
    points = ((-1.7, 0, 0), (-0.25, 0, 0.55), (1.20, 0, 0.05), (2.0, 0, 0.05))
    bpy.ops.object.mode_set(mode="EDIT")
    edit = armature.data.edit_bones
    chain = []
    for index, name in enumerate(("upper", "lower", "hand")):
        chain.append(_bone(edit, name, points[index], points[index + 1], chain[-1] if chain else None))
    names = tuple(bone.name for bone in chain)
    bpy.ops.object.mode_set(mode="POSE")
    _weighted_ribbon("DEMO_B_ArmArt", collection, armature, material, points, names, 0.45)
    select_pose_bones(armature, set(names), names[-1])
    assert bpy.ops.coa_tools2.add_semantic_rig(
        "EXEC_DEFAULT", label="FK IK Contact", initial_dimensions=3
    ) == {"FINISHED"}
    component = armature.coa_tools2_rig.rig_components[-1]
    assert bpy.ops.coa_tools2.add_semantic_stage(
        "EXEC_DEFAULT", stage_type="CHAIN_IK", label="Arm FK IK"
    ) == {"FINISHED"}
    ik_stage = component.semantic_stages[-1]
    ik_uuid = str(ik_stage.stage_uuid)
    ik_stage.use_pole = True
    ik_stage.chain_length = 2
    ik_stage.allow_stretch = False
    _configure_presentation(
        ik_stage.presentation, "TOMBSTONE", width=0.60, height=0.85, corner_radius=0.20, segments=64
    )
    _configure_presentation(
        ik_stage.pole_presentation, "ELLIPSE", width=0.60, height=0.60, segments=64
    )
    select_pose_bones(armature, set(names), names[-1])
    assert bpy.ops.coa_tools2.assign_semantic_stage_chain("EXEC_DEFAULT") == {"FINISHED"}
    assert bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT") == {"FINISHED"}
    ik_stage = next(stage for stage in component.semantic_stages if stage.stage_uuid == ik_uuid)
    layer = resolve_fk_solver_layer(armature, component, ik_stage)
    _assert_production_widget(armature.pose.bones[layer.ik_control_bone], shape="TOMBSTONE")
    _assert_production_widget(armature.pose.bones[layer.pole_bone], shape="ELLIPSE")

    assert bpy.ops.coa_tools2.add_semantic_stage(
        "EXEC_DEFAULT", stage_type="CONTACT_PIN", label="Hand Contact"
    ) == {"FINISHED"}
    contact = component.semantic_stages[-1]
    contact_uuid = str(contact.stage_uuid)
    contact.pin_space = "WORLD"
    contact.pin_position = True
    contact.pin_orientation = False
    contact.contact_transition_frames = 3
    assert bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT") == {"FINISHED"}
    ik_stage = next(stage for stage in component.semantic_stages if stage.stage_uuid == ik_uuid)
    contact = next(stage for stage in component.semantic_stages if stage.stage_uuid == contact_uuid)
    layer = resolve_fk_solver_layer(armature, component, ik_stage)
    fk_controls = tuple(armature.pose.bones[name] for name in layer.fk_control_bones)
    ik_control = armature.pose.bones[layer.ik_control_bone]

    component.semantic_stages_index = next(i for i, stage in enumerate(component.semantic_stages) if stage.stage_uuid == ik_uuid)
    bpy.context.scene.frame_set(1)
    assert bpy.ops.coa_tools2.switch_semantic_ik_fk("EXEC_DEFAULT", mode="FK") == {"FINISHED"}
    for bone in fk_controls:
        _key_pose(bone, 1, rotation=(0.0, 0.0, 0.0))
    _key_pose(fk_controls[0], 12, rotation=(0.0, 0.30, 0.0))
    _key_pose(fk_controls[1], 12, rotation=(0.0, -0.48, 0.0))
    _key_pose(fk_controls[2], 12, rotation=(0.0, 0.18, 0.0))
    bpy.context.scene.frame_set(24)
    assert bpy.ops.coa_tools2.switch_semantic_ik_fk("EXEC_DEFAULT", mode="IK") == {"FINISHED"}
    _key_pose(ik_control, 24, location=tuple(ik_control.location))
    moved = ik_control.location + Vector((0.35, -0.18, 0.65))
    _key_pose(ik_control, 34, location=tuple(moved))

    component.semantic_stages_index = next(i for i, stage in enumerate(component.semantic_stages) if stage.stage_uuid == contact_uuid)
    bpy.context.scene.frame_set(36)
    assert bpy.ops.coa_tools2.switch_semantic_contact("EXEC_DEFAULT", mode="ON") == {"FINISHED"}
    _key_pose(ik_control, 42, location=tuple(moved + Vector((0.55, 0.0, 0.15))))
    bpy.context.scene.frame_set(45)
    assert bpy.ops.coa_tools2.switch_semantic_contact("EXEC_DEFAULT", mode="OFF") == {"FINISHED"}

    action = armature.animation_data.action
    curves = tuple(functions.iter_action_fcurves(action))
    mode_curve = next(curve for curve in curves if curve.data_path == ik_stage.path_from_id("rig_mode"))
    contact_curve = next(curve for curve in curves if curve.data_path == contact.path_from_id("contact_mode"))
    assert all(point.interpolation == "CONSTANT" for point in mode_curve.keyframe_points)
    assert all(point.interpolation == "CONSTANT" for point in contact_curve.keyframe_points)
    driven = armature.pose.bones[contact.pin_driven_bone]
    pin_path = driven.path_from_id(f'["{contact.pin_property}"]')
    pin_curve = next(curve for curve in curves if curve.data_path == pin_path)
    assert all(point.interpolation == "BEZIER" for point in pin_curve.keyframe_points)
    assert len(layer.fk_control_bones) == 3
    return armature, component, ik_stage, contact, layer


def _create_bbone_secondary(collection, material):
    from coa_tools2.rig_control.blender.semantic_compiler import compile_semantic_component
    from coa_tools2.rig_control.blender.semantic_secondary import bake_secondary_motion

    armature = _new_armature("DEMO_C_BBoneSecondary", (-6.0, 0.0, -5.3), collection)
    bpy.ops.object.mode_set(mode="EDIT")
    source = _bone(armature.data.edit_bones, "bbone.deform", (0, 0, 0), (0, 0, 4.3))
    source_name = source.name
    bpy.ops.object.mode_set(mode="POSE")
    points = tuple((0.0, 0.0, 4.3 * index / 12) for index in range(13))
    _weighted_ribbon("DEMO_C_BBoneArt", collection, armature, material, points, (source_name,), 0.58)
    component = _new_component(armature, "B-Bone Bezier Secondary", (source_name,))
    bbone = _new_stage(component, "BBONE_BEZIER", "B-Bone Bezier", 0, (source_name,))
    bbone_uuid = str(bbone.stage_uuid)
    bbone.bbone_segments = 12
    bbone.bbone_use_mid_control = True
    bbone.bbone_mid_influence = 0.45
    compiled = compile_semantic_component(armature, component)
    info = compiled["stage_results"][bbone_uuid].bbone_info
    assert info is not None and len(info.point_control_bones) == 3 and len(info.handle_control_bones) == 2
    for name in info.point_control_bones:
        _assert_production_widget(armature.pose.bones[name], shape="ELLIPSE")
    for name in info.handle_control_bones:
        _assert_production_widget(armature.pose.bones[name], shape="TRIANGLE")

    point_controls = tuple(armature.pose.bones[name] for name in info.point_control_bones)
    handles = tuple(armature.pose.bones[name] for name in info.handle_control_bones)
    for bone in point_controls + handles:
        _key_pose(bone, 1, location=(0, 0, 0), rotation=(0, 0, 0), scale=(1, 1, 1))
    _key_pose(point_controls[1], 18, location=(0.75, 0.0, 0.15))
    _key_pose(handles[0], 18, location=(0.45, 0.0, 0.0), rotation=(0.0, 0.25, 0.0), scale=(1.0, 1.25, 1.0))
    _key_pose(point_controls[1], 34, location=(-0.62, 0.0, 0.05))
    _key_pose(handles[1], 34, location=(-0.38, 0.0, 0.0), rotation=(0.0, -0.22, 0.0), scale=(1.0, 0.82, 1.0))
    for bone in point_controls + handles:
        bone.keyframe_insert("location", frame=48, group=bone.name)
        bone.keyframe_insert("rotation_euler", frame=48, group=bone.name)
        bone.keyframe_insert("scale", frame=48, group=bone.name)

    secondary = _new_stage(component, "SECONDARY_MOTION", "B-Bone Secondary", 1)
    secondary_uuid = str(secondary.stage_uuid)
    secondary.depends_on = bbone_uuid
    secondary.frequency_hz = 2.2
    secondary.damping_ratio = 0.52
    secondary.substeps = 3
    secondary.pre_roll = 4
    secondary.bake_start = 1
    secondary.bake_end = 48
    compiled = compile_semantic_component(armature, component)
    bbone = next(stage for stage in component.semantic_stages if stage.stage_uuid == bbone_uuid)
    secondary = next(stage for stage in component.semantic_stages if stage.stage_uuid == secondary_uuid)
    secondary_info = compiled["stage_results"][secondary_uuid]
    assert secondary_info.bbone_info is not None
    baked = bake_secondary_motion(
        armature,
        component,
        secondary,
        default_source_bones=info.secondary_control_bones,
    )
    assert secondary.secondary_baked and baked.sample_count == 48
    action = bpy.data.actions.get(baked.action_name)
    assert action is not None and action.get("coa_semantic_stage_uuid") == secondary_uuid
    return armature, component, bbone, secondary, info


def _create_vector_output(collection, material):
    from coa_tools2.rig_control.blender.selection import select_pose_bone
    from coa_tools2.rig_control.blender.semantic_compiler import compile_semantic_component

    armature = _new_armature("DEMO_D_VectorOutput", (2.1, 0.0, -4.5), collection)
    bpy.ops.object.mode_set(mode="EDIT")
    source = _bone(armature.data.edit_bones, "vector.input", (-1.7, 0, 0), (-1.7, 0, 1.0))
    driven = _bone(armature.data.edit_bones, "vector.output", (1.2, 0, 0), (1.2, 0, 1.0))
    source_name, driven_name = source.name, driven.name
    bpy.ops.object.mode_set(mode="POSE")
    _weighted_marker("DEMO_D_VectorMarker", collection, armature, material, (1.2, 0, 0.5), driven_name)
    select_pose_bone(armature, source_name, exclusive=True)
    assert bpy.ops.coa_tools2.add_semantic_rig(
        "EXEC_DEFAULT", label="Vector Output Adapter", initial_dimensions=1
    ) == {"FINISHED"}
    component = armature.coa_tools2_rig.rig_components[-1]
    projected, pose_map = component.semantic_stages
    _configure_presentation(
        projected.presentation,
        "ARROW_2D",
        width=1.25,
        height=1.25,
        bar_width=0.10,
        head_length=0.24,
        head_width=0.32,
    )
    compile_semantic_component(armature, component)
    component.semantic_stages_index = next(i for i, stage in enumerate(component.semantic_stages) if stage.stage_uuid == pose_map.stage_uuid)
    assert bpy.ops.coa_tools2.add_semantic_output(
        "EXEC_DEFAULT",
        label="Driven XYZ",
        target_kind="BONE_LOCATION",
        target_object_name=armature.name,
        target_bone=driven_name,
        array_index=0,
        value_arity=3,
    ) == {"FINISHED"}
    control = armature.pose.bones[projected.control_bone]
    driven_pose = armature.pose.bones[driven_name]
    control.location = (0, 0, 0)
    driven_pose.location = (0, 0, 0)
    assert bpy.ops.coa_tools2.begin_semantic_sample("EXEC_DEFAULT") == {"FINISHED"}
    assert bpy.ops.coa_tools2.commit_semantic_sample("EXEC_DEFAULT") == {"FINISHED"}
    control.location.x = 1.0
    bpy.context.view_layer.update()
    assert bpy.ops.coa_tools2.begin_semantic_sample("EXEC_DEFAULT") == {"FINISHED"}
    driven_pose.location = (1.55, 0.60, 1.10)
    assert bpy.ops.coa_tools2.commit_semantic_sample("EXEC_DEFAULT") == {"FINISHED"}
    _key_pose(control, 1, location=(0, 0, 0))
    _key_pose(control, 24, location=(0.55, 0, 0))
    _key_pose(control, 48, location=(1.0, 0, 0))
    _assert_production_widget(control, shape="ARROW_2D")
    output = pose_map.outputs[0]
    assert output.value_arity == 3
    path = driven_pose.path_from_id("location")
    drivers = [curve for curve in armature.animation_data.drivers if curve.data_path == path]
    assert len(drivers) == 3 and {curve.array_index for curve in drivers} == {0, 1, 2}
    assert all("coa_pose_field_component" in curve.driver.expression for curve in drivers)
    return armature, component, projected, pose_map, driven_name


def _text_object(name, body, location, collection, material, *, size=0.30):
    data = bpy.data.curves.new(f"{name}_Font", "FONT")
    data.body = body
    data.align_x = "CENTER"
    data.align_y = "CENTER"
    data.size = size
    data.materials.append(material)
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler.x = math.pi * 0.5
    return obj


def _create_readme(scene):
    readme = bpy.data.texts.new("README_AnimationControls.txt")
    readme.write(
        "COA Tools 2 — Animation Controls Demo\n"
        "========================================\n\n"
        "Generated by scripts/blender_rig_phase10_animation_controls_sample.py.\n"
        "Use frames 1-48 and enable the matching development add-on before opening.\n"
        "All demo Armatures are saved in multi-object Pose Mode.\n\n"
        "A / MANUAL GRAPH LIP SYNC\n"
        "  Select DEMO_A_GraphLipSync, then drag the circular handle inside the Graph.\n"
        "  JP Vowels + MBP are bound to seven existing Shape Keys; no audio is required.\n"
        "  Frames 1, 9, 17, 25, 33, 41, 48 visit REST/A/I/U/E/O/MBP.\n\n"
        "B / FK/IK + CONTACT PIN\n"
        "  N-panel > COA Tools2 > Rig > Animate: select an FK or IK hand control.\n"
        "  Mode and Contact Pin appear together; each switch matches and keys the pose.\n"
        "  FK controls rotate the chain; the tombstone is IK and the ellipse is the pole.\n"
        "  Mode and Contact are discrete keyed controls; private compensation is smooth.\n\n"
        "C / B-BONE BEZIER + SECONDARY\n"
        "  Move points; move/rotate/scale handles to change tangent, roll and ease.\n"
        "  B-Bone Secondary is linked to those controls and baked for frames 1-48.\n\n"
        "D / VECTOR OUTPUT ADAPTER\n"
        "  Move the four-way arrow on local X. One logical output drives XYZ location.\n"
        "  The rose diamond is driven by three managed component drivers.\n\n"
        "UI NOTE\n"
        "  Animate is the default workspace. Graph handles show evaluated mixed weights.\n"
        "  Setup contains State Rig for A and Character Rig for B/C/D.\n"
        "  Setup > Viewport can apply or restore the Animator Display preset.\n"
    )
    scene["coa_demo_readme"] = readme.name
    scene["coa_demo_sections"] = "A Graph Lip Sync; B FK IK Contact; C B-Bone Secondary; D Vector Output"
    scene["coa_demo_frames"] = "1-48"
    return readme


def _camera(scene):
    data = bpy.data.cameras.new("DEMO_Camera")
    camera = bpy.data.objects.new("DEMO_Camera", data)
    scene.collection.objects.link(camera)
    camera.location = (0.0, -30.0, 0.0)
    camera.rotation_euler = (Vector((0, 0, 0)) - camera.location).to_track_quat("-Z", "Y").to_euler()
    data.type = "ORTHO"
    data.ortho_scale = 23.5
    scene.camera = camera


def _prepare_saved_pose_view(armatures, active_armature, active_bone):
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    for armature in armatures:
        armature.hide_set(False)
        armature.select_set(True)
    bpy.context.view_layer.objects.active = active_armature
    bpy.ops.object.mode_set(mode="EDIT")
    for armature in armatures:
        for edit_bone in armature.data.edit_bones:
            selected = armature == active_armature and edit_bone.name == active_bone
            edit_bone.select = selected
            edit_bone.select_head = selected
            edit_bone.select_tail = selected
        if armature == active_armature:
            active_armature.data.edit_bones.active = active_armature.data.edit_bones[active_bone]
    bpy.ops.object.mode_set(mode="POSE")
    assert all(armature.mode == "POSE" and armature.select_get() for armature in armatures)
    assert bpy.context.active_pose_bone.name == active_bone
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.shading.type = "SOLID"
                area.spaces.active.shading.color_type = "MATERIAL"
                area.spaces.active.show_region_ui = True
                area.spaces.active.overlay.show_relationship_lines = False
                area.spaces.active.region_3d.view_perspective = "CAMERA"


def _assert_privacy():
    forbidden = ("c:\\users\\", "/users/", "appdata", "documents\\github")
    strings = []
    datablock_groups = (
        bpy.data.objects,
        bpy.data.meshes,
        bpy.data.curves,
        bpy.data.armatures,
        bpy.data.actions,
        bpy.data.materials,
        bpy.data.node_groups,
        bpy.data.texts,
    )
    for group in datablock_groups:
        strings.extend(item.name for item in group)
    strings.extend(text.as_string() for text in bpy.data.texts)
    strings.extend(str(value) for key, value in bpy.context.scene.items() if key != "_RNA_UI")
    assert not bpy.data.libraries
    violations = [value for value in strings if any(token in value.lower() for token in forbidden)]
    assert not violations, violations


def main():
    _require_disposable_factory_process()
    args = _arguments()
    if str(REPOSITORY_ROOT) not in sys.path:
        sys.path.insert(0, str(REPOSITORY_ROOT))
    import coa_tools2

    _clear_factory_scene()
    coa_tools2.register()
    scene = bpy.context.scene
    scene.name = "COA Animation Controls Demo"
    scene.frame_start = 1
    scene.frame_end = 48
    scene.render.fps = 24
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.world.color = (0.025, 0.032, 0.045)

    root = _collection("DEMO_Animation_Controls")
    a_collection = _collection("A_Graph_Lip_Sync", parent=root)
    b_collection = _collection("B_FK_IK_Contact", parent=root)
    c_collection = _collection("C_BBone_Secondary", parent=root)
    d_collection = _collection("D_Vector_Output", parent=root)
    guides = _collection("DEMO_Guides", parent=root)
    blue = _material("DEMO_Blue", (0.16, 0.48, 0.92))
    green = _material("DEMO_Green", (0.23, 0.76, 0.48))
    amber = _material("DEMO_Amber", (0.96, 0.52, 0.16))
    rose = _material("DEMO_Rose", (0.92, 0.28, 0.47))
    text = _material("DEMO_Text", (0.90, 0.93, 1.0))

    graph_armature, graph_control, _mouth = _create_graph_lipsync(a_collection, blue)
    fk_armature, _fk_component, ik_stage, contact_stage, fk_layer = _create_fk_ik_contact(b_collection, green)
    bbone_armature, _bb_component, bbone_stage, secondary_stage, bbone_info = _create_bbone_secondary(c_collection, amber)
    vector_armature, _vector_component, projected_stage, pose_map, driven_name = _create_vector_output(d_collection, rose)

    _text_object("DEMO_Title", "COA Tools 2 | Animation Controls", (0, -0.3, 7.0), guides, text, size=0.62)
    _text_object("DEMO_Subtitle", "Frames 1-48 | Open README_AnimationControls.txt", (0, -0.3, 6.42), guides, text, size=0.27)
    labels = (
        ("A", "A  GRAPH LIP SYNC | JP VOWELS + MBP", (-5.8, -0.28, 5.75)),
        ("B", "B  FK / IK + CONTACT PIN", (3.0, -0.28, 5.75)),
        ("C", "C  B-BONE BEZIER + SECONDARY", (-5.8, -0.28, 0.35)),
        ("D", "D  VECTOR OUTPUT | 1D -> XYZ", (3.0, -0.28, 0.35)),
    )
    for suffix, body, location in labels:
        _text_object(f"DEMO_Label_{suffix}", body, location, guides, text, size=0.32)
    _text_object("DEMO_Guide_A", "DRAG GRAPH HANDLE | REST A I U E O MBP", (-5.8, -0.28, 1.65), guides, text, size=0.20)
    _text_object("DEMO_Guide_B", "FK ROTATE | TOMBSTONE IK | ELLIPSE POLE | CONTACT ON/OFF", (3.0, -0.28, 1.65), guides, text, size=0.18)
    _text_object("DEMO_Guide_D", "MOVE ARROW X | ROSE DIAMOND RECEIVES XYZ", (3.0, -0.28, -6.75), guides, text, size=0.20)
    _create_readme(scene)
    _camera(scene)

    # Final production-artifact checks before the distributable save.
    assert graph_control.lip_sync_preset == "JP_VOWELS_MBP"
    assert ik_stage.rig_mode in {"FK", "IK"} and contact_stage.contact_mode in {"OFF", "ON"}
    assert len(fk_layer.fk_control_bones) == 3
    assert bbone_stage.stage_type == "BBONE_BEZIER" and secondary_stage.secondary_baked
    assert len(bbone_info.point_control_bones) == 3 and len(bbone_info.handle_control_bones) == 2
    assert pose_map.outputs[0].value_arity == 3
    vector_path = vector_armature.pose.bones[driven_name].path_from_id("location")
    assert len([curve for curve in vector_armature.animation_data.drivers if curve.data_path == vector_path]) == 3
    for obj in bpy.data.objects:
        if obj.type == "MESH" and (
            obj.get("coa_rig_artifact_role") == "widget_cache"
            or str(obj.get("coa_rig_component_role", "")).endswith(":cache")
        ):
            assert obj.data.vertices and obj.data.edges and not obj.data.polygons, obj.name
    _assert_privacy()

    scene.frame_set(24)
    armatures = (graph_armature, fk_armature, bbone_armature, vector_armature)
    _prepare_saved_pose_view(armatures, graph_armature, graph_control.control_bone)
    from coa_tools2.rig_control.blender.viewport_display import apply_animator_display
    for armature in armatures:
        apply_animator_display(armature)
    output = args.output.expanduser().resolve()
    if output.suffix.lower() != ".blend":
        raise RuntimeError("Sample output must use the .blend extension.")
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output), compress=True)
    assert output.is_file() and output.stat().st_size > 0
    print("PHASE10_ANIMATION_CONTROLS_SAMPLE_OK", output)


if __name__ == "__main__":
    main()
