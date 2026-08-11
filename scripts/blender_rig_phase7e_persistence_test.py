#!/usr/bin/env python3
"""Blender 5.1 persistence test for coexisting State and Semantic rigs."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile

import bpy


def _update_scene():
    bpy.context.view_layer.update()
    bpy.context.scene.frame_set(bpy.context.scene.frame_current)
    bpy.context.view_layer.update()


def _activate_armature(armature):
    active = bpy.context.active_object
    if active is not None and active.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="POSE")


def _shape_target(armature, object_name, shape_name):
    mesh = bpy.data.meshes.new(f"{object_name}_Mesh")
    mesh.from_pydata(
        ((-1.0, 0.0, -1.0), (1.0, 0.0, -1.0), (1.0, 0.0, 1.0), (-1.0, 0.0, 1.0)),
        (),
        ((0, 1, 2, 3),),
    )
    target = bpy.data.objects.new(object_name, mesh)
    bpy.context.scene.collection.objects.link(target)
    target.parent = armature
    target.shape_key_add(name="Basis")
    return target, target.shape_key_add(name=shape_name)


def _driver_count(shape_keys):
    animation_data = shape_keys.animation_data
    return len(animation_data.drivers) if animation_data is not None else 0


def _owned_driver_count(shape_keys, armature, output_uuid):
    from coa_tools2.rig_control.blender.semantic_outputs import (
        _driver_uses_output,
    )

    animation_data = shape_keys.animation_data
    if animation_data is None:
        return 0
    return sum(
        _driver_uses_output(fcurve, armature, output_uuid)
        for fcurve in animation_data.drivers
    )


def _component_by_uuid(armature, component_uuid):
    return next(
        component
        for component in armature.coa_tools2_rig.rig_components
        if component.component_uuid == component_uuid
    )


def _control_by_uuid(armature, control_uuid):
    return next(
        control
        for control in armature.coa_tools2_rig.rig_controls
        if control.control_uuid == control_uuid
    )


def _stage_by_uuid(component, stage_uuid):
    return next(
        stage
        for stage in component.semantic_stages
        if stage.stage_uuid == stage_uuid
    )


def _state_signature(armature, control):
    control_pose = armature.pose.bones[control.control_bone]
    display_pose = armature.pose.bones[control.display_bone]
    return (
        control.control_uuid,
        control.control_bone,
        control.display_bone,
        control.name_bone,
        control.name_text_object,
        control_pose.custom_shape.name if control_pose.custom_shape else "",
        display_pose.custom_shape.name if display_pose.custom_shape else "",
        tuple(constraint.name for constraint in control_pose.constraints),
        tuple(
            (
                binding.binding_uuid,
                binding.source_component,
                binding.target_kind,
                binding.target_object.name if binding.target_object else "",
                binding.target_name,
            )
            for binding in control.bindings
        ),
    )


def _assert_value(key_block, expected, label):
    _update_scene()
    assert abs(key_block.value - expected) < 1.0e-4, (
        label,
        key_block.value,
        expected,
    )


def main():
    import coa_tools2
    from coa_tools2.rig_control.blender.selection import select_pose_bone
    from coa_tools2.rig_control.blender.semantic_runtime import (
        CONTINUOUS_NAMESPACE_NAME,
        DISCRETE_NAMESPACE_NAME,
        semantic_runtime_load_post,
    )

    coa_tools2.register()
    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object
    armature.name = "Phase7E_StateSemantic"
    bpy.ops.object.mode_set(mode="EDIT")
    source = armature.data.edit_bones.new("face_source")
    source.head = (0.0, 0.0, 0.0)
    source.tail = (0.0, 0.0, 1.0)
    source_name = source.name
    bpy.ops.object.mode_set(mode="POSE")

    state_target, state_key = _shape_target(
        armature,
        "Phase7E_StateTarget",
        "StateSmile",
    )
    semantic_target, semantic_key = _shape_target(
        armature,
        "Phase7E_SemanticTarget",
        "SemanticTurn",
    )

    _activate_armature(armature)
    result = bpy.ops.coa_tools2.add_rig_control(
        "EXEC_DEFAULT",
        label="Persistent State Slider",
        control_type="SLIDER_1D",
        axis="X",
        width=4.0,
        source_component="X",
        create_initial_binding=True,
        target_object_name=state_target.name,
        shape_key=state_key.name,
    )
    assert result == {"FINISHED"}, result
    state_control = armature.coa_tools2_rig.rig_controls[-1]
    state_control_uuid = state_control.control_uuid
    state_handle = armature.pose.bones[state_control.control_bone]
    state_handle.location.x = 3.0
    _assert_value(state_key, 0.75, "state before semantic build")

    select_pose_bone(armature, source_name, exclusive=True)
    result = bpy.ops.coa_tools2.add_semantic_rig(
        "EXEC_DEFAULT",
        label="Persistent Semantic Pose",
        initial_dimensions=3,
    )
    assert result == {"FINISHED"}, result
    component = armature.coa_tools2_rig.rig_components[-1]
    component_uuid = component.component_uuid
    projected, pose_map = component.semantic_stages
    projected_uuid = projected.stage_uuid
    pose_map_uuid = pose_map.stage_uuid
    semantic_control = armature.pose.bones[projected.control_bone]

    armature.coa_tools2_rig.rig_components_index = (
        len(armature.coa_tools2_rig.rig_components) - 1
    )
    component.semantic_stages_index = 1
    result = bpy.ops.coa_tools2.add_semantic_output(
        "EXEC_DEFAULT",
        label="Persistent Semantic Turn",
        target_kind="SHAPE_KEY",
        target_object_name=semantic_target.name,
        target_name=semantic_key.name,
    )
    assert result == {"FINISHED"}, result
    output_uuid = pose_map.outputs[0].output_uuid

    semantic_control.location = (0.0, 0.0, 0.0)
    assert bpy.ops.coa_tools2.begin_semantic_sample("EXEC_DEFAULT") == {"FINISHED"}
    semantic_key.value = 0.2
    assert bpy.ops.coa_tools2.commit_semantic_sample("EXEC_DEFAULT") == {"FINISHED"}
    semantic_control.location.x = 1.0
    _update_scene()
    assert bpy.ops.coa_tools2.begin_semantic_sample("EXEC_DEFAULT") == {"FINISHED"}
    semantic_key.value = 0.8
    assert bpy.ops.coa_tools2.commit_semantic_sample("EXEC_DEFAULT") == {"FINISHED"}
    assert len(pose_map.samples) == 2

    semantic_control.location.x = 0.5
    _assert_value(semantic_key, 0.5, "semantic before save")
    _assert_value(state_key, 0.75, "state before save")
    assert _driver_count(state_target.data.shape_keys) == 1
    assert _driver_count(semantic_target.data.shape_keys) == 1
    state_signature = _state_signature(armature, state_control)

    assert CONTINUOUS_NAMESPACE_NAME in bpy.app.driver_namespace
    assert DISCRETE_NAMESPACE_NAME in bpy.app.driver_namespace
    assert semantic_runtime_load_post in bpy.app.handlers.load_post

    validation_directory = tempfile.TemporaryDirectory(
        prefix="coa-rig-phase7e-persistence-"
    )
    blend_path = Path(validation_directory.name) / "phase7e-persistence.blend"
    armature_name = armature.name
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    # Prove the persistent load handler, rather than the still-live namespace,
    # restores the scripted Pose Map evaluator after open_mainfile.
    bpy.app.driver_namespace.pop(CONTINUOUS_NAMESPACE_NAME, None)
    bpy.app.driver_namespace.pop(DISCRETE_NAMESPACE_NAME, None)
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    assert CONTINUOUS_NAMESPACE_NAME in bpy.app.driver_namespace
    assert DISCRETE_NAMESPACE_NAME in bpy.app.driver_namespace
    assert semantic_runtime_load_post in bpy.app.handlers.load_post

    armature = bpy.data.objects[armature_name]
    component = _component_by_uuid(armature, component_uuid)
    projected = _stage_by_uuid(component, projected_uuid)
    pose_map = _stage_by_uuid(component, pose_map_uuid)
    state_control = _control_by_uuid(armature, state_control_uuid)
    state_target = bpy.data.objects["Phase7E_StateTarget"]
    state_key = state_target.data.shape_keys.key_blocks["StateSmile"]
    semantic_target = bpy.data.objects["Phase7E_SemanticTarget"]
    semantic_key = semantic_target.data.shape_keys.key_blocks["SemanticTurn"]
    semantic_control = armature.pose.bones[projected.control_bone]
    state_handle = armature.pose.bones[state_control.control_bone]
    assert abs(state_handle.location.x - 3.0) < 1.0e-6
    assert abs(semantic_control.location.x - 0.5) < 1.0e-6
    _assert_value(state_key, 0.75, "state after reload")
    _assert_value(semantic_key, 0.5, "semantic after reload")
    assert _driver_count(state_target.data.shape_keys) == 1
    assert _driver_count(semantic_target.data.shape_keys) == 1
    assert _state_signature(armature, state_control) == state_signature

    # An unrelated driver in the same ShapeKeys must not become the semantic
    # output merely because the stored KeyBlock name becomes stale.
    unmanaged_key = semantic_target.shape_key_add(name="UnmanagedProbe")
    unmanaged_curve = unmanaged_key.driver_add("value")
    unmanaged_curve.driver.type = "SCRIPTED"
    unmanaged_curve.driver.expression = "0.125"

    # Blender updates Object pointers and FCurve paths across datablock renames,
    # while the stored KeyBlock name remains stale.  Reconcile that name before
    # the normal output preflight, without selecting the unrelated driver.
    semantic_target.name = "Phase7E_SemanticTarget_Renamed"
    semantic_key.name = "SemanticTurn_Renamed"
    renamed_target_name = semantic_target.name
    renamed_key_name = semantic_key.name

    _activate_armature(armature)
    rig_data = armature.coa_tools2_rig
    rig_data.rig_components_index = next(
        index
        for index, candidate in enumerate(rig_data.rig_components)
        if candidate.component_uuid == component_uuid
    )
    component.semantic_stages_index = next(
        index
        for index, stage in enumerate(component.semantic_stages)
        if stage.stage_uuid == pose_map_uuid
    )
    output = next(item for item in pose_map.outputs if item.output_uuid == output_uuid)
    assert output.target_object == semantic_target
    assert output.target_name != renamed_key_name
    result = bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT")
    assert result == {"FINISHED"}, result

    component = _component_by_uuid(armature, component_uuid)
    projected = _stage_by_uuid(component, projected_uuid)
    pose_map = _stage_by_uuid(component, pose_map_uuid)
    output = next(item for item in pose_map.outputs if item.output_uuid == output_uuid)
    assert output.target_object == semantic_target
    assert output.target_object.name == renamed_target_name
    assert output.target_name == renamed_key_name
    _assert_value(semantic_key, 0.5, "semantic after rename reconcile")
    assert _owned_driver_count(
        semantic_target.data.shape_keys,
        armature,
        output_uuid,
    ) == 1
    unmanaged_path = unmanaged_key.path_from_id("value")
    unmanaged_drivers = [
        fcurve
        for fcurve in semantic_target.data.shape_keys.animation_data.drivers
        if fcurve.data_path == unmanaged_path
    ]
    assert len(unmanaged_drivers) == 1
    assert unmanaged_drivers[0].driver.expression == "0.125"
    semantic_artifacts = [
        artifact
        for artifact in component.artifacts
        if artifact.data_type == "DRIVER"
        and artifact.binding_uuid == output_uuid
    ]
    assert len(semantic_artifacts) == 1, len(semantic_artifacts)
    assert semantic_artifacts[0].data_path == semantic_key.path_from_id("value")
    print("PHASE7E_OUTPUT_RENAME_OK")

    # Bone metadata reconciliation is tested separately so it cannot mask the
    # Object/KeyBlock rename result above.
    old_control_name = projected.control_bone
    renamed_bone = armature.data.bones[old_control_name]
    renamed_bone.name = "CTRL_Phase7E_Semantic_Renamed"
    renamed_control_name = renamed_bone.name
    result = bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT")
    assert result == {"FINISHED"}, result
    component = _component_by_uuid(armature, component_uuid)
    projected = _stage_by_uuid(component, projected_uuid)
    pose_map = _stage_by_uuid(component, pose_map_uuid)
    output = next(item for item in pose_map.outputs if item.output_uuid == output_uuid)
    assert projected.control_bone == renamed_control_name
    assert all(
        term.source_bone == renamed_control_name
        for channel in pose_map.inputs
        for term in channel.terms
        if term.source_stage_uuid == projected_uuid
    )
    assert output.target_object == semantic_target
    assert output.target_name == renamed_key_name

    semantic_control = armature.pose.bones[renamed_control_name]
    semantic_control.location.x = 0.5
    state_handle = armature.pose.bones[state_control.control_bone]
    state_handle.location.x = 3.0
    _assert_value(semantic_key, 0.5, "semantic after bone rename reconcile")
    _assert_value(state_key, 0.75, "state after semantic rename reconcile")
    assert _driver_count(state_target.data.shape_keys) == 1
    assert _owned_driver_count(
        semantic_target.data.shape_keys,
        armature,
        output_uuid,
    ) == 1
    assert len(rig_data.rig_controls) == 1
    assert _state_signature(armature, state_control) == state_signature

    assert bpy.ops.coa_tools2.validate_rig("EXEC_DEFAULT") == {"FINISHED"}
    assert not rig_data.rig_validation_issues
    validation_directory.cleanup()
    print(
        "PHASE7E_PERSISTENCE_OK",
        _driver_count(state_target.data.shape_keys),
        _owned_driver_count(
            semantic_target.data.shape_keys,
            armature,
            output_uuid,
        ),
        renamed_control_name,
    )


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
