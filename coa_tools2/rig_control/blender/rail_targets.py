"""Hidden mesh targets used to constrain controls to visible rails."""

from __future__ import annotations

import math

import bpy
from mathutils import Matrix

from ..schema import dial_point
from .states import graph_state_edges
from .widgets import ensure_widget_collection


def find_rail_target(control_uuid: str):
    return next(
        (
            obj
            for obj in bpy.data.objects
            if obj.get("coa_rig_control_uuid") == control_uuid
            and obj.get("coa_rig_artifact_role") == "rail_target"
        ),
        None,
    )


def _append_quad(vertices, faces, x_min, x_max, y_min, y_max):
    start = len(vertices)
    vertices.extend(
        (
            (x_min, y_min, 0.0),
            (x_max, y_min, 0.0),
            (x_max, y_max, 0.0),
            (x_min, y_max, 0.0),
        )
    )
    faces.append((start, start + 1, start + 2, start + 3))


def _append_curtain(vertices, faces, start_point, end_point, half_depth):
    start = len(vertices)
    vertices.extend(
        (
            (*start_point, -half_depth),
            (*end_point, -half_depth),
            (*end_point, half_depth),
            (*start_point, half_depth),
        )
    )
    faces.append((start, start + 1, start + 2, start + 3))


def _grid_rail_geometry(control):
    vertices = []
    faces = []
    half_width = control.width * 0.5
    half_height = control.height * 0.5
    half_rail = max(control.stroke_radius * 0.25, 0.001)
    for column in range(control.grid_columns):
        factor = column / (control.grid_columns - 1)
        x = -half_width + control.width * factor
        _append_quad(
            vertices,
            faces,
            x - half_rail,
            x + half_rail,
            -half_height,
            half_height,
        )
    for row in range(control.grid_rows):
        factor = row / (control.grid_rows - 1)
        y = -half_height + control.height * factor
        _append_quad(
            vertices,
            faces,
            -half_width,
            half_width,
            y - half_rail,
            y + half_rail,
        )
    return vertices, faces


def _dial_rail_geometry(control):
    sweep = control.angle_max - control.angle_min
    segments = max(16, min(512, math.ceil(256 * sweep / math.tau)))
    half_rail = max(control.stroke_radius * 0.25, 0.001)
    inner_radius = max(control.radius - half_rail, 0.001)
    outer_radius = control.radius + half_rail
    vertices = []
    for index in range(segments + 1):
        factor = index / segments
        angle = control.angle_min + sweep * factor
        vertices.append((*dial_point(inner_radius, angle), 0.0))
        vertices.append((*dial_point(outer_radius, angle), 0.0))
    faces = [
        (index * 2, index * 2 + 1, index * 2 + 3, index * 2 + 2)
        for index in range(segments)
    ]
    return vertices, faces


def _matrix_domain_geometry(control):
    """Build exact grid centerlines plus freely mixable cell surfaces."""

    vertices = []
    faces = []
    half_width = control.width * 0.5
    half_height = control.height * 0.5
    half_depth = max(control.stroke_radius, 0.01)
    columns = max(2, control.state_columns)
    rows = max(2, control.state_rows)
    x_values = [
        -half_width + control.width * column / (columns - 1)
        for column in range(columns)
    ]
    y_values = [
        -half_height + control.height * row / (rows - 1)
        for row in range(rows)
    ]

    # Vertical curtain faces force Nearest Surface to the exact rail
    # centerline instead of the edge of a thin horizontal strip.
    for x in x_values:
        _append_curtain(
            vertices,
            faces,
            (x, -half_height),
            (x, half_height),
            half_depth,
        )
    for y in y_values:
        _append_curtain(
            vertices,
            faces,
            (-half_width, y),
            (half_width, y),
            half_depth,
        )

    cells = {
        (cell.column, cell.row): cell
        for cell in control.state_cells
    }
    for row in range(rows - 1):
        for column in range(columns - 1):
            cell = cells.get((column, row))
            if cell is None or not cell.mix_enabled:
                continue
            _append_quad(
                vertices,
                faces,
                x_values[column],
                x_values[column + 1],
                y_values[row],
                y_values[row + 1],
            )
    return vertices, faces


def _graph_rail_geometry(control):
    """Build centered vertical curtains for arbitrary fallback edges."""

    vertices = []
    faces = []
    half_depth = max(control.stroke_radius, 0.01)
    points = tuple(control.state_points)
    for start, end in graph_state_edges(control):
        start_point = points[start]
        end_point = points[end]
        start_xy = (
            (float(start_point.graph_position[0]) - 0.5) * control.width,
            (float(start_point.graph_position[1]) - 0.5) * control.height,
        )
        end_xy = (
            (float(end_point.graph_position[0]) - 0.5) * control.width,
            (float(end_point.graph_position[1]) - 0.5) * control.height,
        )
        _append_curtain(vertices, faces, start_xy, end_xy, half_depth)
    if not faces:
        raise ValueError("Named Graph requires at least one fallback edge.")
    return vertices, faces


def ensure_rail_target(armature, control):
    if control.control_type == "DIAL":
        vertices, faces = _dial_rail_geometry(control)
        rail_kind = "DIAL"
    elif (
        control.control_type == "POINT_2D_RECT"
        and control.state_mode == "MATRIX_2D"
    ):
        vertices, faces = _matrix_domain_geometry(control)
        rail_kind = "MATRIX_DOMAIN"
    elif (
        control.control_type == "POINT_2D_RECT"
        and control.state_mode == "GRAPH_2D"
        and control.graph_interpolation == "NAMED_GRAPH"
    ):
        vertices, faces = _graph_rail_geometry(control)
        rail_kind = "GRAPH"
    elif (
        control.control_type == "POINT_2D_RECT"
        and control.rectangle_mode == "GRID"
    ):
        vertices, faces = _grid_rail_geometry(control)
        rail_kind = "GRID"
    else:
        raise ValueError(f"Control does not use a rail target: {control.label}")

    target = find_rail_target(control.control_uuid)
    mesh = bpy.data.meshes.new(f"RAIL_{control.semantic_id}_Mesh")
    mesh.from_pydata(vertices, (), faces)
    mesh.update()
    if target is None:
        target = bpy.data.objects.new(f"RAIL_{control.semantic_id}", mesh)
        ensure_widget_collection().objects.link(target)
    else:
        old_mesh = target.data
        target.data = mesh
        if old_mesh is not None and old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)

    target["coa_rig_managed"] = True
    target["coa_rig_instance_id"] = armature.coa_tools2_rig.rig_instance_id
    target["coa_rig_control_uuid"] = control.control_uuid
    target["coa_rig_artifact_role"] = "rail_target"
    target["coa_rig_rail_kind"] = rail_kind
    target.parent = armature
    target.matrix_parent_inverse = Matrix.Identity(4)
    target.location = control.origin
    target.rotation_mode = "XYZ"
    target.rotation_euler = (math.pi * 0.5, 0.0, 0.0)
    target.hide_render = True
    target.hide_select = True
    target.display_type = "WIRE"
    target.hide_set(True)
    return target
