"""Pure validation helpers for rig-control definitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .schema import BindingSpec, ControlSpec, WidgetLayout, WidgetSpec


class IssueSeverity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass(frozen=True)
class ValidationIssue:
    severity: IssueSeverity
    code: str
    message: str
    subject_id: str = ""


def validate_widget_spec(spec: WidgetSpec) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not spec.widget_uuid.strip():
        issues.append(
            ValidationIssue(
                IssueSeverity.ERROR,
                "widget.missing_uuid",
                "Widget UUID is required.",
            )
        )
    for field_name, value in (
        ("width", spec.width),
        ("height", spec.height),
        ("radius", spec.radius),
        ("tip_radius", spec.tip_radius),
        ("node_radius", spec.node_radius),
        ("bar_width", spec.bar_width),
        ("stroke_radius", spec.stroke_radius),
    ):
        if value <= 0.0:
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "widget.non_positive_dimension",
                    f"Widget {field_name} must be greater than zero.",
                    spec.widget_uuid,
                )
            )
    if spec.layout in {
        WidgetLayout.RECTANGLE,
        WidgetLayout.RECTANGLE_GRID,
        WidgetLayout.MATRIX,
    } and (
        spec.columns < 2 or spec.rows < 2
    ):
        issues.append(
            ValidationIssue(
                IssueSeverity.ERROR,
                "widget.invalid_grid_size",
                "Matrix widgets require at least two columns and two rows.",
                spec.widget_uuid,
            )
        )
    if (
        spec.layout == WidgetLayout.MATRIX
        and spec.mix_cells is not None
        and len(spec.mix_cells) != (spec.columns - 1) * (spec.rows - 1)
    ):
        issues.append(
            ValidationIssue(
                IssueSeverity.ERROR,
                "widget.invalid_cell_mask",
                "Matrix cell mask size must match the state grid.",
                spec.widget_uuid,
            )
        )
    if spec.layout == WidgetLayout.GRAPH:
        if len(spec.graph_points) < 2:
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "widget.graph_too_few_points",
                    "Graph widgets require at least two named points.",
                    spec.widget_uuid,
                )
            )
        if any(
            len(edge) != 2
            or edge[0] == edge[1]
            or not all(0 <= index < len(spec.graph_points) for index in edge)
            for edge in spec.graph_edges
        ):
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "widget.invalid_graph_edge",
                    "Graph widget edges must reference two different points.",
                    spec.widget_uuid,
                )
            )
        if spec.graph_point_shapes and len(spec.graph_point_shapes) != len(
            spec.graph_points
        ):
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "widget.invalid_graph_point_shapes",
                    "Graph point shapes must match the named point count.",
                    spec.widget_uuid,
                )
            )
        if spec.graph_custom_object_names and len(
            spec.graph_custom_object_names
        ) != len(spec.graph_points):
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "widget.invalid_graph_custom_objects",
                    "Graph custom marker references must match the point count.",
                    spec.widget_uuid,
                )
            )
    return issues


def validate_control_spec(spec: ControlSpec) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for field_name, value in (
        ("control_uuid", spec.control_uuid),
        ("semantic_id", spec.semantic_id),
        ("control_bone", spec.control_bone),
        ("display_bone", spec.display_bone),
        ("widget_spec_id", spec.widget_spec_id),
    ):
        if not value.strip():
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    f"control.missing_{field_name}",
                    f"Control {field_name} is required.",
                    spec.control_uuid,
                )
            )
    if spec.value_min[0] >= spec.value_max[0]:
        issues.append(
            ValidationIssue(
                IssueSeverity.ERROR,
                "control.invalid_x_range",
                "Control X minimum must be less than its maximum.",
                spec.control_uuid,
            )
        )
    return issues


def validate_binding_spec(spec: BindingSpec) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not spec.binding_uuid.strip() or not spec.control_uuid.strip():
        issues.append(
            ValidationIssue(
                IssueSeverity.ERROR,
                "binding.missing_id",
                "Binding and control UUIDs are required.",
                spec.binding_uuid,
            )
        )
    if spec.input_min >= spec.input_max:
        issues.append(
            ValidationIssue(
                IssueSeverity.ERROR,
                "binding.invalid_input_range",
                "Binding input minimum must be less than its maximum.",
                spec.binding_uuid,
            )
        )
    if not spec.target_object_name.strip() or not spec.target_name.strip():
        issues.append(
            ValidationIssue(
                IssueSeverity.ERROR,
                "binding.missing_target",
                "Binding target object and target name are required.",
                spec.binding_uuid,
            )
        )
    return issues


def find_duplicate_ids(ids: Iterable[str], subject: str) -> list[ValidationIssue]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for item_id in ids:
        if item_id in seen:
            duplicates.add(item_id)
        seen.add(item_id)
    return [
        ValidationIssue(
            IssueSeverity.ERROR,
            f"{subject}.duplicate_id",
            f"Duplicate {subject} ID: {item_id}",
            item_id,
        )
        for item_id in sorted(duplicates)
    ]
