#!/usr/bin/env python3
"""Blender 5.1 headless regression for the standalone Semantic FK DAG node."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import uuid

import bpy


def _bone(edit_bones, name, head, tail, parent=None):
    bone = edit_bones.new(name)
    bone.head = head
    bone.tail = tail
    bone.parent = parent
    bone.use_connect = parent is not None
    return bone


def _matrix_error(left, right):
    return max(
        abs(float(a) - float(b))
        for left_row, right_row in zip(left, right)
        for a, b in zip(left_row, right_row)
    )


def _driver_count():
    count = 0
    for collection_name in ("objects", "armatures", "meshes", "curves", "shape_keys"):
        for datablock in getattr(bpy.data, collection_name):
            animation_data = getattr(datablock, "animation_data", None)
            count += len(animation_data.drivers) if animation_data else 0
    return count


def _structure(armature, component):
    return (
        len(armature.data.bones),
        sum(len(pose_bone.constraints) for pose_bone in armature.pose.bones),
        _driver_count(),
        len(component.artifacts),
    )


def _bounds(obj):
    coordinates = tuple(tuple(vertex.co) for vertex in obj.data.vertices)
    return tuple(
        max(vertex[axis] for vertex in coordinates)
        - min(vertex[axis] for vertex in coordinates)
        for axis in range(3)
    )


def _owned_widget_pair(armature, component, stage):
    from coa_tools2.rig_control.blender.semantic_presentations import (
        semantic_widget_object_role,
    )
    from coa_tools2.rig_control.blender.semantic_widgets import (
        find_semantic_widget_modifier,
    )

    objects = []
    for artifact_role in ("source", "cache"):
        role = semantic_widget_object_role(
            stage.stage_uuid, "FK_CONTROL", artifact_role
        )
        records = tuple(
            artifact
            for artifact in component.artifacts
            if artifact.role == role and artifact.data_type == "OBJECT"
        )
        assert len(records) == 1 and records[0].owned, role
        obj = bpy.data.objects[records[0].object_name]
        assert obj.get("coa_rig_component_role") == role
        assert obj.get("coa_semantic_widget_target_role") == "FK_CONTROL"
        assert obj.get("coa_semantic_widget_shape") == "ELLIPSE"
        objects.append(obj)
    source, cache = objects
    modifier = find_semantic_widget_modifier(source)
    assert modifier is not None and modifier.type == "NODES"
    assert modifier.node_group.get("coa_semantic_widget_managed")
    assert cache.data.vertices and cache.data.edges and not cache.data.polygons
    assert find_semantic_widget_modifier(cache) is None
    return source, cache, modifier


def main():
    import coa_tools2
    from coa_tools2.rig_control.blender import semantic_compiler
    from coa_tools2.rig_control.blender.semantic_compiler import (
        compile_semantic_component,
    )
    from coa_tools2.rig_control.blender.semantic_presentations import (
        compile_component_presentations,
    )
    from coa_tools2.rig_control.blender.semantic_operators import _new_input
    from coa_tools2.rig_control.blender.semantic_widgets import (
        semantic_widget_modifier_parameters,
    )

    coa_tools2.register()
    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object
    armature.name = "SemanticStandaloneFKValidation"
    bpy.ops.object.mode_set(mode="EDIT")
    bones = armature.data.edit_bones
    upper = _bone(bones, "fk_upper", (0, 0, 0), (1.0, 0.1, 0))
    lower = _bone(bones, "fk_lower", upper.tail, (2.0, -0.1, 0), upper)
    _bone(bones, "fk_hand", lower.tail, (2.65, -0.1, 0), lower)
    bpy.ops.object.mode_set(mode="POSE")

    # State Rig polls and dynamic Enum item callbacks run in Blender's
    # read-only RNA context.  They may inspect the dedicated namespace but must
    # not trigger the lazy legacy migration or resize either definition
    # collection.  The writable Update execute path performs migration.
    assert bpy.ops.coa_tools2.add_rig_control(
        "EXEC_DEFAULT",
        label="Poll Migration State",
        control_type="SLIDER_1D",
        create_initial_binding=False,
    ) == {"FINISHED"}
    rig_data = armature.coa_tools2_rig
    state_definition_counts = (
        len(rig_data.rig_controls),
        len(rig_data.rig_components),
    )
    rig_data.legacy_migration_checked = False
    assert bpy.ops.coa_tools2.update_rig_control.poll()
    assert not rig_data.legacy_migration_checked
    assert state_definition_counts == (
        len(rig_data.rig_controls),
        len(rig_data.rig_components),
    )
    from coa_tools2.rig_control.blender import operators as state_operators

    assert state_operators._binding_source_items(None, bpy.context)
    assert not rig_data.legacy_migration_checked
    assert state_definition_counts == (
        len(rig_data.rig_controls),
        len(rig_data.rig_components),
    )
    assert bpy.ops.coa_tools2.update_rig_control("EXEC_DEFAULT") == {"FINISHED"}
    assert rig_data.legacy_migration_checked
    assert state_definition_counts == (
        len(rig_data.rig_controls),
        len(rig_data.rig_components),
    )

    component = armature.coa_tools2_rig.rig_components.add()
    component.component_uuid = str(uuid.uuid4())
    component.semantic_id = "standalone.fk.validation"
    component.label = "Standalone FK Validation"
    component.component_type = "SEMANTIC"
    component.deformation_mode = "PARAMETRIC"
    for name in ("fk_upper", "fk_lower", "fk_hand"):
        reference = component.source_bones.add()
        reference.bone_name = name

    rig_data = armature.coa_tools2_rig
    rig_data.rig_components_index = len(rig_data.rig_components) - 1
    # Blender 5.1 evaluates operator poll in a read-only RNA context.  Polling
    # must discover the component without marking/migrating legacy storage;
    # the writable execute path performs that migration immediately afterward.
    semantic_definition_counts = (
        len(rig_data.rig_controls),
        len(rig_data.rig_components),
    )
    rig_data.legacy_migration_checked = False
    assert not rig_data.legacy_migration_checked
    assert bpy.ops.coa_tools2.add_semantic_stage.poll()
    assert not rig_data.legacy_migration_checked
    assert semantic_definition_counts == (
        len(rig_data.rig_controls),
        len(rig_data.rig_components),
    )
    assert bpy.ops.coa_tools2.add_semantic_stage(
        "EXEC_DEFAULT",
        stage_type="CHAIN_FK",
        label="Independent FK",
    ) == {"FINISHED"}
    assert rig_data.legacy_migration_checked
    assert semantic_definition_counts == (
        len(rig_data.rig_controls),
        len(rig_data.rig_components),
    )
    fk_stage = component.semantic_stages[-1]
    assert tuple(item.bone_name for item in fk_stage.source_bones) == (
        "fk_upper",
        "fk_lower",
        "fk_hand",
    )
    # The legacy Component operators obey the same read-only contract.  Poll
    # discovers the already-persisted component without changing migration
    # state or either top-level collection; Apply performs migration before
    # compiling the valid standalone FK stage.
    component_definition_counts = (
        len(rig_data.rig_controls),
        len(rig_data.rig_components),
    )
    rig_data.legacy_migration_checked = False
    assert bpy.ops.coa_tools2.update_rig_component.poll()
    assert not rig_data.legacy_migration_checked
    assert component_definition_counts == (
        len(rig_data.rig_controls),
        len(rig_data.rig_components),
    )
    assert bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT") == {"FINISHED"}
    assert rig_data.legacy_migration_checked
    assert component_definition_counts == (
        len(rig_data.rig_controls),
        len(rig_data.rig_components),
    )
    assert bpy.ops.coa_tools2.add_semantic_stage(
        "EXEC_DEFAULT",
        stage_type="POSE_MAP",
        label="FK Downstream",
    ) == {"FINISHED"}
    downstream = component.semantic_stages[-1]
    assert downstream.depends_on == fk_stage.stage_uuid
    downstream_input = _new_input(
        downstream,
        "fk_rotation",
        "FK Rotation",
        "ROT_Z",
    )
    downstream_input.terms[0].source_stage_uuid = fk_stage.stage_uuid

    result = compile_semantic_component(armature, component)
    fk_result = result["stage_results"][fk_stage.stage_uuid]
    assert fk_result.stage_type == "CHAIN_FK"
    output_record = next(
        item
        for item in component.artifacts
        if item.role == f"semantic:{fk_stage.stage_uuid}:fk_output"
    )
    downstream_result = result["stage_results"][downstream.stage_uuid]
    assert downstream_result.primary_control_bone == fk_result.primary_control_bone
    assert downstream_input.terms[0].source_bone == fk_result.primary_control_bone

    prefix = f"semantic:{fk_stage.stage_uuid}:"
    roles = {artifact.role for artifact in component.artifacts}
    control_names = []
    for index, source_name in enumerate(("fk_upper", "fk_lower", "fk_hand")):
        control_role = prefix + f"fk_control:{index}"
        source_role = prefix + f"source_bone:{index}"
        follow_role = prefix + f"source_presentation:{index}"
        assert {control_role, source_role, follow_role}.issubset(roles)
        record = next(item for item in component.artifacts if item.role == control_role)
        control_names.append(record.bone_name)
        source_record = next(item for item in component.artifacts if item.role == source_role)
        assert source_record.bone_name == source_name and not source_record.owned
        follow_record = next(item for item in component.artifacts if item.role == follow_role)
        constraint = armature.pose.bones[source_name].constraints[
            follow_record.constraint_name
        ]
        assert constraint.type == "COPY_TRANSFORMS"
        assert constraint.target == armature
        assert constraint.subtarget == (
            output_record.bone_name if index == 2 else record.bone_name
        )
    output_follow_record = next(
        item
        for item in component.artifacts
        if item.role == prefix + "fk_output_follow"
    )
    output_follow = armature.pose.bones[output_record.bone_name].constraints[
        output_follow_record.constraint_name
    ]
    assert output_follow.target == armature
    assert output_follow.subtarget == control_names[-1]
    assert fk_result.primary_control_bone == control_names[-1]
    assert not any("ik_" in role or ":pole_" in role for role in roles if role.startswith(prefix))

    source, cache, modifier = _owned_widget_pair(
        armature, component, fk_stage
    )
    assert all(
        armature.pose.bones[name].custom_shape == cache for name in control_names
    )
    before_structure = _structure(armature, component)
    before_bounds = _bounds(cache)
    object_pointers = (source.as_pointer(), cache.as_pointer())
    fk_stage.presentation.width *= 1.5
    compile_component_presentations(
        armature,
        component,
        only_target=(fk_stage.stage_uuid, "FK_CONTROL"),
    )
    source, cache, modifier = _owned_widget_pair(armature, component, fk_stage)
    assert _bounds(cache)[0] > before_bounds[0] + 0.1
    assert before_structure == _structure(armature, component)
    assert object_pointers == (source.as_pointer(), cache.as_pointer())

    # The standalone controls are the solver: source deformation follows them
    # without an IK constraint or hidden IK/FK switch.
    armature.pose.bones[control_names[0]].rotation_euler.z = 0.24
    armature.pose.bones[control_names[1]].rotation_euler.z = -0.37
    armature.pose.bones[control_names[2]].rotation_euler.z = 0.12
    bpy.context.view_layer.update()
    for source_name, control_name in zip(
        ("fk_upper", "fk_lower", "fk_hand"), control_names
    ):
        assert _matrix_error(
            armature.pose.bones[source_name].matrix,
            armature.pose.bones[control_name].matrix,
        ) < 1.0e-5

    # Full compile is idempotent, including a downstream semantic DAG node.
    stable = _structure(armature, component)
    result = compile_semantic_component(armature, component)
    assert stable == _structure(armature, component)
    assert (
        result["stage_results"][downstream.stage_uuid].primary_control_bone
        == control_names[-1]
    )

    # A failure after the presentation pass restores all managed geometry and
    # solver ownership; the authored width remains dirty for a later retry.
    stable_parameters = semantic_widget_modifier_parameters(modifier)
    stable_vertices = tuple(tuple(vertex.co) for vertex in cache.data.vertices)
    fk_stage.presentation.width *= 1.25
    original_outputs = semantic_compiler.reconcile_semantic_outputs

    def fail_after_presentations(*_args, **_kwargs):
        raise RuntimeError("injected standalone FK compile failure")

    semantic_compiler.reconcile_semantic_outputs = fail_after_presentations
    try:
        try:
            compile_semantic_component(armature, component)
        except RuntimeError as exc:
            assert "injected standalone FK compile failure" in str(exc)
        else:
            raise AssertionError("Injected standalone FK failure did not propagate")
    finally:
        semantic_compiler.reconcile_semantic_outputs = original_outputs
    source, cache, modifier = _owned_widget_pair(armature, component, fk_stage)
    assert stable == _structure(armature, component)
    assert stable_parameters == semantic_widget_modifier_parameters(modifier)
    assert stable_vertices == tuple(tuple(vertex.co) for vertex in cache.data.vertices)

    temporary = Path(tempfile.gettempdir()) / f"coa_phase11_fk_{uuid.uuid4().hex}.blend"
    try:
        compile_semantic_component(armature, component)
        persisted = _structure(armature, component)
        bpy.ops.wm.save_as_mainfile(filepath=str(temporary), check_existing=False)
        bpy.ops.wm.open_mainfile(filepath=str(temporary), load_ui=False)
        armature = bpy.data.objects["SemanticStandaloneFKValidation"]
        component = armature.coa_tools2_rig.rig_components[0]
        fk_stage = next(
            stage for stage in component.semantic_stages if stage.stage_type == "CHAIN_FK"
        )
        downstream = next(
            stage for stage in component.semantic_stages if stage.stage_type == "POSE_MAP"
        )
        assert downstream.depends_on == fk_stage.stage_uuid
        output_record = next(
            item
            for item in component.artifacts
            if item.role == f"semantic:{fk_stage.stage_uuid}:fk_output"
        )
        source, cache, _modifier = _owned_widget_pair(armature, component, fk_stage)
        assert all(
            armature.pose.bones[item.bone_name].custom_shape == cache
            for item in component.artifacts
            if item.role.startswith(f"semantic:{fk_stage.stage_uuid}:fk_control:")
        )
        compile_semantic_component(armature, component)
        assert persisted == _structure(armature, component)
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass

    print(
        "PHASE11_STANDALONE_FK_OK",
        len(control_names),
        before_structure,
        round(_bounds(cache)[0], 6),
    )


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
