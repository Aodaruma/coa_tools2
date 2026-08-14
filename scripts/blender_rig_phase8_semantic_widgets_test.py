#!/usr/bin/env python3
"""Blender 5.1 integration regression for Semantic Rig presentations.

The test intentionally covers the public Geometry Nodes library and the
solver-independent presentation compiler in one factory-startup session.
"""

from __future__ import annotations

import math
from pathlib import Path
import sys
import tempfile
import uuid

import bpy


def _assert_close(actual, expected, epsilon=1.0e-5):
    assert abs(float(actual) - float(expected)) <= epsilon, (actual, expected)


def _evaluated_topology(obj):
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        vertices = tuple(tuple(vertex.co) for vertex in mesh.vertices)
        edges = tuple(tuple(edge.vertices) for edge in mesh.edges)
        faces = tuple(tuple(face.vertices) for face in mesh.polygons)
    finally:
        evaluated.to_mesh_clear()
    return vertices, edges, faces


def _assert_closed_edge_loop(vertices, edges, faces, label):
    assert vertices and edges, f"{label}: empty evaluated geometry"
    assert not faces, f"{label}: custom shapes must be face-free"
    assert all(
        all(math.isfinite(coordinate) for coordinate in vertex)
        for vertex in vertices
    ), f"{label}: non-finite vertex"

    adjacency = [set() for _vertex in vertices]
    for left, right in edges:
        assert left != right, f"{label}: self edge"
        adjacency[left].add(right)
        adjacency[right].add(left)
    assert all(len(neighbours) == 2 for neighbours in adjacency), (
        label,
        tuple(len(neighbours) for neighbours in adjacency),
    )

    visited = set()
    pending = [0]
    while pending:
        vertex = pending.pop()
        if vertex in visited:
            continue
        visited.add(vertex)
        pending.extend(adjacency[vertex] - visited)
    assert len(visited) == len(vertices), (
        label,
        len(visited),
        len(vertices),
    )


def _validate_all_node_groups():
    from coa_tools2.rig_control.blender.semantic_widgets import (
        SemanticWidgetShape,
        ensure_semantic_widget_modifier,
        ensure_semantic_widget_node_groups,
        semantic_widget_family,
        semantic_widget_modifier_parameters,
        semantic_widget_parameter_defaults,
    )

    groups = ensure_semantic_widget_node_groups()
    assert set(groups) == set(SemanticWidgetShape)
    prototypes = []
    for shape in SemanticWidgetShape:
        family = semantic_widget_family(shape)
        group = groups[shape]
        assert group.name == family.group_name
        assert group.get("coa_semantic_widget_shape") == shape.value
        assert group.get("coa_semantic_widget_managed")

        mesh = bpy.data.meshes.new(f"Phase8_{shape.value}_SourceMesh")
        source = bpy.data.objects.new(f"Phase8_{shape.value}_Source", mesh)
        bpy.context.scene.collection.objects.link(source)
        modifier = ensure_semantic_widget_modifier(source, shape)
        assert modifier.node_group == group
        defaults = semantic_widget_parameter_defaults(shape)
        actual = semantic_widget_modifier_parameters(modifier)
        assert set(actual) == set(defaults)
        for name, expected in defaults.items():
            _assert_close(actual[name], expected)
        if shape in {
            SemanticWidgetShape.CYLINDER_ARROW_1D,
            SemanticWidgetShape.SPHERE_ARROW_2D,
        }:
            assert defaults["Segments"] >= 96, defaults

        topology = _evaluated_topology(source)
        _assert_closed_edge_loop(*topology, shape.value)
        prototypes.append(source)

    # The node groups remain available for the integration test, but these
    # unowned probe objects must not pollute component ownership assertions.
    for source in prototypes:
        mesh = source.data
        bpy.data.objects.remove(source, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    return groups


def _new_bone(edit_bones, name, head, tail, parent=None):
    bone = edit_bones.new(name)
    bone.head = head
    bone.tail = tail
    bone.parent = parent
    bone.use_connect = parent is not None
    return bone


def _new_component(rig_data, label, source_names, stage_type, shape):
    component = rig_data.rig_components.add()
    component.component_uuid = str(uuid.uuid4())
    component.semantic_id = label.lower().replace(" ", ".")
    component.label = label
    component.component_type = "SEMANTIC"
    component.deformation_mode = "PARAMETRIC"
    for name in source_names:
        reference = component.source_bones.add()
        reference.bone_name = name

    stage = component.semantic_stages.add()
    stage.stage_uuid = str(uuid.uuid4())
    stage.semantic_id = f"{component.semantic_id}.stage"
    stage.label = f"{label} Stage"
    stage.stage_type = stage_type
    stage.order = 0
    stage.presentation.live_preview = False
    stage.presentation.shape = shape
    return component, stage


def _driver_count():
    count = 0
    for collection_name in (
        "objects",
        "armatures",
        "meshes",
        "curves",
        "shape_keys",
    ):
        for datablock in getattr(bpy.data, collection_name):
            animation_data = getattr(datablock, "animation_data", None)
            count += len(animation_data.drivers) if animation_data else 0
    return count


def _solver_counts(armature):
    return (
        len(armature.data.bones),
        sum(len(pose_bone.constraints) for pose_bone in armature.pose.bones),
        _driver_count(),
    )


def _object_bounds(obj):
    assert obj.type == "MESH" and obj.data.vertices
    coordinates = tuple(tuple(vertex.co) for vertex in obj.data.vertices)
    return tuple(
        max(vertex[axis] for vertex in coordinates)
        - min(vertex[axis] for vertex in coordinates)
        for axis in range(3)
    )


def _owned_widget_pair(armature, component, stage, target_role):
    from coa_tools2.rig_control.blender.semantic_presentations import (
        semantic_widget_object_role,
    )
    from coa_tools2.rig_control.blender.semantic_widgets import (
        find_semantic_widget_modifier,
    )

    instance_id = armature.coa_tools2_rig.rig_instance_id
    result = []
    for artifact_role in ("source", "cache"):
        role = semantic_widget_object_role(
            stage.stage_uuid,
            target_role,
            artifact_role,
        )
        artifacts = [
            artifact
            for artifact in component.artifacts
            if artifact.role == role and artifact.data_type == "OBJECT"
        ]
        assert len(artifacts) == 1, (role, len(artifacts))
        artifact = artifacts[0]
        assert artifact.owned
        obj = bpy.data.objects.get(artifact.object_name)
        assert obj is not None and obj.type == "MESH", role
        for owner in (obj, obj.data):
            assert owner.get("coa_rig_managed")
            assert owner.get("coa_rig_instance_id") == instance_id
            assert owner.get("coa_rig_component_uuid") == component.component_uuid
            assert owner.get("coa_rig_component_role") == role
        result.append(obj)
    source, cache = result
    modifier = find_semantic_widget_modifier(source)
    assert modifier is not None and modifier.type == "NODES", (
        source.name,
        tuple(
            (
                candidate.name,
                candidate.type,
                candidate.node_group.name if candidate.node_group else "",
                tuple(candidate.keys()),
            )
            for candidate in source.modifiers
        ),
    )
    assert modifier.node_group.get("coa_semantic_widget_managed")
    assert find_semantic_widget_modifier(cache) is None
    assert not cache.data.polygons
    return source, cache, modifier


def _build_semantic_components():
    from coa_tools2.rig_control.blender.semantic_compiler import (
        compile_semantic_component,
    )

    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object
    armature.name = "Phase8_SemanticWidgetRig"
    armature.coa_tools2_rig.rig_instance_id = str(uuid.uuid4())

    bpy.ops.object.mode_set(mode="EDIT")
    bones = armature.data.edit_bones
    _new_bone(bones, "projected.source", (-5, 0, 0), (-5, 0, 1))

    ik_upper = _new_bone(bones, "ik.upper", (-1, 0, 0), (-1, 0, 1))
    ik_lower = _new_bone(bones, "ik.lower", ik_upper.tail, (-0.8, 0, 2), ik_upper)
    _new_bone(bones, "ik.hand", ik_lower.tail, (-0.6, 0, 2.6), ik_lower)

    spline_root = _new_bone(bones, "spline.root", (3, 0, 0), (3, 0, 1))
    _new_bone(bones, "spline.tip", spline_root.tail, (3.2, 0, 2), spline_root)
    bpy.ops.object.mode_set(mode="POSE")

    rig_data = armature.coa_tools2_rig
    projected_component, projected_stage = _new_component(
        rig_data,
        "Projected Widget",
        ("projected.source",),
        "PROJECTED_TRANSFORM",
        "ARROW_2D",
    )
    ik_component, ik_stage = _new_component(
        rig_data,
        "IK Widget",
        ("ik.upper", "ik.lower", "ik.hand"),
        "CHAIN_IK",
        "TOMBSTONE",
    )
    ik_stage.chain_length = 2
    ik_stage.use_pole = True
    ik_stage.pole_presentation.live_preview = False
    ik_stage.pole_presentation.shape = "ELLIPSE"

    spline_component, spline_stage = _new_component(
        rig_data,
        "Spline Widget",
        ("spline.root", "spline.tip"),
        "SPLINE",
        "DIAMOND",
    )
    spline_stage.spline_control_count = 3
    spline_stage.root_pin = False
    spline_stage.tip_pin = False

    compiled = {}
    for component in (projected_component, ik_component, spline_component):
        compiled[component.component_uuid] = compile_semantic_component(
            armature,
            component,
        )
    return armature, (
        (projected_component, projected_stage, compiled[projected_component.component_uuid]),
        (ik_component, ik_stage, compiled[ik_component.component_uuid]),
        (spline_component, spline_stage, compiled[spline_component.component_uuid]),
    )


def _assert_integrated_assignments(armature, components):
    projected_component, projected_stage, projected_build = components[0]
    ik_component, ik_stage, ik_build = components[1]
    spline_component, spline_stage, spline_build = components[2]

    _source, projected_cache, _modifier = _owned_widget_pair(
        armature, projected_component, projected_stage, "PRIMARY"
    )
    projected_control = armature.pose.bones[
        projected_build["primary_control_bone"]
    ]
    assert projected_control.custom_shape == projected_cache
    assert projected_control.custom_shape_transform == armature.pose.bones[
        projected_stage.display_frame_bone
    ]

    _source, ik_cache, _modifier = _owned_widget_pair(
        armature, ik_component, ik_stage, "PRIMARY"
    )
    ik_control = armature.pose.bones[ik_build["primary_control_bone"]]
    assert ik_control.custom_shape == ik_cache
    assert ik_control.custom_shape_transform == armature.pose.bones[
        ik_stage.display_frame_bone
    ]
    _source, pole_cache, _modifier = _owned_widget_pair(
        armature, ik_component, ik_stage, "POLE"
    )
    assert armature.pose.bones[ik_stage.pole_bone].custom_shape == pole_cache

    _source, spline_cache, _modifier = _owned_widget_pair(
        armature, spline_component, spline_stage, "SPLINE_CONTROL"
    )
    spline_info = spline_build["stage_results"][spline_stage.stage_uuid].spline_info
    assert len(spline_info.control_bones) == 3
    assert all(
        armature.pose.bones[name].custom_shape == spline_cache
        for name in spline_info.control_bones
    )

    # Selecting any generated semantic control synchronizes both the owning
    # component and its active stage in the N-panel.
    from coa_tools2.rig_control.blender.component_ui import (
        sync_component_index_from_active_bone,
    )
    from coa_tools2.rig_control.blender.selection import select_pose_bone

    rig_data = armature.coa_tools2_rig
    spline_index = next(
        index
        for index, component in enumerate(rig_data.rig_components)
        if component.component_uuid == spline_component.component_uuid
    )
    select_pose_bone(
        armature,
        spline_info.control_bones[-1],
        exclusive=True,
    )
    assert sync_component_index_from_active_bone(armature, rig_data)
    assert rig_data.rig_components_index == spline_index
    assert spline_component.semantic_stages_index == 0


def _assert_visual_only_updates(armature, components):
    from coa_tools2.rig_control.blender import semantic_presentations
    from coa_tools2.rig_control.blender.semantic_presentations import (
        compile_component_presentations,
        flush_semantic_presentation_updates_now,
        semantic_widget_object_role,
    )
    from coa_tools2.rig_control.blender.semantic_widgets import (
        semantic_widget_modifier_parameters,
    )

    projected_component, stage, build = components[0]
    control = armature.pose.bones[build["primary_control_bone"]]
    display = control.custom_shape_transform
    source, cache, modifier = _owned_widget_pair(
        armature, projected_component, stage, "PRIMARY"
    )
    before_bounds = _object_bounds(cache)
    before_counts = _solver_counts(armature)
    before_roles = tuple(sorted(artifact.role for artifact in projected_component.artifacts))
    before_objects = (source.as_pointer(), cache.as_pointer())

    stage.presentation.width = 3.75
    compile_component_presentations(
        armature,
        projected_component,
        only_target=(stage.stage_uuid, "PRIMARY"),
    )
    source, cache, modifier = _owned_widget_pair(
        armature, projected_component, stage, "PRIMARY"
    )
    after_bounds = _object_bounds(cache)
    assert after_bounds[0] > before_bounds[0] + 0.5, (before_bounds, after_bounds)
    _assert_close(semantic_widget_modifier_parameters(modifier)["Width"], 3.75)
    assert _solver_counts(armature) == before_counts
    assert control.custom_shape_transform == display
    assert (source.as_pointer(), cache.as_pointer()) == before_objects
    assert tuple(sorted(artifact.role for artifact in projected_component.artifacts)) == before_roles

    # Reapplying the same visual state is idempotent and never rebuilds the
    # mechanism graph.
    compile_component_presentations(
        armature,
        projected_component,
        only_target=(stage.stage_uuid, "PRIMARY"),
    )
    source, cache, _modifier = _owned_widget_pair(
        armature, projected_component, stage, "PRIMARY"
    )
    assert _solver_counts(armature) == before_counts
    assert (source.as_pointer(), cache.as_pointer()) == before_objects
    assert tuple(sorted(artifact.role for artifact in projected_component.artifacts)) == before_roles

    # A failed cache synchronization must restore the existing source modifier,
    # baked cache geometry, assignment, and artifact set.
    stable_parameters = semantic_widget_modifier_parameters(modifier)
    stable_vertices = tuple(tuple(vertex.co) for vertex in cache.data.vertices)
    stable_shape = control.custom_shape
    stage.presentation.width = 4.5
    original_sync = semantic_presentations._sync_widget_cache

    def fail_after_sync(*args, **kwargs):
        original_sync(*args, **kwargs)
        raise RuntimeError("injected Phase 8 presentation failure")

    semantic_presentations._sync_widget_cache = fail_after_sync
    try:
        try:
            compile_component_presentations(
                armature,
                projected_component,
                only_target=(stage.stage_uuid, "PRIMARY"),
            )
        except Exception as exc:
            assert "injected Phase 8 presentation failure" in str(exc), str(exc)
        else:
            raise AssertionError("Injected presentation failure did not propagate")
    finally:
        semantic_presentations._sync_widget_cache = original_sync
    source, cache, modifier = _owned_widget_pair(
        armature, projected_component, stage, "PRIMARY"
    )
    assert semantic_widget_modifier_parameters(modifier) == stable_parameters
    assert tuple(tuple(vertex.co) for vertex in cache.data.vertices) == stable_vertices
    assert control.custom_shape == stable_shape == cache
    assert control.custom_shape_transform == display
    assert _solver_counts(armature) == before_counts
    assert tuple(sorted(artifact.role for artifact in projected_component.artifacts)) == before_roles

    # Reconcile the authored value after the deliberate failure.
    compile_component_presentations(
        armature,
        projected_component,
        only_target=(stage.stage_uuid, "PRIMARY"),
    )
    _source, _cache, modifier = _owned_widget_pair(
        armature, projected_component, stage, "PRIMARY"
    )
    _assert_close(semantic_widget_modifier_parameters(modifier)["Width"], 4.5)

    # A later full-component failure must not commit the presentation UI
    # state.  The generated geometry and modifier are rolled back, while the
    # authored definition stays dirty so the user can retry it.
    from coa_tools2.rig_control.blender import semantic_compiler
    from coa_tools2.rig_control.blender.component_compiler import compile_component

    stable_parameters = semantic_widget_modifier_parameters(modifier)
    stage.presentation.width = 4.8
    stage.presentation.last_error = "pending presentation retry"
    assert stage.presentation.needs_rebuild
    original_outputs = semantic_compiler.reconcile_semantic_outputs

    def fail_after_presentations(*_args, **_kwargs):
        raise RuntimeError("injected Phase 8 post-presentation failure")

    semantic_compiler.reconcile_semantic_outputs = fail_after_presentations
    try:
        try:
            compile_component(armature, projected_component)
        except Exception as exc:
            assert "injected Phase 8 post-presentation failure" in str(exc), str(exc)
        else:
            raise AssertionError("Post-presentation failure did not propagate")
    finally:
        semantic_compiler.reconcile_semantic_outputs = original_outputs
    _source, _cache, modifier = _owned_widget_pair(
        armature, projected_component, stage, "PRIMARY"
    )
    assert semantic_widget_modifier_parameters(modifier) == stable_parameters
    assert stage.presentation.needs_rebuild
    assert stage.presentation.last_error == "pending presentation retry"
    compile_component(armature, projected_component)
    _source, _cache, modifier = _owned_widget_pair(
        armature, projected_component, stage, "PRIMARY"
    )
    _assert_close(semantic_widget_modifier_parameters(modifier)["Width"], 4.8)
    assert not stage.presentation.needs_rebuild
    assert stage.presentation.last_error == ""

    generated_roles = {
        semantic_widget_object_role(stage.stage_uuid, "PRIMARY", "source"),
        semantic_widget_object_role(stage.stage_uuid, "PRIMARY", "cache"),
    }
    generated_names = {source.name, cache.name}
    custom_mesh = bpy.data.meshes.new("Phase8_CustomShapeMesh")
    custom_mesh.from_pydata(
        ((-1, 0, 0), (1, 0, 0), (0, 0, 1)),
        ((0, 1), (1, 2), (2, 0)),
        (),
    )
    custom_shape = bpy.data.objects.new("Phase8_CustomShape", custom_mesh)
    bpy.context.scene.collection.objects.link(custom_shape)
    stage.presentation.custom_object = custom_shape
    stage.presentation.shape = "CUSTOM_OBJECT"
    compile_component_presentations(
        armature,
        projected_component,
        only_target=(stage.stage_uuid, "PRIMARY"),
    )
    assert control.custom_shape == custom_shape
    assert not generated_roles.intersection(
        artifact.role for artifact in projected_component.artifacts
    )
    assert all(bpy.data.objects.get(name) is None for name in generated_names)

    stage.presentation.shape = "NONE"
    compile_component_presentations(
        armature,
        projected_component,
        only_target=(stage.stage_uuid, "PRIMARY"),
    )
    assert control.custom_shape is None
    assert bpy.data.objects.get(custom_shape.name) == custom_shape
    assert _solver_counts(armature) == before_counts

    # Live Preview schedules only a presentation refresh.  It recreates the
    # generated pair and leaves the solver counts untouched.
    stage.presentation.shape = "RECTANGLE"
    stage.presentation.width = 3.2
    stage.presentation.height = 1.6
    stage.presentation.live_preview = True
    assert stage.presentation.needs_rebuild
    flush_semantic_presentation_updates_now()
    source, cache, modifier = _owned_widget_pair(
        armature, projected_component, stage, "PRIMARY"
    )
    assert not stage.presentation.needs_rebuild
    assert control.custom_shape == cache
    assert control.custom_shape_transform == display
    assert modifier.node_group.get("coa_semantic_widget_shape") == "RECTANGLE"
    _assert_close(semantic_widget_modifier_parameters(modifier)["Width"], 3.2)
    assert _solver_counts(armature) == before_counts


def _assert_manual_apply_targets_one_presentation(armature, components):
    """The panel's hidden operator properties must isolate PRIMARY from POLE."""

    ik_component, stage, _build = components[1]
    rig_data = armature.coa_tools2_rig
    rig_data.rig_components_index = next(
        index
        for index, component in enumerate(rig_data.rig_components)
        if component.component_uuid == ik_component.component_uuid
    )
    primary_source, _primary_cache, primary_modifier = _owned_widget_pair(
        armature, ik_component, stage, "PRIMARY"
    )
    _pole_source, pole_cache, _pole_modifier = _owned_widget_pair(
        armature, ik_component, stage, "POLE"
    )
    stable_pole_shape = armature.pose.bones[stage.pole_bone].custom_shape
    assert stable_pole_shape == pole_cache

    stage.presentation.width = 2.85
    stage.pole_presentation.shape = "CUSTOM_OBJECT"
    stage.pole_presentation.custom_object = None
    assert stage.presentation.needs_rebuild
    assert stage.pole_presentation.needs_rebuild

    result = bpy.ops.coa_tools2.update_rig_presentation(
        stage_uuid=stage.stage_uuid,
        target_role="PRIMARY",
    )
    assert result == {"FINISHED"}, result
    assert not stage.presentation.needs_rebuild
    assert stage.pole_presentation.needs_rebuild
    assert armature.pose.bones[stage.pole_bone].custom_shape == stable_pole_shape
    primary_modifier = primary_source.modifiers.get(primary_modifier.name)
    assert primary_modifier is not None
    from coa_tools2.rig_control.blender.semantic_widgets import (
        semantic_widget_modifier_parameters,
    )

    _assert_close(semantic_widget_modifier_parameters(primary_modifier)["Width"], 2.85)

    try:
        bpy.ops.coa_tools2.update_rig_presentation(
            stage_uuid=stage.stage_uuid,
            target_role="POLE",
        )
    except RuntimeError as exc:
        assert "custom presentation object is required" in str(exc).lower(), str(exc)
    else:
        raise AssertionError("Invalid POLE presentation unexpectedly applied")
    assert stage.pole_presentation.needs_rebuild
    assert armature.pose.bones[stage.pole_bone].custom_shape == stable_pole_shape

    stage.pole_presentation.shape = "ELLIPSE"
    result = bpy.ops.coa_tools2.update_rig_presentation(
        stage_uuid=stage.stage_uuid,
        target_role="POLE",
    )
    assert result == {"FINISHED"}, result
    assert not stage.pole_presentation.needs_rebuild


def _save_reload_persistence(armature):
    from coa_tools2.rig_control.blender.semantic_presentations import (
        compile_component_presentations,
    )
    from coa_tools2.rig_control.blender.semantic_widgets import (
        find_semantic_widget_modifier,
        semantic_widget_modifier_parameters,
    )

    temporary = Path(tempfile.gettempdir()) / f"coa_phase8_{uuid.uuid4().hex}.blend"
    try:
        bpy.ops.wm.save_as_mainfile(filepath=str(temporary), check_existing=False)
        bpy.ops.wm.open_mainfile(filepath=str(temporary))

        armature = bpy.data.objects["Phase8_SemanticWidgetRig"]
        components = {
            component.semantic_id: component
            for component in armature.coa_tools2_rig.rig_components
        }
        projected = components["projected.widget"]
        stage = projected.semantic_stages[0]
        assert stage.presentation.shape == "RECTANGLE"
        assert stage.presentation.live_preview
        _assert_close(stage.presentation.width, 3.2)
        _assert_close(stage.presentation.height, 1.6)
        control = armature.pose.bones[stage.control_bone]
        assert control.custom_shape is not None
        assert control.custom_shape_transform == armature.pose.bones[
            stage.display_frame_bone
        ]
        source, cache, modifier = _owned_widget_pair(
            armature, projected, stage, "PRIMARY"
        )
        assert control.custom_shape == cache
        assert modifier.node_group.get("coa_semantic_widget_shape") == "RECTANGLE"
        _assert_close(semantic_widget_modifier_parameters(modifier)["Width"], 3.2)

        ik_component = components["ik.widget"]
        ik_stage = ik_component.semantic_stages[0]
        assert ik_stage.presentation.shape == "TOMBSTONE"
        assert ik_stage.pole_presentation.shape == "ELLIPSE"
        _source, primary_cache, _modifier = _owned_widget_pair(
            armature, ik_component, ik_stage, "PRIMARY"
        )
        _source, pole_cache, _modifier = _owned_widget_pair(
            armature, ik_component, ik_stage, "POLE"
        )
        assert armature.pose.bones[ik_stage.control_bone].custom_shape == primary_cache
        assert armature.pose.bones[ik_stage.pole_bone].custom_shape == pole_cache

        spline_component = components["spline.widget"]
        spline_stage = spline_component.semantic_stages[0]
        assert spline_stage.presentation.shape == "DIAMOND"
        _source, spline_cache, _modifier = _owned_widget_pair(
            armature, spline_component, spline_stage, "SPLINE_CONTROL"
        )
        spline_control_names = tuple(
            artifact.bone_name
            for artifact in spline_component.artifacts
            if artifact.role.startswith(
                f"semantic:{spline_stage.stage_uuid}:spline_control:"
            )
            and artifact.data_type == "BONE"
        )
        assert len(spline_control_names) == 3
        assert all(
            armature.pose.bones[name].custom_shape == spline_cache
            for name in spline_control_names
        )

        counts = _solver_counts(armature)
        object_pointers = (source.as_pointer(), cache.as_pointer())
        compile_component_presentations(
            armature,
            projected,
            only_target=(stage.stage_uuid, "PRIMARY"),
        )
        source, cache, _modifier = _owned_widget_pair(
            armature, projected, stage, "PRIMARY"
        )
        assert _solver_counts(armature) == counts
        assert (source.as_pointer(), cache.as_pointer()) == object_pointers
    finally:
        if temporary.exists():
            temporary.unlink()


def main():
    import coa_tools2

    coa_tools2.register()
    groups = _validate_all_node_groups()
    armature, components = _build_semantic_components()
    _assert_integrated_assignments(armature, components)
    _assert_manual_apply_targets_one_presentation(armature, components)
    _assert_visual_only_updates(armature, components)
    _save_reload_persistence(armature)
    print(
        "PHASE8_SEMANTIC_WIDGETS_OK",
        len(groups),
        len(bpy.data.node_groups),
        len(bpy.data.objects),
    )


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
