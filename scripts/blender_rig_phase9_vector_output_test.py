#!/usr/bin/env python3
"""Blender 5.1 integration test for atomic semantic vector outputs."""

from __future__ import annotations

import bpy


def _update_scene():
    bpy.context.view_layer.update()
    bpy.context.scene.frame_set(bpy.context.scene.frame_current)
    bpy.context.view_layer.update()


def _evaluated_location(armature, bone_name):
    evaluated = armature.evaluated_get(bpy.context.evaluated_depsgraph_get())
    return tuple(float(value) for value in evaluated.pose.bones[bone_name].location)


def main():
    import coa_tools2

    coa_tools2.register()
    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object
    bpy.ops.object.mode_set(mode="EDIT")
    source = armature.data.edit_bones.new("source")
    source.head = (0.0, 0.0, 0.0)
    source.tail = (0.0, 0.0, 1.0)
    source_name = source.name
    driven = armature.data.edit_bones.new("driven")
    driven.head = (2.0, 0.0, 0.0)
    driven.tail = (2.0, 0.0, 1.0)
    driven_name = driven.name
    retarget = armature.data.edit_bones.new("driven_retarget")
    retarget.head = (3.0, 0.0, 0.0)
    retarget.tail = (3.0, 0.0, 1.0)
    retarget_name = retarget.name
    scalar_driven = armature.data.edit_bones.new("scalar_driven")
    scalar_driven.head = (4.0, 0.0, 0.0)
    scalar_driven.tail = (4.0, 0.0, 1.0)
    scalar_driven_name = scalar_driven.name
    bpy.ops.object.mode_set(mode="POSE")

    from coa_tools2.rig_control.blender.selection import select_pose_bone

    select_pose_bone(armature, source_name, exclusive=True)
    assert bpy.ops.coa_tools2.add_semantic_rig(
        "EXEC_DEFAULT", label="Vector Pose", initial_dimensions=1
    ) == {"FINISHED"}
    component = armature.coa_tools2_rig.rig_components[0]
    projected, pose_map = component.semantic_stages
    component.semantic_stages_index = 1
    assert bpy.ops.coa_tools2.add_semantic_output(
        "EXEC_DEFAULT",
        label="Driven Location",
        target_kind="BONE_LOCATION",
        target_object_name=armature.name,
        target_bone=driven_name,
        array_index=0,
        value_arity=3,
    ) == {"FINISHED"}
    output = pose_map.outputs[0]
    assert output.value_arity == 3

    control = armature.pose.bones[projected.control_bone]
    driven_pose = armature.pose.bones[driven_name]
    control.location = (0.0, 0.0, 0.0)
    driven_pose.location = (0.0, 0.0, 0.0)
    assert bpy.ops.coa_tools2.begin_semantic_sample("EXEC_DEFAULT") == {"FINISHED"}
    assert bpy.ops.coa_tools2.commit_semantic_sample("EXEC_DEFAULT") == {"FINISHED"}

    control.location.x = 1.0
    bpy.context.view_layer.update()
    assert bpy.ops.coa_tools2.begin_semantic_sample("EXEC_DEFAULT") == {"FINISHED"}
    driven_pose.location = (1.0, 2.0, 3.0)
    assert bpy.ops.coa_tools2.commit_semantic_sample("EXEC_DEFAULT") == {"FINISHED"}

    sample_value = pose_map.samples[-1].outputs[0]
    assert sample_value.value_arity == 3
    assert tuple(round(value, 6) for value in sample_value.value[:3]) == (1.0, 2.0, 3.0)
    control.location.x = 0.5
    armature.update_tag()
    _update_scene()
    result_values = _evaluated_location(armature, driven_name)
    assert all(
        abs(value - expected) < 1.0e-4
        for value, expected in zip(result_values, (0.5, 1.0, 1.5))
    ), result_values

    drivers = tuple(armature.animation_data.drivers)
    owned = [
        curve
        for curve in drivers
        if curve.data_path == driven_pose.path_from_id("location")
    ]
    assert len(owned) == 3
    assert {curve.array_index for curve in owned} == {0, 1, 2}
    assert all("coa_pose_field_component" in curve.driver.expression for curve in owned)

    from coa_tools2.rig_control.blender.component_compiler import compile_component
    from coa_tools2.rig_control.blender.semantic_compiler import (
        SemanticRigCompileError,
    )
    from coa_tools2.rig_control.blender.semantic_outputs import (
        _owned_driver_locations,
    )

    compile_component(armature, component)
    assert len([
        curve
        for curve in armature.animation_data.drivers
        if curve.data_path == driven_pose.path_from_id("location")
    ]) == 3

    # Scalar and custom-array outputs can coexist with one logical Vec3.
    assert bpy.ops.coa_tools2.add_semantic_output(
        "EXEC_DEFAULT",
        label="Scalar Coexistence",
        target_kind="BONE_LOCATION",
        target_object_name=armature.name,
        target_bone=scalar_driven_name,
        array_index=0,
        value_arity=1,
    ) == {"FINISHED"}
    scalar_output = pose_map.outputs[-1]
    scalar_uuid = scalar_output.output_uuid
    scalar_locations = tuple(_owned_driver_locations(armature, scalar_uuid))
    assert len(scalar_locations) == 1
    scalar_curve = next(
        curve
        for curve in scalar_locations[0].id_data.animation_data.drivers
        if curve.data_path == scalar_locations[0].data_path
        and curve.array_index == scalar_locations[0].array_index
    )
    assert "coa_pose_field_scalar" in scalar_curve.driver.expression

    property_target = bpy.data.objects.new("Phase9_VectorProperty", None)
    bpy.context.scene.collection.objects.link(property_target)
    property_target["vector_probe"] = [10.0, 20.0, 30.0, 40.0]
    assert bpy.ops.coa_tools2.add_semantic_output(
        "EXEC_DEFAULT",
        label="Array Slice",
        target_kind="CUSTOM_PROPERTY",
        target_object_name=property_target.name,
        data_path='["vector_probe"]',
        array_index=1,
        value_arity=3,
    ) == {"FINISHED"}
    property_output = pose_map.outputs[-1]
    property_uuid = property_output.output_uuid
    property_locations = tuple(_owned_driver_locations(armature, property_uuid))
    assert len(property_locations) == 3
    assert {location.array_index for location in property_locations} == {1, 2, 3}

    # Changing only the declaration must not silently zero missing components.
    vector_sample_output = next(
        item
        for item in pose_map.samples[0].outputs
        if item.output_uuid == output.output_uuid
    )
    before_mismatch = tuple(
        sorted(
            (location.data_path, location.array_index)
            for location in _owned_driver_locations(armature, output.output_uuid)
        )
    )
    vector_sample_output.value_arity = 1
    try:
        compile_component(armature, component)
    except SemanticRigCompileError as exc:
        assert "Re-record or migrate" in str(exc), exc
    else:
        raise AssertionError("Vec3/sample arity mismatch was accepted")
    after_mismatch = tuple(
        sorted(
            (location.data_path, location.array_index)
            for location in _owned_driver_locations(armature, output.output_uuid)
        )
    )
    assert after_mismatch == before_mismatch
    vector_sample_output.value_arity = 3
    compile_component(armature, component)

    # Cancel restores all three authored components and their managed drivers.
    control.location.x = 0.25
    _update_scene()
    expected_cancel = _evaluated_location(armature, driven_name)
    assert bpy.ops.coa_tools2.begin_semantic_sample("EXEC_DEFAULT") == {"FINISHED"}
    armature.pose.bones[driven_name].location = (9.0, 8.0, 7.0)
    assert bpy.ops.coa_tools2.cancel_semantic_sample("EXEC_DEFAULT") == {"FINISHED"}
    _update_scene()
    cancelled = _evaluated_location(armature, driven_name)
    assert all(
        abs(value - expected) < 1.0e-4
        for value, expected in zip(cancelled, expected_cancel)
    ), (cancelled, expected_cancel)
    assert len(tuple(_owned_driver_locations(armature, output.output_uuid))) == 3

    # Blender updates owned FCurve paths on rename.  Even when a user bone
    # reuses the old name, UUID ownership must migrate metadata to the actual
    # renamed target rather than retargeting the output accidentally.
    renamed_driven_name = "driven_renamed"
    armature.data.bones[driven_name].name = renamed_driven_name
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.mode_set(mode="EDIT")
    reused = armature.data.edit_bones.new(driven_name)
    reused.head = (5.0, 0.0, 0.0)
    reused.tail = (5.0, 0.0, 1.0)
    bpy.ops.object.mode_set(mode="POSE")
    compile_component(armature, component)
    assert output.target_bone == renamed_driven_name
    renamed_path = armature.pose.bones[renamed_driven_name].path_from_id("location")
    reused_path = armature.pose.bones[driven_name].path_from_id("location")
    renamed_locations = tuple(_owned_driver_locations(armature, output.output_uuid))
    assert len(renamed_locations) == 3
    assert {location.data_path for location in renamed_locations} == {renamed_path}
    assert all(location.data_path != reused_path for location in renamed_locations)

    # An explicit retarget differs from rename migration: the stored target no
    # longer matches the old artifact path, so all Vec3 curves move atomically.
    output.target_bone = retarget_name
    compile_component(armature, component)
    retarget_path = armature.pose.bones[retarget_name].path_from_id("location")
    retarget_locations = tuple(_owned_driver_locations(armature, output.output_uuid))
    assert len(retarget_locations) == 3
    assert {location.data_path for location in retarget_locations} == {retarget_path}
    assert not any(
        curve.data_path == renamed_path
        for curve in armature.animation_data.drivers
    )

    # Removing the logical output removes all of its component curves without
    # disturbing neighboring scalar/custom-vector outputs.
    vector_uuid = output.output_uuid
    vector_index = next(
        index
        for index, candidate in enumerate(pose_map.outputs)
        if candidate.output_uuid == vector_uuid
    )
    pose_map.outputs.remove(vector_index)
    compile_component(armature, component)
    assert not tuple(_owned_driver_locations(armature, vector_uuid))
    assert len(tuple(_owned_driver_locations(armature, scalar_uuid))) == 1
    assert len(tuple(_owned_driver_locations(armature, property_uuid))) == 3
    assert not any(
        artifact.binding_uuid == vector_uuid
        for artifact in component.artifacts
        if artifact.data_type == "DRIVER"
    )

    print(
        "PHASE9_VECTOR_OUTPUT_OK",
        tuple(round(value, 4) for value in result_values),
        tuple(round(value, 4) for value in cancelled),
        renamed_driven_name,
    )


if __name__ == "__main__":
    main()
