"""Managed Blender outputs for arbitrary-dimensional semantic pose maps."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re

import bpy

from .artifacts import ensure_rig_instance_id
from .component_artifacts import _record_artifact
from .semantic_runtime import clear_pose_field_cache, pose_field_driver_expression


class SemanticOutputError(RuntimeError):
    pass


@dataclass(frozen=True)
class SemanticTarget:
    id_data: object
    data_path: str
    array_index: int = -1


def _driver_token(output_uuid: str) -> str:
    token = re.sub(r"[^0-9A-Za-z]", "", output_uuid or "")[:12]
    return f"cs_{token or 'unknown'}_"


def _find_driver(target: SemanticTarget):
    animation_data = getattr(target.id_data, "animation_data", None)
    if animation_data is None:
        return None
    return next(
        (
            curve
            for curve in animation_data.drivers
            if curve.data_path == target.data_path
            and curve.array_index == max(0, target.array_index)
        ),
        None,
    )


def _driver_uses_output(fcurve, armature, output_uuid: str) -> bool:
    if fcurve is None:
        return False
    prefix = _driver_token(output_uuid)
    for variable in fcurve.driver.variables:
        if not variable.name.startswith(prefix):
            continue
        if any(target.id == armature for target in variable.targets):
            return True
    return False


def _driver_add(target: SemanticTarget):
    if target.array_index >= 0:
        return target.id_data.driver_add(target.data_path, target.array_index)
    return target.id_data.driver_add(target.data_path)


def _driver_remove(target: SemanticTarget) -> bool:
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


def _target_value(target: SemanticTarget):
    try:
        value = target.id_data.path_resolve(target.data_path)
    except (AttributeError, KeyError, ValueError) as exc:
        raise SemanticOutputError(f"Cannot read output path: {target.data_path}") from exc
    if target.array_index >= 0:
        value = value[target.array_index]
    return float(value)


def capture_semantic_output_value(armature, output) -> float:
    return _target_value(resolve_semantic_target(armature, output))


def _term_value(armature, term) -> float:
    source = term.source_object or armature
    if term.source_kind == "CUSTOM_PROPERTY":
        if not term.data_path:
            raise SemanticOutputError("Input property term needs a data path.")
        value = source.path_resolve(term.data_path)
        if term.array_index >= 0:
            value = value[term.array_index]
        return float(value)
    owner = source.pose.bones.get(term.source_bone) if term.source_bone else source
    if owner is None:
        raise SemanticOutputError(f"Input bone not found: {term.source_bone}")
    transform = term.transform_type
    axis = "XYZ".index(transform[-1])
    if transform.startswith("LOC_"):
        value = owner.location[axis]
    elif transform.startswith("ROT_"):
        if hasattr(owner, "rotation_mode") and owner.rotation_mode == "QUATERNION":
            value = owner.rotation_quaternion.to_euler("XYZ")[axis]
        else:
            value = owner.rotation_euler[axis]
    elif transform.startswith("SCALE_"):
        value = owner.scale[axis]
    else:
        raise SemanticOutputError(f"Unsupported input transform: {transform}")
    return float(value)


def capture_semantic_input_value(armature, channel) -> float:
    value = float(channel.offset)
    for term in channel.terms:
        value += float(term.coefficient) * _term_value(armature, term)
    return value


def _add_term_variable(driver, armature, output_uuid, channel_index, term_index, term):
    variable = driver.variables.new()
    variable.name = f"{_driver_token(output_uuid)}q{channel_index}_{term_index}"
    if term.source_kind == "CUSTOM_PROPERTY":
        source = term.source_object or armature
        if not term.data_path:
            raise SemanticOutputError("Input property term needs a data path.")
        variable.type = "SINGLE_PROP"
        target = variable.targets[0]
        target.id = source
        target.data_path = term.data_path
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
    target = resolve_semantic_target(armature, output)
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
    queries = [
        _channel_expression(driver, armature, output.output_uuid, index, channel)
        for index, channel in enumerate(stage.inputs)
    ]
    driver.expression = pose_field_driver_expression(
        ensure_rig_instance_id(armature),
        component.component_uuid,
        stage.stage_uuid,
        output.output_uuid,
        queries,
        discrete=bool(output.discrete),
    )
    _record_artifact(
        component,
        f"semantic_output:{stage.stage_uuid}",
        "DRIVER",
        object_name=getattr(target.id_data, "name", ""),
        data_path=target.data_path,
        binding_uuid=output.output_uuid,
        owned=True,
    )
    return fcurve


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


def preflight_semantic_outputs(armature, component):
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
        for output in stage.outputs:
            if not output.output_uuid:
                raise SemanticOutputError("Semantic output UUID is missing.")
            if output.output_uuid in seen:
                raise SemanticOutputError(
                    f"Semantic output UUID is duplicated: {output.output_uuid}"
                )
            seen.add(output.output_uuid)
            if not output.enabled:
                continue
            target = resolve_semantic_target(armature, output)
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
                target, token
            )
    for stage in component.semantic_stages:
        for output in stage.outputs:
            try:
                target = resolve_semantic_target(armature, output)
            except SemanticOutputError:
                continue
            locations[(target.id_data.as_pointer(), target.data_path, target.array_index)] = (
                target, output.output_uuid
            )
    return tuple(
        (target, token, _driver_snapshot(_find_driver(target)))
        for target, token in locations.values()
    )


def restore_semantic_output_state(armature, snapshots):
    for target, token, previous in snapshots:
        current = _find_driver(target)
        if previous is None:
            if current is not None and _driver_uses_output(current, armature, token):
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
