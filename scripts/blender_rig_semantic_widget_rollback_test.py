#!/usr/bin/env python3
"""Blender 5.1 rollback regression for procedural semantic widgets."""

from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
import uuid

import bpy


def _tag(owner, instance_id, component_uuid, role):
    owner["coa_rig_managed"] = True
    owner["coa_rig_instance_id"] = instance_id
    owner["coa_rig_component_uuid"] = component_uuid
    owner["coa_rig_component_role"] = role


def _node_group(name):
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    geometry_input = group.interface.new_socket(
        name="Geometry",
        in_out="INPUT",
        socket_type="NodeSocketGeometry",
    )
    width = group.interface.new_socket(
        name="Width",
        in_out="INPUT",
        socket_type="NodeSocketFloat",
    )
    height = group.interface.new_socket(
        name="Height",
        in_out="INPUT",
        socket_type="NodeSocketFloat",
    )
    group.interface.new_socket(
        name="Geometry",
        in_out="OUTPUT",
        socket_type="NodeSocketGeometry",
    )
    group_input = group.nodes.new("NodeGroupInput")
    group_output = group.nodes.new("NodeGroupOutput")
    group.links.new(
        group_input.outputs[geometry_input.identifier],
        group_output.inputs["Geometry"],
    )
    return group, width.identifier, height.identifier


def _assert_vector(actual, expected, epsilon=1.0e-6):
    assert len(actual) == len(expected)
    assert all(abs(a - b) <= epsilon for a, b in zip(actual, expected)), (
        tuple(actual),
        tuple(expected),
    )


def main():
    from coa_tools2.rig_control.blender import component_safety

    armature_data = bpy.data.armatures.new("SemanticWidgetRollbackData")
    armature = bpy.data.objects.new("SemanticWidgetRollback", armature_data)
    bpy.context.scene.collection.objects.link(armature)
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    armature.name = "SemanticWidgetRollback"

    bpy.ops.object.mode_set(mode="EDIT")
    control = armature.data.edit_bones.new("CTRL_widget")
    control.head = (0.0, 0.0, 0.0)
    control.tail = (0.0, 0.0, 1.0)
    display = armature.data.edit_bones.new("MCH_widget_display")
    display.head = (1.0, 0.0, 0.0)
    display.tail = (1.0, 0.0, 1.0)
    control_name = control.name
    display_name = display.name
    bpy.ops.object.mode_set(mode="POSE")

    instance_id = str(uuid.uuid4())
    component_uuid = str(uuid.uuid4())
    component = SimpleNamespace(
        component_uuid=component_uuid,
        source_bones=(SimpleNamespace(bone_name=control_name),),
        frame_bone="",
        control_bone="",
        pole_bone="",
        pole_angle=0.0,
        pole_angle_valid=False,
        constraint_bone="",
        constraint_name="",
        compiled_deformation_mode="",
        needs_rebuild=False,
        last_error="",
        artifacts=[],
    )
    component_safety.ensure_rig_instance_id = lambda _armature: instance_id

    role = "semantic:rollback:widget_object:primary"
    mesh = bpy.data.meshes.new("RollbackWidgetMesh")
    mesh.from_pydata(
        ((-1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 1.0)),
        ((0, 1), (1, 2)),
        ((0, 1, 2),),
    )
    widget = bpy.data.objects.new("RollbackWidget", mesh)
    bpy.context.scene.collection.objects.link(widget)
    _tag(widget, instance_id, component.component_uuid, role)
    _tag(mesh, instance_id, component.component_uuid, role)
    widget["coa_rig_widget_revision"] = 7
    mesh["coa_rig_mesh_revision"] = 3
    original_vertices = tuple(tuple(vertex.co) for vertex in mesh.vertices)
    original_edges = tuple(tuple(edge.vertices) for edge in mesh.edges)
    original_faces = tuple(tuple(polygon.vertices) for polygon in mesh.polygons)

    before = widget.modifiers.new("Before Nodes", "WELD")
    group, width_id, height_id = _node_group("RollbackOriginalGN")
    nodes = widget.modifiers.new("Widget Nodes", "NODES")
    nodes.node_group = group
    nodes[width_id] = 1.25
    nodes[f"{width_id}_use_attribute"] = False
    if height_id in nodes:
        del nodes[height_id]
    nodes["coa_socket_marker"] = "original"
    nodes.show_viewport = False
    nodes.show_render = True
    nodes.show_expanded = False
    after = widget.modifiers.new("After Nodes", "WELD")
    assert [modifier.name for modifier in widget.modifiers] == [
        before.name,
        nodes.name,
        after.name,
    ]
    original_modifier_keys = frozenset(nodes.keys())

    pose_control = armature.pose.bones[control_name]
    pose_control.custom_shape = widget
    pose_control.custom_shape_transform = armature.pose.bones[display_name]
    pose_control.use_custom_shape_bone_size = False
    pose_control.custom_shape_wire_width = 2.5
    pose_control.custom_shape_translation = (0.25, -0.5, 0.75)
    pose_control.custom_shape_rotation_euler = (0.1, -0.2, 0.3)
    pose_control.custom_shape_scale_xyz = (1.5, 0.75, 2.0)

    snapshot = component_safety.capture_component_build_state(armature, component)

    replacement_mesh = bpy.data.meshes.new("ReplacementShapeMesh")
    replacement_shape = bpy.data.objects.new("ReplacementShape", replacement_mesh)
    bpy.context.scene.collection.objects.link(replacement_shape)
    pose_control.custom_shape = replacement_shape
    pose_control.custom_shape_transform = None
    pose_control.custom_shape_translation = (9.0, 9.0, 9.0)
    pose_control.custom_shape_rotation_euler = (1.0, 1.0, 1.0)
    pose_control.custom_shape_scale_xyz = (4.0, 4.0, 4.0)

    mesh.clear_geometry()
    mesh.from_pydata(((8.0, 8.0, 8.0),), (), ())
    widget["coa_rig_widget_revision"] = 99
    widget["coa_rig_transient"] = True
    mesh["coa_rig_mesh_revision"] = 99
    mesh["coa_rig_transient"] = True

    mutated_group, _mutated_width, _mutated_height = _node_group(
        "RollbackMutatedGN"
    )
    nodes.name = "Renamed Failed Nodes"
    nodes.node_group = mutated_group
    nodes.show_viewport = True
    nodes.show_render = False
    nodes.show_expanded = True
    for key in tuple(nodes.keys()):
        del nodes[key]
    nodes[height_id] = 6.5
    widget.modifiers.move(widget.modifiers.find(nodes.name), 0)
    failed_nodes = widget.modifiers.new("Failed Extra Nodes", "NODES")
    failed_nodes.node_group = mutated_group

    generated_mesh = bpy.data.meshes.new("FailedOwnedWidgetMesh")
    generated_widget = bpy.data.objects.new("FailedOwnedWidget", generated_mesh)
    bpy.context.scene.collection.objects.link(generated_widget)
    _tag(
        generated_widget,
        instance_id,
        component.component_uuid,
        "semantic:rollback:widget_object:failed",
    )
    _tag(
        generated_mesh,
        instance_id,
        component.component_uuid,
        "semantic:rollback:widget_object:failed",
    )

    generated_widget_name = generated_widget.name
    generated_mesh_name = generated_mesh.name
    component_safety.rollback_component_build(armature, component, snapshot)

    pose_control = armature.pose.bones[control_name]
    assert pose_control.custom_shape == widget
    assert pose_control.custom_shape_transform == armature.pose.bones[display_name]
    assert not pose_control.use_custom_shape_bone_size
    assert abs(pose_control.custom_shape_wire_width - 2.5) <= 1.0e-6
    _assert_vector(pose_control.custom_shape_translation, (0.25, -0.5, 0.75))
    _assert_vector(pose_control.custom_shape_rotation_euler, (0.1, -0.2, 0.3))
    _assert_vector(pose_control.custom_shape_scale_xyz, (1.5, 0.75, 2.0))

    assert tuple(tuple(vertex.co) for vertex in mesh.vertices) == original_vertices
    assert tuple(tuple(edge.vertices) for edge in mesh.edges) == original_edges
    assert tuple(tuple(polygon.vertices) for polygon in mesh.polygons) == original_faces
    assert widget["coa_rig_widget_revision"] == 7
    assert "coa_rig_transient" not in widget
    assert mesh["coa_rig_mesh_revision"] == 3
    assert "coa_rig_transient" not in mesh

    assert [modifier.name for modifier in widget.modifiers] == [
        "Before Nodes",
        "Widget Nodes",
        "After Nodes",
    ]
    restored = widget.modifiers["Widget Nodes"]
    assert restored.type == "NODES"
    assert restored.node_group == group
    assert not restored.show_viewport
    assert restored.show_render
    assert not restored.show_expanded
    assert frozenset(restored.keys()) == original_modifier_keys
    assert abs(float(restored[width_id]) - 1.25) <= 1.0e-6
    assert restored[f"{width_id}_use_attribute"] is False
    assert height_id not in restored
    assert restored["coa_socket_marker"] == "original"
    assert widget.modifiers.get("Failed Extra Nodes") is None
    assert bpy.data.objects.get(generated_widget_name) is None
    assert bpy.data.meshes.get(generated_mesh_name) is None

    print(
        "SEMANTIC_WIDGET_ROLLBACK_OK",
        restored.name,
        len(restored.keys()),
        pose_control.custom_shape_transform.name,
    )


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
