#!/usr/bin/env python3
"""Blender 5.1+ headless regression for B-Bone Bezier + Secondary Motion."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import uuid

import bpy


def _bone(edit_bones, name, head, tail):
    bone = edit_bones.new(name)
    bone.head = head
    bone.tail = tail
    bone.use_connect = False
    return bone


def _bbone_owner(armature, bone_name, property_name):
    pose_bone = armature.pose.bones[bone_name]
    if hasattr(pose_bone, property_name):
        return pose_bone
    data_bone = armature.data.bones[bone_name]
    assert hasattr(data_bone, property_name), property_name
    return data_bone


def _bbone_value(armature, bone_name, property_name):
    return getattr(_bbone_owner(armature, bone_name, property_name), property_name)


def _new_stage(component, stage_type, label, order):
    stage = component.semantic_stages.add()
    stage.stage_uuid = str(uuid.uuid4())
    stage.semantic_id = label.lower().replace(" ", ".")
    stage.label = label
    stage.stage_type = stage_type
    stage.order = order
    return stage


def _generated_bones(component, stage_uuid, leaf_prefix):
    prefix = f"semantic:{stage_uuid}:{leaf_prefix}"
    return tuple(
        artifact.bone_name
        for artifact in sorted(component.artifacts, key=lambda item: item.role)
        if artifact.data_type == "BONE" and artifact.role.startswith(prefix)
    )


def _evaluated_bbone_matrices(armature, bone_name, segments):
    bpy.context.view_layer.update()
    evaluated = armature.evaluated_get(bpy.context.evaluated_depsgraph_get())
    pose_bone = evaluated.pose.bones[bone_name]
    assert hasattr(pose_bone, "bbone_segment_matrix")
    return tuple(
        pose_bone.bbone_segment_matrix(index, rest=False).copy()
        for index in range(segments + 1)
    )


def _matrix_delta(left, right):
    return max(
        abs(float(left[row][column]) - float(right[row][column]))
        for row in range(4)
        for column in range(4)
    )


def _assert_widget(armature, bone_names, shape, target_role):
    assert bone_names
    widgets = {armature.pose.bones[name].custom_shape for name in bone_names}
    assert len(widgets) == 1
    widget = widgets.pop()
    assert widget is not None and widget.type == "MESH"
    assert widget.get("coa_semantic_widget_shape") == shape
    assert widget.get("coa_semantic_widget_target_role") == target_role
    assert widget.data.vertices and widget.data.edges and not widget.data.polygons


def main():
    import coa_tools2
    from coa_tools2.rig_control.blender.semantic_bbone import BBONE_STATE_KEY
    from coa_tools2.rig_control.blender.semantic_compiler import (
        compile_semantic_component,
    )

    coa_tools2.register()
    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object
    armature.name = "Phase9_BBoneBezier"
    armature.coa_tools2_rig.rig_instance_id = str(uuid.uuid4())
    armature.data.display_type = "BBONE"

    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = armature.data.edit_bones
    _bone(edit_bones, "bbone.deform", (0, 0, 0), (0, 0, 3))
    _bone(edit_bones, "projected.anchor", (-3, 0, 0), (-3, 0, 1))
    bpy.ops.object.mode_set(mode="POSE")

    source_name = "bbone.deform"
    original_segments = int(_bbone_value(armature, source_name, "bbone_segments"))
    original_roll_in = float(
        _bbone_value(armature, source_name, "bbone_rollin")
    )
    original_roll_out = float(
        _bbone_value(armature, source_name, "bbone_rollout")
    )
    original_start_handle = _bbone_value(
        armature, source_name, "bbone_custom_handle_start"
    )
    original_start_handle_name = (
        original_start_handle.name if original_start_handle is not None else ""
    )
    original_end_handle = _bbone_value(
        armature, source_name, "bbone_custom_handle_end"
    )
    original_end_handle_name = (
        original_end_handle.name if original_end_handle is not None else ""
    )

    rig_data = armature.coa_tools2_rig
    component = rig_data.rig_components.add()
    component.component_uuid = str(uuid.uuid4())
    component.semantic_id = "body.bbone_bezier"
    component.label = "B-Bone Bezier"
    component.component_type = "SEMANTIC"
    component.deformation_mode = "PARAMETRIC"
    reference = component.source_bones.add()
    reference.bone_name = source_name

    # Keep one independent primary stage alive so disabling the B-Bone stage
    # can exercise normal compiler cleanup/restoration.
    projected = _new_stage(component, "PROJECTED_TRANSFORM", "Anchor", 0)
    reference = projected.source_bones.add()
    reference.bone_name = "projected.anchor"
    projected.presentation.live_preview = False
    projected.presentation.shape = "NONE"

    bbone = _new_stage(component, "BBONE_BEZIER", "Body Bezier", 1)
    reference = bbone.source_bones.add()
    reference.bone_name = source_name
    bbone.bbone_segments = 12
    bbone.bbone_use_mid_control = True
    bbone.bbone_mid_influence = 0.4
    bbone.bbone_ease_in = 0.75
    bbone.bbone_ease_out = 1.25
    bbone.bbone_roll_in = -0.1
    bbone.bbone_roll_out = 0.2
    bbone.bbone_use_scale = True
    bbone.bbone_scale_in = (1.0, 0.9, 1.0)
    bbone.bbone_scale_out = (1.0, 1.1, 1.0)

    compiled = compile_semantic_component(armature, component)
    info = compiled["stage_results"][bbone.stage_uuid].bbone_info
    assert info is not None
    assert info.source_bone == source_name
    assert len(info.point_control_bones) == 3
    assert len(info.handle_control_bones) == 2
    assert len(info.secondary_control_bones) == 3
    assert armature.data.bones[source_name].get(BBONE_STATE_KEY)
    assert int(_bbone_value(armature, source_name, "bbone_segments")) == 12
    assert _bbone_value(
        armature, source_name, "bbone_handle_type_start"
    ) == "ABSOLUTE"
    assert _bbone_value(
        armature, source_name, "bbone_handle_type_end"
    ) == "ABSOLUTE"
    assert _bbone_value(
        armature, source_name, "bbone_custom_handle_start"
    ).name == info.effective_handle_bones[0]
    assert _bbone_value(
        armature, source_name, "bbone_custom_handle_end"
    ).name == info.effective_handle_bones[1]
    assert abs(float(_bbone_value(armature, source_name, "bbone_easein")) - 0.75) < 1e-6
    assert abs(float(_bbone_value(armature, source_name, "bbone_easeout")) - 1.25) < 1e-6
    assert abs(float(_bbone_value(armature, source_name, "bbone_rollin")) + 0.1) < 1e-6
    assert abs(float(_bbone_value(armature, source_name, "bbone_rollout")) - 0.2) < 1e-6
    assert {
        artifact.role
        for artifact in component.artifacts
        if artifact.data_type == "DRIVER"
    }.issuperset(
        {
            f"semantic:{bbone.stage_uuid}:bbone_roll_driver:in",
            f"semantic:{bbone.stage_uuid}:bbone_roll_driver:out",
        }
    )
    assert bbone.presentation.shape == "ELLIPSE"
    assert bbone.handle_presentation.shape == "TRIANGLE"
    _assert_widget(
        armature, info.point_control_bones, "ELLIPSE", "BBONE_POINT"
    )
    _assert_widget(
        armature, info.handle_control_bones, "TRIANGLE", "BBONE_HANDLE"
    )

    structure = (
        len(armature.data.bones),
        len(component.artifacts),
        tuple(
            len(armature.pose.bones[name].constraints)
            for name in (source_name,) + info.effective_handle_bones
        ),
    )
    compiled_again = compile_semantic_component(armature, component)
    info_again = compiled_again["stage_results"][bbone.stage_uuid].bbone_info
    assert info_again == info
    assert structure == (
        len(armature.data.bones),
        len(component.artifacts),
        tuple(
            len(armature.pose.bones[name].constraints)
            for name in (source_name,) + info.effective_handle_bones
        ),
    )

    # Endpoint and tangent-handle controls must alter the evaluated B-Bone
    # curve rather than rotating a flat artwork mesh as a 3D object.
    before_curve = _evaluated_bbone_matrices(armature, source_name, 12)
    armature.pose.bones[info.handle_control_bones[0]].location.x += 0.7
    armature.pose.bones[info.point_control_bones[1]].location.z += 0.4
    after_curve = _evaluated_bbone_matrices(armature, source_name, 12)
    assert max(
        _matrix_delta(before, after)
        for before, after in zip(before_curve, after_curve)
    ) > 1.0e-4
    armature.pose.bones[info.handle_control_bones[0]].location = (0, 0, 0)
    armature.pose.bones[info.point_control_bones[1]].location = (0, 0, 0)
    bpy.context.view_layer.update()

    # The custom-handle RNA switches make local handle scale and orientation
    # feed native Ease / Roll evaluation without exposing source-bone RNA.
    handle = armature.pose.bones[info.handle_control_bones[0]]
    before_ease = _evaluated_bbone_matrices(armature, source_name, 12)
    handle.scale.y = 1.4
    after_ease = _evaluated_bbone_matrices(armature, source_name, 12)
    assert max(
        _matrix_delta(before, after)
        for before, after in zip(before_ease, after_ease)
    ) > 1.0e-4
    handle.scale = (1, 1, 1)
    bpy.context.view_layer.update()

    before_roll = _evaluated_bbone_matrices(armature, source_name, 12)
    before_roll_value = float(
        _bbone_value(armature, source_name, "bbone_rollin")
    )
    handle.rotation_euler.y = 0.35
    after_roll = _evaluated_bbone_matrices(armature, source_name, 12)
    after_roll_value = float(
        _bbone_value(armature, source_name, "bbone_rollin")
    )
    assert abs((after_roll_value - before_roll_value) - 0.35) < 1.0e-4
    assert max(
        _matrix_delta(before, after)
        for before, after in zip(before_roll, after_roll)
    ) > 1.0e-4
    handle.rotation_euler = (0, 0, 0)
    bpy.context.view_layer.update()

    # Fail after the structural builder by handing presentation compilation
    # an invalid non-Mesh Custom Object.  Raw source RNA and owned structures
    # must roll back to the previously compiled state.
    rollback_state = (
        len(armature.data.bones),
        len(component.artifacts),
        float(_bbone_value(armature, source_name, "bbone_rollin")),
        _bbone_value(
            armature, source_name, "bbone_custom_handle_start"
        ).name,
        _bbone_value(
            armature, source_name, "bbone_custom_handle_end"
        ).name,
    )
    bbone.bbone_roll_in = 0.7
    bbone.handle_presentation.shape = "CUSTOM_OBJECT"
    bbone.handle_presentation.custom_object = armature
    try:
        compile_semantic_component(armature, component)
    except Exception as exc:
        assert "Mesh" in str(exc) or "custom shape" in str(exc), str(exc)
    else:
        raise AssertionError("Invalid B-Bone presentation did not fail.")
    assert rollback_state == (
        len(armature.data.bones),
        len(component.artifacts),
        float(_bbone_value(armature, source_name, "bbone_rollin")),
        _bbone_value(
            armature, source_name, "bbone_custom_handle_start"
        ).name,
        _bbone_value(
            armature, source_name, "bbone_custom_handle_end"
        ).name,
    )
    bbone.bbone_roll_in = -0.1
    bbone.handle_presentation.custom_object = None
    bbone.handle_presentation.shape = "TRIANGLE"
    compile_semantic_component(armature, component)

    secondary = _new_stage(component, "SECONDARY_MOTION", "Handle Follow", 2)
    secondary.depends_on = bbone.stage_uuid
    secondary.frequency_hz = 2.5
    secondary.damping_ratio = 0.6
    compiled = compile_semantic_component(armature, component)
    secondary_info = compiled["stage_results"][secondary.stage_uuid]
    assert secondary_info.bbone_info is not None
    sim_bones = _generated_bones(
        component, secondary.stage_uuid, "secondary_output:"
    )
    assert len(sim_bones) == len(info.secondary_control_bones) == 3
    for owner_name, constraint_name, target_name in zip(
        info.effective_handle_bones,
        info.handle_follow_constraints,
        sim_bones[:2],
    ):
        assert (
            armature.pose.bones[owner_name].constraints[constraint_name].subtarget
            == target_name
        )
    for owner_name, constraint_name in zip(
        info.effective_handle_bones, info.mid_pull_constraints
    ):
        assert (
            armature.pose.bones[owner_name].constraints[constraint_name].subtarget
            == sim_bones[-1]
        )

    # Generated pointers, Geometry Nodes custom shapes and Secondary targets
    # must survive a normal .blend save/reload before any rebuild is requested.
    component_uuid = component.component_uuid
    bbone_uuid = bbone.stage_uuid
    secondary_uuid = secondary.stage_uuid
    temporary = Path(tempfile.gettempdir()) / f"coa_phase9_bbone_{uuid.uuid4().hex}.blend"
    try:
        bpy.ops.wm.save_as_mainfile(filepath=str(temporary))
        bpy.ops.wm.open_mainfile(filepath=str(temporary))
        armature = bpy.data.objects["Phase9_BBoneBezier"]
        component = next(
            item
            for item in armature.coa_tools2_rig.rig_components
            if item.component_uuid == component_uuid
        )
        bbone = next(
            item
            for item in component.semantic_stages
            if item.stage_uuid == bbone_uuid
        )
        secondary = next(
            item
            for item in component.semantic_stages
            if item.stage_uuid == secondary_uuid
        )
        assert armature.data.bones[source_name].get(BBONE_STATE_KEY)
        assert _bbone_value(
            armature, source_name, "bbone_custom_handle_start"
        ).name == info.effective_handle_bones[0]
        assert _bbone_value(
            armature, source_name, "bbone_custom_handle_end"
        ).name == info.effective_handle_bones[1]
        saved_roll = float(
            _bbone_value(armature, source_name, "bbone_rollin")
        )
        armature.pose.bones[info.handle_control_bones[0]].rotation_euler.y = 0.2
        bpy.context.view_layer.update()
        assert abs(
            float(_bbone_value(armature, source_name, "bbone_rollin"))
            - saved_roll
            - 0.2
        ) < 1.0e-4
        armature.pose.bones[info.handle_control_bones[0]].rotation_euler.y = 0.0
        bpy.context.view_layer.update()
        _assert_widget(
            armature, info.point_control_bones, "ELLIPSE", "BBONE_POINT"
        )
        _assert_widget(
            armature, info.handle_control_bones, "TRIANGLE", "BBONE_HANDLE"
        )
        for owner_name, constraint_name, target_name in zip(
            info.effective_handle_bones,
            info.handle_follow_constraints,
            sim_bones[:2],
        ):
            assert (
                armature.pose.bones[owner_name].constraints[
                    constraint_name
                ].subtarget
                == target_name
            )
        compiled = compile_semantic_component(armature, component)
        info = compiled["stage_results"][bbone.stage_uuid].bbone_info
        assert info is not None
    finally:
        if temporary.exists():
            temporary.unlink()

    # Disabling Secondary restores authored controls; disabling B-Bone then
    # restores the source's original raw RNA before deleting custom handles.
    secondary.enabled = False
    compile_semantic_component(armature, component)
    assert all(name not in armature.data.bones for name in sim_bones)
    for owner_name, constraint_name, target_name in zip(
        info.effective_handle_bones,
        info.handle_follow_constraints,
        info.handle_control_bones,
    ):
        assert (
            armature.pose.bones[owner_name].constraints[constraint_name].subtarget
            == target_name
        )

    generated = info.control_bones + info.effective_handle_bones
    bbone.enabled = False
    compile_semantic_component(armature, component)
    assert all(name not in armature.data.bones for name in generated)
    assert armature.data.bones[source_name].get(BBONE_STATE_KEY) is None
    assert int(_bbone_value(armature, source_name, "bbone_segments")) == original_segments
    assert abs(
        float(_bbone_value(armature, source_name, "bbone_rollin"))
        - original_roll_in
    ) < 1.0e-6
    assert abs(
        float(_bbone_value(armature, source_name, "bbone_rollout"))
        - original_roll_out
    ) < 1.0e-6
    assert not any(
        "bbone_rollin" in fcurve.data_path
        or "bbone_rollout" in fcurve.data_path
        for fcurve in (
            armature.animation_data.drivers
            if armature.animation_data is not None
            else ()
        )
    )
    restored_start = _bbone_value(
        armature, source_name, "bbone_custom_handle_start"
    )
    restored_end = _bbone_value(
        armature, source_name, "bbone_custom_handle_end"
    )
    assert (
        restored_start.name if restored_start is not None else ""
    ) == original_start_handle_name
    assert (
        restored_end.name if restored_end is not None else ""
    ) == original_end_handle_name

    print(
        "PHASE9_BBONE_BEZIER_OK",
        len(info.point_control_bones),
        len(info.handle_control_bones),
        len(sim_bones),
    )


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
