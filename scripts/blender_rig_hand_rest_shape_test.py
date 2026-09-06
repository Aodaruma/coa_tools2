#!/usr/bin/env python3
"""Blender integration regression for wrist-anchored IK hand presentations."""

from __future__ import annotations

import math
from pathlib import Path
import sys
import uuid

import bpy
from mathutils import Vector


def _close(actual, expected, epsilon=2.0e-5):
    assert abs(float(actual) - float(expected)) < epsilon, (actual, expected)


def _log(message):
    print("HAND_REST_SHAPE:", message, flush=True)


def _new_bone(bones, name, head, tail, parent=None):
    bone = bones.new(name)
    bone.head = head
    bone.tail = tail
    bone.parent = parent
    bone.use_connect = parent is not None
    return bone


def _vertices(shape):
    return tuple(tuple(vertex.co) for vertex in shape.data.vertices)


def _animation_signature(armature):
    from coa_tools2.functions import iter_action_fcurves

    action = armature.animation_data.action
    return tuple(
        (
            curve.data_path,
            curve.array_index,
            tuple(
                (tuple(point.co), point.interpolation)
                for point in curve.keyframe_points
            ),
        )
        for curve in iter_action_fcurves(action)
    )


def _solver_signature(armature):
    bpy.context.view_layer.update()
    return (
        tuple(
            (
                bone.name,
                tuple(tuple(row) for row in bone.matrix),
                tuple(tuple(row) for row in bone.bone.matrix_local),
                tuple((item.name, item.type) for item in bone.constraints),
            )
            for bone in armature.pose.bones
        ),
        tuple(
            (curve.data_path, curve.array_index, curve.driver.expression)
            for curve in armature.animation_data.drivers
        ),
        _animation_signature(armature),
    )


def _assert_rest_outline(armature, stage, direction, normal):
    control = armature.pose.bones[stage.control_bone]
    display_rotation = control.custom_shape_transform.bone.matrix_local.to_3x3()
    normal = Vector(normal).normalized()
    direction = Vector(direction)
    direction = (direction - normal * direction.dot(normal)).normalized()
    right = direction.cross(normal).normalized()
    coordinates = tuple(
        display_rotation @ vertex.co for vertex in control.custom_shape.data.vertices
    )
    # The wrist is exactly the lower-edge center, and the rounded cap extends
    # along the source hand's projected rest direction, regardless of its roll.
    along = tuple(co.dot(direction) for co in coordinates)
    across = tuple(co.dot(right) for co in coordinates)
    _close(min(along), 0.0)
    _close(max(along), stage.presentation.height)
    _close(min(across), -stage.presentation.width * 0.5)
    _close(max(across), stage.presentation.width * 0.5)
    assert max(abs(co.dot(normal)) for co in coordinates) < 2.0e-5
    # Use a tighter band than the general transform tolerance: the first
    # corner-arc sample is only about 2e-5 above the straight bottom edge.
    # Including that sample can select one rounded side but not the other
    # because of float rounding, producing a false asymmetry.
    bottom_level = min(along)
    bottom = [co for co in coordinates if abs(co.dot(direction) - bottom_level) < 1.0e-6]
    assert len(bottom) >= 2
    _close(min(co.dot(right) for co in bottom), -max(co.dot(right) for co in bottom))
    assert not control.custom_shape.data.polygons


def main():
    import coa_tools2
    from coa_tools2.rig_control.blender.semantic_compiler import compile_semantic_component
    from coa_tools2.rig_control.blender.semantic_presentations import compile_component_presentations
    from coa_tools2.rig_control.blender.semantic_widget_orientation import hand_widget_rest_transform

    coa_tools2.register()
    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object
    armature.name = "HandRestPresentationValidation"
    armature.location = (1.0, -0.3, 0.7)
    armature.rotation_euler = (0.2, -0.1, 0.3)
    armature.scale = (-1.2, 0.9, 1.1)
    cases = (
        ("right", (0.8, 0.0, 0.0), (0.0, 1.0, 0.0)),
        ("left", (-0.8, 0.0, 0.0), (0.0, 1.0, 0.0)),
        ("up", (0.0, 0.0, 0.8), (0.0, 1.0, 0.0)),
        ("depth", (0.4, 0.7, 0.8), (0.0, 1.0, 0.0)),
        ("tilted", (0.5, 0.3, 0.7), (0.2, 0.8, 0.5)),
    )
    bpy.ops.object.mode_set(mode="EDIT")
    bones = armature.data.edit_bones
    for index, (name, direction, _normal) in enumerate(cases):
        origin = Vector((index * 4.0, 0.0, 0.0))
        upper = _new_bone(bones, name + ".upper", origin, origin + Vector((0, 0, 1)))
        lower = _new_bone(bones, name + ".lower", upper.tail, upper.tail + Vector((0.2, 0, 1)), upper)
        hand = _new_bone(bones, name + ".hand", lower.tail, lower.tail + Vector(direction), lower)
        hand.roll = math.radians(19 + index * 33)
        _new_bone(bones, name + ".unused", lower.tail, lower.tail + Vector((1, 0, 0)), lower)
    bpy.ops.object.mode_set(mode="POSE")
    # Adding another collection item can invalidate earlier PropertyGroup RNA
    # wrappers.  Keep only stable UUIDs across rig_components.add() calls.
    components = []
    for index, (name, direction, normal) in enumerate(cases):
        _log(f"Build case {index + 1}/{len(cases)}: {name}")
        component = armature.coa_tools2_rig.rig_components.add()
        component.component_uuid = str(uuid.uuid4())
        component.semantic_id = name
        component.label = name
        component.component_type = "SEMANTIC"
        component.deformation_mode = "PARAMETRIC"
        for suffix in ("upper", "lower", "unused" if index == 4 else "hand"):
            component.source_bones.add().bone_name = name + "." + suffix
        stage = component.semantic_stages.add()
        stage.stage_uuid = str(uuid.uuid4())
        stage.semantic_id = name + ".ik"
        stage.label = name + " IK"
        stage.stage_type = "CHAIN_IK"
        stage.chain_length = 2
        stage.use_pole = False
        stage.art_plane_normal = normal
        if index == 4:
            # An explicit stage chain takes precedence over the component's
            # different end bone when finding the authored hand rest pose.
            for suffix in ("upper", "lower", "hand"):
                stage.source_bones.add().bone_name = name + "." + suffix
        stage.presentation.live_preview = False
        stage.presentation.shape = "TOMBSTONE"
        stage.presentation.width = 0.6
        stage.presentation.height = 0.85
        # Include the exact top midpoint in the sampled semicircle.
        stage.presentation.segments = 97
        assert stage.presentation.align_to_source_rest
        compile_semantic_component(armature, component)
        _log(f"Check rest outline: {name}")
        _assert_rest_outline(armature, stage, direction, normal)
        components.append((component.component_uuid, stage.stage_uuid))

    _log("Resolve first component after all collection additions")
    component_uuid, stage_uuid = components[0]
    component = next(
        item for item in armature.coa_tools2_rig.rig_components
        if item.component_uuid == component_uuid
    )
    stage = next(
        item for item in component.semantic_stages if item.stage_uuid == stage_uuid
    )
    control = armature.pose.bones[stage.control_bone]
    control.location = (0.1, -0.2, 0.3)
    control.keyframe_insert(data_path="location", frame=1)
    control.location = (0.3, 0.4, -0.1)
    control.keyframe_insert(data_path="location", frame=12)
    bpy.context.scene.frame_set(7)
    control.custom_shape_rotation_euler = (0.1, -0.2, 0.3)
    control.custom_shape_translation = (0.2, -0.1, 0.05)
    custom_rotation = tuple(control.custom_shape_rotation_euler)
    custom_translation = tuple(control.custom_shape_translation)
    stable_solver = _solver_signature(armature)
    stable_vertices = _vertices(control.custom_shape)
    for _repeat in range(2):
        _log(f"Reapply animated presentation {_repeat + 1}/2")
        compile_component_presentations(armature, component)
        assert _vertices(control.custom_shape) == stable_vertices
        assert _solver_signature(armature) == stable_solver
        assert tuple(control.custom_shape_rotation_euler) == custom_rotation
        assert tuple(control.custom_shape_translation) == custom_translation

    # Disabled alignment restores canonical display-frame geometry.  Re-enable
    # while animated and verify that it still reads only the authored rest.
    _log("Disable hand rest alignment")
    stage.presentation.align_to_source_rest = False
    compile_component_presentations(armature, component)
    canonical = tuple(vertex.co for vertex in control.custom_shape.data.vertices)
    _close(min(co.y for co in canonical), -stage.presentation.height * 0.5)
    _close(max(co.y for co in canonical), stage.presentation.height * 0.5)
    assert max(abs(co.z) for co in canonical) < 1.0e-6
    _log("Re-enable hand rest alignment while animated")
    stage.presentation.align_to_source_rest = True
    compile_component_presentations(armature, component)
    assert _vertices(control.custom_shape) == stable_vertices
    assert _solver_signature(armature) == stable_solver

    # Custom mesh objects keep their geometry and the user's authored native
    # offsets.  The generated-hand option has no effect on this shape type.
    _log("Apply custom object and preserve authored offsets")
    mesh = bpy.data.meshes.new("ValidationCustomHandMesh")
    mesh.from_pydata(((0, 0, 0), (2, 0, 0), (0, 1, 0)), ((0, 1), (1, 2), (2, 0)), ())
    custom = bpy.data.objects.new("ValidationCustomHand", mesh)
    bpy.context.scene.collection.objects.link(custom)
    custom_vertices = _vertices(custom)
    stage.presentation.custom_object = custom
    stage.presentation.shape = "CUSTOM_OBJECT"
    compile_component_presentations(armature, component)
    assert control.custom_shape == custom
    assert _vertices(custom) == custom_vertices
    assert tuple(control.custom_shape_rotation_euler) == custom_rotation
    assert tuple(control.custom_shape_translation) == custom_translation
    assert _solver_signature(armature) == stable_solver

    # A hand normal to the artwork has no unique projected direction.  Its
    # fallback remains finite, orthonormal and repeatable.
    _log("Check perpendicular-hand fallback")
    source = armature.data.bones["right.hand"]
    display = control.custom_shape_transform.bone
    perpendicular = source.tail_local - source.head_local
    first = hand_widget_rest_transform(source, display, perpendicular, 0.85)
    second = hand_widget_rest_transform(source, display, perpendicular, 0.85)
    assert first == second
    assert all(math.isfinite(value) for row in first for value in row)
    _close(first.to_3x3().determinant(), 1.0)
    print("HAND_REST_SHAPE_OK", len(cases), flush=True)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
