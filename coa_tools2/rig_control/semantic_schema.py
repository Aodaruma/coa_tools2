"""Blender-independent schema for composable semantic rigs.

The schema intentionally separates presentation, input interpretation,
mechanism evaluation and art output.  Solver nodes communicate through named
semantic channels, so IK, pose maps, contact and secondary motion can be
combined instead of becoming mutually exclusive rig types.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Union

from .component_schema import RigWidgetPresentationSpec, RigWidgetShape
from .component_validation import validate_widget_presentation
from .schema import StringEnum


SEMANTIC_RIG_SCHEMA_VERSION = 2


class FrameRole(StringEnum):
    DISPLAY = "DISPLAY"
    INPUT = "INPUT"
    MECHANISM = "MECHANISM"
    ART = "ART"


class FrameSpace(StringEnum):
    WORLD = "WORLD"
    OBJECT = "OBJECT"
    BONE = "BONE"
    CUSTOM = "CUSTOM"


class ChannelKind(StringEnum):
    CONTINUOUS = "CONTINUOUS"
    DISCRETE = "DISCRETE"


class OutputPolicy(StringEnum):
    DIRECT = "DIRECT"
    PROJECT_TO_ART_PLANE = "PROJECT_TO_ART_PLANE"
    PARAMETRIC = "PARAMETRIC"
    HYBRID = "HYBRID"


class OutputTargetKind(StringEnum):
    BONE_TRANSFORM = "BONE_TRANSFORM"
    SHAPE_KEY = "SHAPE_KEY"
    SLOT_INDEX = "SLOT_INDEX"
    Z_VALUE = "Z_VALUE"
    CONSTRAINT_INFLUENCE = "CONSTRAINT_INFLUENCE"
    CUSTOM_PROPERTY = "CUSTOM_PROPERTY"


class SolverType(StringEnum):
    PROJECTED_TRANSFORM = "PROJECTED_TRANSFORM"
    POSE_MAP = "POSE_MAP"
    CHAIN_FK = "CHAIN_FK"
    CHAIN_IK = "CHAIN_IK"
    CONTACT_PIN = "CONTACT_PIN"
    SPLINE = "SPLINE"
    BBONE_BEZIER = "BBONE_BEZIER"
    SECONDARY_MOTION = "SECONDARY_MOTION"


class ProjectionMode(StringEnum):
    SCREEN_PLANE = "SCREEN_PLANE"
    ART_PLANE = "ART_PLANE"
    VISUAL_NORMAL = "VISUAL_NORMAL"


class ContactSpace(StringEnum):
    WORLD = "WORLD"
    CHARACTER = "CHARACTER"
    TARGET = "TARGET"


class RigMode(StringEnum):
    FK = "FK"
    IK = "IK"


class ContactMode(StringEnum):
    OFF = "OFF"
    ON = "ON"


class WidgetTargetRole(StringEnum):
    """Which stage-owned control receives one presentation."""

    PRIMARY = "PRIMARY"
    FK_CONTROL = "FK_CONTROL"
    POLE = "POLE"
    SPLINE_CONTROL = "SPLINE_CONTROL"
    BBONE_POINT = "BBONE_POINT"
    BBONE_HANDLE = "BBONE_HANDLE"


@dataclass(frozen=True)
class RigFrameSpec:
    """A named coordinate frame; its Blender realization is compiler-owned."""

    frame_id: str
    role: FrameRole
    space: FrameSpace = FrameSpace.CUSTOM
    object_name: str = ""
    bone_name: str = ""
    parent_frame_id: str = ""
    rest_matrix: tuple[float, ...] = (
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["role"] = self.role.value
        data["space"] = self.space.value
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RigFrameSpec":
        values = dict(data)
        values["role"] = FrameRole(values["role"])
        values["space"] = FrameSpace(values.get("space", "CUSTOM"))
        values["rest_matrix"] = tuple(values.get("rest_matrix", cls.__dataclass_fields__["rest_matrix"].default))
        return cls(**values)


@dataclass(frozen=True)
class SemanticChannelSpec:
    """Typed value exchanged by solver nodes.

    ``scale`` expresses the meaningful size of one unit on every component.
    It is also suitable for normalizing dimensions in a pose field.
    """

    channel_id: str
    display_name: str = ""
    kind: ChannelKind = ChannelKind.CONTINUOUS
    arity: int = 1
    default_value: tuple[float, ...] = (0.0,)
    scale: tuple[float, ...] = (1.0,)
    semantic_unit: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SemanticChannelSpec":
        values = dict(data)
        values["kind"] = ChannelKind(values.get("kind", "CONTINUOUS"))
        values["default_value"] = tuple(values.get("default_value", (0.0,)))
        values["scale"] = tuple(values.get("scale", (1.0,)))
        return cls(**values)


@dataclass(frozen=True)
class ProjectedTransformSolverSpec:
    display_frame_id: str
    input_frame_id: str
    art_frame_id: str
    projection_mode: ProjectionMode = ProjectionMode.ART_PLANE
    preserve_art_plane: bool = True
    depth_limit: tuple[float, float] = (-0.25, 0.25)
    solver_type: SolverType = field(
        default=SolverType.PROJECTED_TRANSFORM, init=False
    )


@dataclass(frozen=True)
class PoseMapSolverSpec:
    pose_field_id: str
    solver_type: SolverType = field(default=SolverType.POSE_MAP, init=False)


@dataclass(frozen=True)
class ChainFKSolverSpec:
    """Independent or shared FK controls exported as a composable DAG node."""

    mechanism_frame_id: str
    chain_bones: tuple[str, ...]
    solver_type: SolverType = field(default=SolverType.CHAIN_FK, init=False)


@dataclass(frozen=True)
class ChainIKSolverSpec:
    mechanism_frame_id: str
    effector_frame_id: str
    chain_bones: tuple[str, ...]
    pole_frame_id: str = ""
    allow_stretch: bool = False
    solver_type: SolverType = field(default=SolverType.CHAIN_IK, init=False)


@dataclass(frozen=True)
class ContactPinSolverSpec:
    mechanism_frame_id: str
    target_frame_id: str
    weight_channel_id: str
    contact_space: ContactSpace = ContactSpace.WORLD
    pin_position: bool = True
    pin_orientation: bool = False
    solver_type: SolverType = field(default=SolverType.CONTACT_PIN, init=False)


@dataclass(frozen=True)
class SplineSolverSpec:
    mechanism_frame_id: str
    chain_bones: tuple[str, ...]
    curve_reference: str
    root_pin_channel_id: str = ""
    tip_pin_channel_id: str = ""
    allow_stretch: bool = False
    solver_type: SolverType = field(default=SolverType.SPLINE, init=False)


@dataclass(frozen=True)
class BboneBezierSolverSpec:
    """One B-Bone segment driven through semantic Bezier controls.

    The deform bone remains the Blender B-Bone owner.  Start/end points,
    tangent handles and an optional midpoint are compiler-owned controls, so
    presentation and Secondary Motion may be replaced independently.
    """

    mechanism_frame_id: str
    deform_bone: str
    segments: int = 8
    use_mid_control: bool = False
    ease_in: float = 1.0
    ease_out: float = 1.0
    roll_in: float = 0.0
    roll_out: float = 0.0
    scale_in: tuple[float, float, float] = (1.0, 1.0, 1.0)
    scale_out: tuple[float, float, float] = (1.0, 1.0, 1.0)
    solver_type: SolverType = field(default=SolverType.BBONE_BEZIER, init=False)


@dataclass(frozen=True)
class SecondaryMotionSolverSpec:
    mechanism_frame_id: str
    stiffness_channel_id: str = ""
    damping_channel_id: str = ""
    gravity_channel_id: str = ""
    bakeable: bool = True
    solver_type: SolverType = field(
        default=SolverType.SECONDARY_MOTION, init=False
    )


SolverSpec = Union[
    ProjectedTransformSolverSpec,
    PoseMapSolverSpec,
    ChainFKSolverSpec,
    ChainIKSolverSpec,
    ContactPinSolverSpec,
    SplineSolverSpec,
    BboneBezierSolverSpec,
    SecondaryMotionSolverSpec,
]


_SOLVER_CLASSES = {
    SolverType.PROJECTED_TRANSFORM: ProjectedTransformSolverSpec,
    SolverType.POSE_MAP: PoseMapSolverSpec,
    SolverType.CHAIN_FK: ChainFKSolverSpec,
    SolverType.CHAIN_IK: ChainIKSolverSpec,
    SolverType.CONTACT_PIN: ContactPinSolverSpec,
    SolverType.SPLINE: SplineSolverSpec,
    SolverType.BBONE_BEZIER: BboneBezierSolverSpec,
    SolverType.SECONDARY_MOTION: SecondaryMotionSolverSpec,
}


def _solver_to_dict(solver: SolverSpec) -> dict[str, Any]:
    data = asdict(solver)
    data["solver_type"] = solver.solver_type.value
    if isinstance(solver, ProjectedTransformSolverSpec):
        data["projection_mode"] = solver.projection_mode.value
    elif isinstance(solver, ContactPinSolverSpec):
        data["contact_space"] = solver.contact_space.value
    return data


def _solver_from_dict(data: Mapping[str, Any]) -> SolverSpec:
    values = dict(data)
    solver_type = SolverType(values.pop("solver_type"))
    if solver_type is SolverType.PROJECTED_TRANSFORM:
        values["projection_mode"] = ProjectionMode(
            values.get("projection_mode", "ART_PLANE")
        )
        values["depth_limit"] = tuple(values.get("depth_limit", (-0.25, 0.25)))
    elif solver_type is SolverType.CONTACT_PIN:
        values["contact_space"] = ContactSpace(
            values.get("contact_space", "WORLD")
        )
    elif solver_type in {
        SolverType.CHAIN_FK,
        SolverType.CHAIN_IK,
        SolverType.SPLINE,
    }:
        values["chain_bones"] = tuple(values.get("chain_bones", ()))
    elif solver_type is SolverType.BBONE_BEZIER:
        values["scale_in"] = tuple(values.get("scale_in", (1.0, 1.0, 1.0)))
        values["scale_out"] = tuple(values.get("scale_out", (1.0, 1.0, 1.0)))
    return _SOLVER_CLASSES[solver_type](**values)


@dataclass(frozen=True)
class SolverNodeSpec:
    """One composable node in the semantic evaluation graph."""

    node_uuid: str
    semantic_id: str
    solver: SolverSpec
    input_channels: tuple[str, ...] = ()
    output_channels: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_uuid": self.node_uuid,
            "semantic_id": self.semantic_id,
            "solver": _solver_to_dict(self.solver),
            "input_channels": list(self.input_channels),
            "output_channels": list(self.output_channels),
            "depends_on": list(self.depends_on),
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SolverNodeSpec":
        values = dict(data)
        values["solver"] = _solver_from_dict(values["solver"])
        for key in ("input_channels", "output_channels", "depends_on"):
            values[key] = tuple(values.get(key, ()))
        return cls(**values)


@dataclass(frozen=True)
class OutputTargetSpec:
    target_kind: OutputTargetKind
    object_name: str
    target_name: str
    bone_name: str = ""
    data_path: str = ""
    array_index: int = -1

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["target_kind"] = self.target_kind.value
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OutputTargetSpec":
        values = dict(data)
        values["target_kind"] = OutputTargetKind(values["target_kind"])
        return cls(**values)


@dataclass(frozen=True)
class SemanticOutputSpec:
    output_uuid: str
    channel_id: str
    target: OutputTargetSpec
    policy: OutputPolicy = OutputPolicy.PARAMETRIC
    art_frame_id: str = ""
    value_arity: int = 1
    discrete: bool = False
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_uuid": self.output_uuid,
            "channel_id": self.channel_id,
            "target": self.target.to_dict(),
            "policy": self.policy.value,
            "art_frame_id": self.art_frame_id,
            "value_arity": self.value_arity,
            "discrete": self.discrete,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SemanticOutputSpec":
        values = dict(data)
        values["target"] = OutputTargetSpec.from_dict(values["target"])
        values["policy"] = OutputPolicy(values.get("policy", "PARAMETRIC"))
        return cls(**values)


@dataclass(frozen=True)
class WidgetPresentationRef:
    """Reference to replaceable presentation data, not solver behavior."""

    presentation_uuid: str
    control_id: str
    display_frame_id: str
    widget_spec_id: str = ""
    geometry_node_group: str = ""
    preset_id: str = ""
    target_role: WidgetTargetRole = WidgetTargetRole.PRIMARY
    target_index: int = -1
    settings: RigWidgetPresentationSpec = field(
        default_factory=RigWidgetPresentationSpec
    )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["target_role"] = self.target_role.value
        data["settings"] = self.settings.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WidgetPresentationRef":
        values = dict(data)
        values["target_role"] = WidgetTargetRole(
            values.get("target_role", "PRIMARY")
        )
        values["settings"] = RigWidgetPresentationSpec.from_dict(
            values.get("settings", {})
        )
        return cls(**values)


@dataclass(frozen=True)
class SemanticRigSpec:
    rig_uuid: str
    semantic_id: str
    display_name: str
    frames: tuple[RigFrameSpec, ...]
    channels: tuple[SemanticChannelSpec, ...]
    nodes: tuple[SolverNodeSpec, ...]
    outputs: tuple[SemanticOutputSpec, ...] = ()
    presentations: tuple[WidgetPresentationRef, ...] = ()
    schema_version: int = SEMANTIC_RIG_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "rig_uuid": self.rig_uuid,
            "semantic_id": self.semantic_id,
            "display_name": self.display_name,
            "frames": [item.to_dict() for item in self.frames],
            "channels": [item.to_dict() for item in self.channels],
            "nodes": [item.to_dict() for item in self.nodes],
            "outputs": [item.to_dict() for item in self.outputs],
            "presentations": [item.to_dict() for item in self.presentations],
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SemanticRigSpec":
        values = dict(data)
        values["frames"] = tuple(
            RigFrameSpec.from_dict(item) for item in values.get("frames", ())
        )
        values["channels"] = tuple(
            SemanticChannelSpec.from_dict(item)
            for item in values.get("channels", ())
        )
        values["nodes"] = tuple(
            SolverNodeSpec.from_dict(item) for item in values.get("nodes", ())
        )
        values["outputs"] = tuple(
            SemanticOutputSpec.from_dict(item)
            for item in values.get("outputs", ())
        )
        values["presentations"] = tuple(
            WidgetPresentationRef.from_dict(item)
            for item in values.get("presentations", ())
        )
        return cls(**values)


@dataclass(frozen=True)
class SemanticRigValidationIssue:
    code: str
    subject_id: str
    message: str


def _duplicate_ids(values: tuple[str, ...]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def _has_cycle(edges: Mapping[str, tuple[str, ...]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(item: str) -> bool:
        if item in visiting:
            return True
        if item in visited:
            return False
        visiting.add(item)
        if any(visit(parent) for parent in edges.get(item, ()) if parent in edges):
            return True
        visiting.remove(item)
        visited.add(item)
        return False

    return any(visit(item) for item in edges)


def _solver_frame_ids(solver: SolverSpec) -> tuple[str, ...]:
    if isinstance(solver, ProjectedTransformSolverSpec):
        return (solver.display_frame_id, solver.input_frame_id, solver.art_frame_id)
    if isinstance(solver, ChainIKSolverSpec):
        return tuple(
            value
            for value in (
                solver.mechanism_frame_id,
                solver.effector_frame_id,
                solver.pole_frame_id,
            )
            if value
        )
    if isinstance(solver, ChainFKSolverSpec):
        return (solver.mechanism_frame_id,)
    if isinstance(solver, ContactPinSolverSpec):
        return (solver.mechanism_frame_id, solver.target_frame_id)
    if isinstance(
        solver,
        (SplineSolverSpec, BboneBezierSolverSpec, SecondaryMotionSolverSpec),
    ):
        return (solver.mechanism_frame_id,)
    return ()


def _solver_channel_ids(solver: SolverSpec) -> tuple[str, ...]:
    if isinstance(solver, ContactPinSolverSpec):
        return (solver.weight_channel_id,)
    if isinstance(solver, SplineSolverSpec):
        return tuple(
            value
            for value in (solver.root_pin_channel_id, solver.tip_pin_channel_id)
            if value
        )
    if isinstance(solver, SecondaryMotionSolverSpec):
        return tuple(
            value
            for value in (
                solver.stiffness_channel_id,
                solver.damping_channel_id,
                solver.gravity_channel_id,
            )
            if value
        )
    return ()


def validate_semantic_rig(
    spec: SemanticRigSpec,
) -> tuple[SemanticRigValidationIssue, ...]:
    """Return structural errors without requiring Blender or a pose library."""

    issues: list[SemanticRigValidationIssue] = []

    def issue(code: str, subject: str, message: str) -> None:
        issues.append(SemanticRigValidationIssue(code, subject, message))

    if not spec.rig_uuid:
        issue("semantic.missing_rig_uuid", "", "Rig UUID is required.")
    if not spec.semantic_id:
        issue("semantic.missing_semantic_id", spec.rig_uuid, "Semantic ID is required.")

    frame_ids = tuple(item.frame_id for item in spec.frames)
    channel_ids = tuple(item.channel_id for item in spec.channels)
    node_ids = tuple(item.node_uuid for item in spec.nodes)
    output_ids = tuple(item.output_uuid for item in spec.outputs)
    presentation_ids = tuple(item.presentation_uuid for item in spec.presentations)
    for kind, values in (
        ("frame", frame_ids),
        ("channel", channel_ids),
        ("node", node_ids),
        ("output", output_ids),
        ("presentation", presentation_ids),
    ):
        for duplicate in sorted(_duplicate_ids(values)):
            issue(
                f"semantic.duplicate_{kind}_id",
                duplicate,
                f"Duplicate {kind} ID.",
            )

    frame_set = set(frame_ids)
    channel_set = set(channel_ids)
    node_set = set(node_ids)
    roles = {item.role for item in spec.frames}
    for role in FrameRole:
        if role not in roles:
            issue(
                "semantic.missing_frame_role",
                role.value,
                f"At least one {role.value} frame is required.",
            )

    for frame_spec in spec.frames:
        if not frame_spec.frame_id:
            issue("semantic.missing_frame_id", "", "Frame ID is required.")
        if len(frame_spec.rest_matrix) != 16:
            issue(
                "semantic.invalid_frame_matrix",
                frame_spec.frame_id,
                "Frame rest matrix must contain 16 values.",
            )
        if frame_spec.parent_frame_id and frame_spec.parent_frame_id not in frame_set:
            issue(
                "semantic.unknown_parent_frame",
                frame_spec.frame_id,
                f"Unknown parent frame {frame_spec.parent_frame_id!r}.",
            )
    frame_edges = {
        item.frame_id: ((item.parent_frame_id,) if item.parent_frame_id else ())
        for item in spec.frames
    }
    if _has_cycle(frame_edges):
        issue("semantic.frame_cycle", spec.rig_uuid, "Frame hierarchy has a cycle.")

    for channel in spec.channels:
        if not channel.channel_id:
            issue("semantic.missing_channel_id", "", "Channel ID is required.")
        if channel.arity < 1:
            issue("semantic.invalid_channel_arity", channel.channel_id, "Arity must be positive.")
        if len(channel.default_value) != channel.arity:
            issue(
                "semantic.invalid_channel_default",
                channel.channel_id,
                "Default value length must equal channel arity.",
            )
        if len(channel.scale) != channel.arity or any(value <= 0.0 for value in channel.scale):
            issue(
                "semantic.invalid_channel_scale",
                channel.channel_id,
                "Scale must contain one positive value per component.",
            )

    for node in spec.nodes:
        if not node.node_uuid:
            issue("semantic.missing_node_uuid", "", "Node UUID is required.")
        if not node.semantic_id:
            issue("semantic.missing_node_semantic_id", node.node_uuid, "Node semantic ID is required.")
        for channel_id in node.input_channels + node.output_channels + _solver_channel_ids(node.solver):
            if channel_id not in channel_set:
                issue(
                    "semantic.unknown_node_channel",
                    node.node_uuid,
                    f"Unknown channel {channel_id!r}.",
                )
        for dependency in node.depends_on:
            if dependency not in node_set:
                issue(
                    "semantic.unknown_node_dependency",
                    node.node_uuid,
                    f"Unknown node dependency {dependency!r}.",
                )
        for frame_id in _solver_frame_ids(node.solver):
            if frame_id not in frame_set:
                issue(
                    "semantic.unknown_solver_frame",
                    node.node_uuid,
                    f"Unknown solver frame {frame_id!r}.",
                )
        if isinstance(node.solver, PoseMapSolverSpec) and not node.solver.pose_field_id:
            issue("semantic.missing_pose_field", node.node_uuid, "Pose field ID is required.")
        if isinstance(
            node.solver,
            (ChainFKSolverSpec, ChainIKSolverSpec, SplineSolverSpec),
        ) and len(node.solver.chain_bones) < 2:
            issue(
                "semantic.insufficient_chain_bones",
                node.node_uuid,
                "A chain solver requires at least two bones.",
            )
        if isinstance(node.solver, BboneBezierSolverSpec):
            if not node.solver.deform_bone:
                issue(
                    "semantic.missing_bbone_deform_bone",
                    node.node_uuid,
                    "A B-Bone Bezier solver requires one deform bone.",
                )
            if node.solver.segments < 2:
                issue(
                    "semantic.invalid_bbone_segments",
                    node.node_uuid,
                    "B-Bone segments must be at least two.",
                )
            if any(value <= 0.0 for value in node.solver.scale_in + node.solver.scale_out):
                issue(
                    "semantic.invalid_bbone_scale",
                    node.node_uuid,
                    "B-Bone start/end scale components must be positive.",
                )
    node_edges = {item.node_uuid: item.depends_on for item in spec.nodes}
    if _has_cycle(node_edges):
        issue("semantic.node_cycle", spec.rig_uuid, "Solver graph has a cycle.")

    for output in spec.outputs:
        if not 1 <= output.value_arity <= 4:
            issue(
                "semantic.invalid_output_arity",
                output.output_uuid,
                "Output arity must be between one and four.",
            )
        if output.discrete and output.value_arity != 1:
            issue(
                "semantic.vector_discrete_output",
                output.output_uuid,
                "Discrete outputs must be scalar.",
            )
        if output.channel_id not in channel_set:
            issue(
                "semantic.unknown_output_channel",
                output.output_uuid,
                f"Unknown output channel {output.channel_id!r}.",
            )
        if output.art_frame_id and output.art_frame_id not in frame_set:
            issue(
                "semantic.unknown_output_art_frame",
                output.output_uuid,
                f"Unknown art frame {output.art_frame_id!r}.",
            )
        if not output.target.object_name or not output.target.target_name:
            issue(
                "semantic.incomplete_output_target",
                output.output_uuid,
                "Output object and target names are required.",
            )

    for presentation in spec.presentations:
        if presentation.display_frame_id not in frame_set:
            issue(
                "semantic.unknown_presentation_frame",
                presentation.presentation_uuid,
                f"Unknown display frame {presentation.display_frame_id!r}.",
            )
        try:
            target_role = WidgetTargetRole(presentation.target_role)
        except ValueError:
            target_role = None
            issue(
                "semantic.invalid_presentation_role",
                presentation.presentation_uuid,
                f"Unknown presentation target role {presentation.target_role!r}.",
            )
        if presentation.target_index < -1:
            issue(
                "semantic.invalid_presentation_index",
                presentation.presentation_uuid,
                "Presentation target index must be -1 or greater.",
            )
        elif (
            target_role is not None
            and target_role is not WidgetTargetRole.SPLINE_CONTROL
            and presentation.target_index != -1
        ):
            issue(
                "semantic.invalid_presentation_index",
                presentation.presentation_uuid,
                "Only spline-control presentations may select a target index.",
            )
        if not (
            presentation.widget_spec_id
            or presentation.geometry_node_group
            or presentation.preset_id
            or presentation.settings.shape != RigWidgetShape.NONE
        ):
            issue(
                "semantic.missing_widget_reference",
                presentation.presentation_uuid,
                "A widget, Geometry Nodes group or preset reference is required.",
            )
        for presentation_issue in validate_widget_presentation(
            presentation.settings,
            presentation.presentation_uuid,
        ):
            issue(
                presentation_issue.code.replace("component.", "semantic.", 1),
                presentation.presentation_uuid,
                presentation_issue.message,
            )

    return tuple(issues)
