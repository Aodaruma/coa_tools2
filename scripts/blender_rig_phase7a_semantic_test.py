#!/usr/bin/env python3
"""Blender integration test for N-D Projected Transform + Recorded Pose Map."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import bpy


def _probe_driver_term(armature, term):
    from coa_tools2.rig_control.blender.semantic_outputs import _add_term_variable

    property_name = "_coa_semantic_input_probe"
    data_path = f'["{property_name}"]'
    target = bpy.data.objects.new("SemanticDriverProbe", None)
    bpy.context.scene.collection.objects.link(target)
    target[property_name] = 0.0
    fcurve = target.driver_add(data_path)
    driver = fcurve.driver
    driver.type = "SCRIPTED"
    while driver.variables:
        driver.variables.remove(driver.variables[0])
    variable_name = _add_term_variable(driver, armature, "probe", 0, 0, term)
    driver.expression = variable_name
    target.update_tag()
    bpy.context.scene.frame_set(bpy.context.scene.frame_current)
    bpy.context.view_layer.update()
    evaluated = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
    value = float(evaluated[property_name])
    bpy.data.objects.remove(target, do_unlink=True)
    return value


def main():
    import coa_tools2

    coa_tools2.register()
    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object
    bpy.ops.object.mode_set(mode="EDIT")
    bone = armature.data.edit_bones.new("face")
    bone.head = (0.0, 0.0, 0.0)
    bone.tail = (0.0, 0.0, 1.0)
    bpy.ops.object.mode_set(mode="POSE")
    from coa_tools2.rig_control.blender.selection import select_pose_bone

    select_pose_bone(armature, "face", exclusive=True)

    result = bpy.ops.coa_tools2.add_semantic_rig(
        "EXEC_DEFAULT", label="Face Direction", initial_dimensions=3
    )
    assert result == {"FINISHED"}, result
    component = armature.coa_tools2_rig.rig_components[0]
    assert component.component_type == "SEMANTIC"
    assert not bpy.ops.coa_tools2.add_component_binding.poll()
    legacy = component.bindings.add()
    legacy.binding_uuid = "phase7a-legacy-output"
    from coa_tools2.rig_control.blender.component_compiler import compile_component
    try:
        compile_component(armature, component)
    except Exception as exc:
        assert "legacy Pose Outputs" in str(exc), str(exc)
    else:
        raise AssertionError("Semantic compiler accepted a legacy component binding")
    component.bindings.clear()
    assert [stage.stage_type for stage in component.semantic_stages] == [
        "PROJECTED_TRANSFORM", "POSE_MAP"
    ]
    projected, pose_map = component.semantic_stages
    assert projected.control_bone and projected.art_frame_bone
    assert projected.display_frame_bone != projected.art_frame_bone
    assert len(pose_map.inputs) == 3
    assert len(pose_map.inputs[2].terms) == 2
    control = armature.pose.bones[projected.control_bone]
    assert control.custom_shape_transform.name == projected.display_frame_bone
    depth = control.constraints.get(f"COA_COMP_{component.component_uuid[:8]}_Depth")
    assert depth is not None and depth.min_z == 0.0 and depth.max_z == 0.0

    mesh = bpy.data.meshes.new("FaceMesh")
    mesh.from_pydata(((-1, 0, -1), (1, 0, -1), (1, 0, 1), (-1, 0, 1)), (), ((0, 1, 2, 3),))
    sprite = bpy.data.objects.new("FaceSprite", mesh)
    bpy.context.scene.collection.objects.link(sprite)
    sprite.shape_key_add(name="Basis")
    key = sprite.shape_key_add(name="Turn")
    key.value = 0.2

    armature.coa_tools2_rig.rig_components_index = 0
    component.semantic_stages_index = 1
    result = bpy.ops.coa_tools2.add_semantic_output(
        "EXEC_DEFAULT",
        label="Face Turn",
        target_kind="SHAPE_KEY",
        target_object_name=sprite.name,
        target_name=key.name,
    )
    assert result == {"FINISHED"}, result
    assert key.id_data.animation_data is None or not key.id_data.animation_data.drivers

    control.location = (0.0, 0.0, 0.0)
    result = bpy.ops.coa_tools2.begin_semantic_sample("EXEC_DEFAULT")
    assert result == {"FINISHED"}, result
    key.value = 0.2
    result = bpy.ops.coa_tools2.commit_semantic_sample("EXEC_DEFAULT")
    assert result == {"FINISHED"}, result

    control.location.x = 1.0
    bpy.context.view_layer.update()
    result = bpy.ops.coa_tools2.begin_semantic_sample("EXEC_DEFAULT")
    assert result == {"FINISHED"}, result
    key.value = 0.8
    result = bpy.ops.coa_tools2.commit_semantic_sample("EXEC_DEFAULT")
    assert result == {"FINISHED"}, result
    assert len(pose_map.samples) == 2

    control.location.x = 0.5
    bpy.context.view_layer.update()
    assert abs(key.value - 0.5) < 1.0e-4, key.value
    source = armature.pose.bones["face"]
    assert source.matrix_basis.is_identity

    # Extending a recorded field migrates existing samples to neutral values.
    assert bpy.ops.coa_tools2.add_semantic_input(
        "EXEC_DEFAULT",
        channel_id="turn_x",
        label="Turn X",
        transform_type="ROT_X",
        scale=1.0,
    ) == {"FINISHED"}
    added_input = pose_map.inputs[-1]
    added_term = added_input.terms[0]
    assert added_term.source_stage_uuid == projected.stage_uuid
    assert not added_term.source_bone
    added_input_id = added_input.channel_uuid or added_input.channel_id
    assert all(
        any(
            value.channel_id == added_input_id and abs(value.value) < 1.0e-8
            for value in sample.inputs
        )
        for sample in pose_map.samples
    )
    assert bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT") == {"FINISHED"}
    assert added_term.source_bone == projected.control_bone

    migrated_key = sprite.shape_key_add(name="Migrated Output")
    migrated_key.value = 0.35
    assert bpy.ops.coa_tools2.add_semantic_output(
        "EXEC_DEFAULT",
        label="Migrated Output",
        target_kind="SHAPE_KEY",
        target_object_name=sprite.name,
        target_name=migrated_key.name,
    ) == {"FINISHED"}
    migrated_output = pose_map.outputs[-1]
    assert all(
        any(
            value.output_uuid == migrated_output.output_uuid
            and abs(value.value[0] - 0.35) < 1.0e-8
            for value in sample.outputs
        )
        for sample in pose_map.samples
    )

    # Cancel is transactional: a compile error restores both the authored
    # sample and its edit-session identity.
    output = pose_map.outputs[0]
    original_output_uuid = output.output_uuid
    samples_before_cancel = len(pose_map.samples)
    value_before_edit = float(key.value)
    assert bpy.ops.coa_tools2.begin_semantic_sample("EXEC_DEFAULT") == {"FINISHED"}
    key.value = 0.91
    edit_sample_uuid = component.semantic_edit_sample_uuid
    edit_stage_uuid = component.semantic_edit_stage_uuid
    edit_inputs = tuple(
        (value.channel_id, value.value) for value in pose_map.samples[-1].inputs
    )
    output.output_uuid = ""
    try:
        cancel_result = bpy.ops.coa_tools2.cancel_semantic_sample("EXEC_DEFAULT")
    except RuntimeError as exc:
        assert "missing 1 enabled output" in str(exc)
    else:
        assert cancel_result == {"CANCELLED"}
    assert len(pose_map.samples) == samples_before_cancel + 1
    assert component.semantic_edit_sample_uuid == edit_sample_uuid
    assert component.semantic_edit_stage_uuid == edit_stage_uuid
    assert abs(key.value - 0.91) < 1.0e-6
    restored = next(
        sample for sample in pose_map.samples
        if sample.sample_uuid == edit_sample_uuid
    )
    assert tuple((value.channel_id, value.value) for value in restored.inputs) == edit_inputs
    output.output_uuid = original_output_uuid
    assert bpy.ops.coa_tools2.cancel_semantic_sample("EXEC_DEFAULT") == {"FINISHED"}
    assert len(pose_map.samples) == samples_before_cancel
    assert not component.semantic_edit_sample_uuid
    assert not component.semantic_edit_stage_uuid
    output.enabled = False
    assert bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT") == {"FINISHED"}
    assert abs(key.value - value_before_edit) < 1.0e-6, (
        key.value,
        value_before_edit,
    )
    output.enabled = True
    assert bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT") == {"FINISHED"}

    # Sample capture and runtime Transform Channel inputs must agree for all
    # three Blender spaces, including constraints and parenting.
    from coa_tools2.rig_control.blender.semantic_outputs import (
        capture_semantic_input_value,
    )

    parent = bpy.data.objects.new("SemanticInputParent", None)
    probe = bpy.data.objects.new("SemanticInputSource", None)
    target = bpy.data.objects.new("SemanticInputConstraintTarget", None)
    for obj in (parent, probe, target):
        bpy.context.scene.collection.objects.link(obj)
    parent.location = (2.0, -1.0, 0.5)
    parent.rotation_euler.z = 0.25
    probe.parent = parent
    probe.location = (0.75, 0.25, -0.5)
    probe.rotation_euler.z = 0.4
    probe.scale = (1.25, 0.8, 1.1)
    target.location = (4.0, 2.0, -1.0)
    constraint = probe.constraints.new("COPY_LOCATION")
    constraint.target = target
    constraint.influence = 0.35
    bpy.context.view_layer.update()
    for space in ("TRANSFORM_SPACE", "LOCAL_SPACE", "WORLD_SPACE"):
        for transform_type in ("LOC_X", "ROT_Z", "SCALE_X"):
            term = SimpleNamespace(
                source_object=probe,
                source_kind="TRANSFORM",
                source_bone="",
                transform_type=transform_type,
                transform_space=space,
                data_path="",
                array_index=-1,
                coefficient=1.0,
            )
            channel = SimpleNamespace(offset=0.0, terms=(term,))
            captured = capture_semantic_input_value(armature, channel)
            driven = _probe_driver_term(armature, term)
            assert abs(captured - driven) < 1.0e-5, (
                space, transform_type, captured, driven
            )
    probe["semantic_vector"] = [1.25, 2.5, 3.75]
    probe.update_tag()
    bpy.context.view_layer.update()
    property_term = SimpleNamespace(
        source_object=probe,
        source_kind="CUSTOM_PROPERTY",
        source_bone="",
        transform_type="LOC_X",
        transform_space="TRANSFORM_SPACE",
        data_path='["semantic_vector"]',
        array_index=1,
        coefficient=1.0,
    )
    property_channel = SimpleNamespace(offset=0.0, terms=(property_term,))
    assert abs(capture_semantic_input_value(armature, property_channel) - 2.5) < 1.0e-8
    driven_property = _probe_driver_term(armature, property_term)
    assert abs(driven_property - 2.5) < 1.0e-8, driven_property

    # Retargeting an output UUID must move, not duplicate, its managed driver.
    replacement = sprite.shape_key_add(name="Turn Retargeted")
    old_path = key.path_from_id("value")
    output.target_name = replacement.name
    result = bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT")
    assert result == {"FINISHED"}, result
    new_path = replacement.path_from_id("value")
    driver_paths = {
        curve.data_path for curve in sprite.data.shape_keys.animation_data.drivers
    }
    assert old_path not in driver_paths, driver_paths
    assert new_path in driver_paths, driver_paths
    binding_artifacts = [
        artifact
        for artifact in component.artifacts
        if artifact.data_type == "DRIVER"
        and artifact.binding_uuid == output.output_uuid
    ]
    assert len(binding_artifacts) == 1
    assert binding_artifacts[0].data_path == new_path

    before_bones = {bone.name for bone in armature.data.bones}
    result = bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT")
    assert result == {"FINISHED"}, result
    assert {bone.name for bone in armature.data.bones} == before_bones
    print("PHASE7A_SEMANTIC_OK", len(component.artifacts), key.value)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
