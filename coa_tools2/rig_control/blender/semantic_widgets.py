"""Procedural custom-shape widgets for Semantic Rigs.

This module deliberately owns a separate Geometry Nodes namespace from
``rig_control.blender.widgets``.  State Rig widgets and Semantic Rig widgets
can therefore evolve independently and can coexist in the same ``.blend``.

Every group built here outputs one closed, connected, face-free edge loop.
Spatial arrows are not tubes or cones: the cylindrical and spherical shapes
subdivide a flat arrow silhouette and analytically wrap those samples onto a
surface.  They consequently keep the same visual language as the flat arrow
widgets while exposing a higher default surface resolution.

The public entry points are:

``semantic_widget_family``
    Return immutable shape and parameter metadata.
``ensure_semantic_widget_node_group`` / ``ensure_semantic_widget_node_groups``
    Idempotently create versioned production Geometry Nodes groups.
``ensure_semantic_widget_modifier``
    Ensure one managed Nodes modifier on a source Mesh object.
``apply_semantic_widget_parameters``
    Set modifier inputs by their public socket names.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

try:
    import bpy
except ImportError:  # Metadata and value validation remain pure-Python usable.
    bpy = None


SEMANTIC_WIDGET_SCHEMA = "coa-tools2-semantic-widget-v1"
SEMANTIC_WIDGET_NODE_GROUP_VERSION = 1
SEMANTIC_WIDGET_MODIFIER_NAME = "COA Semantic Widget"


class SemanticWidgetShape(str, Enum):
    """Stable identifiers stored in Semantic Rig artifacts."""

    ARROW_1D = "ARROW_1D"
    ARROW_2D = "ARROW_2D"
    CYLINDER_ARROW_1D = "CYLINDER_ARROW_1D"
    SPHERE_ARROW_2D = "SPHERE_ARROW_2D"
    TOMBSTONE = "TOMBSTONE"
    ELLIPSE = "ELLIPSE"
    TRIANGLE = "TRIANGLE"
    RECTANGLE = "RECTANGLE"
    DIAMOND = "DIAMOND"
    SECTOR = "SECTOR"


@dataclass(frozen=True)
class SemanticWidgetParameter:
    """One public Geometry Nodes modifier input."""

    name: str
    socket_type: str
    default: float | int
    minimum: float | int
    maximum: float | int
    description: str
    subtype: str | None = None


@dataclass(frozen=True)
class SemanticWidgetFamily:
    """Immutable metadata used by UI, compilers, and artifact validation."""

    shape: SemanticWidgetShape
    label: str
    group_name: str
    category: str
    parameters: tuple[SemanticWidgetParameter, ...]
    flat_source: SemanticWidgetShape | None = None
    surface_projection: str | None = None
    topology: str = "SINGLE_CLOSED_EDGE_LOOP"
    expected_faces: int = 0


def _float_parameter(
    name: str,
    default: float,
    minimum: float,
    maximum: float,
    description: str,
    *,
    subtype: str | None = None,
) -> SemanticWidgetParameter:
    return SemanticWidgetParameter(
        name,
        "NodeSocketFloat",
        default,
        minimum,
        maximum,
        description,
        subtype,
    )


def _int_parameter(
    name: str,
    default: int,
    minimum: int,
    maximum: int,
    description: str,
) -> SemanticWidgetParameter:
    return SemanticWidgetParameter(
        name,
        "NodeSocketInt",
        default,
        minimum,
        maximum,
        description,
    )


WIDTH = _float_parameter("Width", 2.8, 0.1, 100.0, "Overall local X extent.")
HEIGHT = _float_parameter("Height", 2.2, 0.1, 100.0, "Overall local Y extent.")
BAR_WIDTH = _float_parameter(
    "Bar Width", 0.14, 0.005, 10.0, "Full width of an arrow shaft."
)
ARROW_HEAD_LENGTH = _float_parameter(
    "Arrow Head Length", 0.46, 0.01, 50.0, "Length of each arrow head."
)
ARROW_HEAD_WIDTH = _float_parameter(
    "Arrow Head Width", 0.72, 0.01, 50.0, "Full width of each arrow head."
)
CORNER_RADIUS = _float_parameter(
    "Corner Radius", 0.24, 0.0, 50.0, "Radius used to round polygon corners."
)
CURVE_SEGMENTS = _int_parameter(
    "Segments", 64, 3, 256, "Curve resolution or fillet segment count."
)
SMOOTH_SEGMENTS = _int_parameter(
    "Segments", 96, 8, 256, "Resolution of a smooth outline."
)
SPATIAL_SEGMENTS = _int_parameter(
    "Segments",
    96,
    16,
    256,
    "Target sample count before wrapping the flat arrow onto a surface.",
)
SECTOR_SEGMENTS = _int_parameter(
    "Segments", 96, 3, 256, "Resolution of the inner and outer sector arcs."
)
RADIUS = _float_parameter(
    "Radius", 2.0, 0.01, 1000.0, "Radius of the target cylinder or sphere.",
    subtype="DISTANCE",
)
ARC_ANGLE = _float_parameter(
    "Arc Angle",
    math.radians(220.0),
    math.radians(10.0),
    math.tau,
    "Angular span occupied by the wrapped arrow.",
    subtype="ANGLE",
)
SECTOR_INNER_RADIUS = _float_parameter(
    "Inner Radius",
    0.0,
    0.0,
    1000.0,
    "Inner arc radius; zero produces a center-connected sector.",
    subtype="DISTANCE",
)
SECTOR_OUTER_RADIUS = _float_parameter(
    "Outer Radius",
    1.0,
    0.001,
    1000.0,
    "Outer arc radius.",
    subtype="DISTANCE",
)
SECTOR_START_ANGLE = _float_parameter(
    "Start Angle",
    0.0,
    -1.0e6,
    1.0e6,
    "Angle at which the sector begins; normalized cyclically by the node group.",
    subtype="ANGLE",
)
SECTOR_SWEEP_ANGLE = _float_parameter(
    "Sweep Angle",
    math.pi * 0.5,
    -math.tau,
    math.tau,
    "Signed sector sweep; a negative value reverses its direction.",
    subtype="ANGLE",
)


def _family(
    shape: SemanticWidgetShape,
    label: str,
    suffix: str,
    category: str,
    parameters: Sequence[SemanticWidgetParameter],
    *,
    flat_source: SemanticWidgetShape | None = None,
    surface_projection: str | None = None,
) -> SemanticWidgetFamily:
    return SemanticWidgetFamily(
        shape=shape,
        label=label,
        group_name=f"COA_SemanticWidget_{suffix}_GN",
        category=category,
        parameters=tuple(parameters),
        flat_source=flat_source,
        surface_projection=surface_projection,
    )


_FAMILIES = {
    SemanticWidgetShape.ARROW_1D: _family(
        SemanticWidgetShape.ARROW_1D,
        "1D Double Arrow",
        "Arrow1D",
        "ARROW",
        (WIDTH, BAR_WIDTH, ARROW_HEAD_LENGTH, ARROW_HEAD_WIDTH),
    ),
    SemanticWidgetShape.ARROW_2D: _family(
        SemanticWidgetShape.ARROW_2D,
        "2D Four-way Arrow",
        "Arrow2D",
        "ARROW",
        (WIDTH, HEIGHT, BAR_WIDTH, ARROW_HEAD_LENGTH, ARROW_HEAD_WIDTH),
    ),
    SemanticWidgetShape.CYLINDER_ARROW_1D: _family(
        SemanticWidgetShape.CYLINDER_ARROW_1D,
        "Cylindrical 1D Double Arrow",
        "CylinderArrow1D",
        "SPATIAL_ARROW",
        (RADIUS, ARC_ANGLE, BAR_WIDTH, ARROW_HEAD_LENGTH, ARROW_HEAD_WIDTH, SPATIAL_SEGMENTS),
        flat_source=SemanticWidgetShape.ARROW_1D,
        surface_projection="CYLINDER",
    ),
    SemanticWidgetShape.SPHERE_ARROW_2D: _family(
        SemanticWidgetShape.SPHERE_ARROW_2D,
        "Spherical 2D Four-way Arrow",
        "SphereArrow2D",
        "SPATIAL_ARROW",
        (RADIUS, ARC_ANGLE, BAR_WIDTH, ARROW_HEAD_LENGTH, ARROW_HEAD_WIDTH, SPATIAL_SEGMENTS),
        flat_source=SemanticWidgetShape.ARROW_2D,
        surface_projection="SPHERE",
    ),
    SemanticWidgetShape.TOMBSTONE: _family(
        SemanticWidgetShape.TOMBSTONE,
        "Tombstone",
        "Tombstone",
        "BADGE",
        (WIDTH, HEIGHT, CORNER_RADIUS, CURVE_SEGMENTS),
    ),
    SemanticWidgetShape.ELLIPSE: _family(
        SemanticWidgetShape.ELLIPSE,
        "Ellipse",
        "Ellipse",
        "GEOMETRIC",
        (WIDTH, HEIGHT, SMOOTH_SEGMENTS),
    ),
    SemanticWidgetShape.TRIANGLE: _family(
        SemanticWidgetShape.TRIANGLE,
        "Rounded Triangle",
        "Triangle",
        "GEOMETRIC",
        (WIDTH, HEIGHT, CORNER_RADIUS, CURVE_SEGMENTS),
    ),
    SemanticWidgetShape.RECTANGLE: _family(
        SemanticWidgetShape.RECTANGLE,
        "Rounded Rectangle",
        "Rectangle",
        "GEOMETRIC",
        (WIDTH, HEIGHT, CORNER_RADIUS, CURVE_SEGMENTS),
    ),
    SemanticWidgetShape.DIAMOND: _family(
        SemanticWidgetShape.DIAMOND,
        "Rounded Diamond",
        "Diamond",
        "GEOMETRIC",
        (WIDTH, HEIGHT, CORNER_RADIUS, CURVE_SEGMENTS),
    ),
    SemanticWidgetShape.SECTOR: _family(
        SemanticWidgetShape.SECTOR,
        "Sector",
        "Sector",
        "GEOMETRIC",
        (
            SECTOR_INNER_RADIUS,
            SECTOR_OUTER_RADIUS,
            SECTOR_START_ANGLE,
            SECTOR_SWEEP_ANGLE,
            SECTOR_SEGMENTS,
        ),
    ),
}
SEMANTIC_WIDGET_FAMILIES: Mapping[SemanticWidgetShape, SemanticWidgetFamily] = (
    MappingProxyType(_FAMILIES)
)


def coerce_semantic_widget_shape(
    shape: SemanticWidgetShape | str,
) -> SemanticWidgetShape:
    """Accept stable enum values and their case-insensitive names."""

    if isinstance(shape, SemanticWidgetShape):
        return shape
    text = str(shape).strip().upper()
    try:
        return SemanticWidgetShape(text)
    except ValueError as exc:
        choices = ", ".join(item.value for item in SemanticWidgetShape)
        raise ValueError(
            f"Unsupported Semantic Widget shape {shape!r}; expected {choices}"
        ) from exc


def semantic_widget_family(
    shape: SemanticWidgetShape | str,
) -> SemanticWidgetFamily:
    """Return stable metadata for a Semantic Widget shape."""

    return SEMANTIC_WIDGET_FAMILIES[coerce_semantic_widget_shape(shape)]


def semantic_widget_parameter_defaults(
    shape: SemanticWidgetShape | str,
) -> dict[str, float | int]:
    return {
        parameter.name: parameter.default
        for parameter in semantic_widget_family(shape).parameters
    }


def normalize_semantic_widget_parameters(
    shape: SemanticWidgetShape | str,
    parameters: Mapping[str, float | int],
    *,
    clamp: bool = True,
    strict: bool = True,
) -> dict[str, float | int]:
    """Validate socket-name/value pairs without requiring Blender."""

    family = semantic_widget_family(shape)
    specs = {parameter.name: parameter for parameter in family.parameters}
    result: dict[str, float | int] = {}
    for name, value in parameters.items():
        spec = specs.get(name)
        if spec is None:
            if strict:
                choices = ", ".join(specs)
                raise KeyError(
                    f"Unknown {family.shape.value} parameter {name!r}; "
                    f"expected {choices}"
                )
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{family.shape.value}.{name} must be numeric, got {value!r}")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"{family.shape.value}.{name} must be finite")
        if clamp:
            numeric = max(float(spec.minimum), min(float(spec.maximum), numeric))
        elif numeric < spec.minimum or numeric > spec.maximum:
            raise ValueError(
                f"{family.shape.value}.{name}={numeric} is outside "
                f"[{spec.minimum}, {spec.maximum}]"
            )
        result[name] = int(round(numeric)) if spec.socket_type == "NodeSocketInt" else numeric
    return result


def _require_bpy() -> Any:
    if bpy is None:
        raise RuntimeError("Semantic Widget Geometry Nodes require Blender's bpy module")
    return bpy


def _new_interface_socket(
    group: Any,
    name: str,
    socket_type: str,
    *,
    in_out: str,
    default: float | int | None = None,
    minimum: float | int | None = None,
    maximum: float | int | None = None,
    subtype: str | None = None,
    description: str = "",
) -> Any:
    socket = group.interface.new_socket(name=name, in_out=in_out, socket_type=socket_type)
    if default is not None and hasattr(socket, "default_value"):
        socket.default_value = default
    if minimum is not None and hasattr(socket, "min_value"):
        socket.min_value = minimum
    if maximum is not None and hasattr(socket, "max_value"):
        socket.max_value = maximum
    if subtype is not None and hasattr(socket, "subtype"):
        socket.subtype = subtype
    if description and hasattr(socket, "description"):
        socket.description = description
    return socket


def _new_group(family: SemanticWidgetFamily) -> tuple[Any, Any, Any]:
    blender = _require_bpy()
    group = blender.data.node_groups.new(family.group_name, "GeometryNodeTree")
    group["coa_semantic_widget_managed"] = True
    group["coa_semantic_widget_schema"] = SEMANTIC_WIDGET_SCHEMA
    group["coa_semantic_widget_version"] = SEMANTIC_WIDGET_NODE_GROUP_VERSION
    group["coa_semantic_widget_shape"] = family.shape.value
    group["coa_semantic_widget_category"] = family.category
    group["coa_semantic_widget_topology"] = family.topology
    group["coa_semantic_widget_expected_faces"] = family.expected_faces
    if family.flat_source is not None:
        group["coa_semantic_widget_flat_source"] = family.flat_source.value
    if family.surface_projection is not None:
        group["coa_semantic_widget_surface_projection"] = family.surface_projection
    group.description = (
        f"COA Tools 2 Semantic Rig widget: {family.label}; "
        "one closed face-free edge loop."
    )

    _new_interface_socket(
        group,
        "Geometry",
        "NodeSocketGeometry",
        in_out="OUTPUT",
        description="Face-free edge Mesh suitable for a bone custom shape.",
    )
    for parameter in family.parameters:
        _new_interface_socket(
            group,
            parameter.name,
            parameter.socket_type,
            in_out="INPUT",
            default=parameter.default,
            minimum=parameter.minimum,
            maximum=parameter.maximum,
            subtype=parameter.subtype,
            description=parameter.description,
        )

    input_node = group.nodes.new("NodeGroupInput")
    input_node.name = "Semantic Widget Parameters"
    input_node.label = family.label
    input_node.location = (-1400.0, 0.0)
    output_node = group.nodes.new("NodeGroupOutput")
    output_node.name = "Face-free Widget Output"
    output_node.label = "Closed Edge Loop"
    output_node.location = (1400.0, 0.0)
    output_node.is_active_output = True
    return group, input_node, output_node


def _set_or_link(group: Any, value: Any, input_socket: Any) -> None:
    if hasattr(value, "is_output") and value.is_output:
        group.links.new(value, input_socket)
    else:
        input_socket.default_value = value


def _math(
    group: Any,
    operation: str,
    first: Any,
    second: Any | None = None,
    *,
    label: str,
) -> Any:
    node = group.nodes.new("ShaderNodeMath")
    node.operation = operation
    node.label = label
    _set_or_link(group, first, node.inputs[0])
    if second is not None:
        _set_or_link(group, second, node.inputs[1])
    return node.outputs[0]


def _minimum(group: Any, values: Sequence[Any], *, label: str) -> Any:
    if len(values) < 2:
        raise ValueError("_minimum requires at least two values")
    result = values[0]
    for index, value in enumerate(values[1:], start=1):
        result = _math(group, "MINIMUM", result, value, label=f"{label} {index}")
    return result


def _vector(
    group: Any,
    x: Any,
    y: Any,
    z: Any = 0.0,
    *,
    label: str,
) -> Any:
    node = group.nodes.new("ShaderNodeCombineXYZ")
    node.label = label
    _set_or_link(group, x, node.inputs["X"])
    _set_or_link(group, y, node.inputs["Y"])
    _set_or_link(group, z, node.inputs["Z"])
    return node.outputs["Vector"]


def _compare_input(node: Any, name: str, socket_type: str) -> Any:
    return next(
        socket
        for socket in node.inputs
        if socket.name == name and socket.type == socket_type
    )


def _circle_curve(
    group: Any,
    resolution: Any,
    radius: Any = 1.0,
    *,
    label: str,
) -> Any:
    node = group.nodes.new("GeometryNodeCurvePrimitiveCircle")
    node.mode = "RADIUS"
    node.label = label
    _set_or_link(group, resolution, node.inputs["Resolution"])
    _set_or_link(group, radius, node.inputs["Radius"])
    return node.outputs["Curve"]


def _closed_polygon_curve(
    group: Any,
    points: Sequence[Any],
    *,
    label: str,
) -> Any:
    if len(points) < 3:
        raise ValueError("A closed polygon needs at least three points")
    curve = _circle_curve(group, len(points), label=f"{label} Cyclic Topology")
    index = group.nodes.new("GeometryNodeInputIndex")
    index.label = f"{label} Point Index"
    selected = points[0]
    for point_index, point in enumerate(points[1:], start=1):
        compare = group.nodes.new("FunctionNodeCompare")
        compare.data_type = "INT"
        compare.operation = "EQUAL"
        compare.label = f"{label} Point {point_index}"
        group.links.new(index.outputs["Index"], _compare_input(compare, "A", "INT"))
        _compare_input(compare, "B", "INT").default_value = point_index
        switch = group.nodes.new("GeometryNodeSwitch")
        switch.input_type = "VECTOR"
        switch.label = f"{label} Select {point_index}"
        group.links.new(compare.outputs["Result"], switch.inputs["Switch"])
        _set_or_link(group, selected, switch.inputs["False"])
        _set_or_link(group, point, switch.inputs["True"])
        selected = switch.outputs["Output"]
    set_position = group.nodes.new("GeometryNodeSetPosition")
    set_position.label = label
    group.links.new(curve, set_position.inputs["Geometry"])
    group.links.new(selected, set_position.inputs["Position"])
    return set_position.outputs["Geometry"]


def _line_curve(group: Any, start: Any, end: Any, *, label: str) -> Any:
    node = group.nodes.new("GeometryNodeCurvePrimitiveLine")
    node.mode = "POINTS"
    node.label = label
    _set_or_link(group, start, node.inputs["Start"])
    _set_or_link(group, end, node.inputs["End"])
    return node.outputs["Curve"]


def _arc_curve(
    group: Any,
    resolution: Any,
    radius: Any,
    start_angle: Any,
    sweep_angle: Any,
    *,
    label: str,
    connect_center: bool = False,
) -> Any:
    node = group.nodes.new("GeometryNodeCurveArc")
    node.mode = "RADIUS"
    node.label = label
    _set_or_link(group, resolution, node.inputs["Resolution"])
    _set_or_link(group, radius, node.inputs["Radius"])
    _set_or_link(group, start_angle, node.inputs["Start Angle"])
    _set_or_link(group, sweep_angle, node.inputs["Sweep Angle"])
    if connect_center:
        connect_socket = node.inputs.get("Connect Center")
        if connect_socket is None:
            raise RuntimeError("Curve Arc has no Connect Center input")
        connect_socket.default_value = True
    return node.outputs["Curve"]


def _transform_curve(
    group: Any,
    curve: Any,
    *,
    translation: Any = (0.0, 0.0, 0.0),
    rotation: Any = (0.0, 0.0, 0.0),
    scale: Any = (1.0, 1.0, 1.0),
    label: str,
) -> Any:
    node = group.nodes.new("GeometryNodeTransform")
    node.label = label
    _set_or_link(group, curve, node.inputs["Geometry"])
    _set_or_link(group, translation, node.inputs["Translation"])
    _set_or_link(group, rotation, node.inputs["Rotation"])
    _set_or_link(group, scale, node.inputs["Scale"])
    return node.outputs["Geometry"]


def _join_geometry(group: Any, curves: Iterable[Any], *, label: str) -> Any:
    node = group.nodes.new("GeometryNodeJoinGeometry")
    node.label = label
    for curve in curves:
        group.links.new(curve, node.inputs["Geometry"])
    return node.outputs["Geometry"]


def _fillet_curve(
    group: Any,
    curve: Any,
    radius: Any,
    count: Any,
    *,
    label: str,
) -> Any:
    node = group.nodes.new("GeometryNodeFilletCurve")
    node.inputs["Mode"].default_value = "Poly"
    node.label = label
    _set_or_link(group, curve, node.inputs["Curve"])
    _set_or_link(group, radius, node.inputs["Radius"])
    _set_or_link(group, count, node.inputs["Count"])
    limit_radius = node.inputs.get("Limit Radius")
    if limit_radius is not None:
        limit_radius.default_value = True
    return node.outputs["Curve"]


def _curve_to_edge_mesh(group: Any, curve: Any, *, label: str) -> Any:
    """Convert curve splines to a welded, face-free edge Mesh."""

    point_profile = group.nodes.new("GeometryNodeCurvePrimitiveLine")
    point_profile.mode = "POINTS"
    point_profile.label = f"{label} Point Profile"
    point_profile.inputs["Start"].default_value = (0.0, 0.0, 0.0)
    point_profile.inputs["End"].default_value = (0.0, 0.0, 0.0)
    curve_to_mesh = group.nodes.new("GeometryNodeCurveToMesh")
    curve_to_mesh.label = f"{label} Curve to Edges"
    group.links.new(curve, curve_to_mesh.inputs["Curve"])
    group.links.new(point_profile.outputs["Curve"], curve_to_mesh.inputs["Profile Curve"])
    merge = group.nodes.new("GeometryNodeMergeByDistance")
    merge.label = f"{label} Weld"
    merge.inputs["Distance"].default_value = 1.0e-4
    group.links.new(curve_to_mesh.outputs["Mesh"], merge.inputs["Geometry"])
    return merge.outputs["Geometry"]


def _finish_group(group: Any, output: Any, geometry: Any) -> Any:
    group.links.new(geometry, output.inputs["Geometry"])
    return group


def _safe_bar_width(
    group: Any,
    requested: Any,
    width: Any,
    height: Any | None = None,
    *,
    extra_limits: Sequence[Any] = (),
    label: str,
) -> Any:
    minimum_extent = width
    if height is not None:
        minimum_extent = _math(
            group, "MINIMUM", width, height, label=f"{label} Minimum Extent"
        )
    extent_limit = _math(
        group,
        "MULTIPLY",
        minimum_extent,
        0.2,
        label=f"{label} Extent Limit",
    )
    return _minimum(
        group,
        (requested, extent_limit, *extra_limits),
        label=label,
    )


def _arrow_1d_outline(
    group: Any,
    half_width: Any,
    shaft_half: Any,
    head_length: Any,
    head_half: Any,
    *,
    label: str,
) -> tuple[Any, int]:
    negative_half_width = _math(
        group, "MULTIPLY", half_width, -1.0, label=f"{label} Left Tip X"
    )
    negative_head_half = _math(
        group, "MULTIPLY", head_half, -1.0, label=f"{label} Lower Head Y"
    )
    negative_shaft_half = _math(
        group, "MULTIPLY", shaft_half, -1.0, label=f"{label} Lower Shaft Y"
    )
    left_base = _math(
        group,
        "ADD",
        negative_half_width,
        head_length,
        label=f"{label} Left Base X",
    )
    right_base = _math(
        group,
        "SUBTRACT",
        half_width,
        head_length,
        label=f"{label} Right Base X",
    )
    points = (
        _vector(group, negative_half_width, 0.0, label=f"{label} Left Tip"),
        _vector(group, left_base, head_half, label=f"{label} Left Upper Head"),
        _vector(group, left_base, shaft_half, label=f"{label} Left Upper Shaft"),
        _vector(group, right_base, shaft_half, label=f"{label} Right Upper Shaft"),
        _vector(group, right_base, head_half, label=f"{label} Right Upper Head"),
        _vector(group, half_width, 0.0, label=f"{label} Right Tip"),
        _vector(group, right_base, negative_head_half, label=f"{label} Right Lower Head"),
        _vector(group, right_base, negative_shaft_half, label=f"{label} Right Lower Shaft"),
        _vector(group, left_base, negative_shaft_half, label=f"{label} Left Lower Shaft"),
        _vector(group, left_base, negative_head_half, label=f"{label} Left Lower Head"),
    )
    return _closed_polygon_curve(group, points, label=label), len(points)


def _arrow_2d_outline(
    group: Any,
    half_width: Any,
    half_height: Any,
    shaft_half: Any,
    head_length: Any,
    head_half: Any,
    *,
    label: str,
) -> tuple[Any, int]:
    negative_half_width = _math(
        group, "MULTIPLY", half_width, -1.0, label=f"{label} Left X"
    )
    negative_half_height = _math(
        group, "MULTIPLY", half_height, -1.0, label=f"{label} Bottom Y"
    )
    negative_head_half = _math(
        group, "MULTIPLY", head_half, -1.0, label=f"{label} Negative Head"
    )
    negative_shaft_half = _math(
        group, "MULTIPLY", shaft_half, -1.0, label=f"{label} Negative Shaft"
    )
    left_base = _math(
        group, "ADD", negative_half_width, head_length, label=f"{label} Left Base"
    )
    right_base = _math(
        group, "SUBTRACT", half_width, head_length, label=f"{label} Right Base"
    )
    bottom_base = _math(
        group, "ADD", negative_half_height, head_length, label=f"{label} Bottom Base"
    )
    top_base = _math(
        group, "SUBTRACT", half_height, head_length, label=f"{label} Top Base"
    )
    points = (
        _vector(group, 0.0, half_height, label=f"{label} Top Tip"),
        _vector(group, head_half, top_base, label=f"{label} Top Right Head"),
        _vector(group, shaft_half, top_base, label=f"{label} Top Right Shaft"),
        _vector(group, shaft_half, shaft_half, label=f"{label} Center Top Right"),
        _vector(group, right_base, shaft_half, label=f"{label} Right Upper Shaft"),
        _vector(group, right_base, head_half, label=f"{label} Right Upper Head"),
        _vector(group, half_width, 0.0, label=f"{label} Right Tip"),
        _vector(group, right_base, negative_head_half, label=f"{label} Right Lower Head"),
        _vector(group, right_base, negative_shaft_half, label=f"{label} Right Lower Shaft"),
        _vector(group, shaft_half, negative_shaft_half, label=f"{label} Center Bottom Right"),
        _vector(group, shaft_half, bottom_base, label=f"{label} Bottom Right Shaft"),
        _vector(group, head_half, bottom_base, label=f"{label} Bottom Right Head"),
        _vector(group, 0.0, negative_half_height, label=f"{label} Bottom Tip"),
        _vector(group, negative_head_half, bottom_base, label=f"{label} Bottom Left Head"),
        _vector(group, negative_shaft_half, bottom_base, label=f"{label} Bottom Left Shaft"),
        _vector(
            group,
            negative_shaft_half,
            negative_shaft_half,
            label=f"{label} Center Bottom Left",
        ),
        _vector(group, left_base, negative_shaft_half, label=f"{label} Left Lower Shaft"),
        _vector(group, left_base, negative_head_half, label=f"{label} Left Lower Head"),
        _vector(group, negative_half_width, 0.0, label=f"{label} Left Tip"),
        _vector(group, left_base, head_half, label=f"{label} Left Upper Head"),
        _vector(group, left_base, shaft_half, label=f"{label} Left Upper Shaft"),
        _vector(group, negative_shaft_half, shaft_half, label=f"{label} Center Top Left"),
        _vector(group, negative_shaft_half, top_base, label=f"{label} Top Left Shaft"),
        _vector(group, negative_head_half, top_base, label=f"{label} Top Left Head"),
    )
    return _closed_polygon_curve(group, points, label=label), len(points)


def _build_arrow_1d(family: SemanticWidgetFamily) -> Any:
    group, inputs, output = _new_group(family)
    width = inputs.outputs["Width"]
    half_width = _math(group, "MULTIPLY", width, 0.5, label="Half Width")
    requested_head_half = _math(
        group,
        "MULTIPLY",
        inputs.outputs["Arrow Head Width"],
        0.5,
        label="Requested Head Half Width",
    )
    maximum_head_half = _math(
        group, "MULTIPLY", half_width, 0.9, label="Maximum Head Half Width"
    )
    head_half = _math(
        group,
        "MINIMUM",
        requested_head_half,
        maximum_head_half,
        label="Safe Head Half Width",
    )
    head_width = _math(
        group, "MULTIPLY", head_half, 2.0, label="Safe Head Width"
    )
    head_bar_limit = _math(
        group, "MULTIPLY", head_width, 0.75, label="Head-relative Bar Limit"
    )
    bar_width = _safe_bar_width(
        group,
        inputs.outputs["Bar Width"],
        width,
        extra_limits=(head_bar_limit,),
        label="Safe Bar Width",
    )
    shaft_half = _math(
        group, "MULTIPLY", bar_width, 0.5, label="Shaft Half Width"
    )
    maximum_head_length = _math(
        group,
        "SUBTRACT",
        half_width,
        bar_width,
        label="Maximum Head Length",
    )
    head_length = _math(
        group,
        "MINIMUM",
        inputs.outputs["Arrow Head Length"],
        maximum_head_length,
        label="Safe Head Length",
    )
    outline, _corner_count = _arrow_1d_outline(
        group,
        half_width,
        shaft_half,
        head_length,
        head_half,
        label="Flat 1D Double Arrow",
    )
    mesh = _curve_to_edge_mesh(group, outline, label="Flat 1D Arrow")
    return _finish_group(group, output, mesh)


def _build_arrow_2d(family: SemanticWidgetFamily) -> Any:
    group, inputs, output = _new_group(family)
    width = inputs.outputs["Width"]
    height = inputs.outputs["Height"]
    half_width = _math(group, "MULTIPLY", width, 0.5, label="Half Width")
    half_height = _math(group, "MULTIPLY", height, 0.5, label="Half Height")
    minimum_half_extent = _math(
        group, "MINIMUM", half_width, half_height, label="Minimum Half Extent"
    )
    requested_head_half = _math(
        group,
        "MULTIPLY",
        inputs.outputs["Arrow Head Width"],
        0.5,
        label="Requested Head Half Width",
    )
    maximum_head_half = _math(
        group,
        "MULTIPLY",
        minimum_half_extent,
        0.45,
        label="Maximum Head Half Width",
    )
    head_half = _math(
        group,
        "MINIMUM",
        requested_head_half,
        maximum_head_half,
        label="Safe Head Half Width",
    )
    head_width = _math(
        group, "MULTIPLY", head_half, 2.0, label="Safe Head Width"
    )
    head_bar_limit = _math(
        group, "MULTIPLY", head_width, 0.75, label="Head-relative Bar Limit"
    )
    bar_width = _safe_bar_width(
        group,
        inputs.outputs["Bar Width"],
        width,
        height,
        extra_limits=(head_bar_limit,),
        label="Safe Bar Width",
    )
    shaft_half = _math(
        group, "MULTIPLY", bar_width, 0.5, label="Shaft Half Width"
    )
    head_clearance = _math(
        group, "MAXIMUM", head_half, bar_width, label="Head and Bar Clearance"
    )
    head_clearance = _math(
        group,
        "MULTIPLY",
        head_clearance,
        1.05,
        label="Head and Bar Clearance Margin",
    )
    maximum_head_length = _math(
        group,
        "SUBTRACT",
        minimum_half_extent,
        head_clearance,
        label="Maximum Head Length",
    )
    head_length = _math(
        group,
        "MINIMUM",
        inputs.outputs["Arrow Head Length"],
        maximum_head_length,
        label="Safe Head Length",
    )
    outline, _corner_count = _arrow_2d_outline(
        group,
        half_width,
        half_height,
        shaft_half,
        head_length,
        head_half,
        label="Flat 2D Four-way Arrow",
    )
    mesh = _curve_to_edge_mesh(group, outline, label="Flat 2D Arrow")
    return _finish_group(group, output, mesh)


def _build_tombstone(family: SemanticWidgetFamily) -> Any:
    group, inputs, output = _new_group(family)
    width = inputs.outputs["Width"]
    height = inputs.outputs["Height"]
    half_width = _math(group, "MULTIPLY", width, 0.5, label="Half Width")
    half_height = _math(group, "MULTIPLY", height, 0.5, label="Half Height")
    cap_height = _math(
        group, "MINIMUM", half_width, half_height, label="Top Cap Height"
    )
    remaining_height = _math(
        group,
        "SUBTRACT",
        height,
        cap_height,
        label="Height Below Top Cap",
    )
    corner_width_limit = _math(
        group,
        "MULTIPLY",
        half_width,
        0.95,
        label="Corner Width Limit",
    )
    corner_height_limit = _math(
        group,
        "MULTIPLY",
        remaining_height,
        0.95,
        label="Corner Height Limit",
    )
    corner = _minimum(
        group,
        (
            inputs.outputs["Corner Radius"],
            corner_width_limit,
            corner_height_limit,
        ),
        label="Safe Tombstone Corner",
    )
    negative_half_width = _math(
        group, "MULTIPLY", half_width, -1.0, label="Left X"
    )
    negative_half_height = _math(
        group, "MULTIPLY", half_height, -1.0, label="Bottom Y"
    )
    top_center_y = _math(
        group,
        "SUBTRACT",
        half_height,
        cap_height,
        label="Top Arc Center Y",
    )
    lower_side_y = _math(
        group, "ADD", negative_half_height, corner, label="Lower Side Y"
    )
    left_bottom_x = _math(
        group, "ADD", negative_half_width, corner, label="Bottom Left Inner X"
    )
    right_bottom_x = _math(
        group, "SUBTRACT", half_width, corner, label="Bottom Right Inner X"
    )

    top = _arc_curve(
        group,
        inputs.outputs["Segments"],
        1.0,
        0.0,
        math.pi,
        label="Top Semicircle",
    )
    top = _transform_curve(
        group,
        top,
        translation=_vector(group, 0.0, top_center_y, label="Top Arc Offset"),
        scale=_vector(group, half_width, cap_height, 1.0, label="Top Arc Scale"),
        label="Place Top Semicircle",
    )
    left_side = _line_curve(
        group,
        _vector(group, negative_half_width, top_center_y, label="Left Top"),
        _vector(group, negative_half_width, lower_side_y, label="Left Bottom"),
        label="Left Side",
    )
    right_side = _line_curve(
        group,
        _vector(group, half_width, top_center_y, label="Right Top"),
        _vector(group, half_width, lower_side_y, label="Right Bottom"),
        label="Right Side",
    )
    left_corner = _arc_curve(
        group,
        inputs.outputs["Segments"],
        corner,
        math.pi,
        math.pi * 0.5,
        label="Bottom Left Corner",
    )
    left_corner = _transform_curve(
        group,
        left_corner,
        translation=_vector(
            group, left_bottom_x, lower_side_y, label="Left Corner Center"
        ),
        label="Place Bottom Left Corner",
    )
    right_corner = _arc_curve(
        group,
        inputs.outputs["Segments"],
        corner,
        -math.pi * 0.5,
        math.pi * 0.5,
        label="Bottom Right Corner",
    )
    right_corner = _transform_curve(
        group,
        right_corner,
        translation=_vector(
            group, right_bottom_x, lower_side_y, label="Right Corner Center"
        ),
        label="Place Bottom Right Corner",
    )
    bottom = _line_curve(
        group,
        _vector(group, left_bottom_x, negative_half_height, label="Bottom Left"),
        _vector(group, right_bottom_x, negative_half_height, label="Bottom Right"),
        label="Bottom Edge",
    )
    outline = _join_geometry(
        group,
        (top, left_side, left_corner, bottom, right_corner, right_side),
        label="Tombstone Outline",
    )
    mesh = _curve_to_edge_mesh(group, outline, label="Tombstone")
    return _finish_group(group, output, mesh)


def _build_ellipse(family: SemanticWidgetFamily) -> Any:
    group, inputs, output = _new_group(family)
    half_width = _math(
        group, "MULTIPLY", inputs.outputs["Width"], 0.5, label="Half Width"
    )
    half_height = _math(
        group, "MULTIPLY", inputs.outputs["Height"], 0.5, label="Half Height"
    )
    circle = _circle_curve(
        group, inputs.outputs["Segments"], label="Unit Circle"
    )
    ellipse = _transform_curve(
        group,
        circle,
        scale=_vector(group, half_width, half_height, 1.0, label="Ellipse Scale"),
        label="Scale to Ellipse",
    )
    mesh = _curve_to_edge_mesh(group, ellipse, label="Ellipse")
    return _finish_group(group, output, mesh)


def _build_rounded_polygon(
    family: SemanticWidgetFamily,
    *,
    vertex_count: int,
    rotation_z: float,
) -> Any:
    group, inputs, output = _new_group(family)
    half_width = _math(
        group, "MULTIPLY", inputs.outputs["Width"], 0.5, label="Half Width"
    )
    half_height = _math(
        group, "MULTIPLY", inputs.outputs["Height"], 0.5, label="Half Height"
    )
    polygon = _circle_curve(
        group, vertex_count, label=f"{vertex_count}-vertex Polygon"
    )
    polygon = _transform_curve(
        group,
        polygon,
        rotation=(0.0, 0.0, rotation_z),
        label="Orient Unit Polygon",
    )
    polygon = _transform_curve(
        group,
        polygon,
        scale=_vector(group, half_width, half_height, 1.0, label="Polygon Scale"),
        label="Scale Oriented Polygon",
    )
    rounded = _fillet_curve(
        group,
        polygon,
        inputs.outputs["Corner Radius"],
        inputs.outputs["Segments"],
        label="Round Polygon Corners",
    )
    mesh = _curve_to_edge_mesh(group, rounded, label=family.label)
    return _finish_group(group, output, mesh)


def _build_rectangle(family: SemanticWidgetFamily) -> Any:
    group, inputs, output = _new_group(family)
    rectangle = group.nodes.new("GeometryNodeCurvePrimitiveQuadrilateral")
    rectangle.mode = "RECTANGLE"
    rectangle.label = "Rectangle"
    group.links.new(inputs.outputs["Width"], rectangle.inputs["Width"])
    group.links.new(inputs.outputs["Height"], rectangle.inputs["Height"])
    rounded = _fillet_curve(
        group,
        rectangle.outputs["Curve"],
        inputs.outputs["Corner Radius"],
        inputs.outputs["Segments"],
        label="Round Rectangle Corners",
    )
    mesh = _curve_to_edge_mesh(group, rounded, label="Rectangle")
    return _finish_group(group, output, mesh)


def _safe_sector_parameters(group: Any, inputs: Any) -> dict[str, Any]:
    """Normalize a signed sector without allowing degenerate closed arcs."""

    epsilon = 1.0e-4
    start = group.nodes.new("ShaderNodeMath")
    start.operation = "WRAP"
    start.label = "Normalize Start Angle"
    group.links.new(inputs.outputs["Start Angle"], start.inputs[0])
    start.inputs[1].default_value = math.pi
    start.inputs[2].default_value = -math.pi

    sweep_absolute = _math(
        group,
        "ABSOLUTE",
        inputs.outputs["Sweep Angle"],
        label="Absolute Sweep",
    )
    sweep_floor = _math(
        group,
        "MAXIMUM",
        sweep_absolute,
        epsilon,
        label="Minimum Sweep",
    )
    sweep_magnitude = _math(
        group,
        "MINIMUM",
        sweep_floor,
        math.tau - epsilon,
        label="Maximum Sweep with Closure Clearance",
    )
    negative_sweep_magnitude = _math(
        group,
        "MULTIPLY",
        sweep_magnitude,
        -1.0,
        label="Negative Sweep Magnitude",
    )
    is_negative = group.nodes.new("FunctionNodeCompare")
    is_negative.data_type = "FLOAT"
    is_negative.operation = "LESS_THAN"
    is_negative.label = "Negative Sweep"
    group.links.new(
        inputs.outputs["Sweep Angle"],
        _compare_input(is_negative, "A", "VALUE"),
    )
    _compare_input(is_negative, "B", "VALUE").default_value = 0.0
    signed_sweep = group.nodes.new("GeometryNodeSwitch")
    signed_sweep.input_type = "FLOAT"
    signed_sweep.label = "Restore Sweep Direction"
    group.links.new(is_negative.outputs["Result"], signed_sweep.inputs["Switch"])
    group.links.new(sweep_magnitude, signed_sweep.inputs["False"])
    group.links.new(negative_sweep_magnitude, signed_sweep.inputs["True"])

    outer_radius = _math(
        group,
        "MAXIMUM",
        inputs.outputs["Outer Radius"],
        0.001,
        label="Safe Outer Radius",
    )
    inner_floor = _math(
        group,
        "MAXIMUM",
        inputs.outputs["Inner Radius"],
        0.0,
        label="Non-negative Inner Radius",
    )
    relative_clearance = _math(
        group,
        "MULTIPLY",
        outer_radius,
        1.0e-5,
        label="Relative Radius Clearance",
    )
    radius_clearance = _math(
        group,
        "MAXIMUM",
        relative_clearance,
        1.0e-6,
        label="Minimum Radius Clearance",
    )
    maximum_inner = _math(
        group,
        "SUBTRACT",
        outer_radius,
        radius_clearance,
        label="Maximum Inner Radius",
    )
    inner_radius = _math(
        group,
        "MINIMUM",
        inner_floor,
        maximum_inner,
        label="Safe Inner Radius",
    )
    has_inner = group.nodes.new("FunctionNodeCompare")
    has_inner.data_type = "FLOAT"
    has_inner.operation = "GREATER_THAN"
    has_inner.label = "Annular Sector"
    group.links.new(inner_radius, _compare_input(has_inner, "A", "VALUE"))
    _compare_input(has_inner, "B", "VALUE").default_value = 0.0

    return {
        "inner_radius": inner_radius,
        "outer_radius": outer_radius,
        "start_angle": start.outputs[0],
        "sweep_angle": signed_sweep.outputs["Output"],
        "has_inner": has_inner.outputs["Result"],
        "segments": inputs.outputs["Segments"],
    }


def _polar_point(
    group: Any,
    radius: Any,
    angle: Any,
    *,
    label: str,
) -> Any:
    cosine = _math(group, "COSINE", angle, label=f"{label} Cosine")
    sine = _math(group, "SINE", angle, label=f"{label} Sine")
    x = _math(group, "MULTIPLY", radius, cosine, label=f"{label} X")
    y = _math(group, "MULTIPLY", radius, sine, label=f"{label} Y")
    return _vector(group, x, y, label=label)


def _build_sector(family: SemanticWidgetFamily) -> Any:
    group, inputs, output = _new_group(family)
    parameters = _safe_sector_parameters(group, inputs)
    start_angle = parameters["start_angle"]
    sweep_angle = parameters["sweep_angle"]
    end_angle = _math(
        group, "ADD", start_angle, sweep_angle, label="Sector End Angle"
    )
    negative_sweep = _math(
        group,
        "MULTIPLY",
        sweep_angle,
        -1.0,
        label="Reverse Inner Sweep",
    )

    outer_arc = _arc_curve(
        group,
        parameters["segments"],
        parameters["outer_radius"],
        start_angle,
        sweep_angle,
        label="Outer Arc",
    )
    inner_arc = _arc_curve(
        group,
        parameters["segments"],
        parameters["inner_radius"],
        end_angle,
        negative_sweep,
        label="Reverse Inner Arc",
    )
    outer_start = _polar_point(
        group,
        parameters["outer_radius"],
        start_angle,
        label="Outer Start",
    )
    outer_end = _polar_point(
        group,
        parameters["outer_radius"],
        end_angle,
        label="Outer End",
    )
    inner_start = _polar_point(
        group,
        parameters["inner_radius"],
        start_angle,
        label="Inner Start",
    )
    inner_end = _polar_point(
        group,
        parameters["inner_radius"],
        end_angle,
        label="Inner End",
    )
    end_connector = _line_curve(
        group, outer_end, inner_end, label="Outer-to-inner End Connector"
    )
    start_connector = _line_curve(
        group, inner_start, outer_start, label="Inner-to-outer Start Connector"
    )
    annular_outline = _join_geometry(
        group,
        (outer_arc, end_connector, inner_arc, start_connector),
        label="Annular Sector Outline",
    )

    center = (0.0, 0.0, 0.0)
    end_to_center = _line_curve(
        group, outer_end, center, label="Sector End to Center"
    )
    center_to_start = _line_curve(
        group, center, outer_start, label="Sector Center to Start"
    )
    center_outline = _join_geometry(
        group,
        (outer_arc, end_to_center, center_to_start),
        label="Center-connected Sector Outline",
    )

    choose_outline = group.nodes.new("GeometryNodeSwitch")
    choose_outline.input_type = "GEOMETRY"
    choose_outline.label = "Inner Radius Mode"
    group.links.new(parameters["has_inner"], choose_outline.inputs["Switch"])
    group.links.new(center_outline, choose_outline.inputs["False"])
    group.links.new(annular_outline, choose_outline.inputs["True"])
    mesh = _curve_to_edge_mesh(
        group,
        choose_outline.outputs["Output"],
        label="Sector",
    )
    return _finish_group(group, output, mesh)


def _safe_spatial_arrow_parameters(group: Any, inputs: Any) -> dict[str, Any]:
    """Clamp one flat arrow footprint relative to its target surface."""

    radius = _math(
        group, "MAXIMUM", inputs.outputs["Radius"], 0.01, label="Safe Radius"
    )
    requested_head_half = _math(
        group,
        "MULTIPLY",
        inputs.outputs["Arrow Head Width"],
        0.5,
        label="Requested Head Half Width",
    )
    radius_head_limit = _math(
        group,
        "MULTIPLY",
        radius,
        0.25,
        label="Radius-relative Head Half Limit",
    )
    preliminary_head_half = _math(
        group,
        "MINIMUM",
        requested_head_half,
        radius_head_limit,
        label="Preliminary Head Half Width",
    )
    preliminary_head_width = _math(
        group,
        "MULTIPLY",
        preliminary_head_half,
        2.0,
        label="Preliminary Head Width",
    )
    width_ratio = _math(
        group,
        "DIVIDE",
        preliminary_head_width,
        radius,
        label="Head Width over Radius",
    )
    width_clearance = _math(
        group,
        "MULTIPLY",
        width_ratio,
        1.5,
        label="Head Angular Clearance",
    )
    angular_clearance = _math(
        group,
        "MAXIMUM",
        width_clearance,
        0.08,
        label="Minimum Angular Clearance",
    )
    maximum_arc = _math(
        group,
        "SUBTRACT",
        math.tau,
        angular_clearance,
        label="Maximum Non-overlapping Arc",
    )
    minimum_arc = _math(
        group,
        "MAXIMUM",
        inputs.outputs["Arc Angle"],
        0.20,
        label="Minimum Arc Angle",
    )
    arc_angle = _math(
        group,
        "MINIMUM",
        minimum_arc,
        maximum_arc,
        label="Safe Arc Angle",
    )
    span = _math(
        group, "MULTIPLY", radius, arc_angle, label="Flat Geodesic Span"
    )
    half_span = _math(
        group, "MULTIPLY", span, 0.5, label="Flat Half Span"
    )
    span_head_limit = _math(
        group,
        "MULTIPLY",
        half_span,
        0.35,
        label="Span-relative Head Half Limit",
    )
    head_half = _math(
        group,
        "MINIMUM",
        preliminary_head_half,
        span_head_limit,
        label="Safe Head Half Width",
    )
    head_width = _math(
        group, "MULTIPLY", head_half, 2.0, label="Safe Head Width"
    )
    minimum_bar = _math(
        group,
        "MULTIPLY",
        radius,
        0.005,
        label="Minimum Relative Bar Width",
    )
    radius_bar_limit = _math(
        group,
        "MULTIPLY",
        radius,
        0.12,
        label="Radius-relative Bar Limit",
    )
    head_bar_limit = _math(
        group,
        "MULTIPLY",
        head_width,
        0.75,
        label="Head-relative Bar Limit",
    )
    span_bar_limit = _math(
        group,
        "MULTIPLY",
        span,
        0.20,
        label="Span-relative Bar Limit",
    )
    maximum_bar = _minimum(
        group,
        (radius_bar_limit, head_bar_limit, span_bar_limit),
        label="Maximum Bar Width",
    )
    bar_floor = _math(
        group,
        "MAXIMUM",
        inputs.outputs["Bar Width"],
        minimum_bar,
        label="Minimum Bar Width Clamp",
    )
    bar_width = _math(
        group,
        "MINIMUM",
        bar_floor,
        maximum_bar,
        label="Safe Bar Width",
    )
    shaft_half = _math(
        group, "MULTIPLY", bar_width, 0.5, label="Shaft Half Width"
    )
    head_clearance = _math(
        group,
        "MAXIMUM",
        head_half,
        bar_width,
        label="Head and Bar Clearance",
    )
    head_clearance = _math(
        group,
        "MULTIPLY",
        head_clearance,
        1.05,
        label="Head and Bar Clearance Margin",
    )
    available_head_length = _math(
        group,
        "SUBTRACT",
        half_span,
        head_clearance,
        label="Available Head Length",
    )
    radius_head_length_limit = _math(
        group,
        "MULTIPLY",
        radius,
        0.80,
        label="Radius-relative Head Length Limit",
    )
    maximum_head_length = _math(
        group,
        "MINIMUM",
        available_head_length,
        radius_head_length_limit,
        label="Maximum Head Length",
    )
    minimum_head_length = _math(
        group,
        "MULTIPLY",
        bar_width,
        1.25,
        label="Minimum Head Length",
    )
    head_length_floor = _math(
        group,
        "MAXIMUM",
        inputs.outputs["Arrow Head Length"],
        minimum_head_length,
        label="Minimum Head Length Clamp",
    )
    head_length = _math(
        group,
        "MINIMUM",
        head_length_floor,
        maximum_head_length,
        label="Safe Head Length",
    )
    return {
        "radius": radius,
        "arc_angle": arc_angle,
        "half_span": half_span,
        "shaft_half": shaft_half,
        "head_half": head_half,
        "head_length": head_length,
        "segments": inputs.outputs["Segments"],
    }


def _subdivide_flat_outline(
    group: Any,
    curve: Any,
    segments: Any,
    corner_count: int,
    *,
    label: str,
) -> Any:
    """Densely sample each flat edge while retaining every hard corner."""

    cuts_per_edge = group.nodes.new("FunctionNodeIntegerMath")
    cuts_per_edge.operation = "DIVIDE"
    cuts_per_edge.label = f"{label} Cuts per Edge"
    group.links.new(segments, cuts_per_edge.inputs[0])
    cuts_per_edge.inputs[1].default_value = corner_count
    minimum_cuts = group.nodes.new("FunctionNodeIntegerMath")
    minimum_cuts.operation = "MAXIMUM"
    minimum_cuts.label = f"{label} Minimum Cuts"
    group.links.new(cuts_per_edge.outputs[0], minimum_cuts.inputs[0])
    minimum_cuts.inputs[1].default_value = 1
    subdivide = group.nodes.new("GeometryNodeSubdivideCurve")
    subdivide.label = f"{label} Surface Samples"
    group.links.new(curve, subdivide.inputs["Curve"])
    group.links.new(minimum_cuts.outputs[0], subdivide.inputs["Cuts"])
    return subdivide.outputs["Curve"]


def _position_components(group: Any, *, label: str) -> tuple[Any, Any]:
    position = group.nodes.new("GeometryNodeInputPosition")
    position.label = f"{label} Flat UV Position"
    separate = group.nodes.new("ShaderNodeSeparateXYZ")
    separate.label = f"{label} Separate UV"
    group.links.new(position.outputs["Position"], separate.inputs["Vector"])
    return separate.outputs["X"], separate.outputs["Y"]


def _wrap_cylinder(group: Any, curve: Any, radius: Any) -> Any:
    """Map flat ``(u, v)`` to ``(R cos(u/R), R sin(u/R), v)``."""

    u, v = _position_components(group, label="Cylinder Wrap")
    theta = _math(group, "DIVIDE", u, radius, label="Cylinder Longitude")
    cosine = _math(group, "COSINE", theta, label="Cylinder Cosine")
    sine = _math(group, "SINE", theta, label="Cylinder Sine")
    x = _math(group, "MULTIPLY", radius, cosine, label="Cylinder X")
    y = _math(group, "MULTIPLY", radius, sine, label="Cylinder Y")
    wrapped = _vector(group, x, y, v, label="Cylinder Surface Position")
    set_position = group.nodes.new("GeometryNodeSetPosition")
    set_position.label = "Wrap Flat 1D Arrow onto Cylinder"
    group.links.new(curve, set_position.inputs["Geometry"])
    group.links.new(wrapped, set_position.inputs["Position"])
    return set_position.outputs["Geometry"]


def _wrap_sphere(group: Any, curve: Any, radius: Any) -> Any:
    """Azimuthal-equidistant map centered on local positive X."""

    u, v = _position_components(group, label="Sphere Wrap")
    u_squared = _math(group, "MULTIPLY", u, u, label="Sphere U Squared")
    v_squared = _math(group, "MULTIPLY", v, v, label="Sphere V Squared")
    rho_squared = _math(
        group, "ADD", u_squared, v_squared, label="Sphere Rho Squared"
    )
    rho = _math(group, "SQRT", rho_squared, label="Sphere Flat Radius")
    safe_rho = _math(
        group, "MAXIMUM", rho, 1.0e-6, label="Safe Sphere Flat Radius"
    )
    theta = _math(group, "DIVIDE", rho, radius, label="Sphere Geodesic Angle")
    cosine = _math(group, "COSINE", theta, label="Sphere Cosine")
    sine = _math(group, "SINE", theta, label="Sphere Sine")
    x = _math(group, "MULTIPLY", radius, cosine, label="Sphere X")
    tangent_radius = _math(
        group, "MULTIPLY", radius, sine, label="Sphere Tangent Radius"
    )
    u_direction = _math(
        group, "DIVIDE", u, safe_rho, label="Sphere U Direction"
    )
    v_direction = _math(
        group, "DIVIDE", v, safe_rho, label="Sphere V Direction"
    )
    y = _math(
        group, "MULTIPLY", tangent_radius, u_direction, label="Sphere Y"
    )
    z = _math(
        group, "MULTIPLY", tangent_radius, v_direction, label="Sphere Z"
    )
    wrapped = _vector(group, x, y, z, label="Sphere Surface Position")
    set_position = group.nodes.new("GeometryNodeSetPosition")
    set_position.label = "Wrap Flat 2D Arrow onto Sphere"
    group.links.new(curve, set_position.inputs["Geometry"])
    group.links.new(wrapped, set_position.inputs["Position"])
    return set_position.outputs["Geometry"]


def _build_spatial_arrow(
    family: SemanticWidgetFamily,
    *,
    spherical: bool,
) -> Any:
    group, inputs, output = _new_group(family)
    parameters = _safe_spatial_arrow_parameters(group, inputs)
    half_span = parameters["half_span"]
    if spherical:
        outline, corner_count = _arrow_2d_outline(
            group,
            half_span,
            half_span,
            parameters["shaft_half"],
            parameters["head_length"],
            parameters["head_half"],
            label="Flat 2D Four-way Arrow Source",
        )
    else:
        outline, corner_count = _arrow_1d_outline(
            group,
            half_span,
            parameters["shaft_half"],
            parameters["head_length"],
            parameters["head_half"],
            label="Flat 1D Double Arrow Source",
        )
    sampled = _subdivide_flat_outline(
        group,
        outline,
        parameters["segments"],
        corner_count,
        label="Wrapped Arrow",
    )
    wrapped = (
        _wrap_sphere(group, sampled, parameters["radius"])
        if spherical
        else _wrap_cylinder(group, sampled, parameters["radius"])
    )
    mesh = _curve_to_edge_mesh(group, wrapped, label=family.label)
    return _finish_group(group, output, mesh)


_GROUP_BUILDERS = {
    SemanticWidgetShape.ARROW_1D: _build_arrow_1d,
    SemanticWidgetShape.ARROW_2D: _build_arrow_2d,
    SemanticWidgetShape.CYLINDER_ARROW_1D: lambda family: _build_spatial_arrow(
        family, spherical=False
    ),
    SemanticWidgetShape.SPHERE_ARROW_2D: lambda family: _build_spatial_arrow(
        family, spherical=True
    ),
    SemanticWidgetShape.TOMBSTONE: _build_tombstone,
    SemanticWidgetShape.ELLIPSE: _build_ellipse,
    SemanticWidgetShape.TRIANGLE: lambda family: _build_rounded_polygon(
        family, vertex_count=3, rotation_z=math.pi * 0.5
    ),
    SemanticWidgetShape.RECTANGLE: _build_rectangle,
    SemanticWidgetShape.DIAMOND: lambda family: _build_rounded_polygon(
        family, vertex_count=4, rotation_z=0.0
    ),
    SemanticWidgetShape.SECTOR: _build_sector,
}


def expected_semantic_widget_node_group_names(
    shapes: Iterable[SemanticWidgetShape | str] | None = None,
) -> set[str]:
    selected = SemanticWidgetShape if shapes is None else (
        coerce_semantic_widget_shape(shape) for shape in shapes
    )
    return {semantic_widget_family(shape).group_name for shape in selected}


def _group_has_expected_interface(
    group: Any,
    family: SemanticWidgetFamily,
) -> bool:
    sockets = [
        item
        for item in group.interface.items_tree
        if getattr(item, "item_type", "") == "SOCKET"
    ]
    outputs = [
        (item.name, getattr(item, "socket_type", ""))
        for item in sockets
        if getattr(item, "in_out", "") == "OUTPUT"
    ]
    inputs = [
        (item.name, getattr(item, "socket_type", ""))
        for item in sockets
        if getattr(item, "in_out", "") == "INPUT"
    ]
    expected_inputs = [
        (parameter.name, parameter.socket_type)
        for parameter in family.parameters
    ]
    return outputs == [("Geometry", "NodeSocketGeometry")] and inputs == expected_inputs


def _is_current_group(group: Any, family: SemanticWidgetFamily) -> bool:
    return bool(
        group is not None
        and getattr(group, "bl_idname", "") == "GeometryNodeTree"
        and group.get("coa_semantic_widget_managed")
        and group.get("coa_semantic_widget_schema") == SEMANTIC_WIDGET_SCHEMA
        and group.get("coa_semantic_widget_version")
        == SEMANTIC_WIDGET_NODE_GROUP_VERSION
        and group.get("coa_semantic_widget_shape") == family.shape.value
        and group.get("coa_semantic_widget_topology") == family.topology
        and group.get("coa_semantic_widget_expected_faces") == 0
        and _group_has_expected_interface(group, family)
    )


def _unique_legacy_group_name(group_name: str, version: Any) -> str:
    blender = _require_bpy()
    suffix = "unknown" if version is None else str(version)
    base = f"{group_name}_legacy_v{suffix}"
    candidate = base
    index = 1
    while blender.data.node_groups.get(candidate) is not None:
        candidate = f"{base}_{index:03d}"
        index += 1
    return candidate


def _is_our_managed_group(group: Any) -> bool:
    return bool(
        group.get("coa_semantic_widget_managed")
        and str(group.get("coa_semantic_widget_schema", "")).startswith(
            "coa-tools2-semantic-widget-"
        )
    )


def ensure_semantic_widget_node_group(
    shape: SemanticWidgetShape | str,
) -> Any:
    """Idempotently ensure one current production node group.

    A stale group from this namespace is removed only when it has no users.
    Used groups, and any unrelated user group that happens to own the canonical
    name, are preserved under a unique ``_legacy`` name before rebuilding.
    State Rig groups are never inspected or modified.
    """

    blender = _require_bpy()
    family = semantic_widget_family(shape)
    existing = blender.data.node_groups.get(family.group_name)
    if _is_current_group(existing, family):
        return existing
    if existing is not None:
        if _is_our_managed_group(existing) and existing.users == 0:
            blender.data.node_groups.remove(existing)
        else:
            existing.name = _unique_legacy_group_name(
                family.group_name,
                existing.get("coa_semantic_widget_version"),
            )
    return _GROUP_BUILDERS[family.shape](family)


def ensure_semantic_widget_node_groups(
    shapes: Iterable[SemanticWidgetShape | str] | None = None,
) -> dict[SemanticWidgetShape, Any]:
    """Ensure all groups, or a requested subset, in enum declaration order."""

    selected = tuple(SemanticWidgetShape) if shapes is None else tuple(
        coerce_semantic_widget_shape(shape) for shape in shapes
    )
    return {
        shape: ensure_semantic_widget_node_group(shape)
        for shape in selected
    }


def semantic_widget_modifier_input_identifiers(
    node_group: Any,
) -> dict[str, str]:
    """Map public interface names to Blender modifier ID-property keys."""

    return {
        item.name: item.identifier
        for item in node_group.interface.items_tree
        if getattr(item, "item_type", "") == "SOCKET"
        and getattr(item, "in_out", "") == "INPUT"
    }


def _shape_from_node_group(node_group: Any) -> SemanticWidgetShape:
    if node_group is None:
        raise ValueError("Semantic Widget modifier has no node group")
    if not node_group.get("coa_semantic_widget_managed"):
        raise ValueError(f"{node_group.name!r} is not a managed Semantic Widget group")
    return coerce_semantic_widget_shape(node_group.get("coa_semantic_widget_shape"))


def apply_semantic_widget_parameters(
    modifier: Any,
    parameters: Mapping[str, float | int],
    *,
    shape: SemanticWidgetShape | str | None = None,
    clamp: bool = True,
    strict: bool = True,
) -> dict[str, float | int]:
    """Apply validated values to a Nodes modifier by public socket name.

    Passing ``shape`` also assigns the corresponding current node group.  The
    returned mapping contains the effective, type-normalized values.
    """

    _require_bpy()
    if getattr(modifier, "type", None) != "NODES":
        raise TypeError("Semantic Widget parameters require a Nodes modifier")
    if shape is None:
        resolved_shape = _shape_from_node_group(modifier.node_group)
    else:
        resolved_shape = coerce_semantic_widget_shape(shape)
        modifier.node_group = ensure_semantic_widget_node_group(resolved_shape)
    values = normalize_semantic_widget_parameters(
        resolved_shape,
        parameters,
        clamp=clamp,
        strict=strict,
    )
    identifiers = semantic_widget_modifier_input_identifiers(modifier.node_group)
    missing = set(values).difference(identifiers)
    if missing:
        raise RuntimeError(
            f"{modifier.node_group.name} is missing public inputs: "
            f"{', '.join(sorted(missing))}"
        )
    for name, value in values.items():
        modifier[identifiers[name]] = value
    modifier["coa_semantic_widget_managed"] = True
    modifier["coa_semantic_widget_schema"] = SEMANTIC_WIDGET_SCHEMA
    modifier["coa_semantic_widget_version"] = SEMANTIC_WIDGET_NODE_GROUP_VERSION
    modifier["coa_semantic_widget_shape"] = resolved_shape.value
    owner = getattr(modifier, "id_data", None)
    if owner is not None and hasattr(owner, "update_tag"):
        owner.update_tag()
    return values


def reset_semantic_widget_parameters(
    modifier: Any,
    *,
    shape: SemanticWidgetShape | str | None = None,
) -> dict[str, float | int]:
    resolved_shape = (
        _shape_from_node_group(modifier.node_group)
        if shape is None
        else coerce_semantic_widget_shape(shape)
    )
    return apply_semantic_widget_parameters(
        modifier,
        semantic_widget_parameter_defaults(resolved_shape),
        shape=resolved_shape,
    )


def semantic_widget_modifier_parameters(modifier: Any) -> dict[str, float | int]:
    """Read current public inputs using their stable socket names."""

    shape = _shape_from_node_group(modifier.node_group)
    family = semantic_widget_family(shape)
    identifiers = semantic_widget_modifier_input_identifiers(modifier.node_group)
    result: dict[str, float | int] = {}
    for parameter in family.parameters:
        identifier = identifiers[parameter.name]
        result[parameter.name] = modifier.get(identifier, parameter.default)
    return result


def find_semantic_widget_modifier(obj: Any) -> Any | None:
    """Find the managed Semantic Widget modifier owned by ``obj``."""

    stamped = []
    for modifier in obj.modifiers:
        if (
            modifier.type == "NODES"
            and modifier.get("coa_semantic_widget_managed")
            and modifier.get("coa_semantic_widget_schema") == SEMANTIC_WIDGET_SCHEMA
        ):
            stamped.append(modifier)
    if len(stamped) > 1:
        raise RuntimeError(
            f"{obj.name!r} has multiple managed Semantic Widget modifiers"
        )
    if stamped:
        return stamped[0]

    # Blender 5.1 does not persist arbitrary ID properties on a Nodes
    # modifier.  After loading a .blend, recover ownership only when both the
    # source Object and the assigned Node Group carry our durable markers;
    # never adopt an unrelated user modifier by name alone.
    source_owned = bool(
        obj.get("coa_rig_managed")
        and obj.get("coa_semantic_widget_schema") == SEMANTIC_WIDGET_SCHEMA
        and str(obj.get("coa_rig_component_role", "")).endswith(":source")
    )
    if not source_owned:
        return None
    recovered = [
        modifier
        for modifier in obj.modifiers
        if modifier.type == "NODES"
        and modifier.node_group is not None
        and modifier.node_group.get("coa_semantic_widget_managed")
        and modifier.node_group.get("coa_semantic_widget_schema")
        == SEMANTIC_WIDGET_SCHEMA
    ]
    if len(recovered) > 1:
        raise RuntimeError(
            f"{obj.name!r} has multiple recoverable Semantic Widget modifiers"
        )
    return recovered[0] if recovered else None


def ensure_semantic_widget_modifier(
    obj: Any,
    shape: SemanticWidgetShape | str,
    *,
    parameters: Mapping[str, float | int] | None = None,
    modifier_name: str = SEMANTIC_WIDGET_MODIFIER_NAME,
) -> Any:
    """Ensure and configure the per-source-object Geometry Nodes modifier.

    This function owns the modifier but intentionally does not create the Mesh
    object or assign it to a pose bone.  Artifact naming, collection ownership,
    and ``PoseBone.custom_shape`` assignment remain compiler responsibilities.
    """

    _require_bpy()
    if getattr(obj, "type", None) != "MESH" or not hasattr(obj, "modifiers"):
        raise TypeError("Semantic Widget source must be a Blender Mesh object")
    resolved_shape = coerce_semantic_widget_shape(shape)
    group = ensure_semantic_widget_node_group(resolved_shape)
    modifier = find_semantic_widget_modifier(obj)
    created = modifier is None
    if modifier is None:
        named = obj.modifiers.get(modifier_name)
        if (
            named is not None
            and named.type == "NODES"
            and (
                named.node_group is None
                or named.node_group.get("coa_semantic_widget_managed")
            )
        ):
            modifier = named
        else:
            modifier = obj.modifiers.new(modifier_name, "NODES")
    previous_shape = modifier.get("coa_semantic_widget_shape")
    group_changed = modifier.node_group != group
    modifier.node_group = group
    if created or group_changed or previous_shape != resolved_shape.value:
        reset_semantic_widget_parameters(modifier, shape=resolved_shape)
    if parameters:
        apply_semantic_widget_parameters(
            modifier,
            parameters,
            shape=resolved_shape,
        )
    modifier["coa_semantic_widget_managed"] = True
    modifier["coa_semantic_widget_schema"] = SEMANTIC_WIDGET_SCHEMA
    modifier["coa_semantic_widget_version"] = SEMANTIC_WIDGET_NODE_GROUP_VERSION
    modifier["coa_semantic_widget_shape"] = resolved_shape.value
    obj["coa_semantic_widget_shape"] = resolved_shape.value
    obj["coa_semantic_widget_schema"] = SEMANTIC_WIDGET_SCHEMA
    obj.update_tag()
    return modifier


__all__ = (
    "SEMANTIC_WIDGET_FAMILIES",
    "SEMANTIC_WIDGET_MODIFIER_NAME",
    "SEMANTIC_WIDGET_NODE_GROUP_VERSION",
    "SEMANTIC_WIDGET_SCHEMA",
    "SemanticWidgetFamily",
    "SemanticWidgetParameter",
    "SemanticWidgetShape",
    "apply_semantic_widget_parameters",
    "coerce_semantic_widget_shape",
    "ensure_semantic_widget_modifier",
    "ensure_semantic_widget_node_group",
    "ensure_semantic_widget_node_groups",
    "expected_semantic_widget_node_group_names",
    "find_semantic_widget_modifier",
    "normalize_semantic_widget_parameters",
    "reset_semantic_widget_parameters",
    "semantic_widget_family",
    "semantic_widget_modifier_input_identifiers",
    "semantic_widget_modifier_parameters",
    "semantic_widget_parameter_defaults",
)
