"""Shape Key and constraint outputs driven by parametric pose components."""

from __future__ import annotations

import bpy

from .component_artifacts import _record_artifact
from .drivers import (
    BindingConflictError,
    binding_target_key,
    driver_uses_binding_uuid,
    ensure_binding_driver,
    find_driver,
)
from .properties import get_rig_data
from .states import state_target_key


class ComponentOutputError(RuntimeError):
    pass


def _binding_target(binding):
    target_object = binding.target_object
    if target_object is None:
        raise ComponentOutputError("Binding target object is missing.")
    if binding.target_kind == "SHAPE_KEY_VALUE":
        if target_object.type != "MESH":
            raise ComponentOutputError("Shape Key target must be a Mesh object.")
        shape_keys = getattr(target_object.data, "shape_keys", None)
        if shape_keys is None or binding.target_name not in shape_keys.key_blocks:
            raise ComponentOutputError(
                f"Shape Key not found: {target_object.name} / {binding.target_name}"
            )
        key_block = shape_keys.key_blocks[binding.target_name]
        return shape_keys, key_block.path_from_id("value")
    if binding.target_kind == "CONSTRAINT_INFLUENCE":
        if target_object.type != "ARMATURE":
            raise ComponentOutputError(
                "Constraint binding target must be an Armature object."
            )
        pose_bone = target_object.pose.bones.get(binding.target_bone)
        constraint = (
            pose_bone.constraints.get(binding.target_name)
            if pose_bone is not None
            else None
        )
        if constraint is None:
            raise ComponentOutputError(
                f"Constraint not found: {target_object.name} / "
                f"{binding.target_bone} / {binding.target_name}"
            )
        return target_object, constraint.path_from_id("influence")
    raise ComponentOutputError(
        f"Unsupported binding target: {binding.target_kind}"
    )


def _other_target_keys(armature, component):
    rig_data = get_rig_data(armature)
    for control in rig_data.rig_controls:
        for binding in control.bindings:
            if binding.enabled:
                yield binding_target_key(binding)
        for point in control.state_points:
            if point.enabled and not point.is_empty:
                yield state_target_key(point)
    for other in rig_data.rig_components:
        if other.component_uuid == component.component_uuid:
            continue
        for binding in other.bindings:
            if binding.enabled:
                yield binding_target_key(binding)


def preflight_component_outputs(armature, component):
    """Validate every output before structural component data is changed."""

    rig_data = get_rig_data(armature)
    binding_uuid_counts = {}
    for control in rig_data.rig_controls:
        for binding in control.bindings:
            if binding.binding_uuid:
                binding_uuid_counts[binding.binding_uuid] = (
                    binding_uuid_counts.get(binding.binding_uuid, 0) + 1
                )
    for candidate in rig_data.rig_components:
        for binding in candidate.bindings:
            if binding.binding_uuid:
                binding_uuid_counts[binding.binding_uuid] = (
                    binding_uuid_counts.get(binding.binding_uuid, 0) + 1
                )

    occupied = set(_other_target_keys(armature, component))
    own_targets = set()
    for binding in component.bindings:
        if not binding.binding_uuid:
            raise ComponentOutputError("Component binding UUID is missing.")
        if binding_uuid_counts.get(binding.binding_uuid, 0) != 1:
            raise ComponentOutputError(
                f"Binding UUID is duplicated: {binding.binding_uuid}"
            )
        if not binding.enabled:
            continue
        if binding.input_max <= binding.input_min:
            raise ComponentOutputError(
                "Binding input maximum must be greater than its minimum."
            )
        key = binding_target_key(binding)
        if key in occupied or key in own_targets:
            raise ComponentOutputError(
                f"Target is already assigned: {key[1]} / {key[3]}"
            )
        own_targets.add(key)
        id_data, data_path = _binding_target(binding)
        existing = find_driver(id_data, data_path)
        if existing is not None and not (
            driver_uses_binding_uuid(
                existing,
                armature,
                binding.binding_uuid,
            )
        ):
            raise ComponentOutputError(
                f"Target already has an unmanaged driver: {key[1]} / {key[3]}"
            )


def _remove_artifact_at(component, index):
    component.artifacts.remove(index)


def _iter_driver_hosts():
    yield from bpy.data.shape_keys
    yield from bpy.data.objects


def _owned_driver_locations(armature, binding_uuid):
    for id_data in _iter_driver_hosts():
        animation_data = getattr(id_data, "animation_data", None)
        if animation_data is None:
            continue
        for fcurve in tuple(animation_data.drivers):
            if driver_uses_binding_uuid(fcurve, armature, binding_uuid):
                yield id_data, fcurve.data_path


def _remove_owned_binding_drivers(armature, binding_uuid):
    removed = 0
    for id_data, data_path in tuple(
        _owned_driver_locations(armature, binding_uuid)
    ):
        if id_data.driver_remove(data_path):
            removed += 1
    return removed


def reconcile_component_outputs(armature, component):
    """Create current bindings and remove strictly-owned obsolete drivers."""

    expected = {}
    for binding in component.bindings:
        if not binding.binding_uuid:
            raise ComponentOutputError("Component binding UUID is missing.")
        if binding.enabled:
            _id_data, data_path = _binding_target(binding)
            expected[binding.binding_uuid] = (
                binding.target_object.name,
                data_path,
            )

    for index in range(len(component.artifacts) - 1, -1, -1):
        artifact = component.artifacts[index]
        if artifact.data_type != "DRIVER" or artifact.role != "output_driver":
            continue
        target = expected.get(artifact.binding_uuid)
        if target == (artifact.object_name, artifact.data_path):
            continue
        _remove_owned_binding_drivers(armature, artifact.binding_uuid)
        _remove_artifact_at(component, index)

    compiled = 0
    for binding in component.bindings:
        if not binding.enabled:
            _remove_owned_binding_drivers(armature, binding.binding_uuid)
            continue
        try:
            ensure_binding_driver(
                armature,
                component,
                binding,
                ownership_token=binding.binding_uuid,
            )
        except (BindingConflictError, ValueError) as exc:
            raise ComponentOutputError(str(exc)) from exc
        _id_data, data_path = _binding_target(binding)
        _record_artifact(
            component,
            "output_driver",
            "DRIVER",
            object_name=binding.target_object.name,
            data_path=data_path,
            binding_uuid=binding.binding_uuid,
            owned=True,
        )
        compiled += 1
    return compiled


def remove_component_binding(armature, component, binding):
    removed = _remove_owned_binding_drivers(
        armature,
        binding.binding_uuid,
    )
    for index in range(len(component.artifacts) - 1, -1, -1):
        artifact = component.artifacts[index]
        if (
            artifact.data_type == "DRIVER"
            and artifact.binding_uuid == binding.binding_uuid
        ):
            component.artifacts.remove(index)
    return removed


def _driver_snapshot(fcurve):
    if fcurve is None:
        return None
    driver = fcurve.driver
    return {
        "type": driver.type,
        "expression": driver.expression,
        "use_self": driver.use_self,
        "variables": tuple(
            {
                "name": variable.name,
                "type": variable.type,
                "targets": tuple(
                    {
                        name: getattr(target, name)
                        for name in (
                            "id",
                            "id_type",
                            "data_path",
                            "bone_target",
                            "transform_type",
                            "transform_space",
                            "rotation_mode",
                        )
                        if hasattr(target, name)
                    }
                    for target in variable.targets
                ),
            }
            for variable in driver.variables
        ),
    }


def capture_component_output_state(armature, component):
    locations = {}
    generated_data_paths = {}
    for binding in component.bindings:
        generated_data_paths[binding.binding_uuid] = binding.generated_data_path
        try:
            id_data, data_path = _binding_target(binding)
        except ComponentOutputError:
            continue
        locations[(id_data.as_pointer(), data_path)] = (
            id_data,
            data_path,
            binding.binding_uuid,
        )
    tokens = {
        binding.binding_uuid
        for binding in component.bindings
        if binding.binding_uuid
    }
    tokens.update(
        artifact.binding_uuid
        for artifact in component.artifacts
        if artifact.data_type == "DRIVER"
        and artifact.role == "output_driver"
        and artifact.binding_uuid
    )
    for binding_uuid in tokens:
        for id_data, data_path in _owned_driver_locations(
            armature,
            binding_uuid,
        ):
            locations[(id_data.as_pointer(), data_path)] = (
                id_data,
                data_path,
                binding_uuid,
            )
    return {
        "drivers": tuple(
            {
                "id_data": id_data,
                "data_path": data_path,
                "binding_uuid": binding_uuid,
                "driver": _driver_snapshot(find_driver(id_data, data_path)),
            }
            for id_data, data_path, binding_uuid in locations.values()
        ),
        "generated_data_paths": generated_data_paths,
    }


def restore_component_output_state(armature, component, snapshots):
    """Restore output FCurves after a failed structural/output reconcile."""

    for item in snapshots["drivers"]:
        id_data = item["id_data"]
        data_path = item["data_path"]
        binding_uuid = item["binding_uuid"]
        current = find_driver(id_data, data_path)
        previous = item["driver"]
        if previous is None:
            if current is not None and driver_uses_binding_uuid(
                current,
                armature,
                binding_uuid,
            ):
                id_data.driver_remove(data_path)
            continue

        if current is None:
            current = id_data.driver_add(data_path)
        driver = current.driver
        driver.type = previous["type"]
        driver.expression = previous["expression"]
        driver.use_self = previous["use_self"]
        while driver.variables:
            driver.variables.remove(driver.variables[0])
        for variable_snapshot in previous["variables"]:
            variable = driver.variables.new()
            variable.name = variable_snapshot["name"]
            variable.type = variable_snapshot["type"]
            for target, values in zip(
                variable.targets,
                variable_snapshot["targets"],
            ):
                for name, value in values.items():
                    try:
                        setattr(target, name, value)
                    except (AttributeError, RuntimeError, TypeError):
                        pass
    generated_data_paths = snapshots["generated_data_paths"]
    for binding in component.bindings:
        if binding.binding_uuid in generated_data_paths:
            binding.generated_data_path = generated_data_paths[
                binding.binding_uuid
            ]
