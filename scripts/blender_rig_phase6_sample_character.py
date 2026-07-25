#!/usr/bin/env python3
"""Generate and validate an animated cutout-style Phase 6 sample character."""

from __future__ import annotations

import math
import os
from pathlib import Path
import sys
import uuid

import addon_utils
import bpy
from mathutils import Matrix, Vector


def _create_bone(edit_bones, name, head, tail, *, parent=None, roll=0.0):
    bone = edit_bones.new(name)
    bone.head = head
    bone.tail = tail
    bone.parent = parent
    bone.use_connect = parent is not None and bone.head == parent.tail
    bone.roll = roll
    return bone


def _select_chain(armature, names, active_name):
    from coa_tools2.rig_control.blender.selection import select_pose_bones

    select_pose_bones(armature, names, active_name)
    bpy.context.view_layer.update()


def _add_component(**properties):
    properties.setdefault("deformation_mode", "PARAMETRIC")
    result = bpy.ops.coa_tools2.add_rig_component("EXEC_DEFAULT", **properties)
    assert result == {"FINISHED"}, result


def _material(name, color):
    material = bpy.data.materials.new(name)
    material.diffuse_color = (*color, 1.0)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (*color, 1.0)
    emission.inputs["Strength"].default_value = 1.0
    material.node_tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return material


def _rectangle_mesh(name, width, height):
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    half_width = width * 0.5
    half_height = height * 0.5
    mesh.from_pydata(
        (
            (-half_width, 0.0, -half_height),
            (half_width, 0.0, -half_height),
            (half_width, 0.0, half_height),
            (-half_width, 0.0, half_height),
        ),
        (),
        ((0, 1, 2, 3),),
    )
    mesh.update()
    return mesh


def _disc_mesh(name, radius, segments=32):
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    vertices = [(0.0, 0.0, 0.0)]
    vertices.extend(
        (
            math.cos(math.tau * index / segments) * radius,
            0.0,
            math.sin(math.tau * index / segments) * radius,
        )
        for index in range(segments)
    )
    faces = [
        (0, index + 1, ((index + 1) % segments) + 1)
        for index in range(segments)
    ]
    mesh.from_pydata(vertices, (), faces)
    mesh.update()
    return mesh


def _bone_center_and_angle(armature, bone_name):
    bone = armature.data.bones[bone_name]
    head = bone.head_local
    tail = bone.tail_local
    center = (head + tail) * 0.5
    direction = tail - head
    return center, math.atan2(direction.x, direction.z), direction.length


def _bone_parent_object(
    collection,
    armature,
    name,
    bone_name,
    mesh,
    material,
    world_matrix,
    layer_y,
):
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.data.materials.append(material)
    matrix = world_matrix.copy()
    matrix.translation.y += layer_y
    obj.matrix_world = armature.matrix_world @ matrix
    world = obj.matrix_world.copy()
    obj.parent = armature
    obj.parent_type = "BONE"
    obj.parent_bone = bone_name
    obj.matrix_world = world
    obj["coa_sample_art"] = True
    return obj


def _add_bone_rectangle(
    collection,
    armature,
    bone_name,
    width,
    material,
    *,
    layer_y=0.0,
    length_scale=0.92,
):
    center, angle, length = _bone_center_and_angle(armature, bone_name)
    matrix = Matrix.Translation(center) @ Matrix.Rotation(angle, 4, "Y")
    return _bone_parent_object(
        collection,
        armature,
        f"ART_{bone_name}",
        bone_name,
        _rectangle_mesh(f"ART_{bone_name}", width, length * length_scale),
        material,
        matrix,
        layer_y,
    )


def _add_bone_disc(
    collection,
    armature,
    bone_name,
    radius,
    material,
    *,
    at_tail=False,
    layer_y=0.0,
):
    bone = armature.data.bones[bone_name]
    center = bone.tail_local if at_tail else (bone.head_local + bone.tail_local) * 0.5
    return _bone_parent_object(
        collection,
        armature,
        f"ART_{bone_name}_Disc",
        bone_name,
        _disc_mesh(f"ART_{bone_name}_Disc", radius),
        material,
        Matrix.Translation(center),
        layer_y,
    )


def _key_transform(pose_bone, frame, *, location=None, rotation=None):
    pose_bone.rotation_mode = "XYZ"
    if location is not None:
        pose_bone.location = location
        pose_bone.keyframe_insert("location", frame=frame)
    if rotation is not None:
        pose_bone.rotation_euler = tuple(math.radians(value) for value in rotation)
        pose_bone.keyframe_insert("rotation_euler", frame=frame)


def _matrix_delta(left, right):
    return max(
        abs(left[row][column] - right[row][column])
        for row in range(4)
        for column in range(4)
    )


def _add_planar_pose_keys(obj):
    obj.shape_key_add(name="Basis")
    coordinates = tuple(vertex.co.copy() for vertex in obj.data.vertices)
    span_x = max(max(abs(point.x) for point in coordinates), 0.01)
    span_z = max(max(abs(point.z) for point in coordinates), 0.01)
    transforms = {
        "DepthFront": lambda point: (
            point.x * 0.68,
            point.z + point.x / span_x * span_z * 0.18,
        ),
        "DepthBack": lambda point: (
            point.x * 0.78,
            point.z - point.x / span_x * span_z * 0.12,
        ),
        "TiltXPos": lambda point: (
            point.x,
            point.z + point.x / span_x * span_z * 0.30,
        ),
        "TiltXNeg": lambda point: (
            point.x,
            point.z - point.x / span_x * span_z * 0.30,
        ),
        "TurnYPos": lambda point: (
            point.x * 0.62 + point.z / span_z * span_x * 0.12,
            point.z,
        ),
        "TurnYNeg": lambda point: (
            point.x * 0.62 - point.z / span_z * span_x * 0.12,
            point.z,
        ),
        "RollZPos": lambda point: (
            point.x + point.z / span_z * span_x * 0.22,
            point.z,
        ),
        "RollZNeg": lambda point: (
            point.x - point.z / span_z * span_x * 0.22,
            point.z,
        ),
    }
    for name, transform in transforms.items():
        key = obj.shape_key_add(name=name)
        for key_point, basis_point in zip(key.data, coordinates):
            x, z = transform(basis_point)
            key_point.co = (x, basis_point.y, z)


def _add_binding(
    component,
    target,
    target_name,
    source_component,
    input_min,
    input_max,
    output_min,
    output_max,
):
    binding = component.bindings.add()
    binding.binding_uuid = str(uuid.uuid4())
    binding.control_uuid = component.component_uuid
    binding.source_component = source_component
    binding.target_kind = "SHAPE_KEY_VALUE"
    binding.target_object = target
    binding.target_name = target_name
    binding.input_min = input_min
    binding.input_max = input_max
    binding.output_min = output_min
    binding.output_max = output_max
    binding.clamp = True


def _bind_planar_pose(component, target):
    _add_planar_pose_keys(target)
    depth_min = min(component.depth_min, -0.01)
    depth_max = max(component.depth_max, 0.01)
    mappings = (
        ("DepthFront", "LOC_Z", 0.0, depth_max, 0.0, 1.0),
        ("DepthBack", "LOC_Z", depth_min, 0.0, 1.0, 0.0),
        ("TiltXPos", "ROT_X", 0.0, math.pi * 0.5, 0.0, 1.0),
        ("TiltXNeg", "ROT_X", -math.pi * 0.5, 0.0, 1.0, 0.0),
        ("TurnYPos", "ROT_Y", 0.0, math.pi * 0.5, 0.0, 1.0),
        ("TurnYNeg", "ROT_Y", -math.pi * 0.5, 0.0, 1.0, 0.0),
        ("RollZPos", "ROT_Z", 0.0, math.pi * 0.5, 0.0, 1.0),
        ("RollZNeg", "ROT_Z", -math.pi * 0.5, 0.0, 1.0, 0.0),
    )
    for mapping in mappings:
        _add_binding(component, target, *mapping)


def _evaluated_world_y(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        return tuple((evaluated.matrix_world @ vertex.co).y for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def _render_preview(scene, output_directory, frame):
    scene.frame_set(frame)
    scene.render.filepath = str(output_directory / f"phase6_sample_f{frame:03d}.png")
    bpy.ops.render.render(write_still=True)


def _create_camera(scene):
    camera_data = bpy.data.cameras.new("Phase6SampleCamera")
    camera = bpy.data.objects.new("Phase6SampleCamera", camera_data)
    scene.collection.objects.link(camera)
    camera.location = (0.0, -20.0, 1.9)
    direction = Vector((0.0, 0.0, 1.7)) - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = 10.5
    scene.camera = camera


def main():
    if not addon_utils.check("coa_tools2")[1]:
        if addon_utils.enable("coa_tools2", default_set=False, persistent=False) is None:
            raise RuntimeError("Could not enable coa_tools2.")

    output_directory = Path(
        os.environ.get(
            "COA_TOOLS2_SAMPLE_OUTPUT",
            str(Path(os.environ.get("TEMP", ".")) / "coa_tools2-validation"),
        )
    ).resolve()
    output_directory.mkdir(parents=True, exist_ok=True)

    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object
    armature.name = "COA_Phase6_SampleCharacter"
    armature.data.name = "COA_Phase6_SampleCharacter_Rig"
    armature.show_in_front = True
    armature.data.display_type = "BBONE"

    bpy.ops.object.mode_set(mode="EDIT")
    bones = armature.data.edit_bones
    root = _create_bone(bones, "root", (0, 0, 0), (0, 0, 0.65))
    hips = _create_bone(
        bones, "hips", root.tail, (0, 0, 1.75), parent=root
    )
    spine = _create_bone(
        bones, "spine", hips.tail, (0, 0, 3.05), parent=hips
    )
    chest = _create_bone(
        bones, "chest", spine.tail, (0, 0, 4.25), parent=spine
    )
    head = _create_bone(
        bones, "head", chest.tail, (0, 0, 5.65), parent=chest
    )

    upper_l = _create_bone(
        bones,
        "upper_arm.L",
        (-0.35, 0.0, 4.0),
        (-1.65, 0.08, 3.78),
        parent=chest,
        roll=0.20,
    )
    lower_l = _create_bone(
        bones,
        "forearm.L",
        upper_l.tail,
        (-2.75, 0.26, 3.35),
        parent=upper_l,
        roll=0.42,
    )
    _create_bone(
        bones,
        "hand.L",
        lower_l.tail,
        (-3.45, 0.52, 3.30),
        parent=lower_l,
        roll=0.78,
    )
    upper_r = _create_bone(
        bones,
        "upper_arm.R",
        (0.35, 0.0, 4.0),
        (1.65, -0.08, 3.78),
        parent=chest,
        roll=-0.20,
    )
    lower_r = _create_bone(
        bones,
        "forearm.R",
        upper_r.tail,
        (2.75, -0.26, 3.35),
        parent=upper_r,
        roll=-0.42,
    )
    _create_bone(
        bones,
        "hand.R",
        lower_r.tail,
        (3.45, -0.52, 3.30),
        parent=lower_r,
        roll=-0.78,
    )

    thigh_l = _create_bone(
        bones,
        "thigh.L",
        (-0.38, 0.0, 1.25),
        (-0.52, 0.12, -0.45),
        parent=hips,
        roll=0.12,
    )
    shin_l = _create_bone(
        bones,
        "shin.L",
        thigh_l.tail,
        (-0.36, 0.26, -2.05),
        parent=thigh_l,
        roll=0.22,
    )
    _create_bone(
        bones,
        "foot.L",
        shin_l.tail,
        (-0.92, 0.46, -2.38),
        parent=shin_l,
        roll=0.45,
    )
    thigh_r = _create_bone(
        bones,
        "thigh.R",
        (0.38, 0.0, 1.25),
        (0.52, -0.12, -0.45),
        parent=hips,
        roll=-0.12,
    )
    shin_r = _create_bone(
        bones,
        "shin.R",
        thigh_r.tail,
        (0.36, -0.26, -2.05),
        parent=thigh_r,
        roll=-0.22,
    )
    _create_bone(
        bones,
        "foot.R",
        shin_r.tail,
        (0.92, -0.46, -2.38),
        parent=shin_r,
        roll=-0.45,
    )
    bpy.ops.object.mode_set(mode="POSE")

    _select_chain(armature, {"root"}, "root")
    _add_component(
        label="Body Root",
        component_type="ROOT",
        depth_mode="LIMITED",
        depth_min=-0.35,
        depth_max=0.35,
        widget="ROOT",
        widget_size=0.75,
    )
    _select_chain(armature, {"hips", "spine", "chest", "head"}, "head")
    _add_component(
        label="Body FK",
        component_type="SPINE_FK",
        widget="FK",
        widget_size=0.58,
    )

    limb_specs = (
        (
            "Arm IK.L",
            ("upper_arm.L", "forearm.L", "hand.L"),
            "HAND",
            -0.35,
            0.45,
        ),
        (
            "Arm IK.R",
            ("upper_arm.R", "forearm.R", "hand.R"),
            "HAND",
            -0.35,
            0.45,
        ),
        (
            "Leg IK.L",
            ("thigh.L", "shin.L", "foot.L"),
            "FOOT",
            -0.20,
            0.30,
        ),
        (
            "Leg IK.R",
            ("thigh.R", "shin.R", "foot.R"),
            "FOOT",
            -0.20,
            0.30,
        ),
    )
    for label, chain, widget, depth_min, depth_max in limb_specs:
        _select_chain(armature, set(chain), chain[-1])
        _add_component(
            label=label,
            component_type="LIMB_IK",
            orientation_mode="SOURCE_BONE",
            depth_mode="LIMITED",
            depth_min=depth_min,
            depth_max=depth_max,
            widget=widget,
            widget_size=0.62,
            ik_solver_mode="SPATIAL",
            end_rotation_mode="COPY_WORLD",
            use_stretch=False,
        )

    art_collection = bpy.data.collections.new("COA Sample Art")
    bpy.context.scene.collection.children.link(art_collection)
    skin = _material("Sample Skin", (0.95, 0.64, 0.42))
    shirt = _material("Sample Shirt", (0.20, 0.50, 0.82))
    trousers = _material("Sample Trousers", (0.18, 0.22, 0.34))
    accent = _material("Sample Accent", (0.94, 0.32, 0.30))

    art_by_bone = {}
    art_by_bone["hips"] = _add_bone_rectangle(
        art_collection,
        armature,
        "hips",
        1.45,
        trousers,
        layer_y=0.10,
    )
    art_by_bone["spine"] = _add_bone_rectangle(
        art_collection,
        armature,
        "spine",
        1.70,
        shirt,
        layer_y=0.08,
    )
    art_by_bone["chest"] = _add_bone_rectangle(
        art_collection,
        armature,
        "chest",
        2.10,
        shirt,
        layer_y=0.06,
    )
    art_by_bone["head"] = _add_bone_disc(
        art_collection,
        armature,
        "head",
        0.78,
        skin,
        layer_y=-0.04,
    )
    for name in ("upper_arm.L", "forearm.L", "upper_arm.R", "forearm.R"):
        art_by_bone[name] = _add_bone_rectangle(
            art_collection,
            armature,
            name,
            0.46,
            shirt if "upper" in name else skin,
            layer_y=0.02 if name.endswith(".L") else 0.04,
        )
    for name in ("hand.L", "hand.R"):
        art_by_bone[name] = _add_bone_disc(
            art_collection,
            armature,
            name,
            0.36,
            skin,
            layer_y=-0.06,
        )
    for name in ("thigh.L", "shin.L", "thigh.R", "shin.R"):
        art_by_bone[name] = _add_bone_rectangle(
            art_collection,
            armature,
            name,
            0.56 if "thigh" in name else 0.46,
            trousers,
            layer_y=0.12,
        )
    for name in ("foot.L", "foot.R"):
        art_by_bone[name] = _add_bone_rectangle(
            art_collection,
            armature,
            name,
            0.50,
            accent,
            layer_y=0.02,
            length_scale=1.1,
        )

    components = armature.coa_tools2_rig.rig_components
    controls = {
        component.label: armature.pose.bones[component.control_bone]
        for component in components
    }
    assert len(components) == 6
    assert all(component.control_bone for component in components)
    assert all(
        component.deformation_mode == "PARAMETRIC"
        for component in components
    )
    limb_components = [
        component
        for component in components
        if component.component_type == "LIMB_IK"
    ]
    assert len(limb_components) == 4
    assert all(not component.pole_bone for component in limb_components)
    assert all(
        controls[component.label].custom_shape is not None
        for component in components
    )

    component_art = {
        "Body Root": ("hips",),
        "Body FK": ("spine", "chest", "head"),
        "Arm IK.L": ("upper_arm.L", "forearm.L", "hand.L"),
        "Arm IK.R": ("upper_arm.R", "forearm.R", "hand.R"),
        "Leg IK.L": ("thigh.L", "shin.L", "foot.L"),
        "Leg IK.R": ("thigh.R", "shin.R", "foot.R"),
    }
    from coa_tools2.rig_control.blender.component_compiler import compile_component

    for component in components:
        for bone_name in component_art[component.label]:
            _bind_planar_pose(component, art_by_bone[bone_name])
        compile_component(armature, component)

    source_names = tuple(
        dict.fromkeys(
            reference.bone_name
            for component in components
            for reference in component.source_bones
        )
    )
    source_matrices = {
        name: armature.pose.bones[name].matrix.copy()
        for name in source_names
    }
    for name in source_names:
        pose_bone = armature.pose.bones[name]
        assert pose_bone.custom_shape is None
        assert not any(
            constraint.type in {"IK", "COPY_ROTATION"}
            for constraint in pose_bone.constraints
        )
    art_objects = tuple(art_by_bone.values())
    baseline_y = {
        obj.name: _evaluated_world_y(obj)
        for obj in art_objects
    }

    frames = (1, 13, 25)
    root_pose = controls["Body Root"]
    body_pose = controls["Body FK"]
    arm_l = controls["Arm IK.L"]
    arm_r = controls["Arm IK.R"]
    leg_l = controls["Leg IK.L"]
    leg_r = controls["Leg IK.R"]

    _key_transform(root_pose, 1, location=(0.0, 0.0, 0.0), rotation=(0, 0, -2))
    for control in (body_pose, arm_l, arm_r, leg_l, leg_r):
        _key_transform(control, 1, location=(0, 0, 0), rotation=(0, 0, 0))

    _key_transform(
        root_pose,
        13,
        location=(0.15, 0.05, 0.28),
        rotation=(8, -9, 4),
    )
    _key_transform(body_pose, 13, location=(0.08, 0.0, 0.18), rotation=(12, -10, 10))
    _key_transform(arm_l, 13, location=(0.20, 1.05, 0.38), rotation=(22, -18, 30))
    _key_transform(arm_r, 13, location=(-0.18, -0.72, -0.25), rotation=(-16, 14, -24))
    _key_transform(leg_l, 13, location=(-0.10, 0.22, 0.18), rotation=(8, -8, 6))
    _key_transform(leg_r, 13, location=(0.12, -0.12, -0.10), rotation=(-6, 5, -4))

    _key_transform(
        root_pose,
        25,
        location=(-0.12, -0.06, -0.22),
        rotation=(-6, 11, -5),
    )
    _key_transform(body_pose, 25, location=(-0.06, 0.0, -0.15), rotation=(-10, 12, -12))
    _key_transform(arm_l, 25, location=(-0.12, -0.68, -0.22), rotation=(-18, 20, -28))
    _key_transform(arm_r, 25, location=(0.16, 1.00, 0.34), rotation=(20, -16, 26))
    _key_transform(leg_l, 25, location=(0.15, -0.10, -0.12), rotation=(-7, 6, -5))
    _key_transform(leg_r, 25, location=(-0.10, 0.20, 0.16), rotation=(7, -7, 5))

    scene = bpy.context.scene
    scene.frame_start = frames[0]
    scene.frame_end = frames[-1]
    engine_items = {
        item.identifier
        for item in scene.render.bl_rna.properties["engine"].enum_items
    }
    scene.render.engine = (
        "BLENDER_EEVEE_NEXT"
        if "BLENDER_EEVEE_NEXT" in engine_items
        else "BLENDER_EEVEE"
    )
    scene.render.resolution_x = 720
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.world.color = (0.035, 0.035, 0.05)
    _create_camera(scene)

    scene.frame_set(1)
    start_hand = armature.pose.bones["hand.L"].tail.copy()
    scene.frame_set(13)
    middle_hand = armature.pose.bones["hand.L"].tail.copy()
    assert (middle_hand - start_hand).length < 1e-6
    assert math.isclose(root_pose.location.z, 0.28, abs_tol=1e-5)
    assert abs(arm_l.location.z) <= 0.45
    assert (
        art_by_bone["hand.L"]
        .data.shape_keys.key_blocks["DepthFront"]
        .value
        > 0.5
    )
    assert armature.animation_data is not None
    assert armature.animation_data.action is not None
    from coa_tools2.functions import iter_action_fcurves

    keyed_frames = {
        round(point.co.x)
        for curve in iter_action_fcurves(armature.animation_data.action)
        for point in curve.keyframe_points
    }
    assert set(frames).issubset(keyed_frames)

    for frame in frames:
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        for name, matrix in source_matrices.items():
            assert (
                _matrix_delta(armature.pose.bones[name].matrix, matrix) < 1e-6
            ), (frame, name)
        for obj in art_objects:
            current_y = _evaluated_world_y(obj)
            expected_y = baseline_y[obj.name]
            assert len(current_y) == len(expected_y)
            assert max(
                abs(current - expected)
                for current, expected in zip(current_y, expected_y)
            ) < 1e-5, (frame, obj.name)
        _render_preview(scene, output_directory, frame)

    scene.frame_set(1)
    blend_path = output_directory / "coa_tools2_phase6_sample_character.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    print(f"COA Phase 6 sample character OK: {blend_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"Rig Phase 6 sample failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise
