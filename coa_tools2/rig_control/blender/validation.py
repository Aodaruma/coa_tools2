"""Validation of persisted definitions against Blender artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import math

import bpy

from ..schema import WidgetLayout
from ..validation import IssueSeverity
from .artifacts import (
    find_bone_by_role,
    find_object_by_role,
    limit_distance_name,
    limit_location_name,
    rail_constraint_name,
)
from .drivers import binding_target_key, driver_uses_control, find_driver
from .properties import get_rig_data
from .states import (
    state_dimensions,
    state_point_driver,
    state_point_target,
    summarize_state_mix_policy,
    state_target_key,
)
from .widgets import expected_widget_node_group_names


@dataclass(frozen=True)
class BlenderValidationIssue:
    severity: IssueSeverity
    code: str
    message: str
    control_uuid: str = ""
    binding_uuid: str = ""


def _binding_driver(binding):
    target_object = binding.target_object
    if target_object is None:
        return None
    if binding.target_kind == "SHAPE_KEY_VALUE":
        shape_keys = getattr(target_object.data, "shape_keys", None)
        if shape_keys is None or binding.target_name not in shape_keys.key_blocks:
            return None
        key_block = shape_keys.key_blocks[binding.target_name]
        return find_driver(shape_keys, key_block.path_from_id("value"))
    if binding.target_kind == "CONSTRAINT_INFLUENCE":
        if target_object.type != "ARMATURE":
            return None
        pose_bone = target_object.pose.bones.get(binding.target_bone)
        constraint = pose_bone.constraints.get(binding.target_name) if pose_bone else None
        if constraint is None:
            return None
        return find_driver(target_object, constraint.path_from_id("influence"))
    return None


def validate_rig(armature) -> list[BlenderValidationIssue]:
    issues: list[BlenderValidationIssue] = []
    controls = get_rig_data(armature).rig_controls
    seen_control_ids: set[str] = set()
    seen_targets: dict[tuple[str, str, str, str], str] = {}

    layouts = {WidgetLayout.TIP}
    for control in controls:
        layouts.add(
            WidgetLayout.GRAPH
            if control.state_mode == "GRAPH_2D"
            else WidgetLayout.MATRIX
            if control.state_mode == "MATRIX_2D"
            else {
                "SLIDER_1D": WidgetLayout.LINEAR,
                "POINT_2D_RECT": (
                    WidgetLayout.RECTANGLE_GRID
                    if control.rectangle_mode == "GRID"
                    else WidgetLayout.RECTANGLE
                ),
                "POINT_2D_CIRCLE": WidgetLayout.CIRCLE,
                "DIAL": WidgetLayout.DIAL,
            }[control.control_type]
        )
    missing_groups = sorted(
        expected_widget_node_group_names(layouts)
        - {group.name for group in bpy.data.node_groups}
    )
    if controls and missing_groups:
        issues.append(
            BlenderValidationIssue(
                IssueSeverity.ERROR,
                "artifact.missing_widget_node_group",
                "Managed Geometry Nodes widget groups are missing: "
                + ", ".join(missing_groups),
            )
        )

    for control in controls:
        if not control.control_uuid:
            issues.append(
                BlenderValidationIssue(
                    IssueSeverity.ERROR,
                    "control.missing_uuid",
                    "Control UUID is missing.",
                )
            )
        elif control.control_uuid in seen_control_ids:
            issues.append(
                BlenderValidationIssue(
                    IssueSeverity.ERROR,
                    "control.duplicate_uuid",
                    f"Duplicate control UUID: {control.control_uuid}",
                    control.control_uuid,
                )
            )
        seen_control_ids.add(control.control_uuid)

        display_bone = find_bone_by_role(
            armature, control.control_uuid, "display_bone"
        )
        control_bone = find_bone_by_role(
            armature, control.control_uuid, "control_bone"
        )
        name_bone = find_bone_by_role(
            armature, control.control_uuid, "name_bone"
        )
        name_text = find_object_by_role(control.control_uuid, "name_text")
        if display_bone is None:
            issues.append(
                BlenderValidationIssue(
                    IssueSeverity.ERROR,
                    "artifact.missing_display_bone",
                    f"Display bone is missing for {control.label}.",
                    control.control_uuid,
                )
            )
        if control_bone is None:
            issues.append(
                BlenderValidationIssue(
                    IssueSeverity.ERROR,
                    "artifact.missing_control_bone",
                    f"Control bone is missing for {control.label}.",
                    control.control_uuid,
                )
            )
        if name_bone is None:
            issues.append(
                BlenderValidationIssue(
                    IssueSeverity.ERROR,
                    "artifact.missing_name_bone",
                    f"Name bone is missing for {control.label}.",
                    control.control_uuid,
                )
            )
        if (
            name_text is None
            or name_text.type != "FONT"
            or name_text.data.body != control.label
            or name_text.parent != armature
            or name_text.parent_type != "BONE"
            or (
                name_bone is not None
                and name_text.parent_bone != name_bone.name
            )
        ):
            issues.append(
                BlenderValidationIssue(
                    IssueSeverity.ERROR,
                    "artifact.invalid_name_text",
                    f"Rig name text is missing or stale for {control.label}.",
                    control.control_uuid,
                )
            )
        if display_bone is not None:
            pose_bone = armature.pose.bones.get(display_bone.name)
            if pose_bone is None or pose_bone.custom_shape is None:
                issues.append(
                    BlenderValidationIssue(
                        IssueSeverity.ERROR,
                        "artifact.missing_base_widget",
                        f"Base widget is missing for {control.label}.",
                        control.control_uuid,
                    )
                )
        if control_bone is not None:
            pose_bone = armature.pose.bones.get(control_bone.name)
            if pose_bone is None or pose_bone.custom_shape is None:
                issues.append(
                    BlenderValidationIssue(
                        IssueSeverity.ERROR,
                        "artifact.missing_tip_widget",
                        f"Tip widget is missing for {control.label}.",
                        control.control_uuid,
                    )
                )
            else:
                expected_constraints = [limit_location_name(control.control_uuid)]
                if control.control_type == "POINT_2D_CIRCLE":
                    expected_constraints.append(limit_distance_name(control.control_uuid))
                elif control.control_type == "DIAL" or (
                    control.control_type == "POINT_2D_RECT"
                    and (
                        control.rectangle_mode == "GRID"
                        or control.state_mode == "MATRIX_2D"
                        or (
                            control.state_mode == "GRAPH_2D"
                            and control.graph_interpolation == "NAMED_GRAPH"
                        )
                    )
                ):
                    expected_constraints.append(
                        rail_constraint_name(control.control_uuid)
                    )
                if any(
                    pose_bone.constraints.get(name) is None
                    for name in expected_constraints
                ):
                    issues.append(
                        BlenderValidationIssue(
                            IssueSeverity.ERROR,
                            "artifact.missing_limit",
                            f"Limit constraint is missing for {control.label}.",
                            control.control_uuid,
                        )
                    )

        for binding in control.bindings:
            target_key = binding_target_key(binding)
            if not target_key[1] or not target_key[3]:
                issues.append(
                    BlenderValidationIssue(
                        IssueSeverity.ERROR,
                        "binding.missing_target",
                        f"Binding target is missing for {control.label}.",
                        control.control_uuid,
                        binding.binding_uuid,
                    )
                )
                continue
            previous = seen_targets.get(target_key)
            if previous is not None and previous != binding.binding_uuid:
                issues.append(
                    BlenderValidationIssue(
                        IssueSeverity.ERROR,
                        "binding.duplicate_target",
                        f"Target is controlled by multiple bindings: {target_key[1:]}",
                        control.control_uuid,
                        binding.binding_uuid,
                    )
                )
            seen_targets[target_key] = binding.binding_uuid

            fcurve = _binding_driver(binding)
            if fcurve is None:
                issues.append(
                    BlenderValidationIssue(
                        IssueSeverity.ERROR,
                        "binding.missing_driver",
                        f"Driver is missing for {target_key[1:]}",
                        control.control_uuid,
                        binding.binding_uuid,
                    )
                )
            elif control_bone is not None and not driver_uses_control(
                fcurve,
                armature,
                control_bone.name,
            ):
                issues.append(
                    BlenderValidationIssue(
                        IssueSeverity.ERROR,
                        "binding.driver_source_mismatch",
                        f"Driver uses a different control for {target_key[1:]}",
                        control.control_uuid,
                        binding.binding_uuid,
                    )
                )

        if control.state_mode != "NONE":
            compatible = (
                control.state_mode == "LINEAR_1D"
                and control.control_type == "SLIDER_1D"
            ) or (
                control.state_mode == "MATRIX_2D"
                and control.control_type == "POINT_2D_RECT"
            ) or (
                control.state_mode == "GRAPH_2D"
                and control.control_type == "POINT_2D_RECT"
            )
            if not compatible:
                issues.append(
                    BlenderValidationIssue(
                        IssueSeverity.ERROR,
                        "state.incompatible_control",
                        f"State mode is incompatible with {control.label}.",
                        control.control_uuid,
                    )
                )
                continue

            columns, rows = state_dimensions(control)
            if control.state_mode == "GRAPH_2D":
                point_ids = {
                    point.state_uuid
                    for point in control.state_points
                    if point.state_uuid
                }
                if len(control.state_points) < 2:
                    issues.append(
                        BlenderValidationIssue(
                            IssueSeverity.ERROR,
                            "state.graph_too_few_points",
                            f"State graph needs at least two points for {control.label}.",
                            control.control_uuid,
                        )
                    )
                if any(
                    len(point.graph_position) != 2
                    or not all(
                        math.isfinite(float(value))
                        for value in point.graph_position
                    )
                    for point in control.state_points
                ):
                    issues.append(
                        BlenderValidationIssue(
                            IssueSeverity.ERROR,
                            "state.invalid_graph_position",
                            f"State graph contains an invalid position for {control.label}.",
                            control.control_uuid,
                        )
                    )
                for point in control.state_points:
                    if (
                        point.fallback_state_uuid
                        and point.fallback_state_uuid not in point_ids
                    ):
                        issues.append(
                            BlenderValidationIssue(
                                IssueSeverity.ERROR,
                                "state.invalid_fallback",
                                f"Fallback target is missing for {point.label or control.label}.",
                                control.control_uuid,
                                point.state_uuid,
                            )
                        )
            else:
                expected = {
                    (column, row)
                    for row in range(rows)
                    for column in range(columns)
                }
                coordinates = [
                    (point.column, point.row) for point in control.state_points
                ]
                if (
                    set(coordinates) != expected
                    or len(coordinates) != len(expected)
                ):
                    issues.append(
                        BlenderValidationIssue(
                            IssueSeverity.ERROR,
                            "state.incomplete_grid",
                            f"State grid must be rebuilt for {control.label}.",
                            control.control_uuid,
                        )
                    )

            if control.state_mode == "MATRIX_2D" and control.state_cells:
                expected_cells = {
                    (column, row)
                    for row in range(rows - 1)
                    for column in range(columns - 1)
                }
                cell_coordinates = [
                    (cell.column, cell.row) for cell in control.state_cells
                ]
                if (
                    set(cell_coordinates) != expected_cells
                    or len(cell_coordinates) != len(expected_cells)
                ):
                    issues.append(
                        BlenderValidationIssue(
                            IssueSeverity.ERROR,
                            "state.incomplete_cell_grid",
                            f"Matrix mix cells must be rebuilt for {control.label}.",
                            control.control_uuid,
                        )
                    )
                elif (
                    control.state_mix_policy
                    != summarize_state_mix_policy(control)
                ):
                    issues.append(
                        BlenderValidationIssue(
                            IssueSeverity.WARNING,
                            "state.mix_policy_mismatch",
                            f"Matrix mix preset is stale for {control.label}.",
                            control.control_uuid,
                        )
                    )

            seen_state_ids: set[str] = set()
            for point in control.state_points:
                if not point.state_uuid or point.state_uuid in seen_state_ids:
                    issues.append(
                        BlenderValidationIssue(
                            IssueSeverity.ERROR,
                            "state.invalid_uuid",
                            f"State point ID is missing or duplicated for {control.label}.",
                            control.control_uuid,
                            point.state_uuid,
                        )
                    )
                seen_state_ids.add(point.state_uuid)
                if not point.enabled or point.is_empty:
                    continue
                target_key = state_target_key(point)
                if not target_key[1] or not target_key[3]:
                    point_name = (
                        point.label
                        if control.state_mode == "GRAPH_2D" and point.label
                        else f"[{point.column + 1}, {point.row + 1}]"
                    )
                    issues.append(
                        BlenderValidationIssue(
                            IssueSeverity.WARNING,
                            "state.unassigned_point",
                            f"State {point_name} is unassigned for {control.label}.",
                            control.control_uuid,
                            point.state_uuid,
                        )
                    )
                    continue
                _shape_keys, key_block = state_point_target(point)
                if key_block is None:
                    issues.append(
                        BlenderValidationIssue(
                            IssueSeverity.ERROR,
                            "state.missing_target",
                            f"State target is missing: {target_key[1:]}",
                            control.control_uuid,
                            point.state_uuid,
                        )
                    )
                    continue
                previous = seen_targets.get(target_key)
                if previous is not None and previous != point.state_uuid:
                    issues.append(
                        BlenderValidationIssue(
                            IssueSeverity.ERROR,
                            "state.duplicate_target",
                            f"Target is used by multiple rig inputs: {target_key[1:]}",
                            control.control_uuid,
                            point.state_uuid,
                        )
                    )
                seen_targets[target_key] = point.state_uuid
                fcurve = state_point_driver(point)
                if fcurve is None:
                    issues.append(
                        BlenderValidationIssue(
                            IssueSeverity.ERROR,
                            "state.missing_driver",
                            f"State driver is missing for {target_key[1:]}",
                            control.control_uuid,
                            point.state_uuid,
                        )
                    )
                elif control_bone is not None and not driver_uses_control(
                    fcurve,
                    armature,
                    control_bone.name,
                ):
                    issues.append(
                        BlenderValidationIssue(
                            IssueSeverity.ERROR,
                            "state.driver_source_mismatch",
                            f"State driver uses a different control for {target_key[1:]}",
                            control.control_uuid,
                            point.state_uuid,
                        )
                    )
    return issues


def store_validation_issues(armature, issues):
    collection = get_rig_data(armature).rig_validation_issues
    collection.clear()
    for issue in issues:
        item = collection.add()
        item.severity = issue.severity.value
        item.code = issue.code
        item.message = issue.message
        item.control_uuid = issue.control_uuid
        item.binding_uuid = issue.binding_uuid
    return len(collection)
