"""Managed Blender outputs for arbitrary-dimensional semantic pose maps."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re

import bpy

from .artifacts import ensure_rig_instance_id
from .component_artifacts import _record_artifact
from .properties import get_rig_data
from .semantic_runtime import (
    clear_pose_field_cache,
    evaluate_live_input_term,
    pose_field_driver_expression,
)


class SemanticOutputError(RuntimeError):
    pass


@dataclass(frozen=True)
class SemanticTarget:
    id_data: object
    data_path: str
    array_index: int = -1


def _driver_token(output_uuid: str) -> str:
    token = re.sub(r"[^0-9A-Za-z]", "", output_uuid or "")[:16]
    return f"cs_{token or 'unknown'}_"


def _driver_tokens(output_uuid: str) -> tuple[str, ...]:
    """Return current and pre-16-character ownership prefixes."""

    normalized = re.sub(r"[^0-9A-Za-z]", "", output_uuid or "")
    return tuple(
        dict.fromkeys(
            f"cs_{normalized[:length] or 'unknown'}_" for length in (16, 12)
        )
    )


def _normalized_array_index(value: int) -> int:
    """Match Blender's scalar FCurve convention (reported as index zero)."""

    return max(0, int(value))


def _target_identity(target: SemanticTarget):
    return (
        target.id_data,
        target.data_path,
        _normalized_array_index(target.array_index),
    )


def _find_driver(target: SemanticTarget):
    animation_data = getattr(target.id_data, "animation_data", None)
    if animation_data is None:
        return None
    return next(
        (
            curve
            for curve in animation_data.drivers
            if curve.data_path == target.data_path
            and curve.array_index == _normalized_array_index(target.array_index)
        ),
        None,
    )


def _driver_uses_output(fcurve, armature, output_uuid: str) -> bool:
    if fcurve is None:
        return False
    prefixes = _driver_tokens(output_uuid)
    return any(
        variable.name.startswith(prefixes)
        and any(target.id == armature for target in variable.targets)
        for variable in fcurve.driver.variables
    )


def _shape_key_value_path(name: str) -> str:
    return f'key_blocks["{bpy.utils.escape_identifier(name)}"].value'


def _migrate_renamed_shape_key_output(armature, component, output) -> bool:
    """Follow a Blender-renamed KeyBlock using only strict managed identity.

    A KeyBlock rename updates its FCurve path, but not the stored output name or
    artifact string.  Do not infer from names alone: require one UUID-owned
    driver and its one owned artifact in this exact ShapeKeys datablock.
    """

    if output.target_kind != "SHAPE_KEY" or output.target_object is None:
        return False
    target_object = output.target_object
    if target_object.type != "MESH":
        return False
    shape_keys = getattr(target_object.data, "shape_keys", None)
    if (
        shape_keys is None
        or shape_keys.key_blocks.get(output.target_name) is not None
    ):
        return False

    stale_path = _shape_key_value_path(output.target_name)
    artifacts = [
        artifact
        for artifact in component.artifacts
        if artifact.data_type == "DRIVER"
        and artifact.role.startswith("semantic_output:")
        and artifact.binding_uuid == output.output_uuid
    ]
    locations = tuple(_owned_driver_locations(armature, output.output_uuid))
    if len(artifacts) != 1 or len(locations) != 1:
        return False
    artifact = artifacts[0]
    location = locations[0]
    if (
        not artifact.owned
        or artifact.object_name != shape_keys.name
        or artifact.data_path != stale_path
        or location.id_data != shape_keys
    ):
        return False

    renamed_keys = [
        key_block
        for key_block in shape_keys.key_blocks
        if key_block.path_from_id("value") == location.data_path
    ]
    if len(renamed_keys) != 1:
        return False
    output.target_name = renamed_keys[0].name
    return True


def _migrate_renamed_bone_output(armature, component, output) -> bool:
    """Follow a renamed transform target using strict generated ownership.

    Bone names are stored as strings, while Blender updates an existing
    FCurve path when its target bone is renamed.  The UUID-owned curves are
    therefore authoritative once an output has been compiled.  Requiring the
    complete consecutive component set and one owned artifact prevents an
    unrelated bone that reuses the old name from becoming the new target.
    """

    if output.target_kind not in {"BONE_LOCATION", "BONE_ROTATION"}:
        return False
    target_object = output.target_object
    if target_object is None or target_object.type != "ARMATURE":
        return False

    arity = int(output.value_arity)
    base_index = max(0, int(output.array_index))
    property_name = (
        "location" if output.target_kind == "BONE_LOCATION" else "rotation_euler"
    )
    artifacts = [
        artifact
        for artifact in component.artifacts
        if artifact.data_type == "DRIVER"
        and artifact.role.startswith("semantic_output:")
        and artifact.binding_uuid == output.output_uuid
        and artifact.owned
    ]
    locations = tuple(_owned_driver_locations(armature, output.output_uuid))
    if len(artifacts) != 1 or len(locations) != arity:
        return False
    if any(location.id_data != target_object for location in locations):
        return False

    expected_indices = set(range(base_index, base_index + arity))
    if {location.array_index for location in locations} != expected_indices:
        return False
    paths = {location.data_path for location in locations}
    if len(paths) != 1:
        return False
    owned_path = next(iter(paths))
    stored_path = (
        f'pose.bones["{bpy.utils.escape_identifier(output.target_bone)}"]'
        f".{property_name}"
    )
    if artifacts[0].data_path != stored_path:
        return False

    candidates = [
        pose_bone
        for pose_bone in target_object.pose.bones
        if pose_bone.path_from_id(property_name) == owned_path
    ]
    if len(candidates) != 1:
        return False
    if output.target_bone == candidates[0].name:
        return False
    output.target_bone = candidates[0].name
    return True


def _driver_add(target: SemanticTarget):
    if target.array_index >= 0:
        return target.id_data.driver_add(target.data_path, target.array_index)
    return target.id_data.driver_add(target.data_path)


def _driver_remove(target: SemanticTarget) -> bool:
    try:
        value = target.id_data.path_resolve(target.data_path)
    except (AttributeError, KeyError, ValueError):
        value = None
    if isinstance(value, (bool, int, float)):
        return bool(target.id_data.driver_remove(target.data_path))
    if target.array_index >= 0:
        return bool(target.id_data.driver_remove(target.data_path, target.array_index))
    return bool(target.id_data.driver_remove(target.data_path))


def resolve_semantic_target(armature, output) -> SemanticTarget:
    target_object = output.target_object
    if target_object is None:
        raise SemanticOutputError(f"Output target is missing: {output.label}")
    kind = output.target_kind
    if kind == "SHAPE_KEY":
        if target_object.type != "MESH":
            raise SemanticOutputError("Shape Key output requires a Mesh object.")
        shape_keys = getattr(target_object.data, "shape_keys", None)
        key_block = (
            shape_keys.key_blocks.get(output.target_name)
            if shape_keys is not None
            else None
        )
        if key_block is None:
            raise SemanticOutputError(
                f"Shape Key not found: {target_object.name} / {output.target_name}"
            )
        return SemanticTarget(shape_keys, key_block.path_from_id("value"))
    if kind == "CONSTRAINT_INFLUENCE":
        if target_object.type != "ARMATURE":
            raise SemanticOutputError("Constraint output requires an Armature.")
        pose_bone = target_object.pose.bones.get(output.target_bone)
        constraint = (
            pose_bone.constraints.get(output.target_name)
            if pose_bone is not None
            else None
        )
        if constraint is None:
            raise SemanticOutputError(
                f"Constraint not found: {output.target_bone} / {output.target_name}"
            )
        return SemanticTarget(target_object, constraint.path_from_id("influence"))
    if kind in {"BONE_LOCATION", "BONE_ROTATION"}:
        if target_object.type != "ARMATURE":
            raise SemanticOutputError("Bone transform output requires an Armature.")
        pose_bone = target_object.pose.bones.get(output.target_bone)
        if pose_bone is None:
            raise SemanticOutputError(f"Bone not found: {output.target_bone}")
        property_name = "location" if kind == "BONE_LOCATION" else "rotation_euler"
        return SemanticTarget(
            target_object,
            pose_bone.path_from_id(property_name),
            max(0, output.array_index),
        )
    if kind == "CUSTOM_PROPERTY":
        if not output.data_path:
            raise SemanticOutputError("Custom Property output needs a data path.")
        return SemanticTarget(target_object, output.data_path, output.array_index)
    if kind in {"SLOT_INDEX", "Z_VALUE"}:
        property_name = "slot_index" if kind == "SLOT_INDEX" else "z_value"
        return SemanticTarget(target_object, f"coa_tools2.{property_name}")
    raise SemanticOutputError(f"Unsupported semantic output: {kind}")


def resolve_semantic_targets(armature, output) -> tuple[SemanticTarget, ...]:
    """Resolve one logical output to its one-to-four Blender FCurve targets."""

    arity = int(output.value_arity)
    if not 1 <= arity <= 4:
        raise SemanticOutputError(
            f"Output '{output.label}' arity must be between 1 and 4."
        )
    first = resolve_semantic_target(armature, output)
    if arity == 1:
        return (first,)
    if bool(output.discrete):
        raise SemanticOutputError("Discrete semantic outputs must be scalar.")
    if output.target_kind not in {
        "BONE_LOCATION",
        "BONE_ROTATION",
        "CUSTOM_PROPERTY",
    }:
        raise SemanticOutputError(
            f"Output '{output.label}' does not support vector values."
        )
    if output.target_kind in {"BONE_LOCATION", "BONE_ROTATION"} and arity > 3:
        raise SemanticOutputError("Bone location and Euler rotation support at most 3 values.")

    base_index = max(0, int(output.array_index))
    if output.target_kind in {"BONE_LOCATION", "BONE_ROTATION"}:
        if base_index + arity > 3:
            raise SemanticOutputError(
                f"Output '{output.label}' exceeds the three transform axes."
            )
    else:
        try:
            value = first.id_data.path_resolve(first.data_path)
            length = len(value)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise SemanticOutputError(
                f"Custom Property vector path is not an array: {first.data_path}"
            ) from exc
        if base_index + arity > length:
            raise SemanticOutputError(
                f"Output '{output.label}' needs {arity} values from index "
                f"{base_index}, but the target has length {length}."
            )
    return tuple(
        SemanticTarget(first.id_data, first.data_path, base_index + index)
        for index in range(arity)
    )


def _target_value(target: SemanticTarget):
    try:
        value = target.id_data.path_resolve(target.data_path)
    except (AttributeError, KeyError, ValueError) as exc:
        raise SemanticOutputError(f"Cannot read output path: {target.data_path}") from exc
    if target.array_index >= 0:
        value = value[target.array_index]
    return float(value)


def _set_target_value(target: SemanticTarget, value: float) -> None:
    """Assign a scalar RNA target without evaluating arbitrary Python text."""

    scalar = float(value)
    if target.array_index >= 0:
        try:
            sequence = target.id_data.path_resolve(target.data_path)
            sequence[target.array_index] = scalar
            return
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
            raise SemanticOutputError(
                f"Cannot write output path: {target.data_path}[{target.array_index}]"
            ) from exc

    custom_match = re.match(r'^(.*?)\["((?:\\.|[^"\\])*)"\]$', target.data_path)
    if custom_match is not None:
        parent_path, escaped_name = custom_match.groups()
        parent_path = parent_path.rstrip(".")
        try:
            owner = (
                target.id_data.path_resolve(parent_path)
                if parent_path
                else target.id_data
            )
            owner[bpy.utils.unescape_identifier(escaped_name)] = scalar
            return
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise SemanticOutputError(
                f"Cannot write output path: {target.data_path}"
            ) from exc

    parent_path, separator, property_name = target.data_path.rpartition(".")
    try:
        owner = target.id_data.path_resolve(parent_path) if separator else target.id_data
        setattr(owner, property_name, scalar)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise SemanticOutputError(
            f"Cannot write output path: {target.data_path}"
        ) from exc


def capture_semantic_output_value(armature, output):
    values = tuple(
        _target_value(target) for target in resolve_semantic_targets(armature, output)
    )
    return values[0] if len(values) == 1 else values


def set_semantic_output_value(armature, output, value) -> None:
    targets = resolve_semantic_targets(armature, output)
    values = value if isinstance(value, (tuple, list)) else (value,)
    if len(values) != len(targets):
        raise SemanticOutputError(
            f"Output '{output.label}' expects {len(targets)} values, got {len(values)}."
        )
    for target, scalar in zip(targets, values):
        _set_target_value(target, scalar)


def _term_value(armature, term) -> float:
    try:
        return evaluate_live_input_term(term, armature)
    except Exception as exc:
        raise SemanticOutputError(str(exc)) from exc


def capture_semantic_input_value(armature, channel) -> float:
    value = float(channel.offset)
    for term in channel.terms:
        value += float(term.coefficient) * _term_value(armature, term)
    return value


def _add_term_variable(driver, armature, output_uuid, channel_index, term_index, term):
    variable = driver.variables.new()
    variable.name = f"q{channel_index}_{term_index}"
    if term.source_kind == "CUSTOM_PROPERTY":
        source = term.source_object or armature
        if not term.data_path:
            raise SemanticOutputError("Input property term needs a data path.")
        variable.type = "SINGLE_PROP"
        target = variable.targets[0]
        target.id = source
        target.data_path = (
            f"{term.data_path}[{term.array_index}]"
            if term.array_index >= 0
            else term.data_path
        )
    else:
        source = term.source_object or armature
        variable.type = "TRANSFORMS"
        target = variable.targets[0]
        target.id = source
        target.bone_target = term.source_bone
        target.transform_type = term.transform_type
        target.transform_space = term.transform_space
    return variable.name


def _channel_expression(driver, armature, output_uuid, channel_index, channel):
    terms = []
    for term_index, term in enumerate(channel.terms):
        name = _add_term_variable(
            driver, armature, output_uuid, channel_index, term_index, term
        )
        terms.append(f"({float(term.coefficient):.9g})*({name})")
    expression = f"({float(channel.offset):.9g})"
    if terms:
        expression += "+" + "+".join(terms)
    return expression


def ensure_semantic_output_driver(armature, component, stage, output):
    targets = resolve_semantic_targets(armature, output)
    _remove_stale_output_identity(
        armature,
        component,
        output.output_uuid,
        targets,
    )
    owner_property = (
        "coa_semantic_owner_"
        + re.sub(r"[^0-9A-Za-z]", "", component.component_uuid)[:12]
    )
    if owner_property not in armature:
        armature[owner_property] = 0.0
    fcurves = []
    for component_index, target in enumerate(targets):
        existing = _find_driver(target)
        if existing is not None and not _driver_uses_output(
            existing, armature, output.output_uuid
        ):
            raise SemanticOutputError(
                f"Target already has an unmanaged driver: {output.label}"
            )
        fcurve = _driver_add(target)
        driver = fcurve.driver
        driver.type = "SCRIPTED"
        while driver.variables:
            driver.variables.remove(driver.variables[0])
        owner_variable = driver.variables.new()
        owner_variable.name = f"{_driver_token(output.output_uuid)}owner"
        owner_variable.type = "SINGLE_PROP"
        owner_target = owner_variable.targets[0]
        owner_target.id = armature
        owner_target.data_path = f'["{owner_property}"]'
        dependencies = []
        for channel_index, channel in enumerate(stage.inputs):
            for term_index, term in enumerate(channel.terms):
                dependencies.append(
                    _add_term_variable(
                        driver,
                        armature,
                        output.output_uuid,
                        channel_index,
                        term_index,
                        term,
                    )
                )
        driver.expression = pose_field_driver_expression(
            ensure_rig_instance_id(armature),
            component.component_uuid,
            stage.stage_uuid,
            output.output_uuid,
            (),
            discrete=bool(output.discrete),
            component_index=(component_index if len(targets) > 1 else None),
        )
        if dependencies:
            driver.expression += "+0*(" + "+".join(dependencies) + ")"
        _record_artifact(
            component,
            f"semantic_output:{stage.stage_uuid}",
            "DRIVER",
            object_name=getattr(target.id_data, "name", ""),
            data_path=target.data_path,
            binding_uuid=output.output_uuid,
            owned=True,
        )
        fcurves.append(fcurve)
    return tuple(fcurves)


def _iter_driver_hosts():
    yield from bpy.data.shape_keys
    yield from bpy.data.objects


def _owned_driver_locations(armature, output_uuid):
    for id_data in _iter_driver_hosts():
        animation_data = getattr(id_data, "animation_data", None)
        if animation_data is None:
            continue
        for fcurve in tuple(animation_data.drivers):
            if _driver_uses_output(fcurve, armature, output_uuid):
                yield SemanticTarget(id_data, fcurve.data_path, fcurve.array_index)


def remove_semantic_output_drivers(armature, output_uuid):
    count = 0
    for target in tuple(_owned_driver_locations(armature, output_uuid)):
        count += int(_driver_remove(target))
    return count


def _remove_stale_output_identity(
    armature,
    component,
    output_uuid,
    expected_targets,
):
    """Remove a generated output from its previous Blender destination."""

    expected_identities = {_target_identity(target) for target in expected_targets}
    for target in tuple(_owned_driver_locations(armature, output_uuid)):
        if _target_identity(target) not in expected_identities:
            _driver_remove(target)

    expected_locations = {
        (getattr(target.id_data, "name", ""), target.data_path)
        for target in expected_targets
    }
    for index in range(len(component.artifacts) - 1, -1, -1):
        artifact = component.artifacts[index]
        if (
            artifact.data_type != "DRIVER"
            or not artifact.role.startswith("semantic_output:")
            or artifact.binding_uuid != output_uuid
        ):
            continue
        if (artifact.object_name, artifact.data_path) not in expected_locations:
            component.artifacts.remove(index)


def preflight_semantic_outputs(armature, component):
    token_counts = {}
    for candidate in get_rig_data(armature).rig_components:
        for candidate_stage in candidate.semantic_stages:
            for candidate_output in candidate_stage.outputs:
                if not candidate_output.output_uuid:
                    continue
                token = re.sub(
                    r"[^0-9A-Za-z]", "", candidate_output.output_uuid
                )[:16]
                token_counts[token] = token_counts.get(token, 0) + 1
    seen = set()
    for stage in component.semantic_stages:
        if not stage.enabled or stage.stage_type != "POSE_MAP":
            continue
        if not stage.inputs:
            raise SemanticOutputError(f"Pose Map '{stage.label}' has no inputs.")
        for channel in stage.inputs:
            if not channel.channel_id or not channel.terms:
                raise SemanticOutputError(
                    f"Input channel '{channel.label}' needs an id and source term."
                )
            if channel.scale <= 0.0:
                raise SemanticOutputError("Pose Map input scale must be positive.")
            if channel.kind != "CONTINUOUS":
                raise SemanticOutputError(
                    f"Input channel '{channel.label}' uses {channel.kind}; "
                    "discrete input dimensions are reserved for a later evaluator."
                )
        for output in stage.outputs:
            if not output.output_uuid:
                raise SemanticOutputError("Semantic output UUID is missing.")
            if output.output_uuid in seen:
                raise SemanticOutputError(
                    f"Semantic output UUID is duplicated: {output.output_uuid}"
                )
            seen.add(output.output_uuid)
            token = re.sub(r"[^0-9A-Za-z]", "", output.output_uuid)[:16]
            if not token or token_counts.get(token, 0) != 1:
                raise SemanticOutputError(
                    f"Semantic output UUID/token is duplicated: {output.output_uuid}"
                )
            if not output.enabled:
                continue
            _migrate_renamed_shape_key_output(
                armature,
                component,
                output,
            )
            _migrate_renamed_bone_output(
                armature,
                component,
                output,
            )
            if output.policy != "PARAMETRIC":
                raise SemanticOutputError(
                    f"Output '{output.label}' uses policy {output.policy}; the "
                    "current Blender adapter supports Parametric outputs only."
                )
            for target in resolve_semantic_targets(armature, output):
                existing = _find_driver(target)
                if existing is not None and not _driver_uses_output(
                    existing, armature, output.output_uuid
                ):
                    raise SemanticOutputError(
                        f"Target already has an unmanaged driver: {output.label}"
                    )


def reconcile_semantic_outputs(armature, component):
    expected = {
        output.output_uuid
        for stage in component.semantic_stages
        if stage.enabled and stage.stage_type == "POSE_MAP"
        and any(sample.enabled for sample in stage.samples)
        and not component.semantic_edit_sample_uuid
        for output in stage.outputs
        if output.enabled
    }
    for index in range(len(component.artifacts) - 1, -1, -1):
        artifact = component.artifacts[index]
        if artifact.data_type != "DRIVER" or not artifact.role.startswith(
            "semantic_output:"
        ):
            continue
        if artifact.binding_uuid in expected:
            continue
        remove_semantic_output_drivers(armature, artifact.binding_uuid)
        component.artifacts.remove(index)
    compiled = 0
    for stage in component.semantic_stages:
        if not stage.enabled or stage.stage_type != "POSE_MAP":
            continue
        if component.semantic_edit_sample_uuid or not any(
            sample.enabled for sample in stage.samples
        ):
            for output in stage.outputs:
                remove_semantic_output_drivers(armature, output.output_uuid)
            continue
        for output in stage.outputs:
            if not output.enabled:
                remove_semantic_output_drivers(armature, output.output_uuid)
                continue
            ensure_semantic_output_driver(armature, component, stage, output)
            compiled += 1
    clear_pose_field_cache()
    return compiled


def _driver_snapshot(fcurve):
    if fcurve is None:
        return None
    return {
        "type": fcurve.driver.type,
        "expression": fcurve.driver.expression,
        "use_self": fcurve.driver.use_self,
        "variables": tuple(
            {
                "name": variable.name,
                "type": variable.type,
                "targets": tuple(
                    {
                        name: getattr(target, name)
                        for name in (
                            "id", "id_type", "data_path", "bone_target",
                            "transform_type", "transform_space", "rotation_mode",
                        )
                        if hasattr(target, name)
                    }
                    for target in variable.targets
                ),
            }
            for variable in fcurve.driver.variables
        ),
    }


def capture_semantic_output_state(armature, component):
    tokens = {
        output.output_uuid
        for stage in component.semantic_stages
        for output in stage.outputs
        if output.output_uuid
    }
    tokens.update(
        artifact.binding_uuid
        for artifact in component.artifacts
        if artifact.data_type == "DRIVER"
        and artifact.role.startswith("semantic_output:")
        and artifact.binding_uuid
    )
    locations = {}
    for token in tokens:
        for target in _owned_driver_locations(armature, token):
            locations[(target.id_data.as_pointer(), target.data_path, target.array_index)] = (
                target, token, False
            )
    for stage in component.semantic_stages:
        for output in stage.outputs:
            try:
                targets = resolve_semantic_targets(armature, output)
            except SemanticOutputError:
                continue
            for target in targets:
                locations[(target.id_data.as_pointer(), target.data_path, target.array_index)] = (
                    target, output.output_uuid, False
                )
    for artifact in component.artifacts:
        if (
            artifact.data_type != "DRIVER"
            or not artifact.role.startswith("semantic:")
            or not artifact.data_path
        ):
            continue
        id_data = bpy.data.objects.get(artifact.object_name)
        if id_data is None:
            continue
        target = SemanticTarget(id_data, artifact.data_path)
        locations[(id_data.as_pointer(), artifact.data_path, -1)] = (
            target, artifact.binding_uuid, True
        )
    return tuple(
        (target, token, force_owned, _driver_snapshot(_find_driver(target)))
        for target, token, force_owned in locations.values()
    )


def restore_semantic_output_state(armature, snapshots):
    for target, token, force_owned, previous in snapshots:
        current = _find_driver(target)
        if previous is None:
            if current is not None and (
                force_owned or _driver_uses_output(current, armature, token)
            ):
                _driver_remove(target)
            continue
        if current is None:
            current = _driver_add(target)
        driver = current.driver
        driver.type = previous["type"]
        driver.expression = previous["expression"]
        driver.use_self = previous["use_self"]
        while driver.variables:
            driver.variables.remove(driver.variables[0])
        for variable_state in previous["variables"]:
            variable = driver.variables.new()
            variable.name = variable_state["name"]
            variable.type = variable_state["type"]
            for variable_target, values in zip(
                variable.targets, variable_state["targets"]
            ):
                for name, value in values.items():
                    try:
                        setattr(variable_target, name, value)
                    except (AttributeError, RuntimeError, TypeError):
                        pass
    clear_pose_field_cache()
