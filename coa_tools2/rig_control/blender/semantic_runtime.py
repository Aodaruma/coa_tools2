"""Blender driver runtime for arbitrary-dimensional semantic pose fields.

The driver namespace only receives stable identifiers.  Blender object and
bone names are deliberately not part of the lookup key so renames and file
reloads do not invalidate generated expressions.  PropertyGroup conversion is
kept permissive because the RNA storage schema may evolve independently from
the pure :mod:`coa_tools2.rig_control.pose_field` schema.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
from typing import Any, Iterable, Mapping, Sequence

import bpy
from bpy.app.handlers import persistent

from ..pose_field import (
    DiscreteValue,
    PoseContinuousOutput,
    PoseDiscreteOutput,
    PoseFieldDimension,
    PoseFieldSample,
    PoseFieldSpec,
    PoseOutputSnapshot,
    evaluate_pose_field,
)


CONTINUOUS_NAMESPACE_NAME = "coa_pose_field_scalar"
DISCRETE_NAMESPACE_NAME = "coa_pose_field_discrete"


class SemanticRuntimeError(RuntimeError):
    """Base error for explicit semantic-runtime API calls."""


class PoseFieldAdapterError(SemanticRuntimeError):
    """Raised when persisted pose-field data cannot form a pure spec."""


class PoseFieldResolutionError(SemanticRuntimeError):
    """Raised when a stable runtime key cannot be resolved in the file."""


@dataclass(frozen=True)
class PoseFieldRuntimeKey:
    rig_instance_uuid: str
    component_uuid: str
    stage_uuid: str
    output_id: str

    @property
    def field_key(self) -> tuple[str, str, str]:
        return (
            self.rig_instance_uuid,
            self.component_uuid,
            self.stage_uuid,
        )


_MISSING = object()
_NO_DEFAULT = object()
_FIELD_CACHE: dict[PoseFieldRuntimeKey, PoseFieldSpec | None] = {}


def _stable_token(value: Any, length: int = 16) -> str:
    normalized = re.sub(r"[^0-9A-Za-z]", "", str(value or ""))
    return normalized[:length]


def _id_matches(value: Any, token: str) -> bool:
    normalized = re.sub(r"[^0-9A-Za-z]", "", str(value or ""))
    return bool(token) and (normalized == token or normalized.startswith(token))


def _value(owner: Any, names: Sequence[str], default: Any = _NO_DEFAULT) -> Any:
    """Read the first available attribute or mapping value from ``owner``."""

    for name in names:
        try:
            value = getattr(owner, name)
        except (AttributeError, ReferenceError):
            value = _MISSING
        if value is not _MISSING:
            return value
        if isinstance(owner, Mapping) and name in owner:
            return owner[name]
        getter = getattr(owner, "get", None)
        if getter is not None:
            try:
                value = getter(name, _MISSING)
            except (AttributeError, ReferenceError, TypeError):
                value = _MISSING
            if value is not _MISSING:
                return value
    if default is _NO_DEFAULT:
        raise PoseFieldAdapterError(
            f"Missing persisted field; expected one of {tuple(names)!r}."
        )
    return default


def _collection(owner: Any, names: Sequence[str]) -> tuple[Any, ...]:
    value = _value(owner, names, ())
    if value is None or isinstance(value, (str, bytes)):
        return ()
    try:
        return tuple(value)
    except (ReferenceError, TypeError):
        return ()


def _identifier(owner: Any, names: Sequence[str]) -> str:
    return str(_value(owner, names, "") or "")


def _float_tuple(value: Any) -> tuple[float, ...]:
    if value is None:
        return ()
    if isinstance(value, (int, float)):
        return (float(value),)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return (float(value),)
        return _float_tuple(decoded)
    try:
        values = tuple(value)
    except TypeError:
        scalar = _value(value, ("value", "scalar_value"), _MISSING)
        if scalar is _MISSING:
            raise PoseFieldAdapterError("Expected a scalar or numeric sequence.")
        return (float(scalar),)
    if values and not isinstance(values[0], (int, float)):
        values = tuple(_value(item, ("value", "scalar_value")) for item in values)
    return tuple(float(component) for component in values)


def _discrete_value(item: Any) -> DiscreteValue:
    value_kind = _identifier(item, ("value_type", "kind", "data_type")).upper()
    if value_kind in {"BOOL", "BOOLEAN"}:
        return bool(_value(item, ("bool_value", "value"), False))
    if value_kind in {"INT", "INTEGER", "SLOT", "INDEX"}:
        return int(_value(item, ("int_value", "value"), 0))
    if value_kind in {"FLOAT", "SCALAR"}:
        return float(_value(item, ("float_value", "value"), 0.0))
    if value_kind in {"STRING", "ENUM"}:
        return str(_value(item, ("string_value", "value"), ""))
    return _value(
        item,
        ("value", "discrete_value", "int_value", "float_value", "string_value"),
        None,
    )


def _continuous_outputs(sample: Any, outputs_owner: Any) -> tuple[PoseContinuousOutput, ...]:
    items = _collection(
        outputs_owner,
        ("continuous", "continuous_outputs", "scalar_outputs"),
    )
    if not items and outputs_owner is not sample:
        items = _collection(
            sample,
            ("continuous", "continuous_outputs", "scalar_outputs"),
        )
    result: list[PoseContinuousOutput] = []
    for item in items:
        output_id = _identifier(item, ("output_id", "output_uuid", "channel_id"))
        if not output_id:
            continue
        raw_value = _value(item, ("value", "values", "vector", "scalar_value"), 0.0)
        vector = _float_tuple(raw_value)
        if vector and all(math.isfinite(value) for value in vector):
            result.append(PoseContinuousOutput(output_id, vector))
    return tuple(result)


def _discrete_outputs(sample: Any, outputs_owner: Any) -> tuple[PoseDiscreteOutput, ...]:
    items = _collection(outputs_owner, ("discrete", "discrete_outputs"))
    if not items and outputs_owner is not sample:
        items = _collection(sample, ("discrete", "discrete_outputs"))
    result: list[PoseDiscreteOutput] = []
    for item in items:
        output_id = _identifier(item, ("output_id", "output_uuid", "channel_id"))
        if output_id:
            result.append(PoseDiscreteOutput(output_id, _discrete_value(item)))
    return tuple(result)


def _stage_output_metadata(stage: Any) -> dict[str, Any]:
    """Index enabled stage outputs by both UUID and semantic output ID."""

    metadata: dict[str, Any] = {}
    for output in _collection(stage, ("outputs", "output_channels")):
        if not bool(_value(output, ("enabled", "is_enabled"), True)):
            continue
        for identifier in (
            _identifier(output, ("output_uuid",)),
            _identifier(output, ("output_id", "channel_id")),
        ):
            if identifier:
                metadata[identifier] = output
    return metadata


def _sample_outputs(
    sample: Any,
    stage_outputs: Mapping[str, Any] | None = None,
) -> PoseOutputSnapshot:
    outputs_owner = _value(sample, ("outputs", "output_snapshot"), sample)

    # Current SemanticStage RNA stores all sample outputs in one collection.
    # Output kind belongs to the stage metadata, rather than being duplicated
    # on every recorded sample.
    if stage_outputs is not None:
        continuous: list[PoseContinuousOutput] = []
        discrete: list[PoseDiscreteOutput] = []
        for item in _collection(sample, ("outputs", "output_values")):
            reference = _identifier(
                item, ("output_uuid", "output_id", "channel_id")
            )
            metadata = stage_outputs.get(reference)
            if metadata is None:
                continue
            output_id = _identifier(
                metadata, ("output_uuid", "output_id", "channel_id")
            )
            if not output_id:
                continue
            if bool(_value(metadata, ("discrete", "is_discrete"), False)):
                discrete.append(
                    PoseDiscreteOutput(
                        output_id,
                        _value(item, ("discrete_value", "value"), None),
                    )
                )
                continue
            raw_value = _value(
                item, ("value", "values", "vector", "scalar_value"), ()
            )
            try:
                vector = _float_tuple(raw_value)
                arity = int(
                    _value(
                        item,
                        ("value_arity",),
                        _value(metadata, ("value_arity",), len(vector)),
                    )
                )
            except (PoseFieldAdapterError, TypeError, ValueError):
                continue
            if arity < 1 or len(vector) < arity:
                continue
            vector = vector[:arity]
            if all(math.isfinite(value) for value in vector):
                continuous.append(PoseContinuousOutput(output_id, vector))
        return PoseOutputSnapshot(tuple(continuous), tuple(discrete))

    continuous = _continuous_outputs(sample, outputs_owner)
    discrete = _discrete_outputs(sample, outputs_owner)

    # A single heterogeneous collection is convenient for RNA UIs.  Accept it
    # in addition to the pure schema's two explicitly typed collections.
    if not continuous and not discrete:
        for item in _collection(sample, ("output_values", "values")):
            output_id = _identifier(
                item, ("output_id", "output_uuid", "channel_id")
            )
            if not output_id:
                continue
            output_kind = _identifier(item, ("output_kind", "kind")).upper()
            if output_kind in {"DISCRETE", "STEP", "NEAREST"}:
                discrete += (PoseDiscreteOutput(output_id, _discrete_value(item)),)
            else:
                raw = _value(
                    item, ("value", "values", "vector", "scalar_value"), 0.0
                )
                vector = _float_tuple(raw)
                if vector:
                    continuous += (PoseContinuousOutput(output_id, vector),)
    return PoseOutputSnapshot(continuous, discrete)


def _stage_dimensions(stage: Any) -> tuple[tuple[PoseFieldDimension, ...], tuple[tuple[str, ...], ...]]:
    """Return dimensions and accepted sample-input IDs in stage order."""

    dimensions: list[PoseFieldDimension] = []
    aliases: list[tuple[str, ...]] = []
    for channel in _collection(stage, ("inputs", "input_channels")):
        channel_uuid = _identifier(channel, ("channel_uuid",))
        channel_id = _identifier(channel, ("channel_id", "semantic_id", "name"))
        dimension_id = channel_uuid or channel_id
        if not dimension_id:
            continue
        scale = float(_value(channel, ("scale", "normalization_scale"), 1.0))
        dimensions.append(PoseFieldDimension(dimension_id, scale))
        aliases.append(
            tuple(value for value in (channel_uuid, channel_id) if value)
        )
    return tuple(dimensions), tuple(aliases)


def _stage_sample_position(
    sample: Any,
    dimension_aliases: Sequence[Sequence[str]],
) -> tuple[float, ...] | None:
    """Order recorded inputs by stage channels; reject incomplete samples."""

    recorded: dict[str, float] = {}
    for item in _collection(sample, ("inputs", "input_values")):
        identifier = _identifier(item, ("channel_uuid", "channel_id"))
        if not identifier:
            continue
        try:
            recorded[identifier] = float(_value(item, ("value", "scalar_value")))
        except (PoseFieldAdapterError, TypeError, ValueError):
            return None
    position: list[float] = []
    for aliases in dimension_aliases:
        value = next((recorded[item] for item in aliases if item in recorded), _MISSING)
        if value is _MISSING or not math.isfinite(value):
            return None
        position.append(value)
    return tuple(position)


def pose_field_spec_from_property_group(field: Any) -> PoseFieldSpec:
    """Build a pure :class:`PoseFieldSpec` from flexible RNA-like storage.

    Besides Blender PropertyGroups, dictionaries and small test doubles are
    accepted.  Invalid individual samples are retained where possible so the
    pure evaluator/validator remains the single authority on field validity.
    """

    serialized = _value(
        field, ("pose_field_json", "spec_json", "serialized_spec"), None
    )
    if serialized:
        try:
            return PoseFieldSpec.from_dict(json.loads(str(serialized)))
        except (KeyError, TypeError, ValueError) as error:
            raise PoseFieldAdapterError("Invalid serialized pose-field spec.") from error

    stage_dimensions, dimension_aliases = _stage_dimensions(field)
    stage_outputs = _stage_output_metadata(field)
    uses_stage_storage = bool(stage_dimensions) or bool(stage_outputs)

    dimensions: list[PoseFieldDimension] = list(stage_dimensions)
    if not dimensions:
        for dimension in _collection(
            field, ("dimensions", "input_dimensions", "channels")
        ):
            channel_id = _identifier(
                dimension, ("channel_id", "dimension_id", "semantic_id", "name")
            )
            if not channel_id:
                continue
            scale = float(
                _value(dimension, ("scale", "normalization_scale"), 1.0)
            )
            dimensions.append(PoseFieldDimension(channel_id, scale))

    samples: list[PoseFieldSample] = []
    for sample in _collection(field, ("samples", "pose_samples", "recorded_poses")):
        if uses_stage_storage:
            position = _stage_sample_position(sample, dimension_aliases)
            if position is None:
                continue
        else:
            raw_position = _value(
                sample,
                ("position", "input_position", "query", "coordinates"),
                _MISSING,
            )
            if raw_position is _MISSING:
                raw_position = _collection(
                    sample,
                    ("position_values", "input_values", "coordinates_values"),
                )
            try:
                position = _float_tuple(raw_position)
            except (PoseFieldAdapterError, TypeError, ValueError):
                continue
        samples.append(
            PoseFieldSample(
                sample_uuid=_identifier(
                    sample, ("sample_uuid", "pose_uuid", "uuid", "name")
                ),
                position=position,
                outputs=_sample_outputs(
                    sample, stage_outputs if uses_stage_storage else None
                ),
                display_name=str(_value(sample, ("display_name", "label"), "")),
                enabled=bool(_value(sample, ("enabled", "is_enabled"), True)),
            )
        )

    field_uuid = _identifier(field, ("field_uuid", "pose_field_uuid", "stage_uuid"))
    semantic_id = _identifier(field, ("semantic_id", "field_id", "name"))
    return PoseFieldSpec(
        field_uuid=field_uuid,
        semantic_id=semantic_id or field_uuid,
        dimensions=tuple(dimensions),
        samples=tuple(samples),
        neighborhood_size=int(
            _value(field, ("neighborhood_size", "neighbor_count"), 8)
        ),
        kernel_radius=float(_value(field, ("kernel_radius", "radius"), 2.0)),
        exact_epsilon=float(_value(field, ("exact_epsilon",), 1.0e-8)),
        minimum_weight=float(_value(field, ("minimum_weight",), 1.0e-12)),
        schema_version=int(_value(field, ("schema_version",), 1)),
    )


def clear_pose_field_cache(*_args: Any) -> None:
    """Discard positive and negative UUID-resolution cache entries."""

    _FIELD_CACHE.clear()


def _rig_data(armature: Any) -> Any:
    dedicated = getattr(armature, "coa_tools2_rig", None)
    return dedicated if dedicated is not None else getattr(armature, "coa_tools2", None)


def _find_armature(rig_instance_uuid: str) -> Any | None:
    for armature in bpy.data.objects:
        if getattr(armature, "type", "") != "ARMATURE":
            continue
        rig_data = _rig_data(armature)
        if rig_data is not None and _identifier(
            rig_data, ("rig_instance_id", "rig_instance_uuid", "rig_uuid")
        ) and _id_matches(
            _identifier(rig_data, ("rig_instance_id", "rig_instance_uuid", "rig_uuid")),
            rig_instance_uuid,
        ):
            return armature
    return None


def _find_by_id(items: Iterable[Any], identifier: str, names: Sequence[str]) -> Any | None:
    return next(
        (item for item in items if _id_matches(_identifier(item, names), identifier)),
        None,
    )


def _resolve_field_storage(
    rig_instance_uuid: str,
    component_uuid: str,
    stage_uuid: str,
) -> Any:
    armature = _find_armature(rig_instance_uuid)
    if armature is None:
        raise PoseFieldResolutionError("Semantic rig Armature was not found.")
    rig_data = _rig_data(armature)
    components = _collection(
        rig_data,
        ("semantic_components", "rig_components", "components", "semantic_rigs"),
    )
    component = _find_by_id(
        components,
        component_uuid,
        ("component_uuid", "rig_uuid", "control_uuid", "uuid"),
    )

    if component is not None:
        stages = _collection(
            component,
            ("stages", "solver_stages", "semantic_stages", "nodes", "pose_fields"),
        )
        stage = _find_by_id(
            stages,
            stage_uuid,
            ("stage_uuid", "node_uuid", "field_uuid", "pose_field_uuid", "uuid"),
        )
        if stage is not None:
            nested = _value(stage, ("pose_field", "field", "pose_map"), None)
            if nested is not None:
                return nested
            reference = _identifier(stage, ("pose_field_uuid", "field_uuid"))
            if _collection(stage, ("samples", "pose_samples", "recorded_poses")):
                return stage
            if reference:
                stage_uuid = reference

    # Some schemas keep potentially shared pose fields at rig level and store
    # owner UUIDs beside them.  This path also supports a field before a full
    # semantic component PropertyGroup has been introduced.
    fields = _collection(
        rig_data, ("pose_fields", "recorded_pose_fields", "semantic_pose_fields")
    )
    for field in fields:
        if _identifier(
            field, ("field_uuid", "pose_field_uuid", "stage_uuid", "uuid")
        ) and not _id_matches(
            _identifier(field, ("field_uuid", "pose_field_uuid", "stage_uuid", "uuid")),
            stage_uuid,
        ):
            continue
        owner_uuid = _identifier(
            field, ("component_uuid", "owner_component_uuid", "rig_uuid")
        )
        if not owner_uuid or _id_matches(owner_uuid, component_uuid):
            return field
    raise PoseFieldResolutionError("Semantic pose-field stage was not found.")


def _resolve_spec(key: PoseFieldRuntimeKey) -> PoseFieldSpec | None:
    if key not in _FIELD_CACHE:
        try:
            storage = _resolve_field_storage(*key.field_key)
            _FIELD_CACHE[key] = pose_field_spec_from_property_group(storage)
        except Exception:
            # Driver evaluation must never destabilize Blender's dependency
            # graph.  Explicit conversion/resolution APIs still expose typed
            # errors for callers that need diagnostics.
            _FIELD_CACHE[key] = None
    return _FIELD_CACHE[key]


def _numeric_discrete(value: DiscreteValue) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        result = float(value)
        return result if math.isfinite(result) else 0.0
    try:
        result = float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def _query_for_spec(spec: PoseFieldSpec, values: Sequence[float]) -> tuple[float, ...] | None:
    if len(values) != len(spec.dimensions):
        return None
    try:
        query = tuple(float(value) for value in values)
    except (TypeError, ValueError):
        return None
    return query if all(math.isfinite(value) for value in query) else None


def _raw_rotation(owner: Any):
    mode = getattr(owner, "rotation_mode", "XYZ")
    if mode == "QUATERNION":
        return owner.rotation_quaternion.to_euler("XYZ")
    if mode == "AXIS_ANGLE":
        from mathutils import Quaternion

        angle, x, y, z = owner.rotation_axis_angle
        return Quaternion((x, y, z), angle).to_euler("XYZ")
    return owner.rotation_euler


def _matrix_rotation_order(owner: Any) -> str:
    mode = getattr(owner, "rotation_mode", "XYZ")
    return mode if mode in {"XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"} else "XYZ"


def _evaluated_transform_matrix(
    source: Any,
    owner: Any,
    transform_space: str,
    *,
    is_pose_bone: bool,
):
    """Return the matrix represented by a Transform Channel variable.

    Blender's ``WORLD_SPACE`` includes parenting, rest pose and constraints;
    ``LOCAL_SPACE`` includes constraints but excludes parenting/rest pose.
    Raw channels for ``TRANSFORM_SPACE`` are handled by the caller.
    """

    if transform_space == "WORLD_SPACE":
        return source.matrix_world @ owner.matrix if is_pose_bone else owner.matrix_world
    if transform_space == "LOCAL_SPACE":
        if is_pose_bone:
            return source.convert_space(
                pose_bone=owner,
                matrix=owner.matrix,
                from_space="POSE",
                to_space="LOCAL",
            )
        return owner.matrix_local
    raise PoseFieldAdapterError(
        f"Unsupported live input transform space: {transform_space}"
    )


def evaluate_live_input_term(term: Any, armature: Any) -> float:
    """Evaluate one stored input with the same semantics as its driver target."""

    source = _value(term, ("source_object",), None) or armature
    source_kind = _identifier(term, ("source_kind",)).upper()
    data_path = _identifier(term, ("data_path",))
    array_index = int(_value(term, ("array_index",), -1))
    if source_kind == "CUSTOM_PROPERTY":
        if not data_path:
            raise PoseFieldAdapterError("Live input property path is missing.")
        value = source.path_resolve(data_path)
        if array_index >= 0:
            value = value[array_index]
        return float(value)
    bone_name = _identifier(term, ("source_bone", "bone_target"))
    if bone_name and getattr(source, "type", "") != "ARMATURE":
        raise PoseFieldAdapterError(
            f"Live input bone '{bone_name}' requires an Armature source."
        )
    owner = source.pose.bones.get(bone_name) if bone_name else source
    if owner is None:
        raise PoseFieldAdapterError(f"Live input bone is missing: {bone_name}")
    transform_type = _identifier(term, ("transform_type",)).upper()
    try:
        axis = "XYZ".index(transform_type[-1])
    except (IndexError, ValueError) as exc:
        raise PoseFieldAdapterError("Invalid live input transform type.") from exc
    transform_space = _identifier(term, ("transform_space",)) or "LOCAL_SPACE"
    if transform_space == "TRANSFORM_SPACE":
        if transform_type.startswith("LOC_"):
            return float(owner.location[axis])
        if transform_type.startswith("ROT_"):
            return float(_raw_rotation(owner)[axis])
        if transform_type.startswith("SCALE_"):
            return float(owner.scale[axis])
        raise PoseFieldAdapterError(
            f"Unsupported live input transform: {transform_type}"
        )

    matrix = _evaluated_transform_matrix(
        source,
        owner,
        transform_space,
        is_pose_bone=bool(bone_name),
    )
    location, rotation, scale = matrix.decompose()
    if transform_type.startswith("LOC_"):
        return float(location[axis])
    if transform_type.startswith("ROT_"):
        return float(rotation.to_euler(_matrix_rotation_order(owner))[axis])
    if transform_type.startswith("SCALE_"):
        return float(scale[axis])
    raise PoseFieldAdapterError(f"Unsupported live input transform: {transform_type}")


def _live_term_value(term: Any, armature: Any) -> float:
    return evaluate_live_input_term(term, armature)


def _live_query(storage: Any, spec: PoseFieldSpec, armature: Any) -> tuple[float, ...] | None:
    values = []
    for channel in _collection(storage, ("inputs", "input_channels")):
        value = float(_value(channel, ("offset",), 0.0))
        for term in _collection(channel, ("terms", "input_terms")):
            value += float(_value(term, ("coefficient",), 1.0)) * _live_term_value(
                term, armature
            )
        values.append(value)
    return _query_for_spec(spec, values)


def _runtime_query(key: PoseFieldRuntimeKey, spec: PoseFieldSpec, values):
    if values:
        return _query_for_spec(spec, values)
    try:
        armature = _find_armature(key.rig_instance_uuid)
        storage = _resolve_field_storage(*key.field_key)
        return _live_query(storage, spec, armature) if armature is not None else None
    except Exception:
        return None


def evaluate_continuous_scalar(
    rig_instance_uuid: str,
    component_uuid: str,
    stage_uuid: str,
    output_id: str,
    *query_values: float,
) -> float:
    """Driver-safe continuous scalar lookup; invalid data returns ``0.0``."""

    key = PoseFieldRuntimeKey(
        str(rig_instance_uuid), str(component_uuid), str(stage_uuid), str(output_id)
    )
    spec = _resolve_spec(key)
    query = _runtime_query(key, spec, query_values) if spec is not None else None
    if spec is None or query is None:
        return 0.0
    try:
        evaluated = evaluate_pose_field(spec, query).outputs
        output_id = next(
            (
                item.output_id
                for item in evaluated.continuous
                if _id_matches(item.output_id, key.output_id)
            ),
            key.output_id,
        )
        output = evaluated.continuous_value(output_id)
    except (ArithmeticError, KeyError, TypeError, ValueError):
        return 0.0
    if isinstance(output, tuple):
        if len(output) != 1:
            return 0.0
        output = output[0]
    result = float(output)
    return result if math.isfinite(result) else 0.0


def evaluate_discrete_scalar(
    rig_instance_uuid: str,
    component_uuid: str,
    stage_uuid: str,
    output_id: str,
    *query_values: float,
) -> float:
    """Driver-safe nearest-sample discrete lookup converted to a number."""

    key = PoseFieldRuntimeKey(
        str(rig_instance_uuid), str(component_uuid), str(stage_uuid), str(output_id)
    )
    spec = _resolve_spec(key)
    query = _runtime_query(key, spec, query_values) if spec is not None else None
    if spec is None or query is None:
        return 0.0
    try:
        evaluated = evaluate_pose_field(spec, query).outputs
        output_id = next(
            (
                item.output_id
                for item in evaluated.discrete
                if _id_matches(item.output_id, key.output_id)
            ),
            key.output_id,
        )
        output = evaluated.discrete_value(output_id)
    except (ArithmeticError, KeyError, TypeError, ValueError):
        return 0.0
    return _numeric_discrete(output)


def pose_field_driver_expression(
    rig_instance_uuid: str,
    component_uuid: str,
    stage_uuid: str,
    output_id: str,
    input_expressions: Sequence[str],
    *,
    discrete: bool = False,
) -> str:
    """Return a rename-safe scripted-driver expression for a scalar output."""

    function_name = (
        DISCRETE_NAMESPACE_NAME if discrete else CONTINUOUS_NAMESPACE_NAME
    )
    identifiers = tuple(_stable_token(value) for value in (
        rig_instance_uuid,
        component_uuid,
        stage_uuid,
        output_id,
    ))
    arguments = [json.dumps(str(value)) for value in identifiers]
    arguments.extend(str(expression) for expression in input_expressions)
    return f"{function_name}({','.join(arguments)})"


def register_driver_namespace() -> None:
    """Install runtime callables into Blender's scripted-driver namespace."""

    bpy.app.driver_namespace[CONTINUOUS_NAMESPACE_NAME] = evaluate_continuous_scalar
    bpy.app.driver_namespace[DISCRETE_NAMESPACE_NAME] = evaluate_discrete_scalar


def unregister_driver_namespace() -> None:
    """Remove runtime callables and all cached RNA references/specifications."""

    bpy.app.driver_namespace.pop(CONTINUOUS_NAMESPACE_NAME, None)
    bpy.app.driver_namespace.pop(DISCRETE_NAMESPACE_NAME, None)
    clear_pose_field_cache()


@persistent
def semantic_runtime_load_post(_unused: Any = None) -> None:
    """Persistent ``load_post`` callback; registration is owned by the add-on."""

    clear_pose_field_cache()
    register_driver_namespace()
