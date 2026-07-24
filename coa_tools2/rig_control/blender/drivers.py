"""Driver adapters for rig-control bindings."""

from __future__ import annotations

import math

import bpy

from ..schema import dial_point, dial_rest_angle


class BindingConflictError(RuntimeError):
    pass


def find_driver(id_data, data_path: str):
    animation_data = getattr(id_data, "animation_data", None)
    if animation_data is None:
        return None
    return next(
        (driver for driver in animation_data.drivers if driver.data_path == data_path),
        None,
    )


def driver_uses_control(fcurve, armature, control_bone: str) -> bool:
    for variable in fcurve.driver.variables:
        if variable.type != "TRANSFORMS":
            continue
        target = variable.targets[0]
        if target.id == armature and target.bone_target == control_bone:
            return True
    return False


def _mapping_expression(binding, control_expression="control") -> str:
    span = binding.input_max - binding.input_min
    if span <= 0.0:
        raise ValueError("Binding input range must be positive.")
    normalized = (
        f"((({control_expression})-({binding.input_min:.9g}))/({span:.9g}))"
    )
    if binding.clamp:
        normalized = f"min(max({normalized},0.0),1.0)"
    output_span = binding.output_max - binding.output_min
    return f"({binding.output_min:.9g})+({normalized})*({output_span:.9g})"


def _transform_type(source_component: str) -> str:
    return {
        "X": "LOC_X",
        "Y": "LOC_Y",
        "ROTATION": "ROT_Z",
    }[source_component]


def _add_transform_variable(driver, name, armature, control_bone, transform_type):
    variable = driver.variables.new()
    variable.name = name
    variable.type = "TRANSFORMS"
    target = variable.targets[0]
    target.id = armature
    target.bone_target = control_bone
    target.transform_type = transform_type
    target.transform_space = "LOCAL_SPACE"


def _control_expression(driver, armature, control, binding):
    if binding.source_component == "ROTATION" and control.control_type == "DIAL":
        _add_transform_variable(
            driver,
            "control_x",
            armature,
            control.control_bone,
            "LOC_X",
        )
        _add_transform_variable(
            driver,
            "control_y",
            armature,
            control.control_bone,
            "LOC_Y",
        )
        rest_angle = dial_rest_angle(control.angle_min, control.angle_max)
        rest_x, rest_y = dial_point(control.radius, rest_angle)
        raw_angle = (
            f"atan2(-(control_x+({rest_x:.9g})),"
            f"control_y+({rest_y:.9g}))"
        )
        center = (control.angle_min + control.angle_max) * 0.5
        return (
            f"(({raw_angle})+({math.tau:.9g})*"
            f"floor((({center:.9g})-({raw_angle})+pi)/({math.tau:.9g})))"
        )

    _add_transform_variable(
        driver,
        "control",
        armature,
        control.control_bone,
        _transform_type(binding.source_component),
    )
    return "control"


def ensure_shape_key_driver(armature, control, binding):
    target_object = binding.target_object
    if target_object is None or target_object.type != "MESH":
        raise ValueError("Shape Key binding target must be a Mesh object.")
    shape_keys = getattr(target_object.data, "shape_keys", None)
    if shape_keys is None or binding.target_name not in shape_keys.key_blocks:
        raise ValueError(f"Shape Key not found: {binding.target_name}")

    key_block = shape_keys.key_blocks[binding.target_name]
    data_path = key_block.path_from_id("value")
    existing = find_driver(shape_keys, data_path)
    if existing is not None and not driver_uses_control(
        existing,
        armature,
        control.control_bone,
    ):
        raise BindingConflictError(
            f"Target already has an unmanaged driver: {target_object.name} / {binding.target_name}"
        )

    fcurve = key_block.driver_add("value")
    binding.generated_data_path = data_path

    driver = fcurve.driver
    driver.type = "SCRIPTED"
    while driver.variables:
        driver.variables.remove(driver.variables[0])
    control_expression = _control_expression(
        driver,
        armature,
        control,
        binding,
    )
    driver.expression = _mapping_expression(binding, control_expression)
    return fcurve


def ensure_constraint_driver(armature, control, binding):
    target_object = binding.target_object
    if target_object is None or target_object.type != "ARMATURE":
        raise ValueError("Constraint binding target must be an Armature object.")
    pose_bone = target_object.pose.bones.get(binding.target_bone)
    if pose_bone is None:
        raise ValueError(f"Target pose bone not found: {binding.target_bone}")
    constraint = pose_bone.constraints.get(binding.target_name)
    if constraint is None:
        raise ValueError(f"Target constraint not found: {binding.target_name}")

    data_path = constraint.path_from_id("influence")
    existing = find_driver(target_object, data_path)
    if existing is not None and not driver_uses_control(
        existing,
        armature,
        control.control_bone,
    ):
        raise BindingConflictError(
            f"Target already has an unmanaged driver: {target_object.name} / "
            f"{binding.target_bone} / {binding.target_name}"
        )

    fcurve = constraint.driver_add("influence")
    binding.generated_data_path = data_path
    driver = fcurve.driver
    driver.type = "SCRIPTED"
    while driver.variables:
        driver.variables.remove(driver.variables[0])
    control_expression = _control_expression(
        driver,
        armature,
        control,
        binding,
    )
    driver.expression = _mapping_expression(binding, control_expression)
    return fcurve


def ensure_binding_driver(armature, control, binding):
    if not binding.enabled:
        return None
    if binding.target_kind == "SHAPE_KEY_VALUE":
        return ensure_shape_key_driver(armature, control, binding)
    if binding.target_kind == "CONSTRAINT_INFLUENCE":
        return ensure_constraint_driver(armature, control, binding)
    raise ValueError(f"Unsupported binding target: {binding.target_kind}")


def binding_target_key(binding) -> tuple[str, str, str, str]:
    object_name = binding.target_object.name if binding.target_object else ""
    return (
        binding.target_kind,
        object_name,
        binding.target_bone,
        binding.target_name,
    )


def remove_binding_driver(armature, control, binding) -> bool:
    target_object = binding.target_object
    if target_object is None:
        return False
    if binding.target_kind == "SHAPE_KEY_VALUE":
        shape_keys = getattr(target_object.data, "shape_keys", None)
        if shape_keys is None or binding.target_name not in shape_keys.key_blocks:
            return False
        key_block = shape_keys.key_blocks[binding.target_name]
        fcurve = find_driver(shape_keys, key_block.path_from_id("value"))
        if fcurve is None or not driver_uses_control(
            fcurve, armature, control.control_bone
        ):
            return False
        key_block.driver_remove("value")
        return True
    if binding.target_kind == "CONSTRAINT_INFLUENCE":
        pose_bone = target_object.pose.bones.get(binding.target_bone)
        constraint = pose_bone.constraints.get(binding.target_name) if pose_bone else None
        if constraint is None:
            return False
        fcurve = find_driver(target_object, constraint.path_from_id("influence"))
        if fcurve is None or not driver_uses_control(
            fcurve, armature, control.control_bone
        ):
            return False
        constraint.driver_remove("influence")
        return True
    return False
