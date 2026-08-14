"""Blender-independent key plans for semantic rig state transitions.

Animator-facing state remains discrete.  Solver compensation is deliberately
planned as a separate smooth curve, so a Mode or Contact key never turns into
an exposed blend-weight control.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SemanticTransitionKey:
    """One planned key without depending on Blender's FCurve API."""

    frame: float
    value: float
    interpolation: str


def discrete_state_key(frame: float, value: float) -> SemanticTransitionKey:
    """Return the single CONSTANT key used by a public two-state control."""

    return SemanticTransitionKey(float(frame), float(value), "CONSTANT")


def smooth_compensation_keys(
    frame: float,
    start_value: float,
    end_value: float,
    duration: int,
) -> tuple[SemanticTransitionKey, SemanticTransitionKey]:
    """Plan a private, smooth compensation ramp after a discrete switch."""

    if int(duration) < 1:
        raise ValueError("A semantic transition needs at least one frame.")
    start = float(frame)
    return (
        SemanticTransitionKey(start, float(start_value), "BEZIER"),
        SemanticTransitionKey(
            start + int(duration),
            float(end_value),
            "BEZIER",
        ),
    )


__all__ = [
    "SemanticTransitionKey",
    "discrete_state_key",
    "smooth_compensation_keys",
]
