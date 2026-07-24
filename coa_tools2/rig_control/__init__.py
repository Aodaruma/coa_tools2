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

__all__ = [
    "SCHEMA_VERSION",
    "BindingSpec",
    "ControlAxis",
    "ControlSpec",
    "ControlType",
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
