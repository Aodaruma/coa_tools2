#!/usr/bin/env python3
"""Blender background regression for Graph State and manual lip-sync presets.

Run through the repository's clean Blender launcher.  The script deliberately
uses a temporary save path so it never embeds a developer-specific path in the
fixture or generated .blend data.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import addon_utils
import bpy


def update_scene():
    bpy.context.view_layer.update()
    bpy.context.scene.frame_set(bpy.context.scene.frame_current)
    bpy.context.view_layer.update()


def activate_armature(armature):
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="POSE")


def create_shape_target(armature, name, shape_names):
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.mesh.primitive_plane_add(size=2.0)
    target = bpy.context.active_object
    target.name = name
    target.parent = armature
    target.shape_key_add(name="Basis")
    keys = {
        shape_name: target.shape_key_add(name=shape_name)
        for shape_name in shape_names
    }
    activate_armature(armature)
    return target, keys


def create_custom_point_marker():
    mesh = bpy.data.meshes.new("Phase10CustomPointMarkerMesh")
    mesh.from_pydata(
        ((-1.0, -0.4, 0.0), (0.0, -1.0, 0.0), (1.0, -0.4, 0.0), (0.0, 1.0, 0.0)),
        ((0, 1), (1, 2), (2, 3), (3, 0), (0, 2)),
        (),
    )
    mesh.update()
    marker = bpy.data.objects.new("Phase10CustomPointMarker", mesh)
    bpy.context.scene.collection.objects.link(marker)
    marker.hide_render = True
    return marker


def assert_values(keys, expected, epsilon=2.0e-4):
    update_scene()
    for name, value in expected.items():
        actual = float(keys[name].value)
        assert abs(actual - float(value)) <= epsilon, (name, actual, value)


def transaction_state(armature, target):
    # Stabilize externally authored drivers before taking an equality snapshot.
    # Otherwise the operator invocation can be the first depsgraph evaluation,
    # making a read-only preflight appear to have changed the Shape Key value.
    update_scene()
    shape_keys = target.data.shape_keys
    animation_data = shape_keys.animation_data
    return {
        "controls": tuple(
            control.control_uuid
            for control in armature.coa_tools2_rig.rig_controls
        ),
        "bones": tuple(sorted(bone.name for bone in armature.data.bones)),
        "bone_collections": tuple(
            sorted(collection.name for collection in armature.data.collections)
        ),
        "objects": tuple(sorted(obj.name for obj in bpy.data.objects)),
        "meshes": tuple(sorted(mesh.name for mesh in bpy.data.meshes)),
        "curves": tuple(sorted(curve.name for curve in bpy.data.curves)),
        "node_groups": tuple(sorted(group.name for group in bpy.data.node_groups)),
        "collections": tuple(
            sorted(collection.name for collection in bpy.data.collections)
        ),
        "drivers": tuple(
            sorted(
                (fcurve.data_path, fcurve.driver.expression)
                for fcurve in animation_data.drivers
            )
        ) if animation_data is not None else (),
        "values": tuple(
            (key.name, float(key.value))
            for key in shape_keys.key_blocks
            if key.name != "Basis"
        ),
    }


def assert_transaction_equal(actual, expected, label):
    differences = {
        key: {"before": expected.get(key), "after": actual.get(key)}
        for key in sorted(set(actual) | set(expected))
        if actual.get(key) != expected.get(key)
    }
    assert not differences, (label, differences)


def expect_operator_rejection(operator_call, expected_message):
    """Accept Blender's two APIs for an expected ERROR-report rejection."""

    try:
        result = operator_call()
    except RuntimeError as exc:
        assert expected_message in str(exc), str(exc)
        return
    assert result == {"CANCELLED"}, result


def state_setup_snapshot(armature, control, target):
    update_scene()
    display = armature.pose.bones[control.display_bone]
    tip = armature.pose.bones[control.control_bone]

    def shape_snapshot(shape):
        return (
            shape.name,
            shape.get("coa_rig_widget_uuid", ""),
            len(shape.data.vertices),
            len(shape.data.edges),
            len(shape.data.polygons),
        ) if shape is not None else None

    return {
        "transaction": transaction_state(armature, target),
        "control": (
            control.state_mode,
            control.state_columns,
            control.state_rows,
            control.state_mix_policy,
            control.rectangle_mode,
            control.grid_columns,
            control.grid_rows,
            control.state_points_index,
            control.state_cells_index,
            control.live_preview,
            control.needs_rebuild,
            control.auto_rebuild_error,
        ),
        "points": tuple(
            (
                point.state_uuid,
                point.control_uuid,
                point.label,
                point.column,
                point.row,
                point.target_object.name if point.target_object else "",
                point.target_name,
                point.generated_data_path,
                tuple(point.graph_position),
                point.point_shape,
                point.custom_object.name if point.custom_object else "",
                point.fallback_state_uuid,
                point.is_empty,
                point.enabled,
            )
            for point in control.state_points
        ),
        "cells": tuple(
            (
                cell.cell_uuid,
                cell.control_uuid,
                cell.column,
                cell.row,
                cell.mix_enabled,
            )
            for cell in control.state_cells
        ),
        "constraints": tuple(
            (
                constraint.name,
                constraint.type,
                constraint.target.name if getattr(constraint, "target", None) else "",
            )
            for constraint in tip.constraints
        ),
        "base_shape": shape_snapshot(display.custom_shape),
        "tip_shape": shape_snapshot(tip.custom_shape),
    }


def assert_state_setup_transaction(armature, control, target):
    from coa_tools2.rig_control.blender import operators as operator_module
    from coa_tools2.rig_control.blender.states import ensure_state_driver

    control.live_preview = False
    point = control.state_points[0]
    key = target.data.shape_keys.key_blocks[point.target_name]
    assert key.driver_remove("value")
    unmanaged = key.driver_add("value")
    unmanaged.driver.type = "SCRIPTED"
    unmanaged.driver.expression = "0.375"
    before_conflict = state_setup_snapshot(armature, control, target)
    expect_operator_rejection(
        lambda: bpy.ops.coa_tools2.setup_rig_states(
            "EXEC_DEFAULT",
            mode="GRAPH_2D",
            columns=len(control.state_points),
            rows=1,
            confirm_remove_assigned=False,
        ),
        "State target has an unmanaged driver",
    )
    assert_transaction_equal(
        state_setup_snapshot(armature, control, target),
        before_conflict,
        "Setup unmanaged-driver preflight",
    )
    assert key.driver_remove("value")
    ensure_state_driver(armature, control, point)
    update_scene()

    before_fault = state_setup_snapshot(armature, control, target)
    original_compile = operator_module.compile_control

    def fail_after_compile(*args, **kwargs):
        original_compile(*args, **kwargs)
        raise RuntimeError("phase10 injected State setup failure")

    operator_module.compile_control = fail_after_compile
    try:
        expect_operator_rejection(
            lambda: bpy.ops.coa_tools2.setup_rig_states(
                "EXEC_DEFAULT",
                mode="GRAPH_2D",
                columns=len(control.state_points) - 1,
                rows=1,
                confirm_remove_assigned=True,
            ),
            "phase10 injected State setup failure",
        )
    finally:
        operator_module.compile_control = original_compile
    assert_transaction_equal(
        state_setup_snapshot(armature, control, target),
        before_fault,
        "Setup post-compile rollback",
    )


def assert_lip_add_transaction(armature):
    from coa_tools2.rig_control import LipSyncPreset, lip_sync_preset_points
    from coa_tools2.rig_control.blender import operators as operator_module

    templates = lip_sync_preset_points(LipSyncPreset.MINIMAL)
    shape_names = tuple(template.target_name_candidates[0] for template in templates)
    target, _keys = create_shape_target(
        armature,
        "Phase10LipTransactionTarget",
        shape_names,
    )

    # An unmanaged driver is rejected before a PropertyGroup or artifact is made.
    shape_keys = target.data.shape_keys
    conflict_key = shape_keys.key_blocks[shape_names[0]]
    conflict = conflict_key.driver_add("value")
    conflict.driver.type = "SCRIPTED"
    conflict.driver.expression = "0.25"
    before_conflict = transaction_state(armature, target)
    expect_operator_rejection(
        lambda: bpy.ops.coa_tools2.add_lip_sync_state_rig(
            "EXEC_DEFAULT",
            label="Rejected Lip Conflict",
            preset="MINIMAL",
            graph_interpolation="MAP_2D",
            target_object_name=target.name,
            match_existing_shape_keys=True,
        ),
        "Shape Key already has an unmanaged driver",
    )
    assert_transaction_equal(
        transaction_state(armature, target),
        before_conflict,
        "Add Lip unmanaged-driver preflight",
    )
    conflict_key.driver_remove("value")

    # Fault after a successful compile must roll back drivers and every object,
    # bone, widget datablock, and persisted definition produced by that compile.
    before_fault = transaction_state(armature, target)
    original_compile = operator_module.compile_control

    def fail_after_compile(*args, **kwargs):
        original_compile(*args, **kwargs)
        raise RuntimeError("phase10 injected post-compile failure")

    operator_module.compile_control = fail_after_compile
    try:
        expect_operator_rejection(
            lambda: bpy.ops.coa_tools2.add_lip_sync_state_rig(
                "EXEC_DEFAULT",
                label="Rolled Back Lip",
                preset="MINIMAL",
                graph_interpolation="NAMED_GRAPH",
                target_object_name=target.name,
                match_existing_shape_keys=True,
            ),
            "phase10 injected post-compile failure",
        )
    finally:
        operator_module.compile_control = original_compile
    assert_transaction_equal(
        transaction_state(armature, target),
        before_fault,
        "Add Lip post-compile rollback",
    )


def graph_expected(control, normalized_position):
    from coa_tools2.rig_control import graph_state_weights
    from coa_tools2.rig_control.blender.states import graph_state_point_specs

    return graph_state_weights(
        normalized_position[0],
        normalized_position[1],
        graph_state_point_specs(control),
        control.graph_interpolation,
        control.graph_radius,
    )


def move_graph_handle(armature, control, normalized_position):
    handle = armature.pose.bones[control.control_bone]
    handle.location.x = normalized_position[0] * control.width
    handle.location.y = normalized_position[1] * control.height
    update_scene()
    return handle


def graph_widget_source(control, custom_shape):
    widget_uuid = custom_shape.get("coa_rig_widget_uuid")
    assert widget_uuid == control.base_widget_uuid
    return next(
        obj
        for obj in bpy.data.objects
        if obj.get("coa_rig_widget_uuid") == widget_uuid
        and obj.get("coa_rig_artifact_role") == "widget_source"
    )


def assert_graph_geometry(armature, control):
    display = armature.pose.bones[control.display_bone]
    handle = armature.pose.bones[control.control_bone]
    assert display.custom_shape is not None
    assert handle.custom_shape is not None
    custom_shape = display.custom_shape
    source = graph_widget_source(control, custom_shape)
    modifiers = [
        modifier
        for modifier in source.modifiers
        if modifier.type == "NODES"
    ]
    assert modifiers and modifiers[0].node_group is not None
    assert modifiers[0].node_group.name == "COA_RigWidget_Graph_GN"
    assert modifiers[0].node_group.get("coa_rig_managed")
    assert modifiers[0].node_group.get("coa_rig_widget_family") == "GRAPH"
    enabled_count = len(
        [point for point in control.state_points if point.enabled]
    )
    shape_attribute = source.data.attributes.get("coa_graph_shape")
    assert shape_attribute is not None
    assert sum(item.value >= 0 for item in shape_attribute.data) == enabled_count
    assert len(source.data.vertices) >= enabled_count
    assert len(source.data.edges) >= 1
    if custom_shape.get("coa_rig_artifact_role") == "widget_cache":
        assert len(custom_shape.data.vertices) > 0
        assert len(custom_shape.data.edges) > 0
        assert not custom_shape.data.polygons
    return source, custom_shape


def create_arbitrary_graph(armature):
    names = ("Quiet", "Smile", "Wide", "Round")
    target, keys = create_shape_target(
        armature,
        "Phase10GraphTarget",
        names,
    )
    result = bpy.ops.coa_tools2.add_rig_control(
        "EXEC_DEFAULT",
        label="Arbitrary Mouth Graph",
        control_type="POINT_2D_RECT",
        rectangle_mode="GRAPH",
        graph_interpolation="HYBRID",
        graph_points=4,
        width=4.0,
        height=2.8,
        create_initial_binding=False,
    )
    assert result == {"FINISHED"}, result
    control = armature.coa_tools2_rig.rig_controls[-1]
    assert control.state_mode == "GRAPH_2D"
    control.live_preview = False
    control.graph_radius = 0.18

    positions = (
        (0.08, 0.18),
        (0.82, 0.12),
        (0.72, 0.88),
        (0.24, 0.74),
    )
    shapes = ("CIRCLE", "DIAMOND", "TRIANGLE", "SQUARE")
    for index, point in enumerate(control.state_points):
        point.label = names[index]
        point.graph_position = positions[index]
        point.point_shape = shapes[index]
        point.target_object = target
        point.target_name = names[index]
        point.target_name_candidates = f"{names[index]}, Mouth_{names[index]}"
        point.is_empty = False
        point.enabled = True

    # Authored directed fallbacks produce the undirected path 0-1-2-3.
    fallback_indices = (1, 2, 3, 2)
    for point, fallback_index in zip(control.state_points, fallback_indices):
        point.fallback_state_uuid = control.state_points[fallback_index].state_uuid

    result = bpy.ops.coa_tools2.update_rig_control()
    assert result == {"FINISHED"}, result
    source, custom_shape = assert_graph_geometry(armature, control)
    shape_values = tuple(
        item.value for item in source.data.attributes["coa_graph_shape"].data
    )
    assert shape_values[:4] == (0, 3, 1, 2), shape_values

    # A standard point-shape edit must rebuild production GN/cache geometry.
    standard_edge_count = len(custom_shape.data.edges)
    control.state_points[0].point_shape = "TRIANGLE"
    result = bpy.ops.coa_tools2.update_rig_control()
    assert result == {"FINISHED"}, result
    source, custom_shape = assert_graph_geometry(armature, control)
    assert source.data.attributes["coa_graph_shape"].data[0].value == 1
    assert len(custom_shape.data.edges) != standard_edge_count
    control.state_points[0].point_shape = "CIRCLE"

    # CUSTOM_OBJECT is baked as a non-destructive per-point edge overlay.
    marker = create_custom_point_marker()
    marker_hidden = marker.hide_get()
    marker_mesh = marker.data
    before_custom_edges = len(custom_shape.data.edges)
    control.state_points[3].point_shape = "CUSTOM_OBJECT"
    control.state_points[3].custom_object = marker
    result = bpy.ops.coa_tools2.update_rig_control()
    assert result == {"FINISHED"}, result
    source, custom_shape = assert_graph_geometry(armature, control)
    assert marker.data == marker_mesh
    assert marker.hide_get() == marker_hidden
    assert source.data.attributes["coa_graph_shape"].data[3].value == 4
    assert any(
        item.value
        for item in source.data.attributes["coa_graph_overlay"].data
    )
    assert len(custom_shape.data.edges) != before_custom_edges

    from coa_tools2.rig_control.blender.states import graph_state_edges

    assert graph_state_edges(control) == ((0, 1), (1, 2), (2, 3))

    # Exact named positions must be one-hot even though this is a hybrid graph.
    move_graph_handle(armature, control, positions[0])
    assert_values(
        keys,
        {"Quiet": 1.0, "Smile": 0.0, "Wide": 0.0, "Round": 0.0},
    )

    # Moving the real pose handle changes all driven weights continuously.
    near_smile = (0.70, 0.18)
    expected = graph_expected(control, near_smile)
    move_graph_handle(armature, control, near_smile)
    assert_values(keys, dict(zip(names, expected)))
    assert keys["Smile"].value > keys["Quiet"].value

    # Changing an authored fallback changes the same handle position's result.
    probe = (0.43, 0.55)
    before = graph_expected(control, probe)
    move_graph_handle(armature, control, probe)
    assert_values(keys, dict(zip(names, before)))
    control.state_points[3].fallback_state_uuid = control.state_points[0].state_uuid
    result = bpy.ops.coa_tools2.update_rig_control()
    assert result == {"FINISHED"}, result
    assert graph_state_edges(control) == ((0, 1), (0, 3), (1, 2), (2, 3))
    after = graph_expected(control, probe)
    assert max(abs(a - b) for a, b in zip(before, after)) > 1.0e-3
    move_graph_handle(armature, control, probe)
    assert_values(keys, dict(zip(names, after)))

    drivers = target.data.shape_keys.animation_data.drivers
    assert len(drivers) == len(names)
    for fcurve in drivers:
        variables = {variable.name for variable in fcurve.driver.variables}
        assert variables == {"state_x", "state_y"}, variables
        assert fcurve.driver.expression.startswith("coa_graph_state_weight(")
        assert len(fcurve.driver.expression) <= 240
    return control, target, keys


def create_lip_presets(armature, shape_key_count_before):
    expected_counts = {
        "MINIMAL": 4,
        "JP_VOWELS": 6,
        "JP_VOWELS_MBP": 7,
        "STANDARD_2D": 7,
        "ADVANCED_PHONEME": 10,
    }
    created = {}
    for preset, count in expected_counts.items():
        result = bpy.ops.coa_tools2.add_lip_sync_state_rig(
            "EXEC_DEFAULT",
            label=f"Lip {preset}",
            preset=preset,
            include_optional=False,
            graph_interpolation="MAP_2D",
            target_object_name="",
            match_existing_shape_keys=False,
        )
        assert result == {"FINISHED"}, (preset, result)
        control = armature.coa_tools2_rig.rig_controls[-1]
        assert control.state_mode == "GRAPH_2D"
        assert control.lip_sync_preset == preset
        assert len(control.state_points) == count
        assert all(point.label for point in control.state_points)
        assert all(point.target_name_candidates for point in control.state_points)
        assert all(not point.target_name for point in control.state_points)
        assert all(point.target_object is None for point in control.state_points)
        assert_graph_geometry(armature, control)

        # Manual operation is always available; no audio or handler is needed.
        handle = armature.pose.bones[control.control_bone]
        original = handle.location.copy()
        handle.location.x = min(control.width, original.x + 0.15)
        handle.location.y = min(control.height, original.y + 0.10)
        update_scene()
        assert (handle.location - original).length > 1.0e-4
        created[preset] = control.control_uuid

    result = bpy.ops.coa_tools2.add_lip_sync_state_rig(
        "EXEC_DEFAULT",
        label="Lip STANDARD_2D Optional",
        preset="STANDARD_2D",
        include_optional=True,
        graph_interpolation="HYBRID",
        target_object_name="",
        match_existing_shape_keys=False,
    )
    assert result == {"FINISHED"}, result
    optional = armature.coa_tools2_rig.rig_controls[-1]
    assert len(optional.state_points) == 10
    assert {point.label for point in optional.state_points} >= {"FV", "L", "WQ"}
    created["STANDARD_2D_OPTIONAL"] = optional.control_uuid

    from coa_tools2.rig_control import resolve_phoneme_viseme

    assert resolve_phoneme_viseme("p", "ADVANCED_PHONEME") == "MBP"
    assert resolve_phoneme_viseme("unknown", "ADVANCED_PHONEME") == "ETC"
    assert shape_key_count_before == len(
        bpy.data.objects["Phase10GraphTarget"].data.shape_keys.key_blocks
    ), "Lip presets must not create Shape Keys."
    return created


def main():
    if addon_utils.enable("coa_tools2", default_set=False, persistent=False) is None:
        raise RuntimeError("Could not enable coa_tools2.")
    assert "coa_graph_state_weight" in bpy.app.driver_namespace

    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object
    graph, target, keys = create_arbitrary_graph(armature)
    # Keep scalar/tuple snapshots before later CollectionProperty additions can
    # invalidate the Python proxy returned for this control.
    graph_uuid = str(graph.control_uuid)
    saved_positions = tuple(
        tuple(point.graph_position) for point in graph.state_points
    )
    saved_fallbacks = tuple(
        str(point.fallback_state_uuid) for point in graph.state_points
    )
    assert_state_setup_transaction(armature, graph, target)
    assert_lip_add_transaction(armature)
    lip_controls = create_lip_presets(
        armature,
        len(target.data.shape_keys.key_blocks),
    )

    # Empty preset slots are warnings, not structural validation errors.
    bpy.ops.coa_tools2.validate_rig()
    issues = [
        (issue.severity, issue.code, issue.message)
        for issue in armature.coa_tools2_rig.rig_validation_issues
    ]
    errors = [
        (issue.code, issue.message)
        for issue in armature.coa_tools2_rig.rig_validation_issues
        if issue.severity == "ERROR"
    ]
    assert not errors, errors
    warnings = [issue for issue in issues if issue[0] == "WARNING"]
    assert len(warnings) == 44, warnings
    assert all(issue[1] == "state.unassigned_point" for issue in warnings)

    temporary = tempfile.TemporaryDirectory(prefix="coa-rig-graph-lipsync-")
    blend_path = Path(temporary.name) / "graph-lipsync.blend"
    armature_name = armature.name
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    assert "coa_graph_state_weight" in bpy.app.driver_namespace

    armature = bpy.data.objects[armature_name]
    controls = {
        control.control_uuid: control
        for control in armature.coa_tools2_rig.rig_controls
    }
    graph = controls[graph_uuid]
    assert tuple(tuple(point.graph_position) for point in graph.state_points) == saved_positions
    assert tuple(point.fallback_state_uuid for point in graph.state_points) == saved_fallbacks
    assert all(point.target_name_candidates for point in graph.state_points)
    assert graph.state_points[3].point_shape == "CUSTOM_OBJECT"
    assert graph.state_points[3].custom_object is not None
    assert graph.state_points[3].custom_object.name == "Phase10CustomPointMarker"
    assert_graph_geometry(armature, graph)

    for preset, control_uuid in lip_controls.items():
        control = controls[control_uuid]
        assert control.state_mode == "GRAPH_2D"
        expected = 10 if preset in {"ADVANCED_PHONEME", "STANDARD_2D_OPTIONAL"} else {
            "MINIMAL": 4,
            "JP_VOWELS": 6,
            "JP_VOWELS_MBP": 7,
            "STANDARD_2D": 7,
        }[preset]
        assert len(control.state_points) == expected
        assert armature.pose.bones[control.control_bone].custom_shape is not None

    target = bpy.data.objects["Phase10GraphTarget"]
    keys = {key.name: key for key in target.data.shape_keys.key_blocks}
    probe = (0.61, 0.31)
    expected = graph_expected(graph, probe)
    move_graph_handle(armature, graph, probe)
    assert_values(
        keys,
        dict(zip(("Quiet", "Smile", "Wide", "Round"), expected)),
    )

    bpy.ops.coa_tools2.validate_rig()
    errors = [
        (issue.code, issue.message)
        for issue in armature.coa_tools2_rig.rig_validation_issues
        if issue.severity == "ERROR"
    ]
    assert not errors, errors
    warnings = [
        (issue.code, issue.message)
        for issue in armature.coa_tools2_rig.rig_validation_issues
        if issue.severity == "WARNING"
    ]
    assert len(warnings) == 44, warnings
    assert all(code == "state.unassigned_point" for code, _message in warnings)

    addon_utils.disable("coa_tools2", default_set=False)
    temporary.cleanup()
    print("COA rig Phase 10 Graph State / Lip Sync test OK.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"Rig Phase 10 Graph State / Lip Sync test failed: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise
