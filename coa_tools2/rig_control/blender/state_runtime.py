"""Short, reload-safe Blender driver runtime for arbitrary Graph States."""

from __future__ import annotations

import json
import math

import bpy

from ..schema import (
    GraphInterpolation,
    GraphPointShape,
    StatePointSpec,
    graph_state_weights,
)


GRAPH_STATE_NAMESPACE_NAME = "coa_graph_state_weight"


def _rig_data(armature):
    return getattr(armature, "coa_tools2_rig", None)


def _find_control(rig_instance_uuid: str, control_uuid: str):
    """Resolve persisted IDs on every call so rename/copy/load stays correct."""

    for obj in bpy.data.objects:
        if getattr(obj, "type", "") != "ARMATURE":
            continue
        rig_data = _rig_data(obj)
        if rig_data is None or rig_data.rig_instance_id != rig_instance_uuid:
            continue
        for control in rig_data.rig_controls:
            if control.control_uuid == control_uuid:
                return control
    return None


def _point_specs(control) -> tuple[StatePointSpec, ...]:
    result = []
    for index, point in enumerate(control.state_points):
        result.append(
            StatePointSpec(
                state_uuid=point.state_uuid,
                control_uuid=control.control_uuid,
                column=index,
                row=0,
                display_name=point.label,
                target_object_name=(
                    point.target_object.name if point.target_object else ""
                ),
                target_name=point.target_name,
                is_empty=point.is_empty,
                enabled=point.enabled,
                position=tuple(float(value) for value in point.graph_position),
                point_shape=GraphPointShape(point.point_shape),
                custom_object_name=(
                    point.custom_object.name if point.custom_object else ""
                ),
                fallback_state_uuid=point.fallback_state_uuid,
                target_name_candidates=tuple(
                    candidate.strip()
                    for candidate in point.target_name_candidates.split(",")
                    if candidate.strip()
                ),
                phoneme_aliases=tuple(
                    alias.strip()
                    for alias in point.phoneme_aliases.split(",")
                    if alias.strip()
                ),
            )
        )
    return tuple(result)


def evaluate_graph_state_weight(
    rig_instance_uuid: str,
    control_uuid: str,
    state_uuid: str,
    state_x: float,
    state_y: float,
) -> float:
    """Driver-safe lookup; missing or malformed persisted data evaluates to 0."""

    try:
        control = _find_control(str(rig_instance_uuid), str(control_uuid))
        if control is None or control.state_mode != "GRAPH_2D":
            return 0.0
        width = float(control.width)
        height = float(control.height)
        if width <= 1.0e-12 or height <= 1.0e-12:
            return 0.0
        specs = _point_specs(control)
        index = next(
            index
            for index, point in enumerate(specs)
            if point.state_uuid == str(state_uuid)
        )
        weights = graph_state_weights(
            float(state_x) / width,
            float(state_y) / height,
            specs,
            GraphInterpolation(control.graph_interpolation),
            float(control.graph_radius),
        )
        value = float(weights[index])
    except (
        ArithmeticError,
        AttributeError,
        ReferenceError,
        StopIteration,
        TypeError,
        ValueError,
    ):
        return 0.0
    return value if math.isfinite(value) else 0.0


def graph_state_driver_expression(
    rig_instance_uuid: str,
    control_uuid: str,
    state_uuid: str,
) -> str:
    """Build a compact expression below Blender's scripted-driver limit."""

    arguments = (
        json.dumps(str(rig_instance_uuid)),
        json.dumps(str(control_uuid)),
        json.dumps(str(state_uuid)),
        "state_x",
        "state_y",
    )
    expression = f"{GRAPH_STATE_NAMESPACE_NAME}({','.join(arguments)})"
    if len(expression) > 240:
        raise ValueError("Graph State identifiers are too long for a Blender driver.")
    return expression


def register_graph_driver_namespace() -> None:
    bpy.app.driver_namespace[GRAPH_STATE_NAMESPACE_NAME] = (
        evaluate_graph_state_weight
    )


def unregister_graph_driver_namespace() -> None:
    bpy.app.driver_namespace.pop(GRAPH_STATE_NAMESPACE_NAME, None)
