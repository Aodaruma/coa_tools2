"""Pure data definitions for COA Tools 2 rig controls."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import math
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 2


class StringEnum(str, Enum):
    """Enum whose serialized representation is its string value."""


class ControlType(StringEnum):
    SLIDER_1D = "SLIDER_1D"
    POINT_2D_RECT = "POINT_2D_RECT"
    POINT_2D_CIRCLE = "POINT_2D_CIRCLE"
    DIAL = "DIAL"


class ControlAxis(StringEnum):
    X = "X"
    Y = "Y"
    ROTATION = "ROTATION"


class TargetKind(StringEnum):
    SHAPE_KEY_VALUE = "SHAPE_KEY_VALUE"
    CONSTRAINT_INFLUENCE = "CONSTRAINT_INFLUENCE"


class StateMode(StringEnum):
    NONE = "NONE"
    LINEAR_1D = "LINEAR_1D"
    MATRIX_2D = "MATRIX_2D"
    GRAPH_2D = "GRAPH_2D"


class GraphInterpolation(StringEnum):
    """How an arbitrary two-dimensional State Graph is evaluated."""

    NAMED_GRAPH = "NAMED_GRAPH"
    MAP_2D = "MAP_2D"
    HYBRID = "HYBRID"


class GraphPointShape(StringEnum):
    """Presentation hint for a named graph point."""

    CIRCLE = "CIRCLE"
    DIAMOND = "DIAMOND"
    TRIANGLE = "TRIANGLE"
    SQUARE = "SQUARE"
    CUSTOM_OBJECT = "CUSTOM_OBJECT"


class LipSyncPreset(StringEnum):
    NONE = "NONE"
    MINIMAL = "MINIMAL"
    JP_VOWELS = "JP_VOWELS"
    JP_VOWELS_MBP = "JP_VOWELS_MBP"
    STANDARD_2D = "STANDARD_2D"
    ADVANCED_PHONEME = "ADVANCED_PHONEME"


class StateMixPolicy(StringEnum):
    FULL = "FULL"
    NO_MIX = "NO_MIX"
    PARTIAL = "PARTIAL"


class WidgetLayout(StringEnum):
    TIP = "TIP"
    LINEAR = "LINEAR"
    RECTANGLE = "RECTANGLE"
    RECTANGLE_GRID = "RECTANGLE_GRID"
    MATRIX = "MATRIX"
    GRAPH = "GRAPH"
    CIRCLE = "CIRCLE"
    DIAL = "DIAL"


class WidgetBackend(StringEnum):
    AUTO = "AUTO"
    LIVE_MODIFIER = "LIVE_MODIFIER"
    EVALUATED_MESH_CACHE = "EVALUATED_MESH_CACHE"


@dataclass(frozen=True)
class WidgetSpec:
    widget_uuid: str
    layout: WidgetLayout
    width: float = 4.0
    height: float = 2.0
    radius: float = 2.0
    tip_radius: float = 0.68
    node_radius: float = 0.34
    bar_width: float = 0.28
    stroke_radius: float = 0.035
    columns: int = 2
    rows: int = 2
    arc_start: float = 0.0
    arc_end: float = 6.283185307179586
    schema_version: int = SCHEMA_VERSION
    mix_cells: tuple[bool, ...] | None = None
    graph_points: tuple[tuple[float, float], ...] = ()
    graph_edges: tuple[tuple[int, int], ...] = ()
    graph_point_shapes: tuple[GraphPointShape, ...] = ()
    graph_custom_object_names: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["layout"] = self.layout.value
        data["graph_point_shapes"] = [
            shape.value for shape in self.graph_point_shapes
        ]
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WidgetSpec":
        values = dict(data)
        values["layout"] = WidgetLayout(values["layout"])
        if values.get("mix_cells") is not None:
            values["mix_cells"] = tuple(values["mix_cells"])
        values["graph_points"] = tuple(
            tuple(point) for point in values.get("graph_points", ())
        )
        values["graph_edges"] = tuple(
            tuple(edge) for edge in values.get("graph_edges", ())
        )
        values["graph_point_shapes"] = tuple(
            GraphPointShape(shape)
            for shape in values.get("graph_point_shapes", ())
        )
        values["graph_custom_object_names"] = tuple(
            values.get("graph_custom_object_names", ())
        )
        return cls(**values)


def dial_rest_angle(angle_min: float, angle_max: float) -> float:
    """Choose the neutral dial angle while staying inside its rail."""

    return min(max(0.0, angle_min), angle_max)


def dial_point(radius: float, angle: float) -> tuple[float, float]:
    """Return dial-plane coordinates where angle zero is at the top."""

    return (-math.sin(angle) * radius, math.cos(angle) * radius)


@dataclass(frozen=True)
class ControlSpec:
    control_uuid: str
    semantic_id: str
    display_name: str
    control_type: ControlType
    axis: ControlAxis
    control_bone: str
    display_bone: str
    widget_spec_id: str
    value_min: tuple[float, float] = (-1.0, 0.0)
    value_max: tuple[float, float] = (1.0, 0.0)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["control_type"] = self.control_type.value
        data["axis"] = self.axis.value
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ControlSpec":
        values = dict(data)
        values["control_type"] = ControlType(values["control_type"])
        values["axis"] = ControlAxis(values["axis"])
        values["value_min"] = tuple(values["value_min"])
        values["value_max"] = tuple(values["value_max"])
        return cls(**values)


@dataclass(frozen=True)
class BindingSpec:
    binding_uuid: str
    control_uuid: str
    source_component: ControlAxis
    target_kind: TargetKind
    target_object_name: str
    target_name: str
    input_min: float = -1.0
    input_max: float = 1.0
    output_min: float = 0.0
    output_max: float = 1.0
    clamp: bool = True
    enabled: bool = True
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_component"] = self.source_component.value
        data["target_kind"] = self.target_kind.value
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BindingSpec":
        values = dict(data)
        values["source_component"] = ControlAxis(values["source_component"])
        values["target_kind"] = TargetKind(values["target_kind"])
        return cls(**values)


@dataclass(frozen=True)
class StatePointSpec:
    state_uuid: str
    control_uuid: str
    column: int
    row: int
    display_name: str = ""
    target_object_name: str = ""
    target_name: str = ""
    is_empty: bool = False
    enabled: bool = True
    schema_version: int = SCHEMA_VERSION
    position: tuple[float, float] = (0.0, 0.0)
    point_shape: GraphPointShape = GraphPointShape.CIRCLE
    custom_object_name: str = ""
    fallback_state_uuid: str = ""
    target_name_candidates: tuple[str, ...] = ()
    phoneme_aliases: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["point_shape"] = self.point_shape.value
        data["position"] = list(self.position)
        data["target_name_candidates"] = list(self.target_name_candidates)
        data["phoneme_aliases"] = list(self.phoneme_aliases)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StatePointSpec":
        values = dict(data)
        values["position"] = tuple(values.get("position", (0.0, 0.0)))
        values["point_shape"] = GraphPointShape(
            values.get("point_shape", GraphPointShape.CIRCLE)
        )
        values["target_name_candidates"] = tuple(
            values.get("target_name_candidates", ())
        )
        values["phoneme_aliases"] = tuple(values.get("phoneme_aliases", ()))
        return cls(**values)


@dataclass(frozen=True)
class StateCellSpec:
    cell_uuid: str
    control_uuid: str
    column: int
    row: int
    mix_enabled: bool = True
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StateCellSpec":
        return cls(**dict(data))


@dataclass(frozen=True)
class StateDataSpec:
    control_uuid: str
    mode: StateMode
    columns: int
    rows: int
    points: tuple[StatePointSpec, ...] = ()
    mix_policy: StateMixPolicy = StateMixPolicy.FULL
    schema_version: int = SCHEMA_VERSION
    cells: tuple[StateCellSpec, ...] = ()
    graph_interpolation: GraphInterpolation = GraphInterpolation.MAP_2D
    graph_radius: float = 0.75
    lip_sync_preset: LipSyncPreset = LipSyncPreset.NONE

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["mode"] = self.mode.value
        data["mix_policy"] = self.mix_policy.value
        data["graph_interpolation"] = self.graph_interpolation.value
        data["lip_sync_preset"] = self.lip_sync_preset.value
        data["points"] = [point.to_dict() for point in self.points]
        data["cells"] = [cell.to_dict() for cell in self.cells]
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StateDataSpec":
        values = dict(data)
        values["mode"] = StateMode(values["mode"])
        values["mix_policy"] = StateMixPolicy(values.get("mix_policy", "FULL"))
        values["graph_interpolation"] = GraphInterpolation(
            values.get("graph_interpolation", GraphInterpolation.MAP_2D)
        )
        values["lip_sync_preset"] = LipSyncPreset(
            values.get("lip_sync_preset", LipSyncPreset.NONE)
        )
        values["points"] = tuple(
            StatePointSpec.from_dict(point) for point in values.get("points", ())
        )
        values["cells"] = tuple(
            StateCellSpec.from_dict(cell) for cell in values.get("cells", ())
        )
        return cls(**values)


def state_grid_size(mode: StateMode | str, columns: int, rows: int) -> tuple[int, int]:
    """Return normalized StateData dimensions for a supported control mode."""

    mode = StateMode(mode)
    if mode == StateMode.NONE:
        return 0, 0
    columns = max(2, int(columns))
    if mode == StateMode.LINEAR_1D:
        return columns, 1
    if mode == StateMode.GRAPH_2D:
        return max(1, int(columns)), max(1, int(rows))
    return columns, max(2, int(rows))


def state_point_position(
    column: int,
    row: int,
    columns: int,
    rows: int,
) -> tuple[float, float]:
    """Return a grid point in normalized 0..1 control space."""

    columns, rows = max(2, columns), max(1, rows)
    x = min(max(column, 0), columns - 1) / (columns - 1)
    y = 0.0 if rows == 1 else min(max(row, 0), rows - 1) / (rows - 1)
    return x, y


def hat_basis(value: float, index: int, count: int) -> float:
    """Evaluate the piecewise-linear basis used by 1D and matrix states."""

    count = max(2, int(count))
    coordinate = min(max(float(value), 0.0), 1.0) * (count - 1)
    return max(1.0 - abs(coordinate - int(index)), 0.0)


def state_weights(
    u: float,
    v: float,
    columns: int,
    rows: int,
) -> tuple[float, ...]:
    """Evaluate row-major FULL-mix StateData weights."""

    columns, rows = state_grid_size(
        StateMode.LINEAR_1D if rows == 1 else StateMode.MATRIX_2D,
        columns,
        rows,
    )
    return tuple(
        hat_basis(u, column, columns)
        * (1.0 if rows == 1 else hat_basis(v, row, rows))
        for row in range(rows)
        for column in range(columns)
    )


@dataclass(frozen=True)
class LipSyncPointTemplate:
    """A target-agnostic named mouth state used by preset generators."""

    name: str
    position: tuple[float, float]
    target_name_candidates: tuple[str, ...]
    phoneme_aliases: tuple[str, ...] = ()
    fallback_name: str = "REST"
    point_shape: GraphPointShape = GraphPointShape.CIRCLE


def _lip_point(
    name: str,
    position: tuple[float, float],
    aliases: Sequence[str] = (),
    *,
    fallback: str = "REST",
    point_shape: GraphPointShape = GraphPointShape.CIRCLE,
) -> LipSyncPointTemplate:
    candidates = (
        name,
        f"Mouth_{name}",
        f"mouth_{name.lower()}",
        f"Viseme_{name}",
    )
    return LipSyncPointTemplate(
        name,
        position,
        candidates,
        tuple(str(alias).upper() for alias in aliases),
        fallback,
        point_shape,
    )


_LIP_SYNC_COMMON = {
    "REST": _lip_point(
        "REST",
        (0.5, 0.0),
        ("REST", "SIL", "SP", "PAUSE", "_"),
        fallback="REST",
        point_shape=GraphPointShape.DIAMOND,
    ),
    "A": _lip_point("A", (0.5, 1.0), ("A", "AA", "AH")),
    "I": _lip_point("I", (0.05, 0.66), ("I", "IH", "IY", "Y")),
    "U": _lip_point("U", (0.88, 0.50), ("U", "UH", "UW")),
    "E": _lip_point("E", (0.15, 0.82), ("E", "EH", "EY")),
    "O": _lip_point("O", (0.92, 0.84), ("O", "AO", "OW")),
    "MBP": _lip_point("MBP", (0.5, 0.14), ("M", "B", "P")),
    "ETC": _lip_point(
        "ETC",
        (0.5, 0.48),
        (
            "ETC",
            "T",
            "D",
            "K",
            "G",
            "N",
            "NG",
            "R",
            "S",
            "Z",
            "SH",
            "ZH",
            "CH",
            "JH",
            "TH",
            "DH",
            "H",
        ),
    ),
    "AI": _lip_point(
        "AI",
        (0.28, 0.96),
        ("A", "I", "AA", "AE", "AH", "AY", "IH", "IY", "Y"),
        fallback="ETC",
    ),
    "FV": _lip_point("FV", (0.16, 0.34), ("F", "V"), fallback="ETC"),
    "L": _lip_point("L", (0.43, 0.72), ("L", "EL"), fallback="ETC"),
    "WQ": _lip_point("WQ", (0.84, 0.40), ("W", "Q"), fallback="U"),
}


def lip_sync_preset_points(
    preset: LipSyncPreset | str,
    *,
    include_optional: bool = False,
) -> tuple[LipSyncPointTemplate, ...]:
    """Return stable named points without creating or requiring Shape Keys."""

    preset = LipSyncPreset(preset)
    if preset == LipSyncPreset.NONE:
        return ()
    if preset == LipSyncPreset.MINIMAL:
        return (
            _LIP_SYNC_COMMON["REST"],
            _lip_point("A_E", (0.42, 0.92), ("A", "E", "AA", "AH", "EH")),
            _LIP_SYNC_COMMON["I"],
            _lip_point("U_O", (0.90, 0.72), ("U", "O", "UH", "UW", "OW")),
        )
    if preset in {LipSyncPreset.JP_VOWELS, LipSyncPreset.JP_VOWELS_MBP}:
        names = ["REST", "A", "I", "U", "E", "O"]
        if preset == LipSyncPreset.JP_VOWELS_MBP:
            names.append("MBP")
        return tuple(_LIP_SYNC_COMMON[name] for name in names)

    names = ["REST", "MBP", "ETC", "E", "AI", "O", "U"]
    if include_optional or preset == LipSyncPreset.ADVANCED_PHONEME:
        names.extend(("FV", "L", "WQ"))
    return tuple(_LIP_SYNC_COMMON[name] for name in names)


def phoneme_viseme_alias_map(
    preset: LipSyncPreset | str,
    *,
    include_optional: bool = False,
) -> dict[str, str]:
    """Return a normalized alias-to-viseme map for manual/external timing data."""

    result: dict[str, str] = {}
    for point in lip_sync_preset_points(
        preset,
        include_optional=include_optional,
    ):
        result.setdefault(point.name.upper(), point.name)
        for alias in point.phoneme_aliases:
            result.setdefault(alias.upper(), point.name)
    return result


def resolve_phoneme_viseme(
    phoneme: str,
    preset: LipSyncPreset | str,
    *,
    include_optional: bool = False,
) -> str:
    """Resolve one phoneme token and return a stable preset fallback."""

    preset = LipSyncPreset(preset)
    mapping = phoneme_viseme_alias_map(
        preset,
        include_optional=include_optional,
    )
    token = str(phoneme).strip().upper()
    if token in mapping:
        return mapping[token]
    templates = lip_sync_preset_points(
        preset,
        include_optional=include_optional,
    )
    names = {point.name for point in templates}
    return "ETC" if "ETC" in names else "REST" if "REST" in names else ""


def graph_fallback_edges(
    points: Sequence[StatePointSpec],
) -> tuple[tuple[int, int], ...]:
    """Return explicit edges plus deterministic nearest links for isolated points."""

    enabled = [index for index, point in enumerate(points) if point.enabled]
    by_uuid = {
        point.state_uuid: index
        for index, point in enumerate(points)
        if point.enabled and point.state_uuid
    }
    edges: set[tuple[int, int]] = set()
    for index in enabled:
        fallback = by_uuid.get(points[index].fallback_state_uuid)
        if fallback is None or fallback == index:
            continue
        edges.add(tuple(sorted((index, fallback))))

    # A named graph must remain operable even while an author is still filling
    # its edge metadata. Connect isolated points to their nearest peer only;
    # explicit authored topology is otherwise left untouched.
    connected = {index for edge in edges for index in edge}
    for index in enabled:
        if index in connected or len(enabled) < 2:
            continue
        x, y = points[index].position
        nearest = min(
            (candidate for candidate in enabled if candidate != index),
            key=lambda candidate: (
                (points[candidate].position[0] - x) ** 2
                + (points[candidate].position[1] - y) ** 2,
                candidate,
            ),
        )
        edge = tuple(sorted((index, nearest)))
        edges.add(edge)
        connected.update(edge)
    return tuple(sorted(edges))


def _graph_radial_weights(
    x: float,
    y: float,
    points: Sequence[StatePointSpec],
    radius: float,
) -> tuple[float, ...]:
    result = [0.0] * len(points)
    enabled = [index for index, point in enumerate(points) if point.enabled]
    if not enabled:
        return tuple(result)
    distances = {
        index: (
            (float(x) - float(points[index].position[0])) ** 2
            + (float(y) - float(points[index].position[1])) ** 2
        )
        for index in enabled
    }
    nearest = min(enabled, key=lambda index: (distances[index], index))
    if distances[nearest] <= 1.0e-12:
        result[nearest] = 1.0
        return tuple(result)
    radius = max(float(radius), 1.0e-6)
    radius_squared = radius * radius
    raw = {
        index: 1.0 / (1.0 + distances[index] / radius_squared) ** 2
        for index in enabled
    }
    total = sum(raw.values())
    if total <= 1.0e-12:
        result[nearest] = 1.0
        return tuple(result)
    for index, value in raw.items():
        result[index] = value / total
    return tuple(result)


def _graph_edge_weights(
    x: float,
    y: float,
    points: Sequence[StatePointSpec],
) -> tuple[float, ...]:
    result = [0.0] * len(points)
    edges = graph_fallback_edges(points)
    if not edges:
        return _graph_radial_weights(x, y, points, 1.0e-6)
    raw = [0.0] * len(points)
    for start, end in edges:
        ax, ay = points[start].position
        bx, by = points[end].position
        dx, dy = bx - ax, by - ay
        length_squared = dx * dx + dy * dy
        if length_squared <= 1.0e-12:
            t = 0.0
            projected_x, projected_y = ax, ay
        else:
            t = min(
                max(((x - ax) * dx + (y - ay) * dy) / length_squared, 0.0),
                1.0,
            )
            projected_x = ax + t * dx
            projected_y = ay + t * dy
        distance_squared = (x - projected_x) ** 2 + (y - projected_y) ** 2
        closeness = 1.0 / (distance_squared + 1.0e-9)
        raw[start] += closeness * (1.0 - t)
        raw[end] += closeness * t
    total = sum(raw)
    if total <= 1.0e-12:
        return _graph_radial_weights(x, y, points, 1.0e-6)
    for index, value in enumerate(raw):
        result[index] = value / total
    return tuple(result)


def _inside_convex_hull(
    x: float,
    y: float,
    positions: Sequence[tuple[float, float]],
) -> bool:
    unique = sorted(set(positions))
    if len(unique) < 3:
        return False

    def cross(origin, a, b):
        return (
            (a[0] - origin[0]) * (b[1] - origin[1])
            - (a[1] - origin[1]) * (b[0] - origin[0])
        )

    lower = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0.0:
            lower.pop()
        lower.append(point)
    upper = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0.0:
            upper.pop()
        upper.append(point)
    hull = lower[:-1] + upper[:-1]
    if len(hull) < 3:
        return False
    query = (float(x), float(y))
    return all(
        cross(hull[index], hull[(index + 1) % len(hull)], query) >= -1.0e-9
        for index in range(len(hull))
    )


def graph_state_weights(
    x: float,
    y: float,
    points: Sequence[StatePointSpec],
    interpolation: GraphInterpolation | str = GraphInterpolation.MAP_2D,
    radius: float = 0.75,
) -> tuple[float, ...]:
    """Evaluate arbitrary named graph points in normalized control space."""

    interpolation = GraphInterpolation(interpolation)
    if interpolation == GraphInterpolation.NAMED_GRAPH:
        return _graph_edge_weights(float(x), float(y), points)
    if interpolation == GraphInterpolation.HYBRID:
        radial = _graph_radial_weights(float(x), float(y), points, radius)
        edge = _graph_edge_weights(float(x), float(y), points)
        enabled = [point for point in points if point.enabled]
        if not enabled:
            return radial
        minimum_distance = min(
            (float(x) - float(point.position[0])) ** 2
            + (float(y) - float(point.position[1])) ** 2
            for point in enabled
        )
        influence = min(
            max(minimum_distance / max(float(radius) ** 2, 1.0e-12), 0.0),
            1.0,
        )
        return tuple(
            (1.0 - influence) * radial_value + influence * edge_value
            for radial_value, edge_value in zip(radial, edge)
        )
    return _graph_radial_weights(float(x), float(y), points, radius)


def validate_graph_state_points(
    points: Sequence[StatePointSpec],
) -> tuple[str, ...]:
    """Return stable validation codes for arbitrary named Graph State points."""

    issues: list[str] = []
    enabled = [point for point in points if point.enabled]
    ids = [point.state_uuid for point in enabled]
    if len(enabled) < 2:
        issues.append("state.graph_too_few_points")
    if any(not state_uuid for state_uuid in ids) or len(ids) != len(set(ids)):
        issues.append("state.invalid_uuid")
    labels = [point.display_name.strip().casefold() for point in enabled]
    if any(not label for label in labels):
        issues.append("state.graph_unnamed_point")
    if len(labels) != len(set(labels)):
        issues.append("state.graph_duplicate_name")
    if any(
        len(point.position) != 2
        or not all(math.isfinite(float(value)) for value in point.position)
        for point in enabled
    ):
        issues.append("state.graph_invalid_position")
    known = set(ids)
    if any(
        point.fallback_state_uuid
        and (
            point.fallback_state_uuid == point.state_uuid
            or point.fallback_state_uuid not in known
        )
        for point in enabled
    ):
        issues.append("state.graph_invalid_fallback")
    if any(
        not point.is_empty
        and (not point.target_object_name or not point.target_name)
        for point in enabled
    ):
        issues.append("state.unassigned_point")
    return tuple(issues)


def validate_state_points(
    points: Sequence[StatePointSpec],
    columns: int,
    rows: int,
) -> tuple[str, ...]:
    """Return stable validation codes for the pure StateData layout."""

    issues: list[str] = []
    expected = {(column, row) for row in range(rows) for column in range(columns)}
    coordinates = [(point.column, point.row) for point in points]
    if len(coordinates) != len(set(coordinates)):
        issues.append("state.duplicate_coordinate")
    if set(coordinates) != expected:
        issues.append("state.incomplete_grid")
    if any(
        point.enabled
        and not point.is_empty
        and (not point.target_object_name or not point.target_name)
        for point in points
    ):
        issues.append("state.unassigned_point")
    return tuple(issues)


def state_cell_grid_size(columns: int, rows: int) -> tuple[int, int]:
    """Return the number of four-point cells in a matrix state grid."""

    return max(0, int(columns) - 1), max(0, int(rows) - 1)


def summarize_state_mix(cells: Sequence[StateCellSpec | Any]) -> StateMixPolicy:
    """Return the preset that exactly describes a persisted cell mask."""

    enabled = [bool(cell.mix_enabled) for cell in cells]
    if enabled and all(enabled):
        return StateMixPolicy.FULL
    if not enabled or not any(enabled):
        return StateMixPolicy.NO_MIX
    return StateMixPolicy.PARTIAL


def validate_state_cells(
    cells: Sequence[StateCellSpec],
    columns: int,
    rows: int,
) -> tuple[str, ...]:
    """Return stable validation codes for the matrix domain cell mask."""

    cell_columns, cell_rows = state_cell_grid_size(columns, rows)
    expected = {
        (column, row)
        for row in range(cell_rows)
        for column in range(cell_columns)
    }
    coordinates = [(cell.column, cell.row) for cell in cells]
    issues: list[str] = []
    if len(coordinates) != len(set(coordinates)):
        issues.append("state.duplicate_cell")
    if set(coordinates) != expected:
        issues.append("state.incomplete_cell_grid")
    return tuple(issues)
