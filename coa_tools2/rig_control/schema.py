"""Pure data definitions for COA Tools 2 rig controls."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import math
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1


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


class StateMixPolicy(StringEnum):
    FULL = "FULL"


class WidgetLayout(StringEnum):
    TIP = "TIP"
    LINEAR = "LINEAR"
    RECTANGLE = "RECTANGLE"
    RECTANGLE_GRID = "RECTANGLE_GRID"
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

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["layout"] = self.layout.value
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WidgetSpec":
        values = dict(data)
        values["layout"] = WidgetLayout(values["layout"])
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StatePointSpec":
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

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["mode"] = self.mode.value
        data["mix_policy"] = self.mix_policy.value
        data["points"] = [point.to_dict() for point in self.points]
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StateDataSpec":
        values = dict(data)
        values["mode"] = StateMode(values["mode"])
        values["mix_policy"] = StateMixPolicy(values.get("mix_policy", "FULL"))
        values["points"] = tuple(
            StatePointSpec.from_dict(point) for point in values.get("points", ())
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
