"""Blender artifacts for projected semantic rig stages.

The naming helpers in this module intentionally have no Blender imports.  The
artifact builders import Blender-dependent helpers lazily, which keeps the
deterministic naming/role plan testable with ordinary Python.

The generated projected-IK graph has one direction only::

    control -> hidden 3D IK chain -> projected joints
            -> presentation chain -> source/deform bones

The 3D mechanism never reads a presentation or source bone, preventing a
dependency cycle.  Presentation bones are independently constrained between
projected joints, so their local Z axes remain aligned to the artwork plane.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


SEMANTIC_ROLE_PREFIX = "semantic"


class SemanticArtifactError(RuntimeError):
    """Raised when a semantic stage cannot safely reconcile its artifacts."""


@dataclass(frozen=True)
class ProjectedTransformArtifacts:
    art_frame_bone: str
    display_frame_bone: str
    control_bone: str

    @property
    def primary_control_bone(self) -> str:
        return self.control_bone

    @property
    def generated_bones(self) -> tuple[str, ...]:
        return (self.art_frame_bone, self.display_frame_bone, self.control_bone)


@dataclass(frozen=True)
class ProjectedIKArtifacts:
    frames: ProjectedTransformArtifacts
    mechanism_bones: tuple[str, ...]
    projected_joint_bones: tuple[str, ...]
    presentation_bones: tuple[str, ...]
    source_bones: tuple[str, ...]
    pole_bone: str = ""

    @property
    def primary_control_bone(self) -> str:
        return self.frames.control_bone

    @property
    def generated_bones(self) -> tuple[str, ...]:
        pole = (self.pole_bone,) if self.pole_bone else ()
        return (
            self.frames.generated_bones
            + self.mechanism_bones
            + self.projected_joint_bones
            + self.presentation_bones
            + pole
        )


@dataclass(frozen=True)
class SemanticArtifactNamePlan:
    art_frame: str
    display_frame: str
    control: str
    mechanism_bones: tuple[str, ...]
    projected_joints: tuple[str, ...]
    presentation_bones: tuple[str, ...]
    pole: str


def _slugify(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z_]+", "_", value.strip()).strip("_")
    return slug or "semantic"


def _identifier(owner, *names: str) -> str:
    for name in names:
        value = getattr(owner, name, "")
        if value:
            return str(value)
    return ""


def semantic_stage_role(stage_uuid: str, role: str) -> str:
    """Return a component role scoped to one composable semantic stage."""

    stage_uuid = str(stage_uuid or "").strip()
    role = str(role or "").strip()
    if not stage_uuid:
        raise ValueError("Semantic stage UUID is required for artifact ownership.")
    if not role:
        raise ValueError("Semantic artifact role is required.")
    return f"{SEMANTIC_ROLE_PREFIX}:{stage_uuid}:{role}"


def semantic_artifact_name_plan(
    component,
    stage,
    *,
    chain_size: int = 0,
) -> SemanticArtifactNamePlan:
    """Build stable, collision-resistant names without importing Blender."""

    stage_uuid = _identifier(stage, "stage_uuid", "node_uuid")
    if not stage_uuid:
        raise ValueError("Semantic stage UUID is required.")
    semantic_id = _identifier(stage, "semantic_id", "label") or _identifier(
        component,
        "semantic_id",
        "label",
    )
    slug = _slugify(semantic_id)[:32]
    stage_key = _slugify(stage_uuid.replace("-", ""))[:8]
    stem = f"{slug}_{stage_key}"
    return SemanticArtifactNamePlan(
        art_frame=f"MCH_{stem}_ART",
        display_frame=f"MCH_{stem}_DISPLAY",
        control=f"CTRL_{stem}",
        mechanism_bones=tuple(
            f"MCH_{stem}_IK_{index:02d}" for index in range(chain_size)
        ),
        projected_joints=tuple(
            f"MCH_{stem}_PROJECT_{index:02d}"
            for index in range(chain_size + (1 if chain_size else 0))
        ),
        presentation_bones=tuple(
            f"MCH_{stem}_PRESENT_{index:02d}" for index in range(chain_size)
        ),
        pole=f"CTRL_{stem}_BEND",
    )


def _source_names(component, stage) -> tuple[str, ...]:
    references = tuple(getattr(stage, "source_bones", ()) or ())
    if not references:
        references = tuple(getattr(component, "source_bones", ()) or ())
    names = tuple(
        str(getattr(reference, "bone_name", reference) or "")
        for reference in references
    )
    return tuple(name for name in names if name)


def _stage_uuid(stage) -> str:
    stage_uuid = _identifier(stage, "stage_uuid", "node_uuid")
    if not stage_uuid:
        raise SemanticArtifactError("Semantic stage UUID is required.")
    return stage_uuid


def _component_uuid(component) -> str:
    component_uuid = _identifier(component, "component_uuid", "rig_uuid")
    if not component_uuid:
        raise SemanticArtifactError("Rig component UUID is required.")
    return component_uuid


def _lazy_helpers():
    # Importing component_artifacts imports bpy/mathutils.  Keep it out of the
    # module import path so the deterministic role/name plan stays pure.
    from ... import functions
    from mathutils import Matrix, Vector

    from .component_artifacts import (
        COMPONENT_CONTROL_COLLECTION,
        COMPONENT_MECHANISM_COLLECTION,
        ComponentArtifactConflict,
        _managed_constraint,
        _record_artifact,
        _set_edit_bone_matrix,
        _switch_to_edit_mode,
        _tag_owned_bone,
        find_component_bone,
    )

    return {
        "functions": functions,
        "Matrix": Matrix,
        "Vector": Vector,
        "control_collection": COMPONENT_CONTROL_COLLECTION,
        "mechanism_collection": COMPONENT_MECHANISM_COLLECTION,
        "conflict": ComponentArtifactConflict,
        "managed_constraint": _managed_constraint,
        "record_artifact": _record_artifact,
        "set_edit_bone_matrix": _set_edit_bone_matrix,
        "switch_to_edit_mode": _switch_to_edit_mode,
        "tag_owned_bone": _tag_owned_bone,
        "find_component_bone": find_component_bone,
    }


def _normalized(vector, fallback):
    result = vector.copy()
    if result.length < 1.0e-8:
        result = fallback.copy()
    if result.length < 1.0e-8:
        raise SemanticArtifactError("Cannot construct a semantic coordinate frame.")
    result.normalize()
    return result


def _frame_matrix(origin, y_hint, z_axis, *, Matrix, Vector):
    """Construct a right-handed frame whose local Z is the requested normal."""

    z_axis = _normalized(z_axis, Vector((0.0, 0.0, 1.0)))
    y_axis = y_hint - z_axis * y_hint.dot(z_axis)
    if y_axis.length < 1.0e-8:
        candidates = (
            Vector((0.0, 1.0, 0.0)),
            Vector((1.0, 0.0, 0.0)),
            Vector((0.0, 0.0, 1.0)),
        )
        y_axis = next(
            (
                candidate - z_axis * candidate.dot(z_axis)
                for candidate in candidates
                if (candidate - z_axis * candidate.dot(z_axis)).length
                >= 1.0e-8
            ),
            None,
        )
    if y_axis is None or y_axis.length < 1.0e-8:
        raise SemanticArtifactError("Art-plane axes are degenerate.")
    y_axis.normalize()
    x_axis = y_axis.cross(z_axis).normalized()
    matrix = Matrix.Identity(4)
    matrix.col[0].xyz = x_axis
    matrix.col[1].xyz = y_axis
    matrix.col[2].xyz = z_axis
    matrix.translation = origin
    return matrix


def _owned_bone_names(armature, component, roles: Iterable[str], helpers):
    component_uuid = _component_uuid(component)
    result = {}
    for role in roles:
        bone = helpers["find_component_bone"](armature, component_uuid, role)
        result[role] = bone.name if bone is not None else ""
    return result


def _ensure_edit_bone(
    armature,
    component,
    *,
    role: str,
    default_name: str,
    existing_name: str,
    helpers,
):
    edit_bones = armature.data.edit_bones
    bone = edit_bones.get(existing_name) if existing_name else None
    if bone is None:
        candidate = edit_bones.get(default_name)
        if candidate is not None:
            raise helpers["conflict"](
                f"Bone '{default_name}' already exists and is not owned by "
                "this semantic stage."
            )
        bone = edit_bones.new(default_name)
    helpers["tag_owned_bone"](armature, bone, component, role)
    return bone


def _record_bone(component, role: str, bone_name: str, helpers, *, owned=True):
    helpers["record_artifact"](
        component,
        role,
        "BONE",
        bone_name=bone_name,
        owned=owned,
    )


def _record_constraint(component, role, pose_bone, constraint, helpers):
    helpers["record_artifact"](
        component,
        role,
        "CONSTRAINT",
        bone_name=pose_bone.name,
        constraint_name=constraint.name,
        owned=True,
    )


def _assign_collection(armature, pose_bone, collection, helpers, *, visible):
    helpers["functions"].set_bone_group(
        None,
        armature,
        pose_bone,
        group=collection,
        theme=None,
        visible=visible,
        exclusive=True,
    )


def ensure_projected_transform_artifacts(
    armature,
    component,
    stage,
) -> ProjectedTransformArtifacts:
    """Idempotently create independent Art, Display and Input frames.

    The input control is aligned to the art plane.  Its custom-shape transform
    points at the independently oriented display frame, allowing a future GN
    widget to look tilted without changing the values read from the control.
    """

    if armature is None or getattr(armature, "type", "") != "ARMATURE":
        raise SemanticArtifactError("Projected transforms require an Armature.")
    stage_uuid = _stage_uuid(stage)
    source_names = _source_names(component, stage)
    if not source_names:
        raise SemanticArtifactError("Projected transform requires a source bone.")
    missing = [name for name in source_names if name not in armature.data.bones]
    if missing:
        raise SemanticArtifactError("Missing source bone(s): " + ", ".join(missing))

    helpers = _lazy_helpers()
    roles = {
        "art": semantic_stage_role(stage_uuid, "art_frame"),
        "display": semantic_stage_role(stage_uuid, "display_frame"),
        "control": semantic_stage_role(stage_uuid, "control_bone"),
    }
    existing = _owned_bone_names(armature, component, roles.values(), helpers)
    plan = semantic_artifact_name_plan(component, stage)

    helpers["switch_to_edit_mode"](armature)
    try:
        root = armature.data.edit_bones.get(source_names[0])
        effector = armature.data.edit_bones.get(source_names[-1])
        if root is None or effector is None:
            raise SemanticArtifactError("Source bone disappeared while building frames.")
        Matrix = helpers["Matrix"]
        Vector = helpers["Vector"]
        art_normal = Vector(tuple(getattr(stage, "art_plane_normal", (0.0, 1.0, 0.0))))
        visual_axis = Vector(tuple(getattr(stage, "visual_axis", (0.0, 0.0, 1.0))))
        root_y = root.matrix.to_3x3().col[1].copy()
        effector_y = effector.matrix.to_3x3().col[1].copy()
        art_matrix = _frame_matrix(
            root.head.copy(),
            root_y,
            art_normal,
            Matrix=Matrix,
            Vector=Vector,
        )
        control_matrix = art_matrix.copy()
        control_matrix.translation = effector.head.copy()
        display_matrix = _frame_matrix(
            effector.head.copy(),
            effector_y,
            visual_axis,
            Matrix=Matrix,
            Vector=Vector,
        )
        length = max(float(effector.length), 0.1)

        art = _ensure_edit_bone(
            armature,
            component,
            role=roles["art"],
            default_name=plan.art_frame,
            existing_name=existing[roles["art"]],
            helpers=helpers,
        )
        display = _ensure_edit_bone(
            armature,
            component,
            role=roles["display"],
            default_name=plan.display_frame,
            existing_name=existing[roles["display"]],
            helpers=helpers,
        )
        control = _ensure_edit_bone(
            armature,
            component,
            role=roles["control"],
            default_name=plan.control,
            existing_name=existing[roles["control"]],
            helpers=helpers,
        )
        for bone in (art, display):
            bone.parent = root.parent
            bone.use_connect = False
        control.parent = art
        control.use_connect = False
        helpers["set_edit_bone_matrix"](art, art_matrix, length)
        helpers["set_edit_bone_matrix"](display, display_matrix, length)
        helpers["set_edit_bone_matrix"](control, control_matrix, length)
        names = (art.name, display.name, control.name)
    finally:
        # Existing component artifact helpers also finish their structural
        # edits in Pose mode; use the same contract for compiler integration.
        import bpy

        if armature.mode == "EDIT":
            bpy.ops.object.mode_set(mode="POSE")

    art_pose, display_pose, control_pose = (
        armature.pose.bones[name] for name in names
    )
    for key, pose_bone in (
        ("art", art_pose),
        ("display", display_pose),
        ("control", control_pose),
    ):
        helpers["tag_owned_bone"](armature, pose_bone.bone, component, roles[key])
        _record_bone(component, roles[key], pose_bone.name, helpers)
    for pose_bone in (art_pose, display_pose):
        pose_bone.bone.hide_select = True
        _assign_collection(
            armature,
            pose_bone,
            helpers["mechanism_collection"],
            helpers,
            visible=False,
        )
    control_pose.bone.hide_select = False
    control_pose.rotation_mode = "XYZ"
    control_pose.lock_scale = (True, True, True)
    control_pose.custom_shape_transform = display_pose
    _assign_collection(
        armature,
        control_pose,
        helpers["control_collection"],
        helpers,
        visible=True,
    )

    stage.art_frame_bone = art_pose.name
    stage.display_frame_bone = display_pose.name
    stage.control_bone = control_pose.name
    return ProjectedTransformArtifacts(
        art_frame_bone=art_pose.name,
        display_frame_bone=display_pose.name,
        control_bone=control_pose.name,
    )


def _project_to_frame(point, frame_matrix, Vector):
    local = frame_matrix.inverted() @ point
    local.z = 0.0
    return frame_matrix @ Vector((local.x, local.y, local.z))


def _pole_position(source_bones, art_matrix, Vector):
    upper = source_bones[0]
    lower = source_bones[1]
    start = upper.head.copy()
    joint = lower.head.copy()
    end = lower.tail.copy()
    direction = end - start
    if direction.length < 1.0e-8:
        direction = art_matrix.to_3x3().col[1].copy()
    direction.normalize()
    bend = joint - (start + direction * (joint - start).dot(direction))
    if bend.length < 1.0e-8:
        bend = art_matrix.to_3x3().col[2].copy()
        bend -= direction * bend.dot(direction)
    bend = _normalized(bend, art_matrix.to_3x3().col[0])
    distance = max(sum(float(bone.length) for bone in source_bones[:2]), 0.1)
    return joint + bend * distance


def ensure_projected_ik_artifacts(
    armature,
    component,
    stage,
) -> ProjectedIKArtifacts:
    """Build a real hidden IK chain and a plane-preserving presentation chain."""

    stage_uuid = _stage_uuid(stage)
    source_names = _source_names(component, stage)
    if len(source_names) < 2:
        raise SemanticArtifactError("Projected IK requires at least two source bones.")
    missing = [name for name in source_names if name not in armature.data.bones]
    if missing:
        raise SemanticArtifactError("Missing source bone(s): " + ", ".join(missing))
    for parent_name, child_name in zip(source_names, source_names[1:]):
        child = armature.data.bones[child_name]
        if child.parent is None or child.parent.name != parent_name:
            raise SemanticArtifactError(
                "Projected IK source bones must form one ordered parent chain: "
                f"{parent_name} -> {child_name}."
            )

    helpers = _lazy_helpers()
    frames = ensure_projected_transform_artifacts(armature, component, stage)
    plan = semantic_artifact_name_plan(
        component,
        stage,
        chain_size=len(source_names),
    )
    mechanism_roles = tuple(
        semantic_stage_role(stage_uuid, f"mechanism_bone:{index}")
        for index in range(len(source_names))
    )
    projection_roles = tuple(
        semantic_stage_role(stage_uuid, f"projected_joint:{index}")
        for index in range(len(source_names) + 1)
    )
    presentation_roles = tuple(
        semantic_stage_role(stage_uuid, f"presentation_bone:{index}")
        for index in range(len(source_names))
    )
    pole_role = semantic_stage_role(stage_uuid, "pole_control")
    all_roles = mechanism_roles + projection_roles + presentation_roles + (pole_role,)
    existing = _owned_bone_names(armature, component, all_roles, helpers)

    helpers["switch_to_edit_mode"](armature)
    try:
        source_bones = tuple(armature.data.edit_bones[name] for name in source_names)
        art = armature.data.edit_bones.get(frames.art_frame_bone)
        if art is None:
            raise SemanticArtifactError("Generated art frame is missing.")
        art_matrix = art.matrix.copy()
        source_parent = source_bones[0].parent
        mechanism = []
        for index, (source, role, default_name) in enumerate(
            zip(source_bones, mechanism_roles, plan.mechanism_bones)
        ):
            bone = _ensure_edit_bone(
                armature,
                component,
                role=role,
                default_name=default_name,
                existing_name=existing[role],
                helpers=helpers,
            )
            bone.parent = mechanism[index - 1] if index else source_parent
            bone.use_connect = bool(index and source.use_connect)
            bone.matrix = source.matrix.copy()
            bone.length = max(float(source.length), 1.0e-4)
            mechanism.append(bone)

        Vector = helpers["Vector"]
        joint_points = [bone.head.copy() for bone in mechanism]
        joint_points.append(mechanism[-1].tail.copy())
        projected_points = [
            _project_to_frame(point, art_matrix, Vector) for point in joint_points
        ]
        helper_length = max(
            sum(float(bone.length) for bone in source_bones) * 0.02,
            0.02,
        )
        projected = []
        for point, role, default_name in zip(
            projected_points,
            projection_roles,
            plan.projected_joints,
        ):
            bone = _ensure_edit_bone(
                armature,
                component,
                role=role,
                default_name=default_name,
                existing_name=existing[role],
                helpers=helpers,
            )
            bone.parent = source_parent
            bone.use_connect = False
            matrix = art_matrix.copy()
            matrix.translation = point
            helpers["set_edit_bone_matrix"](bone, matrix, helper_length)
            projected.append(bone)

        presentation = []
        art_normal = art_matrix.to_3x3().col[2].copy()
        for index, (role, default_name) in enumerate(
            zip(presentation_roles, plan.presentation_bones)
        ):
            bone = _ensure_edit_bone(
                armature,
                component,
                role=role,
                default_name=default_name,
                existing_name=existing[role],
                helpers=helpers,
            )
            bone.parent = source_parent
            bone.use_connect = False
            segment = projected_points[index + 1] - projected_points[index]
            length = max(segment.length, 1.0e-4)
            matrix = _frame_matrix(
                projected_points[index],
                segment if segment.length >= 1.0e-8 else art_matrix.to_3x3().col[1],
                art_normal,
                Matrix=helpers["Matrix"],
                Vector=Vector,
            )
            helpers["set_edit_bone_matrix"](bone, matrix, length)
            presentation.append(bone)

        pole = None
        if bool(getattr(stage, "use_pole", False)):
            pole = _ensure_edit_bone(
                armature,
                component,
                role=pole_role,
                default_name=plan.pole,
                existing_name=existing[pole_role],
                helpers=helpers,
            )
            pole.parent = source_parent
            pole.use_connect = False
            matrix = art_matrix.copy()
            matrix.translation = _pole_position(source_bones, art_matrix, Vector)
            helpers["set_edit_bone_matrix"](pole, matrix, helper_length * 4.0)

        mechanism_names = tuple(bone.name for bone in mechanism)
        projection_names = tuple(bone.name for bone in projected)
        presentation_names = tuple(bone.name for bone in presentation)
        pole_name = pole.name if pole is not None else ""
    finally:
        import bpy

        if armature.mode == "EDIT":
            bpy.ops.object.mode_set(mode="POSE")

    for role, name in zip(mechanism_roles, mechanism_names):
        pose_bone = armature.pose.bones[name]
        helpers["tag_owned_bone"](armature, pose_bone.bone, component, role)
        _record_bone(component, role, name, helpers)
    for role, name in zip(projection_roles, projection_names):
        pose_bone = armature.pose.bones[name]
        helpers["tag_owned_bone"](armature, pose_bone.bone, component, role)
        _record_bone(component, role, name, helpers)
    for role, name in zip(presentation_roles, presentation_names):
        pose_bone = armature.pose.bones[name]
        helpers["tag_owned_bone"](armature, pose_bone.bone, component, role)
        _record_bone(component, role, name, helpers)
    if pole_name:
        pole_pose = armature.pose.bones[pole_name]
        helpers["tag_owned_bone"](armature, pole_pose.bone, component, pole_role)
        _record_bone(component, pole_role, pole_name, helpers)
    else:
        pole_pose = None

    for name in mechanism_names + projection_names + presentation_names:
        pose_bone = armature.pose.bones[name]
        pose_bone.bone.hide_select = True
        _assign_collection(
            armature,
            pose_bone,
            helpers["mechanism_collection"],
            helpers,
            visible=False,
        )
    if pole_pose is not None:
        pole_pose.bone.hide_select = False
        pole_pose.lock_rotation = (True, True, True)
        pole_pose.lock_scale = (True, True, True)
        _assign_collection(
            armature,
            pole_pose,
            helpers["control_collection"],
            helpers,
            visible=True,
        )

    short_component = _component_uuid(component).replace("-", "")[:8]
    short_stage = stage_uuid.replace("-", "")[:8]
    constraint_stem = f"COA_SEM_{short_component}_{short_stage}"

    # The final source bone is the hand/foot/end marker.  The IK owner is the
    # preceding segment even for the smallest valid two-bone source chain.
    owner_index = len(mechanism_names) - 2
    ik_owner = armature.pose.bones[mechanism_names[owner_index]]
    ik_role = semantic_stage_role(stage_uuid, "ik_constraint")
    ik = helpers["managed_constraint"](
        ik_owner,
        component,
        f"{constraint_stem}_IK",
        "IK",
    )
    ik.target = armature
    ik.subtarget = frames.control_bone
    available_chain = owner_index + 1 if owner_index >= 0 else len(mechanism_names)
    ik.chain_count = min(
        max(int(getattr(stage, "chain_length", 2)), 1),
        available_chain,
    )
    ik.use_stretch = bool(getattr(stage, "allow_stretch", False))
    if pole_pose is not None:
        ik.pole_target = armature
        ik.pole_subtarget = pole_pose.name
        ik.pole_angle = 0.0
    else:
        ik.pole_target = None
        ik.pole_subtarget = ""
        ik.pole_angle = 0.0
    _record_constraint(component, ik_role, ik_owner, ik, helpers)

    for index, projection_name in enumerate(projection_names):
        pose_bone = armature.pose.bones[projection_name]
        source_index = min(index, len(mechanism_names) - 1)
        copy_role = semantic_stage_role(stage_uuid, f"joint_copy:{index}")
        copy = helpers["managed_constraint"](
            pose_bone,
            component,
            f"{constraint_stem}_JointCopy_{index:02d}",
            "COPY_LOCATION",
        )
        copy.target = armature
        copy.subtarget = mechanism_names[source_index]
        copy.head_tail = 1.0 if index == len(mechanism_names) else 0.0
        copy.owner_space = "WORLD"
        copy.target_space = "WORLD"
        copy.use_x = copy.use_y = copy.use_z = True
        copy.use_offset = False
        _record_constraint(component, copy_role, pose_bone, copy, helpers)

        limit_role = semantic_stage_role(stage_uuid, f"joint_plane_limit:{index}")
        limit = helpers["managed_constraint"](
            pose_bone,
            component,
            f"{constraint_stem}_JointPlane_{index:02d}",
            "LIMIT_LOCATION",
        )
        limit.owner_space = "CUSTOM"
        limit.space_object = armature
        limit.space_subtarget = frames.art_frame_bone
        limit.use_min_x = limit.use_max_x = False
        limit.use_min_y = limit.use_max_y = False
        limit.use_min_z = limit.use_max_z = True
        limit.min_z = limit.max_z = 0.0
        limit.use_transform_limit = True
        _record_constraint(component, limit_role, pose_bone, limit, helpers)

    for index, presentation_name in enumerate(presentation_names):
        pose_bone = armature.pose.bones[presentation_name]
        copy_role = semantic_stage_role(stage_uuid, f"presentation_copy:{index}")
        copy = helpers["managed_constraint"](
            pose_bone,
            component,
            f"{constraint_stem}_PresentCopy_{index:02d}",
            "COPY_LOCATION",
        )
        copy.target = armature
        copy.subtarget = projection_names[index]
        copy.owner_space = "WORLD"
        copy.target_space = "WORLD"
        copy.use_offset = False
        _record_constraint(component, copy_role, pose_bone, copy, helpers)

        stretch_role = semantic_stage_role(stage_uuid, f"presentation_stretch:{index}")
        stretch = helpers["managed_constraint"](
            pose_bone,
            component,
            f"{constraint_stem}_PresentStretch_{index:02d}",
            "STRETCH_TO",
        )
        stretch.target = armature
        stretch.subtarget = projection_names[index + 1]
        stretch.head_tail = 0.0
        stretch.keep_axis = "PLANE_Z"
        stretch.volume = "NO_VOLUME"
        stretch.rest_length = max(float(pose_bone.length), 1.0e-4)
        _record_constraint(component, stretch_role, pose_bone, stretch, helpers)

    for index, (source_name, presentation_name) in enumerate(
        zip(source_names, presentation_names)
    ):
        source_pose = armature.pose.bones[source_name]
        owner_uuid = source_pose.bone.get("coa_rig_component_uuid")
        if owner_uuid not in {None, "", _component_uuid(component)}:
            raise helpers["conflict"](
                f"Source bone '{source_name}' belongs to another pose component."
            )
        source_role = semantic_stage_role(stage_uuid, f"source_bone:{index}")
        _record_bone(component, source_role, source_name, helpers, owned=False)
        copy_role = semantic_stage_role(stage_uuid, f"source_presentation:{index}")
        copy = helpers["managed_constraint"](
            source_pose,
            component,
            f"{constraint_stem}_SourcePresent_{index:02d}",
            "COPY_TRANSFORMS",
        )
        copy.target = armature
        copy.subtarget = presentation_name
        copy.owner_space = "WORLD"
        copy.target_space = "WORLD"
        copy.mix_mode = "REPLACE"
        copy.remove_target_shear = True
        _record_constraint(component, copy_role, source_pose, copy, helpers)

    stage.mechanism_frame_bone = mechanism_names[0]
    stage.pole_bone = pole_name
    import bpy

    bpy.context.view_layer.update()
    return ProjectedIKArtifacts(
        frames=frames,
        mechanism_bones=mechanism_names,
        projected_joint_bones=projection_names,
        presentation_bones=presentation_names,
        source_bones=source_names,
        pole_bone=pole_name,
    )


__all__ = [
    "ProjectedIKArtifacts",
    "ProjectedTransformArtifacts",
    "SemanticArtifactError",
    "SemanticArtifactNamePlan",
    "ensure_projected_ik_artifacts",
    "ensure_projected_transform_artifacts",
    "semantic_artifact_name_plan",
    "semantic_stage_role",
]
