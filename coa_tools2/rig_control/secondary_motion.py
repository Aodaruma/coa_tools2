"""Deterministic, Blender-independent secondary-motion filtering.

The filter solves a damped second-order system for each location component::

    x'' + 2 zeta omega x' + omega^2 x = omega^2 target

Targets are treated as piecewise-linear over every input interval.  Each step
uses the analytical solution for that linear forcing, rather than an explicit
Euler approximation.  This keeps under-, critical- and over-damped settings
stable and makes results depend on elapsed seconds instead of frame count.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence


@dataclass(frozen=True)
class SecondaryMotionSettings:
    frequency_hz: float = 3.0
    damping_ratio: float = 0.7
    substeps: int = 1
    dt: float = 1.0 / 24.0
    pre_roll: float = 0.0


@dataclass(frozen=True)
class SecondaryMotionResult:
    locations: tuple[tuple[float, ...], ...]
    velocities: tuple[tuple[float, ...], ...]


def _validate_settings(settings: SecondaryMotionSettings) -> None:
    if not math.isfinite(settings.frequency_hz) or settings.frequency_hz <= 0.0:
        raise ValueError("frequency_hz must be finite and positive.")
    if not math.isfinite(settings.damping_ratio) or settings.damping_ratio < 0.0:
        raise ValueError("damping_ratio must be finite and non-negative.")
    if isinstance(settings.substeps, bool) or not isinstance(settings.substeps, int):
        raise ValueError("substeps must be a positive integer.")
    if settings.substeps < 1:
        raise ValueError("substeps must be a positive integer.")
    if not math.isfinite(settings.dt) or settings.dt <= 0.0:
        raise ValueError("dt must be finite and positive.")
    if not math.isfinite(settings.pre_roll) or settings.pre_roll < 0.0:
        raise ValueError("pre_roll must be finite and non-negative.")


def _copy_targets(
    targets: Sequence[Sequence[float]],
) -> tuple[tuple[float, ...], ...]:
    copied = tuple(tuple(float(value) for value in target) for target in targets)
    if not copied:
        return ()
    dimensions = len(copied[0])
    if dimensions < 1:
        raise ValueError("Location vectors must have at least one component.")
    for target in copied:
        if len(target) != dimensions:
            raise ValueError("All location vectors must have the same size.")
        if not all(math.isfinite(value) for value in target):
            raise ValueError("Location vectors must contain only finite values.")
    return copied


def _initial_vector(
    value: Sequence[float] | None,
    fallback: tuple[float, ...],
    name: str,
) -> tuple[float, ...]:
    if value is None:
        return fallback
    result = tuple(float(component) for component in value)
    if len(result) != len(fallback):
        raise ValueError(f"{name} must match the target vector size.")
    if not all(math.isfinite(component) for component in result):
        raise ValueError(f"{name} must contain only finite values.")
    return result


def _homogeneous_step(
    displacement: float,
    velocity: float,
    duration: float,
    omega: float,
    damping_ratio: float,
) -> tuple[float, float]:
    """Advance the unforced homogeneous oscillator exactly."""

    if duration == 0.0:
        return displacement, velocity

    # A narrow critical band avoids division by a vanishing damped frequency
    # while remaining continuous at zeta == 1 for animation-scale inputs.
    if abs(damping_ratio - 1.0) <= 1.0e-7:
        decay = math.exp(-omega * duration)
        coefficient = velocity + omega * displacement
        next_displacement = decay * (
            displacement + coefficient * duration
        )
        next_velocity = decay * (
            velocity - omega * coefficient * duration
        )
        return next_displacement, next_velocity

    if damping_ratio < 1.0:
        decay_rate = damping_ratio * omega
        damped_frequency = omega * math.sqrt(
            max(0.0, 1.0 - damping_ratio * damping_ratio)
        )
        angle = damped_frequency * duration
        sine = math.sin(angle)
        cosine = math.cos(angle)
        decay = math.exp(-decay_rate * duration)
        next_displacement = decay * (
            displacement * cosine
            + (velocity + decay_rate * displacement)
            * sine
            / damped_frequency
        )
        next_velocity = decay * (
            velocity * cosine
            - (
                decay_rate * velocity
                + omega * omega * displacement
            )
            * sine
            / damped_frequency
        )
        return next_displacement, next_velocity

    root = math.sqrt(damping_ratio * damping_ratio - 1.0)
    # zeta - sqrt(zeta^2 - 1) loses precision for high damping.  The
    # reciprocal identity below keeps the slow root accurate.
    root_sum = damping_ratio + root
    slow_root = -omega / root_sum
    fast_root = -omega * root_sum
    denominator = slow_root - fast_root
    slow_coefficient = (velocity - fast_root * displacement) / denominator
    fast_coefficient = displacement - slow_coefficient
    slow_decay = math.exp(slow_root * duration)
    fast_decay = math.exp(fast_root * duration)
    next_displacement = (
        slow_coefficient * slow_decay + fast_coefficient * fast_decay
    )
    next_velocity = (
        slow_root * slow_coefficient * slow_decay
        + fast_root * fast_coefficient * fast_decay
    )
    return next_displacement, next_velocity


def _linear_target_step(
    location: float,
    velocity: float,
    target_start: float,
    target_velocity: float,
    duration: float,
    omega: float,
    damping_ratio: float,
) -> tuple[float, float]:
    """Advance one component against ``target_start + velocity * time``."""

    target_offset = 2.0 * damping_ratio * target_velocity / omega
    particular_start = target_start - target_offset
    displacement = location - particular_start
    relative_velocity = velocity - target_velocity
    displacement, relative_velocity = _homogeneous_step(
        displacement,
        relative_velocity,
        duration,
        omega,
        damping_ratio,
    )
    target_end = target_start + target_velocity * duration
    particular_end = target_end - target_offset
    return (
        displacement + particular_end,
        relative_velocity + target_velocity,
    )


def _advance_segment(
    location: tuple[float, ...],
    velocity: tuple[float, ...],
    target_start: tuple[float, ...],
    target_end: tuple[float, ...],
    duration: float,
    omega: float,
    damping_ratio: float,
    substeps: int,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    step_duration = duration / substeps
    target_velocity = tuple(
        (end - start) / duration
        for start, end in zip(target_start, target_end)
    )
    current_location = location
    current_velocity = velocity
    for step_index in range(substeps):
        elapsed = step_index * step_duration
        step_target = tuple(
            start + component_velocity * elapsed
            for start, component_velocity in zip(
                target_start, target_velocity
            )
        )
        advanced = tuple(
            _linear_target_step(
                component_location,
                component_motion,
                component_target,
                component_target_velocity,
                step_duration,
                omega,
                damping_ratio,
            )
            for (
                component_location,
                component_motion,
                component_target,
                component_target_velocity,
            ) in zip(
                current_location,
                current_velocity,
                step_target,
                target_velocity,
            )
        )
        current_location = tuple(item[0] for item in advanced)
        current_velocity = tuple(item[1] for item in advanced)
    return current_location, current_velocity


def simulate_secondary_motion(
    targets: Sequence[Sequence[float]],
    settings: SecondaryMotionSettings = SecondaryMotionSettings(),
    *,
    initial_location: Sequence[float] | None = None,
    initial_velocity: Sequence[float] | None = None,
) -> SecondaryMotionResult:
    """Filter a regularly sampled location-vector sequence.

    The output has one element for every target sample.  ``dt`` is the elapsed
    time in seconds between adjacent targets.  ``pre_roll`` holds the first
    target while advancing an explicitly supplied initial state before the
    first output sample.
    """

    _validate_settings(settings)
    target_values = _copy_targets(targets)
    if not target_values:
        return SecondaryMotionResult((), ())

    location = _initial_vector(
        initial_location, target_values[0], "initial_location"
    )
    velocity = _initial_vector(
        initial_velocity,
        tuple(0.0 for _ in target_values[0]),
        "initial_velocity",
    )
    omega = 2.0 * math.pi * settings.frequency_hz

    if settings.pre_roll > 0.0:
        location, velocity = _advance_segment(
            location,
            velocity,
            target_values[0],
            target_values[0],
            settings.pre_roll,
            omega,
            settings.damping_ratio,
            settings.substeps,
        )

    locations = [location]
    velocities = [velocity]
    for target_start, target_end in zip(target_values, target_values[1:]):
        location, velocity = _advance_segment(
            location,
            velocity,
            target_start,
            target_end,
            settings.dt,
            omega,
            settings.damping_ratio,
            settings.substeps,
        )
        locations.append(location)
        velocities.append(velocity)

    return SecondaryMotionResult(tuple(locations), tuple(velocities))


def filter_secondary_motion(
    targets: Sequence[Sequence[float]],
    settings: SecondaryMotionSettings = SecondaryMotionSettings(),
    *,
    initial_location: Sequence[float] | None = None,
    initial_velocity: Sequence[float] | None = None,
) -> tuple[tuple[float, ...], ...]:
    """Convenience wrapper returning only the filtered location vectors."""

    return simulate_secondary_motion(
        targets,
        settings,
        initial_location=initial_location,
        initial_velocity=initial_velocity,
    ).locations
