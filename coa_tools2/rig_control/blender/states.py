"""Blender adapters for continuous 1D and 2D StateData."""

from __future__ import annotations

from ..schema import state_grid_size, state_point_position
from .drivers import (
    BindingConflictError,
    binding_target_key,
    driver_uses_control,
    find_driver,
)


def state_dimensions(control) -> tuple[int, int]:
    return state_grid_size(
        control.state_mode,
        control.state_columns,
        control.state_rows,
    )


def state_target_key(point) -> tuple[str, str, str, str]:
    object_name = point.target_object.name if point.target_object else ""
    return ("SHAPE_KEY_VALUE", object_name, "", point.target_name)


def state_point_target(point):
    target_object = point.target_object
    if target_object is None or target_object.type != "MESH":
        return None, None
    shape_keys = getattr(target_object.data, "shape_keys", None)
    if shape_keys is None or point.target_name not in shape_keys.key_blocks:
        return shape_keys, None
    return shape_keys, shape_keys.key_blocks[point.target_name]


def state_point_driver(point):
    shape_keys, key_block = state_point_target(point)
    if shape_keys is None or key_block is None:
        return None
    return find_driver(shape_keys, key_block.path_from_id("value"))


def _add_transform_variable(driver, name, armature, control_bone, transform_type):
    variable = driver.variables.new()
    variable.name = name
    variable.type = "TRANSFORMS"
    target = variable.targets[0]
    target.id = armature
    target.bone_target = control_bone
    target.transform_type = transform_type
    target.transform_space = "LOCAL_SPACE"


def _hat_expression(variable: str, span: float, index: int, count: int) -> str:
    if span <= 0.0:
        raise ValueError("State control span must be positive.")
    coordinate = (
        f"(min(max(({variable})/({span:.9g}),0.0),1.0)*({count - 1}))"
    )
    return f"max(1.0-abs(({coordinate})-({index})),0.0)"


def state_driver_expression(control, point) -> str:
    columns, rows = state_dimensions(control)
    if not (0 <= point.column < columns and 0 <= point.row < rows):
        raise ValueError(
            f"State point [{point.column}, {point.row}] is outside the grid."
        )
    x = _hat_expression("state_x", control.width, point.column, columns)
    if rows == 1:
        return x
    y = _hat_expression("state_y", control.height, point.row, rows)
    return f"({x})*({y})"


def ensure_state_driver(armature, control, point):
    if not point.enabled or point.is_empty:
        return None
    shape_keys, key_block = state_point_target(point)
    if shape_keys is None or key_block is None:
        raise ValueError(
            f"Shape Key not found: "
            f"{point.target_object.name if point.target_object else 'Missing'} / "
            f"{point.target_name or 'Missing'}"
        )

    data_path = key_block.path_from_id("value")
    existing = find_driver(shape_keys, data_path)
    if existing is not None and not driver_uses_control(
        existing,
        armature,
        control.control_bone,
    ):
        raise BindingConflictError(
            f"Target already has an unmanaged driver: "
            f"{point.target_object.name} / {point.target_name}"
        )

    fcurve = key_block.driver_add("value")
    point.generated_data_path = data_path
    driver = fcurve.driver
    driver.type = "SCRIPTED"
    while driver.variables:
        driver.variables.remove(driver.variables[0])

    transform_x = (
        "LOC_Y"
        if control.state_mode == "LINEAR_1D" and control.axis == "Y"
        else "LOC_X"
    )
    _add_transform_variable(
        driver,
        "state_x",
        armature,
        control.control_bone,
        transform_x,
    )
    if control.state_mode == "MATRIX_2D":
        _add_transform_variable(
            driver,
            "state_y",
            armature,
            control.control_bone,
            "LOC_Y",
        )
    driver.expression = state_driver_expression(control, point)
    return fcurve


def remove_state_driver(armature, control, point) -> bool:
    shape_keys, key_block = state_point_target(point)
    if shape_keys is None or key_block is None:
        return False
    fcurve = find_driver(shape_keys, key_block.path_from_id("value"))
    if fcurve is None or not driver_uses_control(
        fcurve,
        armature,
        control.control_bone,
    ):
        return False
    key_block.driver_remove("value")
    point.generated_data_path = ""
    return True


def sync_state_control_geometry(control):
    """Keep StateData dimensions and the visible control ABI aligned."""

    if control.state_mode == "LINEAR_1D":
        if control.control_type != "SLIDER_1D":
            raise ValueError("1D States require a 1D Slider control.")
        control.state_rows = 1
    elif control.state_mode == "MATRIX_2D":
        if control.control_type != "POINT_2D_RECT":
            raise ValueError("2D State Matrix requires a 2D Rectangle control.")
        control.state_rows = max(2, control.state_rows)
        control.rectangle_mode = "FREE"
        control.grid_columns = control.state_columns
        control.grid_rows = control.state_rows


def ensure_state_drivers(armature, control) -> int:
    if control.state_mode == "NONE":
        return 0
    sync_state_control_geometry(control)
    columns, rows = state_dimensions(control)
    expected = {(column, row) for row in range(rows) for column in range(columns)}
    actual = {(point.column, point.row) for point in control.state_points}
    if actual != expected or len(actual) != len(control.state_points):
        raise ValueError("StateData grid must be rebuilt before compiling.")

    seen = {
        binding_target_key(binding)
        for binding in control.bindings
        if binding.enabled
    }
    compiled = 0
    for point in control.state_points:
        if not point.enabled or point.is_empty:
            continue
        key = state_target_key(point)
        if not key[1] or not key[3]:
            continue
        if key in seen:
            raise BindingConflictError(
                f"Target is assigned more than once: {key[1]} / {key[3]}"
            )
        seen.add(key)
        ensure_state_driver(armature, control, point)
        compiled += 1
    return compiled


def state_point_local_position(control, point) -> tuple[float, float]:
    columns, rows = state_dimensions(control)
    u, v = state_point_position(
        point.column,
        point.row,
        columns,
        rows,
    )
    if control.state_mode == "LINEAR_1D" and control.axis == "Y":
        return 0.0, u * control.width
    return u * control.width, v * control.height
