"""Geometry Nodes based custom-shape widget generation."""

from __future__ import annotations

from typing import Any

import bpy

from ..schema import WidgetBackend, WidgetLayout, WidgetSpec


NODE_GROUP_NAME = "COA_RigWidget_GN"
WIDGET_COLLECTION_NAME = "COA Rig Widgets"
NODE_GROUP_VERSION = 1

_LAYOUT_VALUES = {
    WidgetLayout.TIP: 0,
    WidgetLayout.LINEAR: 1,
    WidgetLayout.RECTANGLE: 2,
    WidgetLayout.CIRCLE: 3,
    WidgetLayout.DIAL: 4,
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


def _rectangle_mesh(
    nodes,
    links,
    width_socket,
    height_socket,
    stroke_socket,
    label,
):
    path = nodes.new("GeometryNodeCurvePrimitiveQuadrilateral")
    path.mode = "RECTANGLE"
    path.label = f"{label} Path"
    links.new(width_socket, path.inputs["Width"])
    links.new(height_socket, path.inputs["Height"])

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


def _translated_geometry(nodes, links, geometry_socket, x_socket, label):
    combine = nodes.new("ShaderNodeCombineXYZ")
    combine.label = f"{label} Translation"
    links.new(x_socket, combine.inputs["X"])

    transform = nodes.new("GeometryNodeTransform")
    transform.label = label
    links.new(geometry_socket, transform.inputs["Geometry"])
    links.new(combine.outputs["Vector"], transform.inputs["Translation"])
    return transform.outputs["Geometry"]


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
    _new_interface_socket(node_group, "Tip Radius", "INPUT", "NodeSocketFloat", 0.28)
    _new_interface_socket(node_group, "Node Radius", "INPUT", "NodeSocketFloat", 0.34)
    _new_interface_socket(node_group, "Bar Width", "INPUT", "NodeSocketFloat", 0.28)
    _new_interface_socket(node_group, "Stroke Radius", "INPUT", "NodeSocketFloat", 0.035)
    _new_interface_socket(node_group, "Columns", "INPUT", "NodeSocketInt", 2)
    _new_interface_socket(node_group, "Rows", "INPUT", "NodeSocketInt", 2)

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

    bar_geometry = _rectangle_mesh(
        nodes,
        links,
        group_input.outputs["Width"],
        group_input.outputs["Bar Width"],
        group_input.outputs["Stroke Radius"],
        "Linear Bar",
    )

    endpoint_geometry = _circle_mesh(
        nodes,
        links,
        group_input.outputs["Node Radius"],
        group_input.outputs["Stroke Radius"],
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
    linear_join = nodes.new("GeometryNodeJoinGeometry")
    linear_join.label = "Linear Widget"
    links.new(bar_geometry, linear_join.inputs["Geometry"])
    links.new(left_endpoint, linear_join.inputs["Geometry"])
    links.new(right_endpoint, linear_join.inputs["Geometry"])

    is_linear = _math_node(nodes, "COMPARE", "Layout Is Linear")
    is_linear.inputs[1].default_value = float(_LAYOUT_VALUES[WidgetLayout.LINEAR])
    is_linear.inputs[2].default_value = 0.1
    links.new(group_input.outputs["Layout"], is_linear.inputs[0])

    layout_switch = nodes.new("GeometryNodeSwitch")
    layout_switch.input_type = "GEOMETRY"
    layout_switch.label = "Select Layout"
    links.new(is_linear.outputs[0], layout_switch.inputs["Switch"])
    links.new(tip_geometry, layout_switch.inputs["False"])
    links.new(linear_join.outputs["Geometry"], layout_switch.inputs["True"])
    links.new(layout_switch.outputs["Output"], group_output.inputs["Geometry"])

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
        "Tip Radius": spec.tip_radius,
        "Node Radius": spec.node_radius,
        "Bar Width": spec.bar_width,
        "Stroke Radius": spec.stroke_radius,
        "Columns": spec.columns,
        "Rows": spec.rows,
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
