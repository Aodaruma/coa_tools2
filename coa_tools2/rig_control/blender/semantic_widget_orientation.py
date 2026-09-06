"""Rest-only transforms for generated widget geometry.

The solver's input and display bones remain unchanged.  The cached mesh is
expressed in the existing display bone's local coordinates instead.
"""

from __future__ import annotations


def hand_widget_rest_transform(source_bone, display_bone, art_normal, height):
    """Place a centered +Y hand outline at the wrist in the artwork plane.

    Data-bone coordinates deliberately exclude the current animation pose and
    bone roll.  A hand pointing straight out of the art plane uses the same
    deterministic in-plane fallback as the semantic coordinate frames.
    """

    from mathutils import Matrix, Vector

    from .semantic_artifacts import _frame_matrix

    direction = source_bone.tail_local - source_bone.head_local
    desired = _frame_matrix(
        Vector((0.0, 0.0, 0.0)),
        direction,
        Vector(art_normal),
        Matrix=Matrix,
        Vector=Vector,
    )
    # Tombstone geometry is centered.  Put its lower edge's center at the
    # control origin, leaving the cap on the finger side of the wrist.
    desired.translation = desired.col[1].xyz * (float(height) * 0.5)
    display_rotation = display_bone.matrix_local.to_3x3().to_4x4()
    return display_rotation.inverted() @ desired
