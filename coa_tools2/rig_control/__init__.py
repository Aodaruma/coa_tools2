"""COA Tools 2 rig-control domain package.

Modules at this package level must stay importable without Blender so the
definition and validation layers can be tested with standard Python.
"""

from .schema import (
    SCHEMA_VERSION,
    BindingSpec,
    ControlAxis,
    ControlSpec,
    ControlType,
    StateDataSpec,
    StateCellSpec,
    StateMixPolicy,
    StateMode,
    StatePointSpec,
    TargetKind,
    WidgetBackend,
    WidgetLayout,
    WidgetSpec,
)
from .component_schema import (
    RIG_COMPONENT_SCHEMA_VERSION,
    RigComponentSide,
    RigComponentSpec,
    RigComponentType,
    RigComponentWidget,
    RigDepthMode,
    RigOrientationMode,
)

__all__ = [
    "SCHEMA_VERSION",
    "RIG_COMPONENT_SCHEMA_VERSION",
    "BindingSpec",
    "ControlAxis",
    "ControlSpec",
    "ControlType",
    "RigComponentSide",
    "RigComponentSpec",
    "RigComponentType",
    "RigComponentWidget",
    "RigDepthMode",
    "RigOrientationMode",
    "StateDataSpec",
    "StateCellSpec",
    "StateMixPolicy",
    "StateMode",
    "StatePointSpec",
    "TargetKind",
    "WidgetBackend",
    "WidgetLayout",
    "WidgetSpec",
]
