"""Validation of persisted definitions against Blender artifacts."""

from __future__ import annotations

from dataclasses import dataclass

import bpy

from ..validation import IssueSeverity
from .artifacts import (
    find_bone_by_role,
    limit_distance_name,
    limit_location_name,
    rail_constraint_name,
)
from .drivers import binding_target_key, driver_uses_control, find_driver
from .properties import get_rig_data
from .widgets import NODE_GROUP_NAME


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

    if controls and NODE_GROUP_NAME not in bpy.data.node_groups:
        issues.append(
            BlenderValidationIssue(
                IssueSeverity.ERROR,
                "artifact.missing_widget_node_group",
                "The managed Geometry Nodes widget group is missing.",
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
                    and control.rectangle_mode == "GRID"
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
