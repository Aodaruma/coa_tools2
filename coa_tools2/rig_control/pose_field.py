"""Pure-math recorded pose-field evaluation for semantic rigs.

The evaluator is deliberately independent of Blender and supports any positive
number of input dimensions.  It uses a compact local radial basis kernel,
normalizes weights, reproduces exact samples, and falls back to the nearest
sample when a query lies outside all local kernels.  Discrete outputs always
use nearest-sample selection and are never numerically blended.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Mapping, Sequence, Union


POSE_FIELD_SCHEMA_VERSION = 1
DiscreteValue = Union[None, bool, int, float, str]


@dataclass(frozen=True)
class PoseContinuousOutput:
    output_id: str
    value: tuple[float, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"output_id": self.output_id, "value": list(self.value)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PoseContinuousOutput":
        return cls(str(data["output_id"]), tuple(float(v) for v in data["value"]))


@dataclass(frozen=True)
class PoseDiscreteOutput:
    output_id: str
    value: DiscreteValue

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PoseDiscreteOutput":
        return cls(str(data["output_id"]), data.get("value"))


@dataclass(frozen=True)
class PoseOutputSnapshot:
    """All outputs recorded at a pose-field sample.

    Continuous values are vectors so a snapshot can carry a scalar Shape Key,
    a 3D translation, a quaternion or a complete transform without changing
    the interpolation schema.  Discrete outputs cover slots, modes and other
    nearest/step values.
    """

    continuous: tuple[PoseContinuousOutput, ...] = ()
    discrete: tuple[PoseDiscreteOutput, ...] = ()

    @classmethod
    def from_values(
        cls,
        continuous: Mapping[str, Union[float, Sequence[float]]] | None = None,
        discrete: Mapping[str, DiscreteValue] | None = None,
    ) -> "PoseOutputSnapshot":
        continuous_items: list[PoseContinuousOutput] = []
        for output_id, value in (continuous or {}).items():
            if isinstance(value, (int, float)):
                vector = (float(value),)
            else:
                vector = tuple(float(component) for component in value)
            continuous_items.append(PoseContinuousOutput(output_id, vector))
        discrete_items = tuple(
            PoseDiscreteOutput(output_id, value)
            for output_id, value in (discrete or {}).items()
        )
        return cls(tuple(continuous_items), discrete_items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "continuous": [item.to_dict() for item in self.continuous],
            "discrete": [item.to_dict() for item in self.discrete],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PoseOutputSnapshot":
        return cls(
            tuple(
                PoseContinuousOutput.from_dict(item)
                for item in data.get("continuous", ())
            ),
            tuple(
                PoseDiscreteOutput.from_dict(item)
                for item in data.get("discrete", ())
            ),
        )

    def continuous_value(self, output_id: str) -> Union[float, tuple[float, ...]]:
        for item in self.continuous:
            if item.output_id == output_id:
                return item.value[0] if len(item.value) == 1 else item.value
        raise KeyError(output_id)

    def discrete_value(self, output_id: str) -> DiscreteValue:
        for item in self.discrete:
            if item.output_id == output_id:
                return item.value
        raise KeyError(output_id)


@dataclass(frozen=True)
class PoseFieldDimension:
    channel_id: str
    scale: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PoseFieldDimension":
        return cls(str(data["channel_id"]), float(data.get("scale", 1.0)))


@dataclass(frozen=True)
class PoseFieldSample:
    sample_uuid: str
    position: tuple[float, ...]
    outputs: PoseOutputSnapshot
    display_name: str = ""
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_uuid": self.sample_uuid,
            "position": list(self.position),
            "outputs": self.outputs.to_dict(),
            "display_name": self.display_name,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PoseFieldSample":
        return cls(
            sample_uuid=str(data["sample_uuid"]),
            position=tuple(float(value) for value in data["position"]),
            outputs=PoseOutputSnapshot.from_dict(data["outputs"]),
            display_name=str(data.get("display_name", "")),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass(frozen=True)
class PoseFieldSpec:
    field_uuid: str
    semantic_id: str
    dimensions: tuple[PoseFieldDimension, ...]
    samples: tuple[PoseFieldSample, ...]
    neighborhood_size: int = 8
    kernel_radius: float = 2.0
    exact_epsilon: float = 1.0e-8
    minimum_weight: float = 1.0e-12
    schema_version: int = POSE_FIELD_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_uuid": self.field_uuid,
            "semantic_id": self.semantic_id,
            "dimensions": [item.to_dict() for item in self.dimensions],
            "samples": [item.to_dict() for item in self.samples],
            "neighborhood_size": self.neighborhood_size,
            "kernel_radius": self.kernel_radius,
            "exact_epsilon": self.exact_epsilon,
            "minimum_weight": self.minimum_weight,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PoseFieldSpec":
        values = dict(data)
        values["dimensions"] = tuple(
            PoseFieldDimension.from_dict(item)
            for item in values.get("dimensions", ())
        )
        values["samples"] = tuple(
            PoseFieldSample.from_dict(item) for item in values.get("samples", ())
        )
        return cls(**values)


@dataclass(frozen=True)
class PoseSampleWeight:
    sample_uuid: str
    weight: float
    distance: float


@dataclass(frozen=True)
class PoseFieldEvaluation:
    outputs: PoseOutputSnapshot
    sample_weights: tuple[PoseSampleWeight, ...]
    exact_sample_uuid: str = ""
    used_nearest_fallback: bool = False


@dataclass(frozen=True)
class PoseFieldValidationIssue:
    code: str
    subject_id: str
    message: str


def _scaled_distance(
    position: Sequence[float],
    sample: Sequence[float],
    dimensions: Sequence[PoseFieldDimension],
) -> float:
    return math.sqrt(
        sum(
            ((float(value) - float(sample_value)) / dimension.scale) ** 2
            for value, sample_value, dimension in zip(
                position, sample, dimensions
            )
        )
    )


def _wendland_c2(distance: float, radius: float) -> float:
    normalized = distance / radius
    if normalized >= 1.0:
        return 0.0
    remainder = 1.0 - normalized
    return remainder ** 4 * (4.0 * normalized + 1.0)


def _query_vector(
    spec: PoseFieldSpec,
    query: Union[Sequence[float], Mapping[str, float]],
) -> tuple[float, ...]:
    if isinstance(query, Mapping):
        try:
            vector = tuple(float(query[item.channel_id]) for item in spec.dimensions)
        except KeyError as error:
            raise ValueError(f"Missing pose-field input {error.args[0]!r}.") from error
    else:
        vector = tuple(float(value) for value in query)
    if len(vector) != len(spec.dimensions):
        raise ValueError(
            f"Expected {len(spec.dimensions)} pose-field values, got {len(vector)}."
        )
    if not all(math.isfinite(value) for value in vector):
        raise ValueError("Pose-field input values must be finite.")
    return vector


def _weighted_snapshot(
    neighbors: Sequence[tuple[float, int, PoseFieldSample, float]],
) -> PoseOutputSnapshot:
    continuous_ids: list[str] = []
    for _, _, sample, _ in neighbors:
        for output in sample.outputs.continuous:
            if output.output_id not in continuous_ids:
                continuous_ids.append(output.output_id)

    continuous: list[PoseContinuousOutput] = []
    for output_id in continuous_ids:
        contributors: list[tuple[float, tuple[float, ...]]] = []
        for _, _, sample, weight in neighbors:
            for output in sample.outputs.continuous:
                if output.output_id == output_id:
                    contributors.append((weight, output.value))
                    break
        total = sum(weight for weight, _ in contributors)
        if total <= 0.0:
            continue
        component_count = len(contributors[0][1])
        value = tuple(
            sum(weight * vector[index] for weight, vector in contributors) / total
            for index in range(component_count)
        )
        continuous.append(PoseContinuousOutput(output_id, value))

    nearest_sample = min(neighbors, key=lambda item: (item[0], item[1]))[2]
    return PoseOutputSnapshot(tuple(continuous), nearest_sample.outputs.discrete)


def evaluate_pose_field(
    spec: PoseFieldSpec,
    query: Union[Sequence[float], Mapping[str, float]],
) -> PoseFieldEvaluation:
    """Evaluate an arbitrary-dimensional local RBF pose field.

    Enabled samples keep their declaration order as a deterministic tie-break.
    An exact match bypasses interpolation.  If no compact kernel reaches the
    query, the nearest sample is returned as a safe extrapolation fallback.
    """

    if not spec.dimensions:
        raise ValueError("A pose field needs at least one input dimension.")
    if any(dimension.scale <= 0.0 for dimension in spec.dimensions):
        raise ValueError("Pose-field channel scales must be positive.")
    if spec.neighborhood_size < 1:
        raise ValueError("Pose-field neighborhood size must be positive.")
    if spec.kernel_radius <= 0.0:
        raise ValueError("Pose-field kernel radius must be positive.")

    vector = _query_vector(spec, query)
    ranked: list[tuple[float, int, PoseFieldSample]] = []
    for index, sample in enumerate(spec.samples):
        if not sample.enabled:
            continue
        if len(sample.position) != len(spec.dimensions):
            raise ValueError(
                f"Sample {sample.sample_uuid!r} has the wrong input dimension."
            )
        distance = _scaled_distance(vector, sample.position, spec.dimensions)
        ranked.append((distance, index, sample))
    if not ranked:
        raise ValueError("A pose field needs at least one enabled sample.")
    ranked.sort(key=lambda item: (item[0], item[1]))

    nearest_distance, _, nearest_sample = ranked[0]
    if nearest_distance <= spec.exact_epsilon:
        return PoseFieldEvaluation(
            nearest_sample.outputs,
            (PoseSampleWeight(nearest_sample.sample_uuid, 1.0, nearest_distance),),
            exact_sample_uuid=nearest_sample.sample_uuid,
        )

    local = ranked[: spec.neighborhood_size]
    weighted = [
        (distance, index, sample, _wendland_c2(distance, spec.kernel_radius))
        for distance, index, sample in local
    ]
    weight_sum = sum(item[3] for item in weighted)
    if weight_sum <= spec.minimum_weight:
        return PoseFieldEvaluation(
            nearest_sample.outputs,
            (PoseSampleWeight(nearest_sample.sample_uuid, 1.0, nearest_distance),),
            used_nearest_fallback=True,
        )

    normalized = tuple(
        PoseSampleWeight(sample.sample_uuid, weight / weight_sum, distance)
        for distance, _, sample, weight in weighted
        if weight > 0.0
    )
    active_ids = {item.sample_uuid: item.weight for item in normalized}
    active = tuple(
        (distance, index, sample, active_ids[sample.sample_uuid])
        for distance, index, sample, _ in weighted
        if sample.sample_uuid in active_ids
    )
    return PoseFieldEvaluation(
        _weighted_snapshot(active),
        normalized,
    )


def validate_pose_field(
    spec: PoseFieldSpec,
) -> tuple[PoseFieldValidationIssue, ...]:
    issues: list[PoseFieldValidationIssue] = []

    def issue(code: str, subject: str, message: str) -> None:
        issues.append(PoseFieldValidationIssue(code, subject, message))

    if not spec.field_uuid:
        issue("pose_field.missing_uuid", "", "Pose-field UUID is required.")
    if not spec.semantic_id:
        issue("pose_field.missing_semantic_id", spec.field_uuid, "Semantic ID is required.")
    if not spec.dimensions:
        issue("pose_field.missing_dimensions", spec.field_uuid, "At least one dimension is required.")
    dimension_ids = [item.channel_id for item in spec.dimensions]
    if any(not item for item in dimension_ids):
        issue("pose_field.missing_channel_id", spec.field_uuid, "Dimension channel IDs are required.")
    if len(set(dimension_ids)) != len(dimension_ids):
        issue("pose_field.duplicate_channel", spec.field_uuid, "Dimension channel IDs must be unique.")
    for dimension in spec.dimensions:
        if not math.isfinite(dimension.scale) or dimension.scale <= 0.0:
            issue("pose_field.invalid_scale", dimension.channel_id, "Dimension scale must be finite and positive.")
    if spec.neighborhood_size < 1:
        issue("pose_field.invalid_neighborhood", spec.field_uuid, "Neighborhood size must be positive.")
    if not math.isfinite(spec.kernel_radius) or spec.kernel_radius <= 0.0:
        issue("pose_field.invalid_radius", spec.field_uuid, "Kernel radius must be finite and positive.")
    if spec.exact_epsilon < 0.0 or not math.isfinite(spec.exact_epsilon):
        issue("pose_field.invalid_epsilon", spec.field_uuid, "Exact epsilon must be finite and non-negative.")
    if spec.minimum_weight < 0.0 or not math.isfinite(spec.minimum_weight):
        issue("pose_field.invalid_minimum_weight", spec.field_uuid, "Minimum weight must be finite and non-negative.")

    sample_ids: set[str] = set()
    sample_positions: set[tuple[float, ...]] = set()
    output_dimensions: dict[str, int] = {}
    enabled_count = 0
    for sample in spec.samples:
        if not sample.sample_uuid:
            issue("pose_field.missing_sample_uuid", "", "Sample UUID is required.")
        elif sample.sample_uuid in sample_ids:
            issue("pose_field.duplicate_sample_uuid", sample.sample_uuid, "Sample UUID must be unique.")
        sample_ids.add(sample.sample_uuid)
        if sample.enabled:
            enabled_count += 1
        if len(sample.position) != len(spec.dimensions):
            issue("pose_field.sample_dimension_mismatch", sample.sample_uuid, "Sample position dimension does not match the field.")
        elif not all(math.isfinite(value) for value in sample.position):
            issue("pose_field.non_finite_position", sample.sample_uuid, "Sample position must be finite.")
        elif sample.enabled and sample.position in sample_positions:
            issue("pose_field.duplicate_position", sample.sample_uuid, "Enabled sample positions must be unique.")
        if sample.enabled:
            sample_positions.add(sample.position)

        continuous_ids: set[str] = set()
        discrete_ids: set[str] = set()
        for output in sample.outputs.continuous:
            if not output.output_id or output.output_id in continuous_ids:
                issue("pose_field.duplicate_continuous_output", sample.sample_uuid, "Continuous output IDs must be present and unique per sample.")
            continuous_ids.add(output.output_id)
            if not output.value or not all(math.isfinite(value) for value in output.value):
                issue("pose_field.invalid_continuous_output", output.output_id, "Continuous output vectors must be non-empty and finite.")
            previous = output_dimensions.setdefault(output.output_id, len(output.value))
            if previous != len(output.value):
                issue("pose_field.output_dimension_mismatch", output.output_id, "An output must keep the same vector size in every sample.")
        for output in sample.outputs.discrete:
            if not output.output_id or output.output_id in discrete_ids:
                issue("pose_field.duplicate_discrete_output", sample.sample_uuid, "Discrete output IDs must be present and unique per sample.")
            discrete_ids.add(output.output_id)
        for conflict in continuous_ids & discrete_ids:
            issue("pose_field.output_kind_conflict", conflict, "An output cannot be continuous and discrete in the same sample.")

    if enabled_count == 0:
        issue("pose_field.no_enabled_samples", spec.field_uuid, "At least one enabled sample is required.")
    return tuple(issues)
