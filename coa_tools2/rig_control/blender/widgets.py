"""Geometry Nodes based custom-shape widget generation."""

from __future__ import annotations

import math
from typing import Any

import bpy

from ..schema import WidgetBackend, WidgetLayout, WidgetSpec


NODE_GROUP_NAME = "COA_RigWidget_GN"
WIDGET_COLLECTION_NAME = "COA Rig Widgets"
NODE_GROUP_VERSION = 4
_BOOLEAN_SOLID_DEPTH = 0.1

_LAYOUT_VALUES = {
    WidgetLayout.TIP: 0,
    WidgetLayout.LINEAR: 1,
    WidgetLayout.RECTANGLE: 2,
    WidgetLayout.CIRCLE: 3,
    WidgetLayout.DIAL: 4,
    WidgetLayout.RECTANGLE_GRID: 5,
}


def ensure_widget_collection(scene: bpy.types.Scene | None = None):
    scene = scene or bpy.context.scene
    collection = bpy.data.collections.get(WIDGET_COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(WIDGET_COLLECTION_NAME)
    if collection.name not in {child.name for child in scene.collection.children}:
        scene.collection.children.link(collection)
    collection.hide_render = True
    return collection


def _new_interface_socket(node_group, name, in_out, socket_type, default=None):
    socket = node_group.interface.new_socket(
        name=name,
        in_out=in_out,
        socket_type=socket_type,
    )
    if default is not None and hasattr(socket, "default_value"):
        socket.default_value = default
    return socket


def _math_node(nodes, operation, label):
    node = nodes.new("ShaderNodeMath")
    node.operation = operation
    node.label = label
    return node


def _circle_mesh(nodes, links, radius_socket, stroke_socket, label):
    path = nodes.new("GeometryNodeCurvePrimitiveCircle")
    path.mode = "RADIUS"
    path.label = f"{label} Path"
    path.inputs["Resolution"].default_value = 32
    links.new(radius_socket, path.inputs["Radius"])

    profile = nodes.new("GeometryNodeCurvePrimitiveCircle")
    profile.mode = "RADIUS"
    profile.label = f"{label} Profile"
    profile.inputs["Resolution"].default_value = 6
    links.new(stroke_socket, profile.inputs["Radius"])

    curve_to_mesh = nodes.new("GeometryNodeCurveToMesh")
    curve_to_mesh.label = label
    links.new(path.outputs["Curve"], curve_to_mesh.inputs["Curve"])
    links.new(profile.outputs["Curve"], curve_to_mesh.inputs["Profile Curve"])
    return curve_to_mesh.outputs["Mesh"]


def _arc_mesh(
    nodes,
    links,
    radius_socket,
    start_socket,
    end_socket,
    stroke_socket,
    label,
):
    start_angle = _math_node(nodes, "ADD", f"{label} Start Angle")
    start_angle.inputs[1].default_value = math.pi * 0.5
    links.new(start_socket, start_angle.inputs[0])
    sweep_angle = _math_node(nodes, "SUBTRACT", f"{label} Sweep Angle")
    links.new(end_socket, sweep_angle.inputs[0])
    links.new(start_socket, sweep_angle.inputs[1])

    path = nodes.new("GeometryNodeCurveArc")
    path.mode = "RADIUS"
    path.label = f"{label} Path"
    path.inputs["Resolution"].default_value = 64
    links.new(radius_socket, path.inputs["Radius"])
    links.new(start_angle.outputs[0], path.inputs["Start Angle"])
    links.new(sweep_angle.outputs[0], path.inputs["Sweep Angle"])

    profile = nodes.new("GeometryNodeCurvePrimitiveCircle")
    profile.mode = "RADIUS"
    profile.label = f"{label} Profile"
    profile.inputs["Resolution"].default_value = 6
    links.new(stroke_socket, profile.inputs["Radius"])

    curve_to_mesh = nodes.new("GeometryNodeCurveToMesh")
    curve_to_mesh.label = label
    links.new(path.outputs["Curve"], curve_to_mesh.inputs["Curve"])
    links.new(profile.outputs["Curve"], curve_to_mesh.inputs["Profile Curve"])
    return curve_to_mesh.outputs["Mesh"]


def _solid_box_mesh(
    nodes,
    links,
    width_socket,
    height_socket,
    label,
):
    size = nodes.new("ShaderNodeCombineXYZ")
    size.label = f"{label} Size"
    links.new(width_socket, size.inputs["X"])
    links.new(height_socket, size.inputs["Y"])
    size.inputs["Z"].default_value = _BOOLEAN_SOLID_DEPTH

    box = nodes.new("GeometryNodeMeshCube")
    box.label = label
    links.new(size.outputs["Vector"], box.inputs["Size"])
    return box.outputs["Mesh"]


def _solid_circle_mesh(nodes, links, radius_socket, label):
    cylinder = nodes.new("GeometryNodeMeshCylinder")
    cylinder.label = label
    cylinder.inputs["Vertices"].default_value = 32
    cylinder.inputs["Side Segments"].default_value = 1
    cylinder.inputs["Fill Segments"].default_value = 1
    links.new(radius_socket, cylinder.inputs["Radius"])
    cylinder.inputs["Depth"].default_value = _BOOLEAN_SOLID_DEPTH
    return cylinder.outputs["Mesh"]


def _compare_input(node, name, socket_type):
    return next(
        socket
        for socket in node.inputs
        if socket.name == name and socket.type == socket_type
    )


def _union_outline_mesh(nodes, links, geometries, stroke_socket, label):
    boolean = nodes.new("GeometryNodeMeshBoolean")
    boolean.operation = "UNION"
    boolean.solver = "EXACT"
    boolean.label = f"{label} Union"
    mesh_input = next(
        socket
        for socket in boolean.inputs
        if socket.type == "GEOMETRY"
        and socket.is_multi_input
        and socket.enabled
    )
    for geometry in geometries:
        links.new(geometry, mesh_input)

    position = nodes.new("GeometryNodeInputPosition")
    position.label = f"{label} Position"
    separate_position = nodes.new("ShaderNodeSeparateXYZ")
    separate_position.label = f"{label} Separate Position"
    links.new(position.outputs["Position"], separate_position.inputs["Vector"])

    is_top = nodes.new("FunctionNodeCompare")
    is_top.data_type = "FLOAT"
    is_top.operation = "GREATER_THAN"
    is_top.label = f"{label} Top Faces"
    links.new(
        separate_position.outputs["Z"],
        _compare_input(is_top, "A", "VALUE"),
    )
    _compare_input(is_top, "B", "VALUE").default_value = (
        _BOOLEAN_SOLID_DEPTH * 0.25
    )

    top_surface = nodes.new("GeometryNodeSeparateGeometry")
    top_surface.domain = "FACE"
    top_surface.label = f"{label} Top Surface"
    links.new(boolean.outputs["Mesh"], top_surface.inputs["Geometry"])
    links.new(is_top.outputs["Result"], top_surface.inputs["Selection"])

    edge_neighbors = nodes.new("GeometryNodeInputMeshEdgeNeighbors")
    edge_neighbors.label = f"{label} Edge Neighbors"
    is_boundary = nodes.new("FunctionNodeCompare")
    is_boundary.data_type = "INT"
    is_boundary.operation = "EQUAL"
    is_boundary.label = f"{label} Boundary Edges"
    links.new(
        edge_neighbors.outputs["Face Count"],
        _compare_input(is_boundary, "A", "INT"),
    )
    _compare_input(is_boundary, "B", "INT").default_value = 1

    boundary = nodes.new("GeometryNodeMeshToCurve")
    boundary.label = f"{label} Boundary"
    links.new(top_surface.outputs["Selection"], boundary.inputs["Mesh"])
    links.new(is_boundary.outputs["Result"], boundary.inputs["Selection"])

    profile = nodes.new("GeometryNodeCurvePrimitiveCircle")
    profile.mode = "RADIUS"
    profile.label = f"{label} Profile"
    profile.inputs["Resolution"].default_value = 6
    links.new(stroke_socket, profile.inputs["Radius"])

    curve_to_mesh = nodes.new("GeometryNodeCurveToMesh")
    curve_to_mesh.label = label
    links.new(boundary.outputs["Curve"], curve_to_mesh.inputs["Curve"])
    links.new(profile.outputs["Curve"], curve_to_mesh.inputs["Profile Curve"])
    return curve_to_mesh.outputs["Mesh"]


def _translated_geometry(
    nodes,
    links,
    geometry_socket,
    x_socket,
    label,
    y_socket=None,
):
    combine = nodes.new("ShaderNodeCombineXYZ")
    combine.label = f"{label} Translation"
    if x_socket is not None:
        links.new(x_socket, combine.inputs["X"])
    if y_socket is not None:
        links.new(y_socket, combine.inputs["Y"])

    transform = nodes.new("GeometryNodeTransform")
    transform.label = label
    links.new(geometry_socket, transform.inputs["Geometry"])
    links.new(combine.outputs["Vector"], transform.inputs["Translation"])
    return transform.outputs["Geometry"]


def _grid_bar_instances(
    nodes,
    links,
    instance_geometry,
    count_socket,
    span_socket,
    negative_half_span_socket,
    axis,
    label,
):
    step_count = _math_node(nodes, "SUBTRACT", f"{label} Step Count")
    step_count.inputs[1].default_value = 1.0
    links.new(count_socket, step_count.inputs[0])
    spacing = _math_node(nodes, "DIVIDE", f"{label} Spacing")
    links.new(span_socket, spacing.inputs[0])
    links.new(step_count.outputs[0], spacing.inputs[1])

    start = nodes.new("ShaderNodeCombineXYZ")
    start.label = f"{label} Start"
    offset = nodes.new("ShaderNodeCombineXYZ")
    offset.label = f"{label} Offset"
    links.new(negative_half_span_socket, start.inputs[axis])
    links.new(spacing.outputs[0], offset.inputs[axis])

    points = nodes.new("GeometryNodeMeshLine")
    points.mode = "OFFSET"
    points.label = f"{label} Points"
    links.new(count_socket, points.inputs["Count"])
    links.new(start.outputs["Vector"], points.inputs["Start Location"])
    links.new(offset.outputs["Vector"], points.inputs["Offset"])

    instances = nodes.new("GeometryNodeInstanceOnPoints")
    instances.label = label
    links.new(points.outputs["Mesh"], instances.inputs["Points"])
    links.new(instance_geometry, instances.inputs["Instance"])

    realize = nodes.new("GeometryNodeRealizeInstances")
    realize.label = f"{label} Realized"
    links.new(instances.outputs["Instances"], realize.inputs["Geometry"])
    return realize.outputs["Geometry"]


def ensure_widget_node_group():
    existing = bpy.data.node_groups.get(NODE_GROUP_NAME)
    if existing is not None and existing.get("coa_rig_widget_version") == NODE_GROUP_VERSION:
        return existing
    if existing is not None:
        if existing.users:
            existing.name = f"{NODE_GROUP_NAME}_legacy"
        else:
            bpy.data.node_groups.remove(existing)

    node_group = bpy.data.node_groups.new(NODE_GROUP_NAME, "GeometryNodeTree")
    node_group["coa_rig_managed"] = True
    node_group["coa_rig_widget_version"] = NODE_GROUP_VERSION

    _new_interface_socket(node_group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    _new_interface_socket(node_group, "Layout", "INPUT", "NodeSocketInt", 0)
    _new_interface_socket(node_group, "Width", "INPUT", "NodeSocketFloat", 4.0)
    _new_interface_socket(node_group, "Height", "INPUT", "NodeSocketFloat", 2.0)
    _new_interface_socket(node_group, "Radius", "INPUT", "NodeSocketFloat", 2.0)
    _new_interface_socket(node_group, "Tip Radius", "INPUT", "NodeSocketFloat", 0.28)
    _new_interface_socket(node_group, "Node Radius", "INPUT", "NodeSocketFloat", 0.34)
    _new_interface_socket(node_group, "Bar Width", "INPUT", "NodeSocketFloat", 0.28)
    _new_interface_socket(node_group, "Stroke Radius", "INPUT", "NodeSocketFloat", 0.035)
    _new_interface_socket(node_group, "Columns", "INPUT", "NodeSocketInt", 2)
    _new_interface_socket(node_group, "Rows", "INPUT", "NodeSocketInt", 2)
    _new_interface_socket(
        node_group,
        "Arc Start",
        "INPUT",
        "NodeSocketFloat",
        -math.pi * 0.5,
    )
    _new_interface_socket(
        node_group,
        "Arc End",
        "INPUT",
        "NodeSocketFloat",
        math.pi * 0.5,
    )

    nodes = node_group.nodes
    links = node_group.links
    group_input = nodes.new("NodeGroupInput")
    group_input.location = (-900, 0)
    group_output = nodes.new("NodeGroupOutput")
    group_output.location = (900, 0)

    tip_geometry = _circle_mesh(
        nodes,
        links,
        group_input.outputs["Tip Radius"],
        group_input.outputs["Stroke Radius"],
        "Tip",
    )

    bar_geometry = _solid_box_mesh(
        nodes,
        links,
        group_input.outputs["Width"],
        group_input.outputs["Bar Width"],
        "Linear Bar",
    )

    endpoint_geometry = _solid_circle_mesh(
        nodes,
        links,
        group_input.outputs["Node Radius"],
        "Endpoint",
    )
    half_width = _math_node(nodes, "MULTIPLY", "Half Width")
    half_width.inputs[1].default_value = 0.5
    links.new(group_input.outputs["Width"], half_width.inputs[0])
    negative_half_width = _math_node(nodes, "MULTIPLY", "Negative Half Width")
    negative_half_width.inputs[1].default_value = -0.5
    links.new(group_input.outputs["Width"], negative_half_width.inputs[0])

    left_endpoint = _translated_geometry(
        nodes,
        links,
        endpoint_geometry,
        negative_half_width.outputs[0],
        "Left Endpoint",
    )
    right_endpoint = _translated_geometry(
        nodes,
        links,
        endpoint_geometry,
        half_width.outputs[0],
        "Right Endpoint",
    )
    linear_geometry = _union_outline_mesh(
        nodes,
        links,
        (bar_geometry, left_endpoint, right_endpoint),
        group_input.outputs["Stroke Radius"],
        "Linear Widget",
    )

    horizontal_bar = _solid_box_mesh(
        nodes,
        links,
        group_input.outputs["Width"],
        group_input.outputs["Bar Width"],
        "Rectangle Horizontal Bar",
    )
    vertical_bar = _solid_box_mesh(
        nodes,
        links,
        group_input.outputs["Bar Width"],
        group_input.outputs["Height"],
        "Rectangle Vertical Bar",
    )
    half_height = _math_node(nodes, "MULTIPLY", "Half Height")
    half_height.inputs[1].default_value = 0.5
    links.new(group_input.outputs["Height"], half_height.inputs[0])
    negative_half_height = _math_node(nodes, "MULTIPLY", "Negative Half Height")
    negative_half_height.inputs[1].default_value = -0.5
    links.new(group_input.outputs["Height"], negative_half_height.inputs[0])
    rectangle_parts = []
    for label, y_socket in (
        ("Bottom Bar", negative_half_height.outputs[0]),
        ("Top Bar", half_height.outputs[0]),
    ):
        rectangle_parts.append(
            _translated_geometry(
                nodes,
                links,
                horizontal_bar,
                None,
                label,
                y_socket,
            )
        )
    for label, x_socket in (
        ("Left Bar", negative_half_width.outputs[0]),
        ("Right Bar", half_width.outputs[0]),
    ):
        rectangle_parts.append(
            _translated_geometry(
                nodes,
                links,
                vertical_bar,
                x_socket,
                label,
            )
        )
    for label, x_socket, y_socket in (
        (
            "Bottom Left",
            negative_half_width.outputs[0],
            negative_half_height.outputs[0],
        ),
        ("Bottom Right", half_width.outputs[0], negative_half_height.outputs[0]),
        ("Top Left", negative_half_width.outputs[0], half_height.outputs[0]),
        ("Top Right", half_width.outputs[0], half_height.outputs[0]),
    ):
        corner = _translated_geometry(
            nodes,
            links,
            endpoint_geometry,
            x_socket,
            label,
            y_socket,
        )
        rectangle_parts.append(corner)
    rectangle_geometry = _union_outline_mesh(
        nodes,
        links,
        rectangle_parts,
        group_input.outputs["Stroke Radius"],
        "Rectangle Widget",
    )
    grid_vertical_bars = _grid_bar_instances(
        nodes,
        links,
        vertical_bar,
        group_input.outputs["Columns"],
        group_input.outputs["Width"],
        negative_half_width.outputs[0],
        "X",
        "Grid Vertical Bars",
    )
    grid_horizontal_bars = _grid_bar_instances(
        nodes,
        links,
        horizontal_bar,
        group_input.outputs["Rows"],
        group_input.outputs["Height"],
        negative_half_height.outputs[0],
        "Y",
        "Grid Horizontal Bars",
    )
    grid_rectangle_geometry = _union_outline_mesh(
        nodes,
        links,
        (grid_vertical_bars, grid_horizontal_bars, *rectangle_parts[-4:]),
        group_input.outputs["Stroke Radius"],
        "Grid Rectangle Widget",
    )

    circle_geometry = _circle_mesh(
        nodes,
        links,
        group_input.outputs["Radius"],
        group_input.outputs["Stroke Radius"],
        "Circle Widget",
    )
    dial_geometry = _arc_mesh(
        nodes,
        links,
        group_input.outputs["Radius"],
        group_input.outputs["Arc Start"],
        group_input.outputs["Arc End"],
        group_input.outputs["Stroke Radius"],
        "Dial Widget",
    )

    is_linear = _math_node(nodes, "COMPARE", "Layout Is Linear")
    is_linear.inputs[1].default_value = float(_LAYOUT_VALUES[WidgetLayout.LINEAR])
    is_linear.inputs[2].default_value = 0.1
    links.new(group_input.outputs["Layout"], is_linear.inputs[0])

    layout_switch = nodes.new("GeometryNodeSwitch")
    layout_switch.input_type = "GEOMETRY"
    layout_switch.label = "Select Linear"
    links.new(is_linear.outputs[0], layout_switch.inputs["Switch"])
    links.new(tip_geometry, layout_switch.inputs["False"])
    links.new(linear_geometry, layout_switch.inputs["True"])

    is_rectangle = _math_node(nodes, "COMPARE", "Layout Is Rectangle")
    is_rectangle.inputs[1].default_value = float(
        _LAYOUT_VALUES[WidgetLayout.RECTANGLE]
    )
    is_rectangle.inputs[2].default_value = 0.1
    links.new(group_input.outputs["Layout"], is_rectangle.inputs[0])
    rectangle_switch = nodes.new("GeometryNodeSwitch")
    rectangle_switch.input_type = "GEOMETRY"
    rectangle_switch.label = "Select Rectangle"
    links.new(is_rectangle.outputs[0], rectangle_switch.inputs["Switch"])
    links.new(layout_switch.outputs["Output"], rectangle_switch.inputs["False"])
    links.new(rectangle_geometry, rectangle_switch.inputs["True"])

    is_circle = _math_node(nodes, "COMPARE", "Layout Is Circle")
    is_circle.inputs[1].default_value = float(_LAYOUT_VALUES[WidgetLayout.CIRCLE])
    is_circle.inputs[2].default_value = 0.1
    links.new(group_input.outputs["Layout"], is_circle.inputs[0])
    circle_switch = nodes.new("GeometryNodeSwitch")
    circle_switch.input_type = "GEOMETRY"
    circle_switch.label = "Select Circle"
    links.new(is_circle.outputs[0], circle_switch.inputs["Switch"])
    links.new(rectangle_switch.outputs["Output"], circle_switch.inputs["False"])
    links.new(circle_geometry, circle_switch.inputs["True"])

    is_grid_rectangle = _math_node(nodes, "COMPARE", "Layout Is Grid Rectangle")
    is_grid_rectangle.inputs[1].default_value = float(
        _LAYOUT_VALUES[WidgetLayout.RECTANGLE_GRID]
    )
    is_grid_rectangle.inputs[2].default_value = 0.1
    links.new(group_input.outputs["Layout"], is_grid_rectangle.inputs[0])
    grid_rectangle_switch = nodes.new("GeometryNodeSwitch")
    grid_rectangle_switch.input_type = "GEOMETRY"
    grid_rectangle_switch.label = "Select Grid Rectangle"
    links.new(
        is_grid_rectangle.outputs[0],
        grid_rectangle_switch.inputs["Switch"],
    )
    links.new(circle_switch.outputs["Output"], grid_rectangle_switch.inputs["False"])
    links.new(grid_rectangle_geometry, grid_rectangle_switch.inputs["True"])

    is_dial = _math_node(nodes, "COMPARE", "Layout Is Dial")
    is_dial.inputs[1].default_value = float(_LAYOUT_VALUES[WidgetLayout.DIAL])
    is_dial.inputs[2].default_value = 0.1
    links.new(group_input.outputs["Layout"], is_dial.inputs[0])
    dial_switch = nodes.new("GeometryNodeSwitch")
    dial_switch.input_type = "GEOMETRY"
    dial_switch.label = "Select Dial"
    links.new(is_dial.outputs[0], dial_switch.inputs["Switch"])
    links.new(grid_rectangle_switch.outputs["Output"], dial_switch.inputs["False"])
    links.new(dial_geometry, dial_switch.inputs["True"])
    links.new(dial_switch.outputs["Output"], group_output.inputs["Geometry"])

    return node_group


def _modifier_input_identifiers(node_group) -> dict[str, str]:
    identifiers: dict[str, str] = {}
    for item in node_group.interface.items_tree:
        if getattr(item, "item_type", "") != "SOCKET":
            continue
        if getattr(item, "in_out", "") != "INPUT":
            continue
        identifiers[item.name] = item.identifier
    return identifiers


def apply_widget_spec(modifier: bpy.types.NodesModifier, spec: WidgetSpec):
    node_group = modifier.node_group or ensure_widget_node_group()
    modifier.node_group = node_group
    identifiers = _modifier_input_identifiers(node_group)
    values: dict[str, Any] = {
        "Layout": _LAYOUT_VALUES[spec.layout],
        "Width": spec.width,
        "Height": spec.height,
        "Radius": spec.radius,
        "Tip Radius": spec.tip_radius,
        "Node Radius": spec.node_radius,
        "Bar Width": spec.bar_width,
        "Stroke Radius": spec.stroke_radius,
        "Columns": spec.columns,
        "Rows": spec.rows,
        "Arc Start": spec.arc_start,
        "Arc End": spec.arc_end,
    }
    for name, value in values.items():
        modifier[identifiers[name]] = value


def ensure_widget_source(spec: WidgetSpec, name: str | None = None):
    collection = ensure_widget_collection()
    source = next(
        (
            obj
            for obj in collection.objects
            if obj.get("coa_rig_widget_uuid") == spec.widget_uuid
            and obj.get("coa_rig_artifact_role") == "widget_source"
        ),
        None,
    )
    if source is None:
        mesh = bpy.data.meshes.new(f"{name or spec.layout.value}_WidgetSourceMesh")
        source = bpy.data.objects.new(
            f"{name or spec.layout.value}_WidgetSource",
            mesh,
        )
        collection.objects.link(source)
    source["coa_rig_managed"] = True
    source["coa_rig_widget_uuid"] = spec.widget_uuid
    source["coa_rig_artifact_role"] = "widget_source"
    source.hide_render = True

    modifier = source.modifiers.get("COA Rig Widget")
    if modifier is None or modifier.type != "NODES":
        if modifier is not None:
            source.modifiers.remove(modifier)
        modifier = source.modifiers.new("COA Rig Widget", "NODES")
    modifier.node_group = ensure_widget_node_group()
    apply_widget_spec(modifier, spec)
    source.data.update()
    return source


def sync_evaluated_mesh_cache(
    source: bpy.types.Object,
    spec: WidgetSpec,
    name: str | None = None,
):
    collection = ensure_widget_collection()
    cache = next(
        (
            obj
            for obj in collection.objects
            if obj.get("coa_rig_widget_uuid") == spec.widget_uuid
            and obj.get("coa_rig_artifact_role") == "widget_cache"
        ),
        None,
    )
    was_hidden = source.hide_get()
    source.hide_set(False)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    bpy.context.view_layer.update()
    evaluated = source.evaluated_get(depsgraph)
    mesh = bpy.data.meshes.new_from_object(
        evaluated,
        preserve_all_data_layers=False,
        depsgraph=depsgraph,
    )
    source.hide_set(was_hidden)
    mesh.name = f"{name or spec.layout.value}_WidgetMesh"

    if cache is None:
        cache = bpy.data.objects.new(f"{name or spec.layout.value}_Widget", mesh)
        collection.objects.link(cache)
    else:
        old_mesh = cache.data
        cache.data = mesh
        if old_mesh is not None and old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)
    cache["coa_rig_managed"] = True
    cache["coa_rig_widget_uuid"] = spec.widget_uuid
    cache["coa_rig_artifact_role"] = "widget_cache"
    cache.hide_render = True
    return cache


def ensure_widget(
    spec: WidgetSpec,
    name: str | None = None,
    backend: WidgetBackend = WidgetBackend.EVALUATED_MESH_CACHE,
):
    source = ensure_widget_source(spec, name=name)
    if backend == WidgetBackend.LIVE_MODIFIER:
        source.hide_set(True)
        return source
    cache = sync_evaluated_mesh_cache(source, spec, name=name)
    source.hide_set(True)
    cache.hide_set(True)
    return cache
