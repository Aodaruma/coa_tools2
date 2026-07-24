"""Geometry Nodes based custom-shape widget generation."""

from __future__ import annotations

import math
from typing import Any, Callable

import bpy

from ..schema import WidgetBackend, WidgetLayout, WidgetSpec


WIDGET_COLLECTION_NAME = "COA Rig Widgets"
NODE_GROUP_VERSION = 5
LEGACY_NODE_GROUP_NAME = "COA_RigWidget_GN"
NODE_GROUP_NAMES = {
    "TIP": "COA_RigWidget_Tip_GN",
    "SLIDER": "COA_RigWidget_Slider_GN",
    "RADIAL": "COA_RigWidget_Radial_GN",
    "RECTANGLE": "COA_RigWidget_Rectangle_GN",
}
_BOOLEAN_SOLID_DEPTH = 0.1


def widget_family(layout: WidgetLayout) -> str:
    if layout == WidgetLayout.TIP:
        return "TIP"
    if layout == WidgetLayout.LINEAR:
        return "SLIDER"
    if layout in {WidgetLayout.CIRCLE, WidgetLayout.DIAL}:
        return "RADIAL"
    if layout in {WidgetLayout.RECTANGLE, WidgetLayout.RECTANGLE_GRID}:
        return "RECTANGLE"
    raise ValueError(f"Unsupported widget layout: {layout}")


def expected_widget_node_group_names(
    layouts: set[WidgetLayout] | None = None,
) -> set[str]:
    if layouts is None:
        families = set(NODE_GROUP_NAMES)
    else:
        families = {widget_family(layout) for layout in layouts}
    return {NODE_GROUP_NAMES[family] for family in families}


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


def _compare_input(node, name, socket_type):
    return next(
        socket
        for socket in node.inputs
        if socket.name == name and socket.type == socket_type
    )


def _circle_curve(nodes, links, radius_socket, label):
    circle = nodes.new("GeometryNodeCurvePrimitiveCircle")
    circle.mode = "RADIUS"
    circle.label = label
    circle.inputs["Resolution"].default_value = 48
    links.new(radius_socket, circle.inputs["Radius"])
    return circle.outputs["Curve"]


def _arc_curve(nodes, links, radius_socket, start_socket, end_socket, label):
    start_angle = _math_node(nodes, "ADD", f"{label} Start Angle")
    start_angle.inputs[1].default_value = math.pi * 0.5
    links.new(start_socket, start_angle.inputs[0])
    sweep_angle = _math_node(nodes, "SUBTRACT", f"{label} Sweep Angle")
    links.new(end_socket, sweep_angle.inputs[0])
    links.new(start_socket, sweep_angle.inputs[1])

    arc = nodes.new("GeometryNodeCurveArc")
    arc.mode = "RADIUS"
    arc.label = label
    arc.inputs["Resolution"].default_value = 64
    links.new(radius_socket, arc.inputs["Radius"])
    links.new(start_angle.outputs[0], arc.inputs["Start Angle"])
    links.new(sweep_angle.outputs[0], arc.inputs["Sweep Angle"])
    return arc.outputs["Curve"]


def _line_curve(nodes, links, start_x_socket, end_x_socket, label):
    start = nodes.new("ShaderNodeCombineXYZ")
    start.label = f"{label} Start"
    end = nodes.new("ShaderNodeCombineXYZ")
    end.label = f"{label} End"
    links.new(start_x_socket, start.inputs["X"])
    links.new(end_x_socket, end.inputs["X"])

    line = nodes.new("GeometryNodeCurvePrimitiveLine")
    line.mode = "POINTS"
    line.label = label
    links.new(start.outputs["Vector"], line.inputs["Start"])
    links.new(end.outputs["Vector"], line.inputs["End"])
    return line.outputs["Curve"]


def _curve_to_edge_mesh(nodes, links, curve_socket, label):
    """Convert curves to mesh edges without adding an inner stroke contour."""

    point_profile = nodes.new("GeometryNodeCurvePrimitiveLine")
    point_profile.mode = "POINTS"
    point_profile.label = f"{label} Point Profile"
    point_profile.inputs["Start"].default_value = (0.0, 0.0, 0.0)
    point_profile.inputs["End"].default_value = (0.0, 0.0, 0.0)

    curve_to_mesh = nodes.new("GeometryNodeCurveToMesh")
    curve_to_mesh.label = f"{label} Curve to Edges"
    links.new(curve_socket, curve_to_mesh.inputs["Curve"])
    links.new(point_profile.outputs["Curve"], curve_to_mesh.inputs["Profile Curve"])

    merge = nodes.new("GeometryNodeMergeByDistance")
    merge.label = label
    merge.inputs["Distance"].default_value = 0.0001
    links.new(curve_to_mesh.outputs["Mesh"], merge.inputs["Geometry"])
    return merge.outputs["Geometry"]


def _solid_box_mesh(nodes, links, width_socket, height_socket, label):
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
    cylinder.inputs["Vertices"].default_value = 48
    cylinder.inputs["Side Segments"].default_value = 1
    cylinder.inputs["Fill Segments"].default_value = 1
    links.new(radius_socket, cylinder.inputs["Radius"])
    cylinder.inputs["Depth"].default_value = _BOOLEAN_SOLID_DEPTH
    return cylinder.outputs["Mesh"]


def _solid_rail_from_path(
    nodes,
    links,
    path_curve_socket,
    bar_width_socket,
    label,
):
    profile = nodes.new("GeometryNodeCurvePrimitiveQuadrilateral")
    profile.mode = "RECTANGLE"
    profile.label = f"{label} Rail Profile"
    links.new(bar_width_socket, profile.inputs["Width"])
    profile.inputs["Height"].default_value = _BOOLEAN_SOLID_DEPTH

    curve_to_mesh = nodes.new("GeometryNodeCurveToMesh")
    curve_to_mesh.label = label
    curve_to_mesh.inputs["Fill Caps"].default_value = True
    links.new(path_curve_socket, curve_to_mesh.inputs["Curve"])
    links.new(profile.outputs["Curve"], curve_to_mesh.inputs["Profile Curve"])
    return curve_to_mesh.outputs["Mesh"]


def _boundary_curve_from_union(nodes, links, geometries, label):
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
    return boundary.outputs["Curve"]


def _union_outline_mesh(nodes, links, geometries, label):
    boundary = _boundary_curve_from_union(nodes, links, geometries, label)
    return _curve_to_edge_mesh(nodes, links, boundary, label)


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
    points.label = f"{label} Repeat Points"
    links.new(count_socket, points.inputs["Count"])
    links.new(start.outputs["Vector"], points.inputs["Start Location"])
    links.new(offset.outputs["Vector"], points.inputs["Offset"])

    instances = nodes.new("GeometryNodeInstanceOnPoints")
    instances.label = f"{label} Repeat"
    links.new(points.outputs["Mesh"], instances.inputs["Points"])
    links.new(instance_geometry, instances.inputs["Instance"])

    realize = nodes.new("GeometryNodeRealizeInstances")
    realize.label = f"{label} Realized"
    links.new(instances.outputs["Instances"], realize.inputs["Geometry"])
    return realize.outputs["Geometry"]


def _half_dimension(nodes, links, dimension_socket, label, factor=0.5):
    value = _math_node(nodes, "MULTIPLY", label)
    value.inputs[1].default_value = factor
    links.new(dimension_socket, value.inputs[0])
    return value.outputs[0]


def _endpoint_instances_on_arc(
    nodes,
    links,
    arc_curve_socket,
    endpoint_geometry,
    label,
):
    points = nodes.new("GeometryNodeCurveToPoints")
    points.mode = "COUNT"
    points.label = f"{label} Endpoint Points"
    points.inputs["Count"].default_value = 2
    links.new(arc_curve_socket, points.inputs["Curve"])

    instances = nodes.new("GeometryNodeInstanceOnPoints")
    instances.label = f"{label} Endpoint Nodes"
    links.new(points.outputs["Points"], instances.inputs["Points"])
    links.new(endpoint_geometry, instances.inputs["Instance"])

    realize = nodes.new("GeometryNodeRealizeInstances")
    realize.label = f"{label} Endpoints Realized"
    links.new(instances.outputs["Instances"], realize.inputs["Geometry"])
    return realize.outputs["Geometry"]


def _new_group(name, family):
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    group["coa_rig_managed"] = True
    group["coa_rig_widget_version"] = NODE_GROUP_VERSION
    group["coa_rig_widget_family"] = family
    _new_interface_socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    return group


def _group_io(group):
    group_input = group.nodes.new("NodeGroupInput")
    group_input.location = (-900, 0)
    group_output = group.nodes.new("NodeGroupOutput")
    group_output.location = (900, 0)
    return group_input, group_output


def _build_tip_group(name):
    group = _new_group(name, "TIP")
    _new_interface_socket(group, "Tip Radius", "INPUT", "NodeSocketFloat", 0.68)
    nodes = group.nodes
    links = group.links
    group_input, group_output = _group_io(group)
    circle = _circle_curve(
        nodes,
        links,
        group_input.outputs["Tip Radius"],
        "Tip Circle Closure",
    )
    geometry = _curve_to_edge_mesh(nodes, links, circle, "Tip Outline")
    links.new(geometry, group_output.inputs["Geometry"])
    return group


def _build_slider_group(name):
    group = _new_group(name, "SLIDER")
    _new_interface_socket(group, "Width", "INPUT", "NodeSocketFloat", 4.0)
    _new_interface_socket(group, "Node Radius", "INPUT", "NodeSocketFloat", 0.34)
    _new_interface_socket(group, "Bar Width", "INPUT", "NodeSocketFloat", 0.28)
    nodes = group.nodes
    links = group.links
    group_input, group_output = _group_io(group)

    endpoint = _solid_circle_mesh(
        nodes,
        links,
        group_input.outputs["Node Radius"],
        "Slider Endpoint",
    )
    half_width = _half_dimension(
        nodes,
        links,
        group_input.outputs["Width"],
        "Slider Half Width",
    )
    negative_half_width = _half_dimension(
        nodes,
        links,
        group_input.outputs["Width"],
        "Slider Negative Half Width",
        -0.5,
    )
    centerline = _line_curve(
        nodes,
        links,
        negative_half_width,
        half_width,
        "Slider Centerline",
    )
    bar = _solid_rail_from_path(
        nodes,
        links,
        centerline,
        group_input.outputs["Bar Width"],
        "Slider Offset Rail",
    )
    left = _translated_geometry(
        nodes,
        links,
        endpoint,
        negative_half_width,
        "Slider Left Endpoint",
    )
    right = _translated_geometry(
        nodes,
        links,
        endpoint,
        half_width,
        "Slider Right Endpoint",
    )
    geometry = _union_outline_mesh(
        nodes,
        links,
        (bar, left, right),
        "Slider Outline",
    )
    links.new(geometry, group_output.inputs["Geometry"])
    return group


def _build_rectangle_group(name):
    group = _new_group(name, "RECTANGLE")
    _new_interface_socket(group, "Grid Mode", "INPUT", "NodeSocketBool", False)
    _new_interface_socket(group, "Width", "INPUT", "NodeSocketFloat", 4.0)
    _new_interface_socket(group, "Height", "INPUT", "NodeSocketFloat", 2.0)
    _new_interface_socket(group, "Node Radius", "INPUT", "NodeSocketFloat", 0.34)
    _new_interface_socket(group, "Bar Width", "INPUT", "NodeSocketFloat", 0.28)
    _new_interface_socket(group, "Columns", "INPUT", "NodeSocketInt", 2)
    _new_interface_socket(group, "Rows", "INPUT", "NodeSocketInt", 2)
    nodes = group.nodes
    links = group.links
    group_input, group_output = _group_io(group)

    half_width = _half_dimension(
        nodes,
        links,
        group_input.outputs["Width"],
        "Rectangle Half Width",
    )
    negative_half_width = _half_dimension(
        nodes,
        links,
        group_input.outputs["Width"],
        "Rectangle Negative Half Width",
        -0.5,
    )
    half_height = _half_dimension(
        nodes,
        links,
        group_input.outputs["Height"],
        "Rectangle Half Height",
    )
    negative_half_height = _half_dimension(
        nodes,
        links,
        group_input.outputs["Height"],
        "Rectangle Negative Half Height",
        -0.5,
    )

    endpoint = _solid_circle_mesh(
        nodes,
        links,
        group_input.outputs["Node Radius"],
        "Rectangle Node",
    )
    corners = []
    for label, x_socket, y_socket in (
        ("Bottom Left", negative_half_width, negative_half_height),
        ("Bottom Right", half_width, negative_half_height),
        ("Top Left", negative_half_width, half_height),
        ("Top Right", half_width, half_height),
    ):
        corners.append(
            _translated_geometry(
                nodes,
                links,
                endpoint,
                x_socket,
                label,
                y_socket,
            )
        )

    free_width = _math_node(nodes, "ADD", "Free Outer Width")
    links.new(group_input.outputs["Width"], free_width.inputs[0])
    links.new(group_input.outputs["Bar Width"], free_width.inputs[1])
    free_height = _math_node(nodes, "ADD", "Free Outer Height")
    links.new(group_input.outputs["Height"], free_height.inputs[0])
    links.new(group_input.outputs["Bar Width"], free_height.inputs[1])
    filled_interior = _solid_box_mesh(
        nodes,
        links,
        free_width.outputs[0],
        free_height.outputs[0],
        "Free Interior Fill",
    )
    free_geometry = _union_outline_mesh(
        nodes,
        links,
        (filled_interior, *corners),
        "Rectangle Free Outer Outline",
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
    vertical_bars = _grid_bar_instances(
        nodes,
        links,
        vertical_bar,
        group_input.outputs["Columns"],
        group_input.outputs["Width"],
        negative_half_width,
        "X",
        "Grid Columns",
    )
    horizontal_bars = _grid_bar_instances(
        nodes,
        links,
        horizontal_bar,
        group_input.outputs["Rows"],
        group_input.outputs["Height"],
        negative_half_height,
        "Y",
        "Grid Rows",
    )
    grid_geometry = _union_outline_mesh(
        nodes,
        links,
        (vertical_bars, horizontal_bars, *corners),
        "Rectangle Grid Outline",
    )

    switch = nodes.new("GeometryNodeSwitch")
    switch.input_type = "GEOMETRY"
    switch.label = "Free or Grid"
    links.new(group_input.outputs["Grid Mode"], switch.inputs["Switch"])
    links.new(free_geometry, switch.inputs["False"])
    links.new(grid_geometry, switch.inputs["True"])
    links.new(switch.outputs["Output"], group_output.inputs["Geometry"])
    return group


def _build_radial_group(name):
    group = _new_group(name, "RADIAL")
    _new_interface_socket(group, "Dial Mode", "INPUT", "NodeSocketBool", False)
    _new_interface_socket(group, "Radius", "INPUT", "NodeSocketFloat", 2.0)
    _new_interface_socket(group, "Node Radius", "INPUT", "NodeSocketFloat", 0.34)
    _new_interface_socket(group, "Bar Width", "INPUT", "NodeSocketFloat", 0.28)
    _new_interface_socket(
        group,
        "Arc Start",
        "INPUT",
        "NodeSocketFloat",
        -math.pi * 0.5,
    )
    _new_interface_socket(
        group,
        "Arc End",
        "INPUT",
        "NodeSocketFloat",
        math.pi * 0.5,
    )
    nodes = group.nodes
    links = group.links
    group_input, group_output = _group_io(group)

    half_bar = _half_dimension(
        nodes,
        links,
        group_input.outputs["Bar Width"],
        "Radial Half Bar Width",
    )
    outer_radius = _math_node(nodes, "ADD", "Circle Outer Radius")
    links.new(group_input.outputs["Radius"], outer_radius.inputs[0])
    links.new(half_bar, outer_radius.inputs[1])
    circle = _circle_curve(
        nodes,
        links,
        outer_radius.outputs[0],
        "Circle Outer Closure",
    )
    circle_geometry = _curve_to_edge_mesh(
        nodes,
        links,
        circle,
        "Circle Outer Outline",
    )

    dial_arc = _arc_curve(
        nodes,
        links,
        group_input.outputs["Radius"],
        group_input.outputs["Arc Start"],
        group_input.outputs["Arc End"],
        "Dial Rail Centerline",
    )
    dial_rail = _solid_rail_from_path(
        nodes,
        links,
        dial_arc,
        group_input.outputs["Bar Width"],
        "Dial Offset Rail",
    )
    endpoint = _solid_circle_mesh(
        nodes,
        links,
        group_input.outputs["Node Radius"],
        "Dial Endpoint Node",
    )
    endpoints = _endpoint_instances_on_arc(
        nodes,
        links,
        dial_arc,
        endpoint,
        "Dial",
    )
    dial_geometry = _union_outline_mesh(
        nodes,
        links,
        (dial_rail, endpoints),
        "Dial Rail Outline",
    )

    switch = nodes.new("GeometryNodeSwitch")
    switch.input_type = "GEOMETRY"
    switch.label = "Circle or Dial"
    links.new(group_input.outputs["Dial Mode"], switch.inputs["Switch"])
    links.new(circle_geometry, switch.inputs["False"])
    links.new(dial_geometry, switch.inputs["True"])
    links.new(switch.outputs["Output"], group_output.inputs["Geometry"])
    return group


_GROUP_BUILDERS: dict[str, Callable[[str], bpy.types.GeometryNodeTree]] = {
    "TIP": _build_tip_group,
    "SLIDER": _build_slider_group,
    "RADIAL": _build_radial_group,
    "RECTANGLE": _build_rectangle_group,
}


def _remove_unused_legacy_groups():
    legacy_prefixes = (
        LEGACY_NODE_GROUP_NAME,
        *(f"{name}_legacy" for name in NODE_GROUP_NAMES.values()),
    )
    for group in list(bpy.data.node_groups):
        if (
            group.get("coa_rig_managed")
            and group.users == 0
            and any(group.name.startswith(prefix) for prefix in legacy_prefixes)
        ):
            bpy.data.node_groups.remove(group)


def ensure_widget_node_group(layout: WidgetLayout = WidgetLayout.LINEAR):
    family = widget_family(layout)
    name = NODE_GROUP_NAMES[family]
    existing = bpy.data.node_groups.get(name)
    if (
        existing is not None
        and existing.get("coa_rig_widget_version") == NODE_GROUP_VERSION
        and existing.get("coa_rig_widget_family") == family
    ):
        return existing
    if existing is not None:
        if existing.users:
            existing.name = f"{name}_legacy"
        else:
            bpy.data.node_groups.remove(existing)
    return _GROUP_BUILDERS[family](name)


def ensure_widget_node_groups():
    return {
        family: ensure_widget_node_group(
            {
                "TIP": WidgetLayout.TIP,
                "SLIDER": WidgetLayout.LINEAR,
                "RADIAL": WidgetLayout.CIRCLE,
                "RECTANGLE": WidgetLayout.RECTANGLE,
            }[family]
        )
        for family in NODE_GROUP_NAMES
    }


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
    node_group = ensure_widget_node_group(spec.layout)
    modifier.node_group = node_group
    identifiers = _modifier_input_identifiers(node_group)
    values: dict[str, Any] = {
        "Grid Mode": spec.layout == WidgetLayout.RECTANGLE_GRID,
        "Dial Mode": spec.layout == WidgetLayout.DIAL,
        "Width": spec.width,
        "Height": spec.height,
        "Radius": spec.radius,
        "Tip Radius": spec.tip_radius,
        "Node Radius": spec.node_radius,
        "Bar Width": spec.bar_width,
        "Columns": spec.columns,
        "Rows": spec.rows,
        "Arc Start": spec.arc_start,
        "Arc End": spec.arc_end,
    }
    for name, value in values.items():
        identifier = identifiers.get(name)
        if identifier is not None:
            modifier[identifier] = value


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
    source["coa_rig_widget_layout"] = spec.layout.value
    source["coa_rig_widget_family"] = widget_family(spec.layout)
    source.hide_render = True

    modifier = source.modifiers.get("COA Rig Widget")
    if modifier is None or modifier.type != "NODES":
        if modifier is not None:
            source.modifiers.remove(modifier)
        modifier = source.modifiers.new("COA Rig Widget", "NODES")
    apply_widget_spec(modifier, spec)
    source.data.update()
    _remove_unused_legacy_groups()
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
    cache["coa_rig_widget_layout"] = spec.layout.value
    cache["coa_rig_widget_family"] = widget_family(spec.layout)
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
