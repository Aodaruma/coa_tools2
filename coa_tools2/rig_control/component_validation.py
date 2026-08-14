"""Pure validation helpers for character posing rig components."""

from __future__ import annotations

from .component_schema import (
    RigDeformationMode,
    RigComponentSpec,
    RigComponentType,
    RigDepthMode,
    RigOrientationMode,
    RigWidgetPresentationSpec,
    RigWidgetShape,
)
from .validation import IssueSeverity, ValidationIssue


_WIDTH_HEIGHT_SHAPES = {
    RigWidgetShape.ARROW_1D,
    RigWidgetShape.ARROW_2D,
    RigWidgetShape.TOMBSTONE,
    RigWidgetShape.ELLIPSE,
    RigWidgetShape.TRIANGLE,
    RigWidgetShape.RECTANGLE,
    RigWidgetShape.DIAMOND,
}
_ARROW_SHAPES = {
    RigWidgetShape.ARROW_1D,
    RigWidgetShape.ARROW_2D,
    RigWidgetShape.CYLINDER_ARROW_1D,
    RigWidgetShape.SPHERE_ARROW_2D,
}
_SEGMENT_SHAPES = {
    RigWidgetShape.CYLINDER_ARROW_1D,
    RigWidgetShape.SPHERE_ARROW_2D,
    RigWidgetShape.TOMBSTONE,
    RigWidgetShape.ELLIPSE,
    RigWidgetShape.TRIANGLE,
    RigWidgetShape.RECTANGLE,
    RigWidgetShape.DIAMOND,
    RigWidgetShape.SECTOR,
}


def validate_widget_presentation(
    presentation: RigWidgetPresentationSpec,
    subject_id: str,
) -> list[ValidationIssue]:
    """Validate only parameters consumed by the selected presentation shape."""

    issues: list[ValidationIssue] = []

    def error(code: str, message: str) -> None:
        issues.append(
            ValidationIssue(
                IssueSeverity.ERROR,
                code,
                message,
                subject_id,
            )
        )

    shape = presentation.shape
    if shape == RigWidgetShape.NONE:
        return issues
    if not 0.5 <= presentation.wire_width <= 16.0:
        error(
            "component.presentation_invalid_wire_width",
            "Viewport wire width must be between 0.5 and 16.0.",
        )
    if shape == RigWidgetShape.CUSTOM_OBJECT:
        if not presentation.custom_object_name.strip():
            error(
                "component.presentation_missing_custom_object",
                "A custom presentation object is required.",
            )
        return issues
    if shape in _WIDTH_HEIGHT_SHAPES:
        if presentation.width <= 0.0 or (
            shape != RigWidgetShape.ARROW_1D and presentation.height <= 0.0
        ):
            error(
                "component.presentation_invalid_size",
                "Presentation width and height must be greater than zero.",
            )
    if shape in {
        RigWidgetShape.TOMBSTONE,
        RigWidgetShape.TRIANGLE,
        RigWidgetShape.RECTANGLE,
        RigWidgetShape.DIAMOND,
    }:
        maximum = min(presentation.width, presentation.height) * 0.5
        if not 0.0 <= presentation.corner_radius <= maximum:
            error(
                "component.presentation_invalid_corner_radius",
                "Corner radius must fit inside half of the smaller dimension.",
            )
    if shape in _ARROW_SHAPES:
        if presentation.bar_width <= 0.0:
            error(
                "component.presentation_invalid_bar_width",
                "Arrow bar width must be greater than zero.",
            )
        if presentation.head_length <= 0.0 or presentation.head_width <= 0.0:
            error(
                "component.presentation_invalid_arrow_head",
                "Arrow head length and width must be greater than zero.",
            )
    if shape in {
        RigWidgetShape.CYLINDER_ARROW_1D,
        RigWidgetShape.SPHERE_ARROW_2D,
    }:
        if presentation.radius <= 0.0:
            error(
                "component.presentation_invalid_radius",
                "Curved arrow radius must be greater than zero.",
            )
        if not 0.0 < presentation.arc_angle <= 6.283185307179586:
            error(
                "component.presentation_invalid_arc_angle",
                "Arc angle must be greater than zero and at most one turn.",
            )
    if shape == RigWidgetShape.SECTOR:
        if not (
            0.0 <= presentation.sector_inner_radius
            < presentation.sector_outer_radius
        ):
            error(
                "component.presentation_invalid_sector_radius",
                "Sector radii must satisfy 0 <= inner < outer.",
            )
        if not 0.0 < abs(presentation.sector_sweep_angle) <= 6.283185307179586:
            error(
                "component.presentation_invalid_sector_sweep",
                "Sector sweep must be non-zero and at most one turn.",
            )
    if shape in _SEGMENT_SHAPES and not 3 <= presentation.segments <= 256:
        error(
            "component.presentation_invalid_segments",
            "Presentation segments must be between 3 and 256.",
        )
    return issues


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
    issues.extend(validate_widget_presentation(spec.presentation, spec.component_uuid))
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
