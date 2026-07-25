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
    RigComponentOutputSpec,
    RigDeformationMode,
    RigComponentSide,
    RigComponentSpec,
    RigComponentType,
    RigComponentWidget,
    RigBendAxis,
    RigDepthMode,
    RigEndRotationMode,
    RigOrientationMode,
    RigParameterChannel,
    RigSolverMode,
)

__all__ = [
    "SCHEMA_VERSION",
    "RIG_COMPONENT_SCHEMA_VERSION",
    "BindingSpec",
    "ControlAxis",
    "ControlSpec",
    "ControlType",
    "RigComponentOutputSpec",
    "RigDeformationMode",
    "RigComponentSide",
    "RigComponentSpec",
    "RigComponentType",
    "RigComponentWidget",
    "RigBendAxis",
    "RigDepthMode",
    "RigEndRotationMode",
    "RigOrientationMode",
    "RigParameterChannel",
    "RigSolverMode",
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
