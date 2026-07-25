"""Pure data definitions for character posing rig components."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .schema import StringEnum


RIG_COMPONENT_SCHEMA_VERSION = 1


class RigComponentType(StringEnum):
    """Typed structural modules used to pose a character."""

    ROOT = "ROOT"
    FK_CHAIN = "FK_CHAIN"
    LIMB_IK = "LIMB_IK"
    SPINE_FK = "SPINE_FK"


class RigComponentSide(StringEnum):
    CENTER = "CENTER"
    LEFT = "LEFT"
    RIGHT = "RIGHT"


class RigOrientationMode(StringEnum):
    """How the control's rest axes are aligned."""

    WORLD_VIEW = "WORLD_VIEW"
    SOURCE_BONE = "SOURCE_BONE"
    CUSTOM = "CUSTOM"


class RigDepthMode(StringEnum):
    """How movement along the visual normal (control-local Z) is restricted."""

    LOCKED = "LOCKED"
    LIMITED = "LIMITED"
    FREE = "FREE"


class RigComponentWidget(StringEnum):
    ROOT = "ROOT"
    FK = "FK"
    HAND = "HAND"
    FOOT = "FOOT"
    SQUARE = "SQUARE"


class RigSolverMode(StringEnum):
    SPATIAL = "SPATIAL"
    PLANAR = "PLANAR"


class RigBendAxis(StringEnum):
    AUTO = "AUTO"
    X = "X"
    Y = "Y"
    Z = "Z"


class RigEndRotationMode(StringEnum):
    COPY_WORLD = "COPY_WORLD"
    COPY_LOCAL = "COPY_LOCAL"
    NONE = "NONE"


@dataclass(frozen=True)
class RigComponentSpec:
    """Blender-independent definition of a character posing component.

    The control-local XY plane represents the artwork plane. Control-local Z
    is its visual normal/depth axis. ``SOURCE_BONE`` copies those axes from the
    reference bone, allowing a hand or foot control to follow the apparent
    orientation of the cutout art instead of the camera plane.
    """

    component_uuid: str
    semantic_id: str
    display_name: str
    component_type: RigComponentType
    source_bones: tuple[str, ...]
    side: RigComponentSide = RigComponentSide.CENTER
    orientation_mode: RigOrientationMode = RigOrientationMode.SOURCE_BONE
    orientation_reference: str = ""
    orientation_euler: tuple[float, float, float] = (0.0, 0.0, 0.0)
    depth_mode: RigDepthMode = RigDepthMode.LIMITED
    depth_min: float = -0.25
    depth_max: float = 0.25
    allow_translation: tuple[bool, bool, bool] = (True, True, True)
    allow_rotation: tuple[bool, bool, bool] = (True, True, True)
    widget: RigComponentWidget = RigComponentWidget.SQUARE
    widget_size: float = 1.0
    ik_chain_length: int = 2
    solver_mode: RigSolverMode = RigSolverMode.SPATIAL
    bend_axis: RigBendAxis = RigBendAxis.AUTO
    use_bend_hint: bool = True
    pole_distance: float = 1.0
    use_stretch: bool = False
    end_rotation_mode: RigEndRotationMode = RigEndRotationMode.COPY_WORLD
    enabled: bool = True
    schema_version: int = RIG_COMPONENT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["component_type"] = self.component_type.value
        data["side"] = self.side.value
        data["orientation_mode"] = self.orientation_mode.value
        data["depth_mode"] = self.depth_mode.value
        data["widget"] = self.widget.value
        data["solver_mode"] = self.solver_mode.value
        data["bend_axis"] = self.bend_axis.value
        data["end_rotation_mode"] = self.end_rotation_mode.value
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RigComponentSpec":
        values = dict(data)
        values["component_type"] = RigComponentType(values["component_type"])
        values["side"] = RigComponentSide(values.get("side", "CENTER"))
        values["orientation_mode"] = RigOrientationMode(
            values.get("orientation_mode", "SOURCE_BONE")
        )
        values["depth_mode"] = RigDepthMode(values.get("depth_mode", "LIMITED"))
        values["widget"] = RigComponentWidget(values.get("widget", "SQUARE"))
        values["solver_mode"] = RigSolverMode(values.get("solver_mode", "SPATIAL"))
        values["bend_axis"] = RigBendAxis(values.get("bend_axis", "AUTO"))
        values["end_rotation_mode"] = RigEndRotationMode(
            values.get("end_rotation_mode", "COPY_WORLD")
        )
        values["source_bones"] = tuple(values.get("source_bones", ()))
        values["orientation_euler"] = tuple(
            values.get("orientation_euler", (0.0, 0.0, 0.0))
        )
        values["allow_translation"] = tuple(
            values.get("allow_translation", (True, True, True))
        )
        values["allow_rotation"] = tuple(
            values.get("allow_rotation", (True, True, True))
        )
        return cls(**values)
