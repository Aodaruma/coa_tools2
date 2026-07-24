#!/usr/bin/env python3
"""Background Blender test for the Geometry Nodes rig-widget foundation."""

from __future__ import annotations

import math
import sys

import addon_utils
import bpy


def evaluated_bounds(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        if not mesh.vertices:
            raise AssertionError("Geometry Nodes widget produced no vertices.")
        xs = [vertex.co.x for vertex in mesh.vertices]
        return (
            min(xs),
            max(xs),
            len(mesh.vertices),
            len(mesh.edges),
            len(mesh.polygons),
        )
    finally:
        evaluated.to_mesh_clear()


def connected_component_count(mesh):
    adjacency = [set() for _vertex in mesh.vertices]
    for edge in mesh.edges:
        left, right = edge.vertices
        adjacency[left].add(right)
        adjacency[right].add(left)
    remaining = set(range(len(mesh.vertices)))
    components = 0
    while remaining:
        components += 1
        stack = [remaining.pop()]
        while stack:
            for neighbor in adjacency[stack.pop()]:
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    stack.append(neighbor)
    return components


def main():
    module = addon_utils.enable("coa_tools2", default_set=False, persistent=False)
    if module is None:
        raise RuntimeError("Could not enable coa_tools2.")

    from coa_tools2.rig_control.blender.widgets import (
        LEGACY_NODE_GROUP_NAME,
        NODE_GROUP_NAMES,
        ensure_widget,
        ensure_widget_node_group,
        ensure_widget_node_groups,
        ensure_widget_source,
    )
    from coa_tools2.rig_control.schema import (
        WidgetBackend,
        WidgetLayout,
        WidgetSpec,
    )

    groups = ensure_widget_node_groups()
    assert {group.name for group in groups.values()} == set(
        NODE_GROUP_NAMES.values()
    )
    assert len({group.as_pointer() for group in groups.values()}) == 5
    slider_group = ensure_widget_node_group(WidgetLayout.LINEAR)
    assert slider_group == groups["SLIDER"]
    assert (
        ensure_widget_node_group(WidgetLayout.CIRCLE)
        == ensure_widget_node_group(WidgetLayout.DIAL)
        == groups["RADIAL"]
    )
    assert (
        ensure_widget_node_group(WidgetLayout.RECTANGLE)
        == ensure_widget_node_group(WidgetLayout.RECTANGLE_GRID)
        == groups["RECTANGLE"]
    )
    assert ensure_widget_node_group(WidgetLayout.MATRIX) == groups["MATRIX"]

    narrow = WidgetSpec(
        widget_uuid="phase0-linear",
        layout=WidgetLayout.LINEAR,
        width=4.0,
    )
    source = ensure_widget_source(narrow, name="Phase0Linear")
    narrow_bounds = evaluated_bounds(source)
    assert narrow_bounds[2] > 0
    assert narrow_bounds[3] > 0
    assert narrow_bounds[4] == 0
    assert source.modifiers["COA Rig Widget"].node_group == groups["SLIDER"]

    wide = WidgetSpec(
        widget_uuid="phase0-linear",
        layout=WidgetLayout.LINEAR,
        width=8.0,
    )
    source_again = ensure_widget_source(wide, name="Phase0Linear")
    assert source_again == source
    wide_bounds = evaluated_bounds(source_again)
    assert wide_bounds[1] - wide_bounds[0] > narrow_bounds[1] - narrow_bounds[0]

    cache = ensure_widget(
        wide,
        name="Phase0Linear",
        backend=WidgetBackend.EVALUATED_MESH_CACHE,
    )
    assert cache.type == "MESH"
    assert len(cache.data.vertices) > 0
    assert cache.get("coa_rig_artifact_role") == "widget_cache"
    assert connected_component_count(cache.data) == 1
    assert len(cache.data.polygons) == 0

    rectangle = WidgetSpec(
        widget_uuid="phase0-rectangle",
        layout=WidgetLayout.RECTANGLE,
        width=4.0,
        height=3.0,
    )
    rectangle_cache = ensure_widget(
        rectangle,
        name="Phase0Rectangle",
        backend=WidgetBackend.EVALUATED_MESH_CACHE,
    )
    # Free mode deliberately removes the interior boundary and keeps only the
    # outside perimeter of the merged frame/node shape.
    assert connected_component_count(rectangle_cache.data) == 1
    assert len(rectangle_cache.data.polygons) == 0
    assert (
        sum(
            node.bl_idname == "GeometryNodeMeshBoolean"
            for node in groups["RECTANGLE"].nodes
        )
        == 2
    )

    grid_rectangle = WidgetSpec(
        widget_uuid="phase0-grid-rectangle",
        layout=WidgetLayout.RECTANGLE_GRID,
        width=4.0,
        height=3.0,
        columns=3,
        rows=3,
    )
    grid_cache = ensure_widget(
        grid_rectangle,
        name="Phase0GridRectangle",
        backend=WidgetBackend.EVALUATED_MESH_CACHE,
    )
    # One outside boundary plus one loop around each of the four cells.
    assert connected_component_count(grid_cache.data) == 5
    assert len(grid_cache.data.polygons) == 0

    matrix = WidgetSpec(
        widget_uuid="phase4-matrix",
        layout=WidgetLayout.MATRIX,
        width=4.0,
        height=3.0,
        columns=3,
        rows=3,
    )
    matrix_cache = ensure_widget(
        matrix,
        name="Phase4Matrix",
        backend=WidgetBackend.EVALUATED_MESH_CACHE,
    )
    # FULL mix keeps the interior free: the outside frame is one component
    # and the center state point is a separate circle, with no internal rails.
    assert connected_component_count(matrix_cache.data) == 2
    assert len(matrix_cache.data.polygons) == 0

    circle = WidgetSpec(
        widget_uuid="phase0-circle",
        layout=WidgetLayout.CIRCLE,
        radius=2.0,
    )
    circle_cache = ensure_widget(
        circle,
        name="Phase0Circle",
        backend=WidgetBackend.EVALUATED_MESH_CACHE,
    )
    assert connected_component_count(circle_cache.data) == 1
    assert len(circle_cache.data.polygons) == 0

    dial = WidgetSpec(
        widget_uuid="phase0-dial",
        layout=WidgetLayout.DIAL,
        radius=2.0,
        arc_start=-math.pi * 0.5,
        arc_end=math.pi * 0.5,
    )
    dial_cache = ensure_widget(
        dial,
        name="Phase0Dial",
        backend=WidgetBackend.EVALUATED_MESH_CACHE,
    )
    assert connected_component_count(dial_cache.data) == 1
    assert len(dial_cache.data.polygons) == 0
    assert min(vertex.co.y for vertex in dial_cache.data.vertices) > -0.5
    assert (
        sum(
            node.bl_idname == "GeometryNodeMeshBoolean"
            for node in groups["RADIAL"].nodes
        )
        == 1
    )

    tip = WidgetSpec(
        widget_uuid="phase0-tip",
        layout=WidgetLayout.TIP,
        tip_radius=0.5,
    )
    tip_source = ensure_widget_source(tip, name="Phase0Tip")
    tip_bounds = evaluated_bounds(tip_source)
    assert tip_bounds[2] > 0
    assert tip_bounds[4] == 0
    assert tip_source.modifiers["COA Rig Widget"].node_group == groups["TIP"]

    defaults = WidgetSpec(widget_uuid="phase0-defaults", layout=WidgetLayout.TIP)
    assert defaults.tip_radius == defaults.node_radius * 2.0
    assert LEGACY_NODE_GROUP_NAME not in bpy.data.node_groups

    addon_utils.disable("coa_tools2", default_set=False)
    print("COA rig widget Geometry Nodes test OK.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Rig widget test failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
