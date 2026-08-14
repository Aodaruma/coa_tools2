"""Pure identifier planning for copied Rig Control definitions."""

from __future__ import annotations

from dataclasses import dataclass
import uuid
from typing import Callable, Sequence


@dataclass(frozen=True)
class RigControlIdentifierSnapshot:
    """Identifier-only view of one persisted Rig Control."""

    control_uuid: str
    tip_widget_uuid: str = ""
    base_widget_uuid: str = ""
    binding_uuids: tuple[str, ...] = ()
    state_uuids: tuple[str, ...] = ()
    cell_uuids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RigControlIdentifierFork:
    """Fresh identifiers allocated for one copied Rig Control."""

    control_uuid: str
    tip_widget_uuid: str
    base_widget_uuid: str
    binding_uuids: tuple[str, ...]
    state_uuids: tuple[str, ...]
    cell_uuids: tuple[str, ...]
    state_uuid_remap: tuple[tuple[str, str], ...]


def build_rig_control_identifier_forks(
    snapshots: Sequence[RigControlIdentifierSnapshot],
    uuid_factory: Callable[[], str] | None = None,
) -> tuple[RigControlIdentifierFork, ...]:
    """Allocate a collision-free, deterministic-shape fork plan.

    The UUID generator is injectable so the complete nested remapping can be
    tested without Blender.  Existing identifiers are reserved as well: a
    copied definition can never accidentally keep one of its source IDs.
    """

    uuid_factory = uuid_factory or (lambda: str(uuid.uuid4()))
    reserved = {
        value
        for snapshot in snapshots
        for value in (
            snapshot.control_uuid,
            snapshot.tip_widget_uuid,
            snapshot.base_widget_uuid,
            *snapshot.binding_uuids,
            *snapshot.state_uuids,
            *snapshot.cell_uuids,
        )
        if value
    }

    def fresh() -> str:
        for _attempt in range(1024):
            candidate = str(uuid_factory())
            if candidate and candidate not in reserved:
                reserved.add(candidate)
                return candidate
        raise ValueError("UUID factory did not produce a fresh identifier.")

    forks = []
    for snapshot in snapshots:
        state_uuids = tuple(fresh() for _value in snapshot.state_uuids)
        forks.append(
            RigControlIdentifierFork(
                control_uuid=fresh(),
                tip_widget_uuid=fresh(),
                base_widget_uuid=fresh(),
                binding_uuids=tuple(
                    fresh() for _value in snapshot.binding_uuids
                ),
                state_uuids=state_uuids,
                cell_uuids=tuple(fresh() for _value in snapshot.cell_uuids),
                state_uuid_remap=tuple(zip(snapshot.state_uuids, state_uuids)),
            )
        )
    return tuple(forks)
