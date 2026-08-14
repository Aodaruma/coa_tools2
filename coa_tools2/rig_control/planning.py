"""Pure planning primitives shared by Blender compiler backends."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ArtifactAction(str, Enum):
    CREATE = "CREATE"
    UPDATE_OWNED = "UPDATE_OWNED"
    KEEP = "KEEP"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True)
class ArtifactPlanItem:
    role: str
    artifact_key: str
    action: ArtifactAction
    reason: str = ""


def plan_artifact(
    role: str,
    artifact_key: str,
    *,
    exists: bool,
    owned: bool,
    matches: bool,
) -> ArtifactPlanItem:
    if not exists:
        return ArtifactPlanItem(role, artifact_key, ArtifactAction.CREATE)
    if not owned:
        return ArtifactPlanItem(
            role,
            artifact_key,
            ArtifactAction.CONFLICT,
            "Existing artifact is not managed by this rig control.",
        )
    if matches:
        return ArtifactPlanItem(role, artifact_key, ArtifactAction.KEEP)
    return ArtifactPlanItem(role, artifact_key, ArtifactAction.UPDATE_OWNED)
