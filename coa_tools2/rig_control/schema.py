"""Pure data definitions for COA Tools 2 rig controls."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping


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


class WidgetLayout(StringEnum):
    TIP = "TIP"
    LINEAR = "LINEAR"
    RECTANGLE = "RECTANGLE"
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
    tip_radius: float = 0.28
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
