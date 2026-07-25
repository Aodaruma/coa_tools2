#!/usr/bin/env python3
"""Blender integration test for parametric 3D pose controls."""

from __future__ import annotations

import math
import os
import sys
import tempfile
import uuid

import addon_utils
import bpy


def _create_bone(edit_bones, name, head, tail, *, parent=None, roll=0.0):
    bone = edit_bones.new(name)
    bone.head = head
    bone.tail = tail
    bone.parent = parent
    bone.roll = roll
    bone.use_connect = parent is not None and bone.head == parent.tail
    return bone


def _matrix_delta(left, right):
    return max(
        abs(left[row][column] - right[row][column])
        for row in range(4)
        for column in range(4)
    )


def _select_pose_bones(armature, names, active_name):
    from coa_tools2.rig_control.blender.selection import select_pose_bones

    select_pose_bones(armature, names, active_name)
    bpy.context.view_layer.update()


def _flat_art_mesh(armature):
    mesh = bpy.data.meshes.new("ParametricFlatArtMesh")
    mesh.from_pydata(
        (
            (-0.5, 0.0, -0.4),
            (0.5, 0.0, -0.4),
            (0.5, 0.0, 0.4),
            (-0.5, 0.0, 0.4),
        ),
        (),
        ((0, 1, 2, 3),),
    )
    mesh.update()
    art = bpy.data.objects.new("ParametricFlatArt", mesh)
    bpy.context.scene.collection.objects.link(art)
    art.shape_key_add(name="Basis")
    for name, offsets in (
        (
            "DepthFront",
            ((-0.20, 0.0, 0.0), (0.20, 0.0, 0.0), (0.35, 0.0, 0.30), (-0.35, 0.0, 0.30)),
        ),
        (
            "DepthBack",
            ((-0.12, 0.0, -0.20), (0.12, 0.0, -0.20), (0.18, 0.0, 0.10), (-0.18, 0.0, 0.10)),
        ),
        (
            "TiltPositive",
            ((-0.15, 0.0, -0.10), (0.15, 0.0, 0.10), (0.18, 0.0, 0.25), (-0.18, 0.0, 0.05)),
        ),
        (
            "TiltNegative",
            ((-0.15, 0.0, 0.10), (0.15, 0.0, -0.10), (0.18, 0.0, 0.05), (-0.18, 0.0, 0.25)),
        ),
    ):
        key = art.shape_key_add(name=name)
        for point, offset in zip(key.data, offsets):
            point.co.x += offset[0]
            point.co.y += offset[1]
            point.co.z += offset[2]

    group = art.vertex_groups.new(name="hand.L")
    group.add(range(len(mesh.vertices)), 1.0, "REPLACE")
    modifier = art.modifiers.new("Armature", "ARMATURE")
    modifier.object = armature
    return art


def _add_binding(
    component,
    target,
    shape_key,
    source,
    input_min,
    input_max,
    output_min,
    output_max,
):
    binding = component.bindings.add()
    binding.binding_uuid = str(uuid.uuid4())
    binding.control_uuid = component.component_uuid
    binding.source_component = source
    binding.target_kind = "SHAPE_KEY_VALUE"
    binding.target_object = target
    binding.target_name = shape_key
    binding.input_min = input_min
    binding.input_max = input_max
    binding.output_min = output_min
    binding.output_max = output_max
    binding.clamp = True
    return binding


def _evaluated_world_y_values(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        return tuple((evaluated.matrix_world @ vertex.co).y for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def _assert_flat(obj, tolerance=1e-5):
    values = _evaluated_world_y_values(obj)
    assert values
    assert max(values) - min(values) < tolerance, values
    assert max(abs(value) for value in values) < tolerance, values


def _assert_source_pose(armature, expected):
    for name, matrix in expected.items():
        assert _matrix_delta(armature.pose.bones[name].matrix, matrix) < 1e-6, name


def main():
    if not addon_utils.check("coa_tools2")[1]:
        if addon_utils.enable("coa_tools2", default_set=False, persistent=False) is None:
            raise RuntimeError("Could not enable coa_tools2.")

    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object
    armature.name = "COA_Parametric_Test"

    bpy.ops.object.mode_set(mode="EDIT")
    root = _create_bone(
        armature.data.edit_bones,
        "root",
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 1.0),
    )
    upper = _create_bone(
        armature.data.edit_bones,
        "upper_arm.L",
        (0.0, 0.0, 1.0),
        (1.2, 0.0, 1.15),
        parent=root,
        roll=0.15,
    )
    lower = _create_bone(
        armature.data.edit_bones,
        "forearm.L",
        upper.tail,
        (2.25, 0.0, 0.95),
        parent=upper,
        roll=0.32,
    )
    _create_bone(
        armature.data.edit_bones,
        "hand.L",
        lower.tail,
        (2.90, 0.0, 0.90),
        parent=lower,
        roll=0.55,
    )
    bpy.ops.object.mode_set(mode="POSE")

    art = _flat_art_mesh(armature)
    source_names = ("upper_arm.L", "forearm.L", "hand.L")
    source_pose = {
        name: armature.pose.bones[name].matrix.copy()
        for name in source_names
    }
    _select_pose_bones(armature, set(source_names), "hand.L")
    result = bpy.ops.coa_tools2.add_rig_component(
        "EXEC_DEFAULT",
        label="Parametric Hand.L",
        component_type="LIMB_IK",
        deformation_mode="PARAMETRIC",
        orientation_mode="SOURCE_BONE",
        depth_mode="LIMITED",
        depth_min=-0.5,
        depth_max=0.5,
        widget="HAND",
        widget_size=0.65,
    )
    assert result == {"FINISHED"}, result

    component = armature.coa_tools2_rig.rig_components[0]
    assert component.schema_version == 2
    assert component.deformation_mode == "PARAMETRIC"
    assert component.control_bone not in source_names
    assert component.frame_bone
    assert not component.pole_bone
    for name in source_names:
        pose_bone = armature.pose.bones[name]
        assert pose_bone.custom_shape is None
        assert not any(
            constraint.type in {"IK", "COPY_ROTATION"}
            for constraint in pose_bone.constraints
        )
    _assert_source_pose(armature, source_pose)

    _add_binding(component, art, "DepthFront", "LOC_Z", 0.0, 0.5, 0.0, 1.0)
    _add_binding(component, art, "DepthBack", "LOC_Z", -0.5, 0.0, 1.0, 0.0)
    _add_binding(
        component,
        art,
        "TiltPositive",
        "ROT_X",
        0.0,
        1.0,
        0.0,
        1.0,
    )
    _add_binding(
        component,
        art,
        "TiltNegative",
        "ROT_X",
        -1.0,
        0.0,
        1.0,
        0.0,
    )

    from coa_tools2.rig_control.blender.component_compiler import compile_component
    from coa_tools2.rig_control.blender.drivers import (
        driver_uses_binding,
        find_driver,
    )

    compile_component(armature, component)
    artifact_count = len(component.artifacts)
    bone_count = len(armature.data.bones)
    compile_component(armature, component)
    assert len(component.artifacts) == artifact_count
    assert len(armature.data.bones) == bone_count
    assert component.compiled_deformation_mode == "PARAMETRIC"

    component.deformation_mode = "DIRECT_BONES"
    try:
        compile_component(armature, component)
    except RuntimeError as exc:
        assert "Changing Artwork Deformation" in str(exc)
    else:
        raise AssertionError("Built deformation mode was changed in-place.")
    component.deformation_mode = "PARAMETRIC"
    compile_component(armature, component)

    shape_keys = art.data.shape_keys
    for binding in component.bindings:
        key_block = shape_keys.key_blocks[binding.target_name]
        fcurve = find_driver(shape_keys, key_block.path_from_id("value"))
        assert fcurve is not None
        assert driver_uses_binding(
            fcurve,
            armature,
            component.control_bone,
            binding.binding_uuid,
        )

    # Renaming a generated control is reconciled from its ownership tags
    # before strict output ownership is checked.
    previous_control_name = component.control_bone
    armature.data.bones[previous_control_name].name = "CTRL_Parametric_Renamed"
    compile_component(armature, component)
    assert component.control_bone == "CTRL_Parametric_Renamed"
    for binding in component.bindings:
        key_block = shape_keys.key_blocks[binding.target_name]
        fcurve = find_driver(shape_keys, key_block.path_from_id("value"))
        assert driver_uses_binding(
            fcurve,
            armature,
            component.control_bone,
            binding.binding_uuid,
        )

    operator_key = art.shape_key_add(name="OperatorOutput")
    result = bpy.ops.coa_tools2.add_component_binding(
        "EXEC_DEFAULT",
        source_component="ROT_Z",
        target_kind="SHAPE_KEY_VALUE",
        target_object_name=art.name,
        target_name=operator_key.name,
        input_min=-1.0,
        input_max=1.0,
        output_min=0.0,
        output_max=1.0,
    )
    assert result == {"FINISHED"}, result
    operator_path = operator_key.path_from_id("value")
    assert find_driver(shape_keys, operator_path) is not None
    result = bpy.ops.coa_tools2.remove_component_binding("EXEC_DEFAULT")
    assert result == {"FINISHED"}, result
    assert find_driver(shape_keys, operator_path) is None

    operator_rollback_key = art.shape_key_add(name="OperatorRollback")
    binding_count = len(component.bindings)
    from coa_tools2.rig_control.blender import component_compiler

    original_operator_reconcile = (
        component_compiler.reconcile_component_outputs
    )

    def _fail_operator_reconcile(test_armature, test_component):
        original_operator_reconcile(test_armature, test_component)
        raise RuntimeError("injected Add Output failure")

    component_compiler.reconcile_component_outputs = _fail_operator_reconcile
    try:
        try:
            result = bpy.ops.coa_tools2.add_component_binding(
                "EXEC_DEFAULT",
                source_component="ROT_Z",
                target_kind="SHAPE_KEY_VALUE",
                target_object_name=art.name,
                target_name=operator_rollback_key.name,
                input_min=-1.0,
                input_max=1.0,
                output_min=0.0,
                output_max=1.0,
            )
        except RuntimeError as exc:
            assert "injected Add Output failure" in str(exc)
            result = {"CANCELLED"}
    finally:
        component_compiler.reconcile_component_outputs = (
            original_operator_reconcile
        )
    assert result == {"CANCELLED"}, result
    assert len(component.bindings) == binding_count
    assert find_driver(
        shape_keys,
        operator_rollback_key.path_from_id("value"),
    ) is None

    control = armature.pose.bones[component.control_bone]
    control.rotation_mode = "XYZ"
    for frame, depth, tilt in (
        (1, 0.0, 0.0),
        (13, 0.25, 0.50),
        (25, -0.25, -0.50),
    ):
        control.location = (0.0, 0.0, depth)
        control.rotation_euler = (tilt, 0.0, 0.0)
        control.keyframe_insert("location", frame=frame)
        control.keyframe_insert("rotation_euler", frame=frame)

    expected_values = {
        1: (0.0, 0.0, 0.0, 0.0),
        13: (0.5, 0.0, 0.5, 0.0),
        25: (0.0, 0.5, 0.0, 0.5),
    }
    key_names = ("DepthFront", "DepthBack", "TiltPositive", "TiltNegative")
    for frame, expected in expected_values.items():
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        _assert_source_pose(armature, source_pose)
        _assert_flat(art)
        actual = tuple(shape_keys.key_blocks[name].value for name in key_names)
        for value, target in zip(actual, expected):
            assert math.isclose(value, target, abs_tol=1e-5), (frame, actual)

    # All output conflicts are rejected before another valid driver is created.
    valid_key = art.shape_key_add(name="RollbackValid")
    conflict_key = art.shape_key_add(name="RollbackConflict")
    unmanaged = conflict_key.driver_add("value")
    unmanaged.driver.expression = "0.25"
    valid_binding = _add_binding(
        component,
        art,
        valid_key.name,
        "LOC_X",
        -1.0,
        1.0,
        0.0,
        1.0,
    )
    conflict_binding = _add_binding(
        component,
        art,
        conflict_key.name,
        "LOC_Y",
        -1.0,
        1.0,
        0.0,
        1.0,
    )
    valid_binding_uuid = valid_binding.binding_uuid
    conflict_binding_uuid = conflict_binding.binding_uuid
    try:
        compile_component(armature, component)
    except RuntimeError as exc:
        assert "unmanaged driver" in str(exc)
    else:
        raise AssertionError("Unmanaged output driver was not rejected.")
    assert find_driver(
        shape_keys,
        valid_key.path_from_id("value"),
    ) is None
    assert find_driver(
        shape_keys,
        conflict_key.path_from_id("value"),
    ) == unmanaged
    component.bindings.remove(len(component.bindings) - 1)
    component.bindings.remove(len(component.bindings) - 1)
    assert valid_binding_uuid != conflict_binding_uuid

    duplicate_key = art.shape_key_add(name="DuplicateUUID")
    duplicate_binding = _add_binding(
        component,
        art,
        duplicate_key.name,
        "ROT_Z",
        -1.0,
        1.0,
        0.0,
        1.0,
    )
    duplicate_binding.binding_uuid = component.bindings[0].binding_uuid
    try:
        compile_component(armature, component)
    except RuntimeError as exc:
        assert "Duplicate pose output UUID" in str(exc)
    else:
        raise AssertionError("Duplicate component binding UUID was accepted.")
    component.bindings.remove(len(component.bindings) - 1)
    assert find_driver(
        shape_keys,
        duplicate_key.path_from_id("value"),
    ) is None

    # Raw definition removal is reconciled through the persisted driver
    # UUID scan, even after Object and Shape Key renames.
    orphan_key = art.shape_key_add(name="OrphanOutput")
    orphan_binding = _add_binding(
        component,
        art,
        orphan_key.name,
        "ROT_Z",
        -1.0,
        1.0,
        0.0,
        1.0,
    )
    orphan_uuid = orphan_binding.binding_uuid
    compile_component(armature, component)
    art.name = "ParametricFlatArt_Renamed"
    orphan_key.name = "OrphanOutput_Renamed"
    orphan_path = orphan_key.path_from_id("value")
    assert find_driver(shape_keys, orphan_path) is not None
    component.bindings.remove(len(component.bindings) - 1)
    compile_component(armature, component)
    assert find_driver(shape_keys, orphan_path) is None
    assert not any(
        artifact.binding_uuid == orphan_uuid
        for artifact in component.artifacts
    )
    art.name = "ParametricFlatArt"

    # If a later step fails after obsolete-output cleanup, both its old
    # managed FCurve and DRIVER Artifact are transactionally restored.
    rollback_key = art.shape_key_add(name="OutputRollback")
    rollback_binding = _add_binding(
        component,
        art,
        rollback_key.name,
        "ROT_Z",
        -1.0,
        1.0,
        0.0,
        1.0,
    )
    rollback_uuid = rollback_binding.binding_uuid
    compile_component(armature, component)
    rollback_path = rollback_key.path_from_id("value")
    component.bindings.remove(len(component.bindings) - 1)
    original_reconcile = component_compiler.reconcile_component_outputs

    def _fail_after_output_reconcile(test_armature, test_component):
        original_reconcile(test_armature, test_component)
        raise RuntimeError("injected output transaction failure")

    component_compiler.reconcile_component_outputs = (
        _fail_after_output_reconcile
    )
    try:
        try:
            compile_component(armature, component)
        except RuntimeError as exc:
            assert "injected output transaction failure" in str(exc)
        else:
            raise AssertionError("Injected output failure did not propagate.")
    finally:
        component_compiler.reconcile_component_outputs = original_reconcile
    restored_rollback_driver = find_driver(shape_keys, rollback_path)
    assert restored_rollback_driver is not None
    assert any(
        artifact.binding_uuid == rollback_uuid
        for artifact in component.artifacts
    )
    compile_component(armature, component)
    assert find_driver(shape_keys, rollback_path) is None

    # A Component-owned constraint can itself be an output target. If a
    # setting temporarily deletes it, structural rollback must happen before
    # its driver FCurve is restored.
    depth_name = f"COA_COMP_{component.component_uuid[:8]}_Depth"
    depth_binding = component.bindings.add()
    depth_binding.binding_uuid = str(uuid.uuid4())
    depth_binding.control_uuid = component.component_uuid
    depth_binding.source_component = "ROT_Z"
    depth_binding.target_kind = "CONSTRAINT_INFLUENCE"
    depth_binding.target_object = armature
    depth_binding.target_bone = component.control_bone
    depth_binding.target_name = depth_name
    depth_binding.input_min = -1.0
    depth_binding.input_max = 1.0
    compile_component(armature, component)
    depth_constraint = armature.pose.bones[
        component.control_bone
    ].constraints[depth_name]
    depth_path = depth_constraint.path_from_id("influence")
    assert find_driver(armature, depth_path) is not None
    component.depth_mode = "FREE"
    try:
        compile_component(armature, component)
    except RuntimeError as exc:
        assert "Constraint not found" in str(exc)
    else:
        raise AssertionError("Missing owned output target was not rejected.")
    depth_constraint = armature.pose.bones[
        component.control_bone
    ].constraints[depth_name]
    depth_path = depth_constraint.path_from_id("influence")
    assert find_driver(armature, depth_path) is not None
    component.depth_mode = "LIMITED"
    remove_index = len(component.bindings) - 1
    from coa_tools2.rig_control.blender.component_outputs import (
        remove_component_binding,
    )

    remove_component_binding(
        armature,
        component,
        component.bindings[remove_index],
    )
    component.bindings.remove(remove_index)
    compile_component(armature, component)

    file_descriptor, blend_path = tempfile.mkstemp(
        prefix="coa_phase6c_parametric_",
        suffix=".blend",
    )
    os.close(file_descriptor)
    try:
        bpy.context.scene.frame_set(13)
        bpy.ops.wm.save_as_mainfile(filepath=blend_path)
        bpy.ops.wm.open_mainfile(filepath=blend_path)
        armature = bpy.data.objects["COA_Parametric_Test"]
        art = bpy.data.objects["ParametricFlatArt"]
        component = armature.coa_tools2_rig.rig_components[0]
        assert component.deformation_mode == "PARAMETRIC"
        assert len(component.bindings) == 4
        bpy.context.scene.frame_set(25)
        bpy.context.view_layer.update()
        _assert_flat(art)
        restored_keys = art.data.shape_keys
        assert math.isclose(
            restored_keys.key_blocks["DepthBack"].value,
            0.5,
            abs_tol=1e-5,
        )
        for binding in component.bindings:
            key_block = restored_keys.key_blocks[binding.target_name]
            fcurve = find_driver(
                restored_keys,
                key_block.path_from_id("value"),
            )
            assert driver_uses_binding(
                fcurve,
                armature,
                component.control_bone,
                binding.binding_uuid,
            )
    finally:
        if os.path.exists(blend_path):
            os.unlink(blend_path)

    print("COA rig Phase 6C parametric pose test OK.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"Rig Phase 6C parametric test failed: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise
