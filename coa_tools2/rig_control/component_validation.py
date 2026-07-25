"""Pure validation helpers for character posing rig components."""

from __future__ import annotations

from .component_schema import (
    RigDeformationMode,
    RigComponentSpec,
    RigComponentType,
    RigDepthMode,
    RigOrientationMode,
)
from .validation import IssueSeverity, ValidationIssue


def validate_component_spec(spec: RigComponentSpec) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for field_name, value in (
        ("component_uuid", spec.component_uuid),
        ("semantic_id", spec.semantic_id),
        ("display_name", spec.display_name),
    ):
        if not value.strip():
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    f"component.missing_{field_name}",
                    f"Component {field_name} is required.",
                    spec.component_uuid,
                )
            )
    if not spec.source_bones:
        issues.append(
            ValidationIssue(
                IssueSeverity.ERROR,
                "component.missing_source_bones",
                "At least one source bone is required.",
                spec.component_uuid,
            )
        )
    if len(set(spec.source_bones)) != len(spec.source_bones):
        issues.append(
            ValidationIssue(
                IssueSeverity.ERROR,
                "component.duplicate_source_bone",
                "Source bones must be unique and ordered.",
                spec.component_uuid,
            )
        )
    minimum_bones = {
        RigComponentType.ROOT: 1,
        RigComponentType.FK_CHAIN: 1,
        RigComponentType.LIMB_IK: 3,
        RigComponentType.SPINE_FK: 2,
    }[spec.component_type]
    if len(spec.source_bones) < minimum_bones:
        issues.append(
            ValidationIssue(
                IssueSeverity.ERROR,
                "component.insufficient_source_bones",
                (
                    f"{spec.component_type.value} requires at least "
                    f"{minimum_bones} source bone(s)."
                ),
                spec.component_uuid,
            )
        )
    if (
        spec.orientation_mode == RigOrientationMode.SOURCE_BONE
        and spec.orientation_reference
        and spec.orientation_reference not in spec.source_bones
    ):
        issues.append(
            ValidationIssue(
                IssueSeverity.ERROR,
                "component.invalid_orientation_reference",
                "Orientation reference must be one of the source bones.",
                spec.component_uuid,
            )
        )
    if spec.depth_mode == RigDepthMode.LIMITED and spec.depth_min > spec.depth_max:
        issues.append(
            ValidationIssue(
                IssueSeverity.ERROR,
                "component.invalid_depth_range",
                "Depth minimum must not exceed the maximum.",
                spec.component_uuid,
            )
        )
    if spec.widget_size <= 0.0:
        issues.append(
            ValidationIssue(
                IssueSeverity.ERROR,
                "component.invalid_widget_size",
                "Component widget size must be greater than zero.",
                spec.component_uuid,
            )
        )
    binding_ids = set()
    for binding in spec.bindings:
        if not binding.binding_uuid.strip():
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "component.binding_missing_uuid",
                    "Pose output binding UUID is required.",
                    spec.component_uuid,
                )
            )
        elif binding.binding_uuid in binding_ids:
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "component.binding_duplicate_uuid",
                    f"Duplicate pose output UUID: {binding.binding_uuid}",
                    spec.component_uuid,
                )
            )
        binding_ids.add(binding.binding_uuid)
        if binding.input_min >= binding.input_max:
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "component.binding_invalid_input_range",
                    "Pose output input minimum must be less than its maximum.",
                    binding.binding_uuid,
                )
            )
        if (
            not binding.target_object_name.strip()
            or not binding.target_name.strip()
        ):
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "component.binding_missing_target",
                    "Pose output target object and target name are required.",
                    binding.binding_uuid,
                )
            )
    if spec.bindings and spec.deformation_mode != RigDeformationMode.PARAMETRIC:
        issues.append(
            ValidationIssue(
                IssueSeverity.ERROR,
                "component.outputs_require_parametric_mode",
                "Pose outputs require Parametric deformation mode.",
                spec.component_uuid,
            )
        )
    if spec.component_type == RigComponentType.LIMB_IK:
        if spec.ik_chain_length < 1:
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "component.invalid_ik_chain_length",
                    "IK chain length must be at least one.",
                    spec.component_uuid,
                )
            )
        elif spec.ik_chain_length >= len(spec.source_bones):
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "component.ik_chain_exceeds_sources",
                    "IK chain length must leave one source bone as the end control.",
                    spec.component_uuid,
                )
            )
        if spec.use_bend_hint and spec.pole_distance <= 0.0:
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "component.invalid_pole_distance",
                    "Bend hint distance must be greater than zero.",
                    spec.component_uuid,
                )
            )
    return issues
