#!/usr/bin/env python3
"""Blender 5.1 integration test for Spline + Secondary Motion stages."""

from __future__ import annotations

from pathlib import Path
import sys
import uuid

import bpy
from mathutils import Vector


def _bone(edit_bones, name, head, tail, parent=None):
    bone = edit_bones.new(name)
    bone.head = head
    bone.tail = tail
    bone.parent = parent
    bone.use_connect = parent is not None
    bone.align_roll(Vector((0.0, 1.0, 0.0)))
    return bone


def _evaluated_curve_vertices(curve_object):
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = curve_object.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        return tuple(evaluated.matrix_world @ vertex.co for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def _maximum_geometry_delta(before, after):
    assert len(before) == len(after) and before
    return max((right - left).length for left, right in zip(before, after))


def _evaluated_bone_head(armature, bone_name):
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = armature.evaluated_get(depsgraph)
    return (evaluated.matrix_world @ evaluated.pose.bones[bone_name].matrix).translation


def _evaluated_mesh_vertices(mesh_object):
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = mesh_object.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        return tuple(evaluated.matrix_world @ vertex.co for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def _maximum_art_depth(armature, art_frame_bone, world_points):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = armature.evaluated_get(depsgraph)
    art_world = evaluated.matrix_world @ evaluated.pose.bones[art_frame_bone].matrix
    inverse = art_world.inverted()
    return max(abs((inverse @ point).z) for point in world_points)


def _art_depth(armature, art_frame_bone, world_point):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = armature.evaluated_get(depsgraph)
    art_world = evaluated.matrix_world @ evaluated.pose.bones[art_frame_bone].matrix
    return abs((art_world.inverted() @ world_point).z)


def _owned_actions(stage_uuid):
    return tuple(
        action
        for action in bpy.data.actions
        if action.get("coa_semantic_stage_uuid") == stage_uuid
    )


def _owned_tracks(armature, actions):
    action_set = set(actions)
    return tuple(
        track
        for track in armature.animation_data.nla_tracks
        if any(strip.action in action_set for strip in track.strips)
    )


def _key_location(pose_bone, frame, value):
    pose_bone.location = value
    pose_bone.keyframe_insert("location", frame=frame)


def main():
    import coa_tools2
    from coa_tools2 import functions
    from coa_tools2.rig_control.blender.selection import (
        active_pose_bone,
        select_pose_bone,
    )
    from coa_tools2.rig_control.blender.semantic_compiler import (
        compile_semantic_component,
    )
    from coa_tools2.rig_control.blender.semantic_secondary import (
        bake_secondary_motion,
        ensure_secondary_motion_artifacts,
    )
    from coa_tools2.rig_control.blender.semantic_spline import (
        ensure_spline_chain_artifacts,
        retarget_spline_hooks,
    )

    coa_tools2.register()
    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object
    armature.name = "Phase7D_SplineSecondary"

    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = armature.data.edit_bones
    chain = []
    heads = (
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 1.0),
        (0.2, 0.0, 2.0),
    )
    for index in range(2):
        chain.append(
            _bone(
                edit_bones,
                f"strand.{index:03d}",
                heads[index],
                heads[index + 1],
                chain[-1] if chain else None,
            )
        )
    source_bone_names = tuple(bone.name for bone in chain)
    bpy.ops.object.mode_set(mode="POSE")

    mesh = bpy.data.meshes.new("Phase7D_FlatStripMesh")
    vertices = []
    for point in heads:
        vertices.extend(((-0.15, 0.0, point[2]), (0.15, 0.0, point[2])))
    faces = [
        (index * 2, index * 2 + 1, index * 2 + 3, index * 2 + 2)
        for index in range(len(heads) - 1)
    ]
    mesh.from_pydata(vertices, (), faces)
    flat_sprite = bpy.data.objects.new("Phase7D_FlatSprite", mesh)
    bpy.context.scene.collection.objects.link(flat_sprite)
    deform = flat_sprite.modifiers.new("Phase7D_Armature", "ARMATURE")
    deform.object = armature
    for index, bone_name in enumerate(source_bone_names):
        group = flat_sprite.vertex_groups.new(name=bone_name)
        group.add((index * 2, index * 2 + 1), 1.0, "REPLACE")
        if index == len(source_bone_names) - 1:
            group.add((index * 2 + 2, index * 2 + 3), 1.0, "REPLACE")

    rig_data = armature.coa_tools2_rig
    rig_data.rig_instance_id = str(uuid.uuid4())
    component = rig_data.rig_components.add()
    component.component_uuid = str(uuid.uuid4())
    component.semantic_id = "strand.motion"
    component.display_name = "Spline Secondary"
    component.component_type = "SEMANTIC"
    component.deformation_mode = "PARAMETRIC"
    for name in source_bone_names:
        reference = component.source_bones.add()
        reference.bone_name = name

    spline_stage = component.semantic_stages.add()
    spline_stage.stage_uuid = str(uuid.uuid4())
    spline_stage.semantic_id = "strand.spline"
    spline_stage.label = "Spline Chain"
    spline_stage.stage_type = "SPLINE"
    # Deliberately use more Spline controls than source bones.  This catches
    # stale-role cleanup that incorrectly falls back to the source-chain size
    # through a pass-through Pose Map dependency.
    spline_stage.spline_control_count = 3
    spline_stage.root_pin = False
    spline_stage.tip_pin = False
    for source in component.source_bones:
        reference = spline_stage.source_bones.add()
        reference.bone_name = source.bone_name

    spline = ensure_spline_chain_artifacts(
        armature, component, spline_stage
    )
    assert len(spline.control_bones) == 3
    assert len(spline.mechanism_bones) == 2
    assert len(spline.projected_joint_bones) == 3
    assert len(spline.presentation_bones) == 2
    assert spline.art_frame_bone
    assert spline.art_frame_owned
    assert len(spline.hook_bindings) == 3
    assert spline.source_bones == source_bone_names
    curve_object = bpy.data.objects[spline.curve_object]
    assert tuple(
        curve_object.modifiers[binding.modifier_name].subtarget
        for binding in spline.hook_bindings
    ) == spline.control_bones

    # Reconciliation is idempotent, including projection/presentation bones
    # and source CopyTransforms constraints.
    structure_before = (
        len(armature.data.bones),
        len(component.artifacts),
        len(curve_object.modifiers),
        tuple(len(armature.pose.bones[name].constraints) for name in source_bone_names),
    )
    spline_again = ensure_spline_chain_artifacts(
        armature, component, spline_stage
    )
    assert spline_again == spline
    assert structure_before == (
        len(armature.data.bones),
        len(component.artifacts),
        len(curve_object.modifiers),
        tuple(len(armature.pose.bones[name].constraints) for name in source_bone_names),
    )

    # Moving an authored CTRL must deform both the hooked Curve and the hidden
    # Spline IK mechanism before Secondary Motion is introduced.
    middle_control = armature.pose.bones[spline.control_bones[1]]
    curve_before = _evaluated_curve_vertices(curve_object)
    mechanism_before = _evaluated_bone_head(
        armature, spline.mechanism_bones[1]
    )
    source_before = _evaluated_bone_head(armature, source_bone_names[1])
    flat_before = _evaluated_mesh_vertices(flat_sprite)
    flat_depth_before = _maximum_art_depth(
        armature, spline.art_frame_bone, flat_before
    )
    assert flat_depth_before < 1.0e-5, flat_depth_before
    middle_control.location.x += 0.9
    middle_control.location.z += 0.6
    curve_after = _evaluated_curve_vertices(curve_object)
    mechanism_after = _evaluated_bone_head(
        armature, spline.mechanism_bones[1]
    )
    source_after = _evaluated_bone_head(armature, source_bone_names[1])
    flat_after = _evaluated_mesh_vertices(flat_sprite)
    assert _maximum_geometry_delta(curve_before, curve_after) > 0.25
    assert (mechanism_after - mechanism_before).length > 1.0e-4
    assert _art_depth(
        armature, spline.art_frame_bone, mechanism_after
    ) > 0.05
    assert (source_after - source_before).length > 1.0e-4
    flat_depth_after = _maximum_art_depth(
        armature, spline.art_frame_bone, flat_after
    )
    assert flat_depth_after < 1.0e-5, flat_depth_after

    evaluated = armature.evaluated_get(bpy.context.evaluated_depsgraph_get())
    art_normal = evaluated.pose.bones[
        spline.art_frame_bone
    ].matrix.to_3x3().col[2].normalized()
    for name in spline.presentation_bones + source_bone_names:
        local_z = evaluated.pose.bones[name].matrix.to_3x3().col[2].normalized()
        assert local_z.dot(art_normal) > 0.9999, (name, local_z, art_normal)
    art_inverse = evaluated.pose.bones[spline.art_frame_bone].matrix.inverted()
    for name in spline.projected_joint_bones:
        local = art_inverse @ evaluated.pose.bones[name].head
        assert abs(local.z) < 1.0e-5, (name, local)
    middle_control.location = (0.0, 0.0, 0.0)
    bpy.context.view_layer.update()

    secondary_stage = component.semantic_stages.add()
    secondary_stage.stage_uuid = str(uuid.uuid4())
    secondary_stage.semantic_id = "strand.secondary"
    secondary_stage.label = "Secondary Motion"
    secondary_stage.stage_type = "SECONDARY_MOTION"
    secondary_stage.frequency_hz = 2.0
    secondary_stage.damping_ratio = 0.4
    secondary_stage.substeps = 2
    secondary_stage.pre_roll = 3
    secondary_stage.bake_start = 1
    secondary_stage.bake_end = 20
    pass_through_stage = component.semantic_stages.add()
    pass_through_stage.stage_uuid = str(uuid.uuid4())
    pass_through_stage.semantic_id = "strand.pose_map_pass_through"
    pass_through_stage.label = "Pose Map Pass Through"
    pass_through_stage.stage_type = "POSE_MAP"
    pass_through_stage.order = 1
    pass_through_stage.depends_on = spline_stage.stage_uuid
    from coa_tools2.rig_control.blender.semantic_operators import _new_input
    pass_through_input = _new_input(
        pass_through_stage,
        "spline_motion",
        "Spline Motion",
        "LOC_X",
    )
    pass_through_input.terms[0].source_stage_uuid = spline_stage.stage_uuid
    secondary_stage.order = 2
    secondary_stage.depends_on = pass_through_stage.stage_uuid

    compiled = compile_semantic_component(armature, component)
    spline_result = compiled["stage_results"][spline_stage.stage_uuid]
    secondary_result = compiled["stage_results"][secondary_stage.stage_uuid]
    assert spline_result.spline_info is not None
    assert secondary_result.spline_info is spline_result.spline_info
    assert secondary_result.primary_control_bone == spline.primary_control_bone
    compiled_sim_bones = tuple(
        artifact.bone_name
        for artifact in sorted(component.artifacts, key=lambda item: item.role)
        if artifact.role.startswith(
            f"semantic:{secondary_stage.stage_uuid}:secondary_output:"
        )
    )
    assert len(compiled_sim_bones) == len(spline.control_bones) == 3
    assert tuple(
        curve_object.modifiers[name].subtarget
        for name in spline.hook_modifiers
    ) == compiled_sim_bones

    secondary = ensure_secondary_motion_artifacts(
        armature,
        component,
        secondary_stage,
        default_source_bones=spline.control_bones,
    )
    assert secondary.source_bones == spline.control_bones
    assert len(secondary.output_bones) == 3
    assert len(secondary.follow_constraints) == 3
    for source_name, output_name, constraint_name in zip(
        secondary.source_bones,
        secondary.output_bones,
        secondary.follow_constraints,
    ):
        constraint = armature.pose.bones[output_name].constraints[constraint_name]
        assert not constraint.mute
        assert constraint.type == "COPY_TRANSFORMS"
        assert constraint.subtarget == source_name

    bindings = retarget_spline_hooks(
        curve_object,
        secondary.output_bones,
        armature=armature,
        hook_names=spline.hook_modifiers,
    )
    assert tuple(binding.bone_name for binding in bindings) == secondary.output_bones
    assert tuple(
        curve_object.modifiers[name].subtarget
        for name in spline.hook_modifiers
    ) == secondary.output_bones

    # The unbaked SIM chain follows CTRLs, so Hook retargeting must not change
    # authored behavior before the first bake.
    curve_before = _evaluated_curve_vertices(curve_object)
    driven_control = armature.pose.bones[spline.control_bones[2]]
    driven_control.location.x = -0.8
    curve_after = _evaluated_curve_vertices(curve_object)
    assert _maximum_geometry_delta(curve_before, curve_after) > 0.25
    driven_control.location = (0.0, 0.0, 0.0)

    # Animate generated Spline CTRLs.  Negative frames provide actual motion
    # history for the Secondary stage pre-roll.
    controls = tuple(
        armature.pose.bones[name] for name in spline.control_bones
    )
    for control in controls:
        _key_location(control, -2, (0.0, 0.0, 0.0))
        _key_location(control, 1, (0.0, 0.0, 0.0))
        _key_location(control, 20, (0.0, 0.0, 0.0))
    _key_location(controls[1], 7, (1.3, 0.0, 0.1))
    _key_location(controls[1], 13, (-0.4, 0.0, 0.0))
    _key_location(controls[2], 10, (-1.0, 0.0, 0.25))
    _key_location(controls[2], 16, (0.7, 0.0, 0.0))
    # Object-level motion must use the Armature world matrix evaluated at each
    # sampled frame.  Converting every sample with the end-frame matrix would
    # introduce a large false local offset at the start of the bake.
    armature.location = (0.0, 0.0, 0.0)
    armature.keyframe_insert("location", frame=-2)
    armature.keyframe_insert("location", frame=1)
    armature.location = (2.0, 0.0, 0.0)
    armature.keyframe_insert("location", frame=20)
    source_action = armature.animation_data.action

    # Preserve more than the default frame: active Action, Pose mode, object
    # selection and active PoseBone must all survive the bake transaction.
    marker = bpy.data.objects.new("Phase7D_ContextMarker", None)
    bpy.context.scene.collection.objects.link(marker)
    marker.select_set(True)
    select_pose_bone(armature, spline.control_bones[2], exclusive=True)
    bpy.context.scene.frame_set(6)
    selected_objects = {obj.name for obj in bpy.context.selected_objects}

    # The authoring operator must use the compiler's propagated Spline result,
    # not require a definition-level direct Spline dependency.
    component.semantic_stages_index = next(
        index
        for index, candidate in enumerate(component.semantic_stages)
        if candidate.stage_uuid == secondary_stage.stage_uuid
    )
    assert bpy.ops.coa_tools2.bake_semantic_secondary("EXEC_DEFAULT") == {
        "FINISHED"
    }
    assert len(_owned_actions(secondary_stage.stage_uuid)) == 1

    first = bake_secondary_motion(
        armature,
        component,
        secondary_stage,
        default_source_bones=spline.control_bones,
    )
    assert first.source_bones == spline.control_bones
    assert first.output_bones == secondary.output_bones
    assert first.sample_count == 20
    assert secondary_stage.secondary_baked
    for output_name, constraint_name in zip(
        secondary.output_bones, secondary.follow_constraints
    ):
        assert armature.pose.bones[output_name].constraints[constraint_name].mute
    assert armature.animation_data.action == source_action
    assert bpy.context.scene.frame_current == 6
    assert armature.mode == "POSE"
    assert active_pose_bone(armature).name == spline.control_bones[2]
    assert {obj.name for obj in bpy.context.selected_objects} == selected_objects

    bpy.context.scene.frame_set(1)
    for source_name, output_name in zip(
        spline.control_bones, secondary.output_bones
    ):
        source_world = _evaluated_bone_head(armature, source_name)
        output_world = _evaluated_bone_head(armature, output_name)
        assert (source_world - output_world).length < 1.0e-4, (
            source_name,
            output_name,
            source_world,
            output_world,
        )
    bpy.context.scene.frame_set(6)

    actions = _owned_actions(secondary_stage.stage_uuid)
    tracks = _owned_tracks(armature, actions)
    assert len(actions) == 1
    assert len(tracks) == 1
    curves = tuple(functions.iter_action_fcurves(actions[0]))
    assert len(curves) == len(secondary.output_bones) * 3
    assert all(len(curve.keyframe_points) == 20 for curve in curves)
    assert any(
        max(point.co.y for point in curve.keyframe_points)
        - min(point.co.y for point in curve.keyframe_points)
        > 0.05
        for curve in curves
    )

    bpy.context.scene.frame_set(10)
    baked_curve_point = _evaluated_curve_vertices(curve_object)
    bpy.context.scene.frame_set(1)
    rest_curve_point = _evaluated_curve_vertices(curve_object)
    assert _maximum_geometry_delta(rest_curve_point, baked_curve_point) > 0.05

    # Re-baking replaces, rather than accumulates, the generated Action/track.
    bpy.context.scene.frame_set(6)
    second = bake_secondary_motion(
        armature,
        component,
        secondary_stage,
        default_source_bones=spline.control_bones,
    )
    actions = _owned_actions(secondary_stage.stage_uuid)
    tracks = _owned_tracks(armature, actions)
    assert len(actions) == 1
    assert len(tracks) == 1
    assert second.output_bones == first.output_bones
    assert secondary_stage.secondary_source_signature == "\n".join(
        spline.control_bones
    )

    # A failure before the visible swap must preserve the complete prior bake
    # and restore all user-facing context.
    old_action = actions[0]
    old_track = tracks[0]
    state_before = (
        len(armature.data.bones),
        len(component.artifacts),
        len(bpy.data.actions),
        len(armature.animation_data.nla_tracks),
        tuple(
            curve_object.modifiers[name].subtarget
            for name in spline.hook_modifiers
        ),
    )

    def fail_before_swap(point):
        if point == "before_swap":
            raise RuntimeError("phase7d injected failure")

    try:
        bake_secondary_motion(
            armature,
            component,
            secondary_stage,
            default_source_bones=spline.control_bones,
            failure_hook=fail_before_swap,
        )
    except Exception as exc:
        assert "phase7d injected failure" in str(exc)
    else:
        raise AssertionError("Secondary failure injection did not fail.")

    actions = _owned_actions(secondary_stage.stage_uuid)
    tracks = _owned_tracks(armature, actions)
    assert actions == (old_action,)
    assert tracks == (old_track,)
    assert state_before == (
        len(armature.data.bones),
        len(component.artifacts),
        len(bpy.data.actions),
        len(armature.animation_data.nla_tracks),
        tuple(
            curve_object.modifiers[name].subtarget
            for name in spline.hook_modifiers
        ),
    )
    assert secondary_stage.secondary_baked
    assert armature.animation_data.action == source_action
    assert bpy.context.scene.frame_current == 6
    assert armature.mode == "POSE"
    assert active_pose_bone(armature).name == spline.control_bones[2]
    assert {obj.name for obj in bpy.context.selected_objects} == selected_objects
    assert all(
        armature.pose.bones[output_name].constraints[constraint_name].mute
        for output_name, constraint_name in zip(
            secondary.output_bones, secondary.follow_constraints
        )
    )

    # A failure immediately after the visible swap must restore the same
    # prior Action/track and live state as a pre-swap failure.
    def fail_after_swap(point):
        if point == "after_swap":
            raise RuntimeError("phase7d post-swap failure")

    try:
        bake_secondary_motion(
            armature,
            component,
            secondary_stage,
            default_source_bones=spline.control_bones,
            failure_hook=fail_after_swap,
        )
    except Exception as exc:
        assert "phase7d post-swap failure" in str(exc)
    else:
        raise AssertionError("Secondary post-swap failure did not fail.")
    assert _owned_actions(secondary_stage.stage_uuid) == (old_action,)
    assert _owned_tracks(armature, (old_action,)) == (old_track,)
    assert state_before == (
        len(armature.data.bones),
        len(component.artifacts),
        len(bpy.data.actions),
        len(armature.animation_data.nla_tracks),
        tuple(
            curve_object.modifiers[name].subtarget
            for name in spline.hook_modifiers
        ),
    )
    assert secondary_stage.secondary_baked

    # Disabling the layer removes only its owned SIM/Action/NLA artifacts and
    # restores authored Spline Hooks; the Spline itself remains usable.
    baked_action_name = first.action_name
    sim_bone_names = tuple(secondary.output_bones)
    secondary_stage.enabled = False
    compile_semantic_component(armature, component)
    assert not secondary_stage.secondary_baked
    assert not secondary_stage.secondary_source_signature
    assert bpy.data.actions.get(baked_action_name) is None
    assert not _owned_actions(secondary_stage.stage_uuid)
    assert all(name not in armature.data.bones for name in sim_bone_names)
    assert tuple(
        curve_object.modifiers[name].subtarget
        for name in spline.hook_modifiers
    ) == spline.control_bones

    print(
        "PHASE7D_SPLINE_SECONDARY_OK",
        len(spline.control_bones),
        len(curves),
        baked_action_name,
    )


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
