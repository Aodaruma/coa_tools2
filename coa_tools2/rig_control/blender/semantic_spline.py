"""Blender artifacts for composable semantic Spline Chain stages.

The pure plan/result types in this module deliberately avoid importing Blender.
Runtime imports are deferred until an artifact builder or hook retarget is used.

The generated dependency direction is::

    CTRL point bones -> Curve Hook modifiers -> NURBS Curve
                     -> hidden MCH chain Spline IK
                     -> projected joints in the Art Plane
                     -> presentation chain -> source artwork bones

The curve-point-to-Hook ordering is public so a Secondary Motion stage can
retarget selected hooks from authored controls to deterministic simulation
output bones without rebuilding the curve or its Spline IK constraint.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .semantic_artifacts import (
    SemanticArtifactError,
    _frame_matrix,
    _project_to_frame,
    _reconcile_owned_bone_renames,
    semantic_stage_role,
)


@dataclass(frozen=True)
class SplineHookBinding:
    point_index: int
    modifier_name: str
    bone_name: str
    pinned: bool = False


@dataclass(frozen=True)
class SplineChainArtifacts:
    primary_control_bone: str
    control_bones: tuple[str, ...]
    mechanism_bones: tuple[str, ...]
    curve_object: str
    source_bones: tuple[str, ...]
    hook_bindings: tuple[SplineHookBinding, ...]
    projected_joint_bones: tuple[str, ...] = ()
    presentation_bones: tuple[str, ...] = ()
    art_frame_bone: str = ""
    art_frame_owned: bool = False

    @property
    def curve(self) -> str:
        """Compatibility shorthand for compiler adapters."""

        return self.curve_object

    @property
    def hook_modifiers(self) -> tuple[str, ...]:
        return tuple(binding.modifier_name for binding in self.hook_bindings)

    @property
    def hook_bones(self) -> tuple[str, ...]:
        return tuple(binding.bone_name for binding in self.hook_bindings)

    @property
    def generated_bones(self) -> tuple[str, ...]:
        art_frame = (
            (self.art_frame_bone,)
            if self.art_frame_bone and self.art_frame_owned
            else ()
        )
        return (
            self.control_bones
            + self.mechanism_bones
            + self.projected_joint_bones
            + self.presentation_bones
            + art_frame
        )


@dataclass(frozen=True)
class SplineArtifactNamePlan:
    art_frame: str
    curve_object: str
    curve_data: str
    control_bones: tuple[str, ...]
    mechanism_bones: tuple[str, ...]
    projected_joints: tuple[str, ...]
    presentation_bones: tuple[str, ...]
    hook_modifiers: tuple[str, ...]
    spline_constraint: str


class SemanticSplineError(SemanticArtifactError):
    """Raised when a Spline stage cannot safely reconcile its artifacts."""


def _slugify(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z_]+", "_", str(value or "").strip()).strip("_")
    return slug or "spline"


def _identifier(owner, *names: str) -> str:
    for name in names:
        value = getattr(owner, name, "")
        if value:
            return str(value)
    return ""


def semantic_spline_name_plan(
    component,
    stage,
    *,
    source_count: int,
    control_count: int,
) -> SplineArtifactNamePlan:
    """Return stable Spline object, bone, modifier and constraint names."""

    if source_count < 2:
        raise ValueError("A Spline chain requires at least two source bones.")
    if control_count < 2:
        raise ValueError("A Spline curve requires at least two control points.")
    component_uuid = _identifier(component, "component_uuid", "rig_uuid")
    stage_uuid = _identifier(stage, "stage_uuid", "node_uuid")
    if not component_uuid:
        raise ValueError("Rig component UUID is required.")
    if not stage_uuid:
        raise ValueError("Semantic stage UUID is required.")
    semantic_id = _identifier(stage, "semantic_id", "label") or _identifier(
        component,
        "semantic_id",
        "label",
    )
    slug = _slugify(semantic_id)[:24]
    component_key = _slugify(component_uuid.replace("-", ""))[:8]
    stage_key = _slugify(stage_uuid.replace("-", ""))[:8]
    stem = f"{slug}_{component_key}_{stage_key}"
    constraint_stem = f"COA_SEM_{component_key}_{stage_key}"
    return SplineArtifactNamePlan(
        art_frame=f"MCH_{stem}_ART_FRAME",
        curve_object=f"CRV_{stem}",
        curve_data=f"CRV_{stem}_Data",
        control_bones=tuple(
            f"CTRL_{stem}_POINT_{index:02d}" for index in range(control_count)
        ),
        mechanism_bones=tuple(
            f"MCH_{stem}_SPLINE_{index:02d}" for index in range(source_count)
        ),
        projected_joints=tuple(
            f"MCH_{stem}_PROJECTED_JOINT_{index:02d}"
            for index in range(source_count + 1)
        ),
        presentation_bones=tuple(
            f"MCH_{stem}_PRESENT_{index:02d}" for index in range(source_count)
        ),
        hook_modifiers=tuple(
            f"{constraint_stem}_Hook_{index:02d}" for index in range(control_count)
        ),
        spline_constraint=f"{constraint_stem}_SplineIK",
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


def _runtime_helpers():
    import bpy
    from mathutils import Matrix, Vector

    from ... import functions
    from .artifacts import ensure_rig_instance_id
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
        find_component_object,
    )

    return {
        "bpy": bpy,
        "Matrix": Matrix,
        "Vector": Vector,
        "functions": functions,
        "ensure_rig_instance_id": ensure_rig_instance_id,
        "control_collection": COMPONENT_CONTROL_COLLECTION,
        "mechanism_collection": COMPONENT_MECHANISM_COLLECTION,
        "conflict": ComponentArtifactConflict,
        "managed_constraint": _managed_constraint,
        "record_artifact": _record_artifact,
        "set_edit_bone_matrix": _set_edit_bone_matrix,
        "switch_to_edit_mode": _switch_to_edit_mode,
        "tag_owned_bone": _tag_owned_bone,
        "find_component_bone": find_component_bone,
        "find_component_object": find_component_object,
    }


def _component_uuid(component) -> str:
    value = _identifier(component, "component_uuid", "rig_uuid")
    if not value:
        raise SemanticSplineError("Rig component UUID is required.")
    return value


def _stage_uuid(stage) -> str:
    value = _identifier(stage, "stage_uuid", "node_uuid")
    if not value:
        raise SemanticSplineError("Semantic stage UUID is required.")
    return value


def _record_bone(component, role, bone_name, helpers, *, owned=True):
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


def _record_modifier(component, role, curve_object, modifier, helpers):
    helpers["record_artifact"](
        component,
        role,
        "MODIFIER",
        object_name=curve_object.name,
        constraint_name=modifier.name,
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


def _owned_bone_name(armature, component, role, helpers) -> str:
    bone = helpers["find_component_bone"](
        armature,
        _component_uuid(component),
        role,
    )
    return bone.name if bone is not None else ""


def _ensure_edit_bone(
    armature,
    component,
    *,
    role,
    default_name,
    existing_name,
    helpers,
):
    edit_bones = armature.data.edit_bones
    bone = edit_bones.get(existing_name) if existing_name else None
    if bone is None:
        candidate = edit_bones.get(default_name)
        if candidate is not None:
            raise helpers["conflict"](
                f"Bone '{default_name}' already exists and is not owned by "
                "this Spline stage."
            )
        bone = edit_bones.new(default_name)
    helpers["tag_owned_bone"](armature, bone, component, role)
    return bone


def _polyline_samples(points, count, Vector):
    if count < 2:
        raise SemanticSplineError("A Spline curve requires at least two points.")
    if len(points) < 2:
        raise SemanticSplineError("A Spline source chain has no measurable path.")
    lengths = [0.0]
    for start, end in zip(points, points[1:]):
        lengths.append(lengths[-1] + (end - start).length)
    total = lengths[-1]
    if total < 1.0e-8:
        raise SemanticSplineError("A Spline source chain has zero total length.")
    result = []
    segment = 0
    for index in range(count):
        target = total * index / (count - 1)
        while segment + 1 < len(lengths) - 1 and lengths[segment + 1] < target:
            segment += 1
        span = lengths[segment + 1] - lengths[segment]
        factor = 0.0 if span < 1.0e-8 else (target - lengths[segment]) / span
        result.append(points[segment].lerp(points[segment + 1], factor))
    return tuple(Vector(point) for point in result)


def _tag_owned_curve(armature, curve_object, component, role, helpers):
    instance_id = helpers["ensure_rig_instance_id"](armature)
    component_uuid = _component_uuid(component)
    for owner in (curve_object, curve_object.data):
        existing_uuid = owner.get("coa_rig_component_uuid")
        existing_instance = owner.get("coa_rig_instance_id")
        if existing_uuid not in {None, "", component_uuid}:
            raise helpers["conflict"](
                f"Curve '{curve_object.name}' belongs to another pose component."
            )
        # ``ensure_unique_component_instance`` copies owned objects and their
        # data before this builder runs.  A single-user copied Curve datablock
        # therefore legitimately still carries the source instance tag.
        forked_curve_data = (
            owner == curve_object.data
            and owner.users == 1
            and curve_object.get("coa_rig_instance_id") == instance_id
            and curve_object.get("coa_rig_component_uuid") == component_uuid
        )
        if existing_uuid == component_uuid and existing_instance not in {
            None,
            "",
            instance_id,
        } and not forked_curve_data:
            raise helpers["conflict"](
                f"Curve '{curve_object.name}' belongs to another Armature instance."
            )
        owner["coa_rig_instance_id"] = instance_id
        owner["coa_rig_component_uuid"] = component_uuid
        owner["coa_rig_component_role"] = role
        owner["coa_rig_managed"] = True


def _ensure_curve_object(armature, component, role, plan, helpers):
    bpy = helpers["bpy"]
    curve_object = helpers["find_component_object"](
        armature,
        _component_uuid(component),
        role,
    )
    if curve_object is None:
        candidate = bpy.data.objects.get(plan.curve_object)
        if candidate is not None:
            raise helpers["conflict"](
                f"Object '{plan.curve_object}' already exists and is not owned "
                "by this Spline stage."
            )
        curve_data = bpy.data.curves.get(plan.curve_data)
        if curve_data is not None:
            instance_id = helpers["ensure_rig_instance_id"](armature)
            reusable = (
                curve_data.users == 0
                and curve_data.get("coa_rig_instance_id") == instance_id
                and curve_data.get("coa_rig_component_uuid")
                == _component_uuid(component)
                and curve_data.get("coa_rig_component_role") == role
            )
            if not reusable:
                raise helpers["conflict"](
                    f"Curve data '{plan.curve_data}' already exists and is unmanaged."
                )
        else:
            curve_data = bpy.data.curves.new(plan.curve_data, "CURVE")
        curve_object = bpy.data.objects.new(plan.curve_object, curve_data)
        collections = tuple(getattr(armature, "users_collection", ()) or ())
        collection = collections[0] if collections else bpy.context.scene.collection
        collection.objects.link(curve_object)
    if getattr(curve_object, "type", "") != "CURVE":
        raise helpers["conflict"](
            f"Owned Spline object '{curve_object.name}' is not a Curve."
        )
    _tag_owned_curve(armature, curve_object, component, role, helpers)
    stage_prefix = f"{role.rsplit(':', 1)[0]}:"
    for artifact in component.artifacts:
        if (
            artifact.owned
            and artifact.role.startswith(stage_prefix)
            and artifact.data_type in {"OBJECT", "MODIFIER"}
            and (
                artifact.role == role
                or ":spline_hook:" in artifact.role
            )
        ):
            artifact.object_name = curve_object.name
    curve_object.parent = armature
    curve_object.parent_type = "OBJECT"
    curve_object.matrix_parent_inverse = helpers["Matrix"].Identity(4)
    curve_object.matrix_basis = helpers["Matrix"].Identity(4)
    curve_object.hide_render = True
    curve_object.hide_select = True
    curve_object.display_type = "WIRE"
    curve_object.show_in_front = True
    helpers["record_artifact"](
        component,
        role,
        "OBJECT",
        object_name=curve_object.name,
        owned=True,
    )
    return curve_object


def _configure_curve(curve_object, points):
    curve_data = curve_object.data
    curve_data.dimensions = "3D"
    curve_data.resolution_u = 12
    curve_data.render_resolution_u = 12
    curve_data.twist_mode = "MINIMUM"
    for spline in tuple(curve_data.splines):
        curve_data.splines.remove(spline)
    spline = curve_data.splines.new("NURBS")
    spline.points.add(len(points) - 1)
    for index, point in enumerate(points):
        spline.points[index].co = (*point, 1.0)
        spline.points[index].radius = 1.0
        spline.points[index].tilt = 0.0
    spline.order_u = min(4, len(points))
    spline.use_endpoint_u = True
    spline.use_cyclic_u = False
    return spline


def _recorded_hook_modifier(
    curve_object,
    component,
    role,
    *,
    allow_missing,
    helpers,
):
    """Resolve one generated Hook conservatively on Blender 5.1.

    Modifier RNA does not support custom ID properties, so a stale serialized
    name cannot be repaired automatically.  An extra unrecorded Hook is treated
    as possible evidence that the generated Hook was renamed; rebuilding then
    stops before touching either candidate.
    """

    artifacts = [
        artifact
        for artifact in component.artifacts
        if artifact.owned
        and artifact.data_type == "MODIFIER"
        and artifact.role == role
    ]
    if len(artifacts) > 1:
        raise helpers["conflict"](f"Multiple Hook artifacts use role '{role}'.")
    if not artifacts:
        return None
    artifact = artifacts[0]
    if artifact.object_name != curve_object.name:
        raise helpers["conflict"](
            f"Hook role '{role}' moved from Curve '{artifact.object_name}' "
            f"to '{curve_object.name}'."
        )
    referenced_names = {
        candidate.constraint_name
        for candidate in component.artifacts
        if candidate.owned
        and candidate.data_type == "MODIFIER"
        and candidate.object_name == curve_object.name
        and candidate.constraint_name
    }
    unrecorded_hooks = [
        modifier
        for modifier in curve_object.modifiers
        if modifier.type == "HOOK" and modifier.name not in referenced_names
    ]
    modifier = curve_object.modifiers.get(artifact.constraint_name)
    if modifier is None:
        if unrecorded_hooks:
            raise helpers["conflict"](
                f"Generated Hook for role '{role}' may have been renamed; "
                "ownership is ambiguous."
            )
        if allow_missing:
            return None
        raise helpers["conflict"](
            f"Generated Hook '{artifact.constraint_name}' is missing."
        )
    if modifier.type != "HOOK":
        raise helpers["conflict"](
            f"Recorded Hook name '{artifact.constraint_name}' is now used by "
            "an incompatible Modifier."
        )
    if unrecorded_hooks:
        raise helpers["conflict"](
            f"Hook ownership for role '{role}' is ambiguous after a rename."
        )
    return modifier


def _ensure_hook_modifier(
    curve_object,
    armature,
    component,
    stage_uuid,
    *,
    point_index,
    modifier_name,
    bone_name,
    point,
    helpers,
):
    role = semantic_stage_role(stage_uuid, f"spline_hook:{point_index}")
    modifier = _recorded_hook_modifier(
        curve_object,
        component,
        role,
        allow_missing=False,
        helpers=helpers,
    )
    if modifier is None and curve_object.modifiers.get(modifier_name) is not None:
        raise helpers["conflict"](
            f"Modifier '{modifier_name}' is not owned by this Spline stage."
        )
    if modifier is None:
        modifier = curve_object.modifiers.new(modifier_name, "HOOK")
        # Record ownership before configuring RNA fields so a failure between
        # creation and the caller's final reconcile is still rollback-visible.
        helpers["record_artifact"](
            component,
            role,
            "MODIFIER",
            object_name=curve_object.name,
            constraint_name=modifier.name,
            owned=True,
        )
    modifier.object = armature
    modifier.subtarget = bone_name
    modifier.strength = 1.0
    modifier.falloff_type = "NONE"
    modifier.center = point
    modifier.matrix_inverse = helpers["Matrix"].Identity(4)
    modifier.vertex_indices_set([point_index])
    return modifier


def _remove_obsolete_hooks(curve_object, component, stage_uuid, expected, helpers):
    expected_roles = {
        semantic_stage_role(stage_uuid, f"spline_hook:{index}")
        for index in range(len(tuple(expected)))
    }
    hook_prefix = semantic_stage_role(stage_uuid, "spline_hook:")
    stale_roles = {
        artifact.role
        for artifact in component.artifacts
        if artifact.role.startswith(hook_prefix)
        and artifact.data_type == "MODIFIER"
        and artifact.role not in expected_roles
        and artifact.owned
    }
    for role in stale_roles:
        modifier = _recorded_hook_modifier(
            curve_object,
            component,
            role,
            allow_missing=True,
            helpers=helpers,
        )
        if modifier is not None:
            curve_object.modifiers.remove(modifier)
    for index in range(len(component.artifacts) - 1, -1, -1):
        artifact = component.artifacts[index]
        if artifact.role in stale_roles:
            component.artifacts.remove(index)


def retarget_spline_hooks(
    curve_object,
    bone_names,
    *,
    armature=None,
    hook_names=None,
) -> tuple[SplineHookBinding, ...]:
    """Retarget managed Hook modifiers in curve-point order.

    ``bone_names`` is commonly a Secondary Motion output chain.  Root/tip pin
    policy remains explicit: callers keep the authored CTRL name at an endpoint
    that should stay pinned and substitute simulated names for other points.
    """

    helpers = _runtime_helpers()
    bpy = helpers["bpy"]
    if isinstance(curve_object, str):
        curve_object = bpy.data.objects.get(curve_object)
    if curve_object is None or getattr(curve_object, "type", "") != "CURVE":
        raise SemanticSplineError("Hook retarget requires a Curve object.")
    bones = tuple(str(name or "") for name in bone_names)
    if not bones or any(not name for name in bones):
        raise SemanticSplineError("Every retargeted Hook needs a bone name.")
    requested_names = tuple(hook_names) if hook_names is not None else tuple(
        str(curve_object.get("coa_rig_spline_hook_order", "") or "").splitlines()
    )
    all_hooks = tuple(
        modifier for modifier in curve_object.modifiers if modifier.type == "HOOK"
    )
    if not requested_names:
        raise SemanticSplineError("No recorded Spline Hook order was found.")
    modifiers = []
    for name in requested_names:
        modifier = curve_object.modifiers.get(name)
        if modifier is None or modifier.type != "HOOK":
            raise SemanticSplineError(f"Managed Hook '{name}' is missing or renamed.")
        modifiers.append(modifier)
    if len(all_hooks) != len(modifiers) or set(all_hooks) != set(modifiers):
        raise SemanticSplineError(
            "Spline Hook ownership is ambiguous; an unrecorded or renamed Hook exists."
        )
    if len(modifiers) != len(bones):
        raise SemanticSplineError(
            "Hook and retarget bone counts must match "
            f"({len(modifiers)} != {len(bones)})."
        )
    if armature is None:
        targets = {modifier.object for modifier in modifiers if modifier.object}
        if len(targets) != 1:
            raise SemanticSplineError(
                "Pass armature explicitly when Hook targets are missing or mixed."
            )
        armature = targets.pop()
    if getattr(armature, "type", "") != "ARMATURE":
        raise SemanticSplineError("Hook targets require an Armature.")
    missing = [name for name in bones if name not in armature.data.bones]
    if missing:
        raise SemanticSplineError("Missing Hook target bone(s): " + ", ".join(missing))
    result = []
    for point_index, (modifier, bone_name) in enumerate(zip(modifiers, bones)):
        modifier.object = armature
        modifier.subtarget = bone_name
        modifier.matrix_inverse = helpers["Matrix"].Identity(4)
        modifier.vertex_indices_set([point_index])
        result.append(
            SplineHookBinding(
                point_index=point_index,
                modifier_name=modifier.name,
                bone_name=bone_name,
            )
        )
    bpy.context.view_layer.update()
    return tuple(result)


def ensure_spline_chain_artifacts(
    armature,
    component,
    stage,
    *,
    art_frame_bone="",
) -> SplineChainArtifacts:
    """Build a 3D Spline mechanism and a flat artwork presentation chain.

    ``art_frame_bone`` may reference a frame exported by an upstream stage.
    Without one, this stage owns a frame generated from ``art_plane_normal``.
    The hidden Spline IK remains fully spatial; only its joints are projected
    before presentation transforms are copied to the artwork source bones.
    """

    if armature is None or getattr(armature, "type", "") != "ARMATURE":
        raise SemanticSplineError("Spline stages require an Armature.")
    component_uuid = _component_uuid(component)
    stage_uuid = _stage_uuid(stage)
    source_names = _source_names(component, stage)
    if len(source_names) < 2:
        raise SemanticSplineError("A Spline chain requires at least two source bones.")
    missing = [name for name in source_names if name not in armature.data.bones]
    if missing:
        raise SemanticSplineError("Missing source bone(s): " + ", ".join(missing))
    for parent_name, child_name in zip(source_names, source_names[1:]):
        child = armature.data.bones[child_name]
        if child.parent is None or child.parent.name != parent_name:
            raise SemanticSplineError(
                "Spline source bones must form one ordered parent chain: "
                f"{parent_name} -> {child_name}."
            )
    control_count = max(int(getattr(stage, "spline_control_count", 3)), 2)
    plan = semantic_spline_name_plan(
        component,
        stage,
        source_count=len(source_names),
        control_count=control_count,
    )
    helpers = _runtime_helpers()
    Vector = helpers["Vector"]
    rest_bones = tuple(armature.data.bones[name] for name in source_names)
    joint_points = [bone.head_local.copy() for bone in rest_bones]
    joint_points.append(rest_bones[-1].tail_local.copy())
    curve_points = _polyline_samples(joint_points, control_count, Vector)

    mechanism_roles = tuple(
        semantic_stage_role(stage_uuid, f"spline_mechanism:{index}")
        for index in range(len(source_names))
    )
    control_roles = tuple(
        semantic_stage_role(stage_uuid, f"spline_control:{index}")
        for index in range(control_count)
    )
    art_frame_role = semantic_stage_role(stage_uuid, "art_frame")
    projection_roles = tuple(
        semantic_stage_role(stage_uuid, f"projected_joint:{index}")
        for index in range(len(source_names) + 1)
    )
    presentation_roles = tuple(
        semantic_stage_role(stage_uuid, f"presentation_bone:{index}")
        for index in range(len(source_names))
    )
    _reconcile_owned_bone_renames(
        armature,
        component,
        (
            *mechanism_roles,
            *control_roles,
            art_frame_role,
            *projection_roles,
            *presentation_roles,
        ),
        helpers,
    )
    existing_mechanism = tuple(
        _owned_bone_name(armature, component, role, helpers)
        for role in mechanism_roles
    )
    existing_controls = tuple(
        _owned_bone_name(armature, component, role, helpers)
        for role in control_roles
    )
    existing_art_frame = _owned_bone_name(
        armature, component, art_frame_role, helpers
    )
    existing_projected = tuple(
        _owned_bone_name(armature, component, role, helpers)
        for role in projection_roles
    )
    existing_presentation = tuple(
        _owned_bone_name(armature, component, role, helpers)
        for role in presentation_roles
    )

    requested_art_frame = str(
        getattr(art_frame_bone, "name", art_frame_bone) or ""
    )
    if requested_art_frame and requested_art_frame not in armature.data.bones:
        raise SemanticSplineError(
            f"Spline art frame bone not found: {requested_art_frame}"
        )
    owns_art_frame = not bool(requested_art_frame)

    helpers["switch_to_edit_mode"](armature)
    try:
        source_edit = tuple(armature.data.edit_bones[name] for name in source_names)
        source_parent = source_edit[0].parent
        total_length = sum(float(bone.length) for bone in source_edit)
        helper_length = max(total_length * 0.02, 0.02)

        if requested_art_frame:
            art = armature.data.edit_bones.get(requested_art_frame)
            if art is None:
                raise SemanticSplineError(
                    f"Spline art frame bone not found: {requested_art_frame}"
                )
        else:
            art = _ensure_edit_bone(
                armature,
                component,
                role=art_frame_role,
                default_name=plan.art_frame,
                existing_name=existing_art_frame,
                helpers=helpers,
            )
            normal = Vector(
                tuple(getattr(stage, "art_plane_normal", (0.0, 1.0, 0.0)))
            )
            if normal.length < 1.0e-8:
                normal = Vector((0.0, 1.0, 0.0))
            direction = source_edit[-1].tail - source_edit[0].head
            art_matrix = _frame_matrix(
                source_edit[0].head.copy(),
                direction,
                normal,
                Matrix=helpers["Matrix"],
                Vector=Vector,
            )
            art.parent = source_parent
            art.use_connect = False
            art.use_deform = False
            helpers["set_edit_bone_matrix"](art, art_matrix, helper_length)
        art_name = art.name
        art_matrix = art.matrix.copy()

        mechanism = []
        for index, (source, role, name, existing_name) in enumerate(
            zip(
                source_edit,
                mechanism_roles,
                plan.mechanism_bones,
                existing_mechanism,
            )
        ):
            bone = _ensure_edit_bone(
                armature,
                component,
                role=role,
                default_name=name,
                existing_name=existing_name,
                helpers=helpers,
            )
            bone.parent = mechanism[index - 1] if index else source_parent
            bone.use_connect = bool(index and source.use_connect)
            bone.use_deform = False
            bone.matrix = source.matrix.copy()
            bone.length = max(float(source.length), 1.0e-4)
            mechanism.append(bone)

        control_length = max(total_length * 0.05, 0.05)
        controls = []
        for index, (point, role, name, existing_name) in enumerate(
            zip(curve_points, control_roles, plan.control_bones, existing_controls)
        ):
            bone = _ensure_edit_bone(
                armature,
                component,
                role=role,
                default_name=name,
                existing_name=existing_name,
                helpers=helpers,
            )
            source_index = min(
                int(index * len(source_edit) / max(control_count - 1, 1)),
                len(source_edit) - 1,
            )
            matrix = source_edit[source_index].matrix.copy()
            matrix.translation = point
            bone.parent = source_parent
            bone.use_connect = False
            bone.use_deform = False
            helpers["set_edit_bone_matrix"](bone, matrix, control_length)
            controls.append(bone)

        joint_points = [bone.head.copy() for bone in mechanism]
        joint_points.append(mechanism[-1].tail.copy())
        projected_points = tuple(
            _project_to_frame(point, art_matrix, Vector)
            for point in joint_points
        )
        projected = []
        for point, role, name, existing_name in zip(
            projected_points,
            projection_roles,
            plan.projected_joints,
            existing_projected,
        ):
            bone = _ensure_edit_bone(
                armature,
                component,
                role=role,
                default_name=name,
                existing_name=existing_name,
                helpers=helpers,
            )
            matrix = art_matrix.copy()
            matrix.translation = point
            bone.parent = source_parent
            bone.use_connect = False
            bone.use_deform = False
            helpers["set_edit_bone_matrix"](bone, matrix, helper_length)
            projected.append(bone)

        presentation = []
        art_normal = art_matrix.to_3x3().col[2].copy()
        for index, (role, name, existing_name) in enumerate(
            zip(
                presentation_roles,
                plan.presentation_bones,
                existing_presentation,
            )
        ):
            bone = _ensure_edit_bone(
                armature,
                component,
                role=role,
                default_name=name,
                existing_name=existing_name,
                helpers=helpers,
            )
            segment = projected_points[index + 1] - projected_points[index]
            direction = (
                segment
                if segment.length >= 1.0e-8
                else art_matrix.to_3x3().col[1]
            )
            matrix = _frame_matrix(
                projected_points[index],
                direction,
                art_normal,
                Matrix=helpers["Matrix"],
                Vector=Vector,
            )
            bone.parent = source_parent
            bone.use_connect = False
            bone.use_deform = False
            helpers["set_edit_bone_matrix"](
                bone,
                matrix,
                max(segment.length, 1.0e-4),
            )
            presentation.append(bone)
        mechanism_names = tuple(bone.name for bone in mechanism)
        control_names = tuple(bone.name for bone in controls)
        projection_names = tuple(bone.name for bone in projected)
        presentation_names = tuple(bone.name for bone in presentation)
    finally:
        bpy = helpers["bpy"]
        if armature.mode == "EDIT":
            bpy.ops.object.mode_set(mode="POSE")

    for role, name in zip(mechanism_roles, mechanism_names):
        pose_bone = armature.pose.bones[name]
        helpers["tag_owned_bone"](armature, pose_bone.bone, component, role)
        _record_bone(component, role, name, helpers)
        pose_bone.bone.hide_select = True
        _assign_collection(
            armature,
            pose_bone,
            helpers["mechanism_collection"],
            helpers,
            visible=False,
        )

    if owns_art_frame:
        art_pose = armature.pose.bones[art_name]
        helpers["tag_owned_bone"](
            armature, art_pose.bone, component, art_frame_role
        )
        _record_bone(component, art_frame_role, art_name, helpers)
        art_pose.bone.hide_select = True
        _assign_collection(
            armature,
            art_pose,
            helpers["mechanism_collection"],
            helpers,
            visible=False,
        )
    for role, name in zip(projection_roles, projection_names):
        pose_bone = armature.pose.bones[name]
        helpers["tag_owned_bone"](armature, pose_bone.bone, component, role)
        _record_bone(component, role, name, helpers)
        pose_bone.bone.hide_select = True
        _assign_collection(
            armature,
            pose_bone,
            helpers["mechanism_collection"],
            helpers,
            visible=False,
        )
    for role, name in zip(presentation_roles, presentation_names):
        pose_bone = armature.pose.bones[name]
        helpers["tag_owned_bone"](armature, pose_bone.bone, component, role)
        _record_bone(component, role, name, helpers)
        pose_bone.bone.hide_select = True
        _assign_collection(
            armature,
            pose_bone,
            helpers["mechanism_collection"],
            helpers,
            visible=False,
        )

    root_pin = bool(getattr(stage, "root_pin", True))
    tip_pin = bool(getattr(stage, "tip_pin", False))
    pin_flags = tuple(
        (index == 0 and root_pin)
        or (index == control_count - 1 and tip_pin)
        for index in range(control_count)
    )
    for role, name, pinned in zip(control_roles, control_names, pin_flags):
        pose_bone = armature.pose.bones[name]
        helpers["tag_owned_bone"](armature, pose_bone.bone, component, role)
        _record_bone(component, role, name, helpers)
        pose_bone.bone.hide_select = False
        pose_bone.rotation_mode = "XYZ"
        pose_bone.lock_location = (pinned, pinned, pinned)
        pose_bone.lock_rotation = (True, True, True)
        pose_bone.lock_scale = (True, True, True)
        _assign_collection(
            armature,
            pose_bone,
            helpers["control_collection"],
            helpers,
            visible=True,
        )

    curve_role = semantic_stage_role(stage_uuid, "spline_curve")
    curve_object = _ensure_curve_object(
        armature,
        component,
        curve_role,
        plan,
        helpers,
    )
    _configure_curve(curve_object, curve_points)
    _remove_obsolete_hooks(
        curve_object,
        component,
        stage_uuid,
        plan.hook_modifiers,
        helpers,
    )
    hook_bindings = []
    for index, (modifier_name, bone_name, point, pinned) in enumerate(
        zip(plan.hook_modifiers, control_names, curve_points, pin_flags)
    ):
        hook_role = semantic_stage_role(stage_uuid, f"spline_hook:{index}")
        modifier = _ensure_hook_modifier(
            curve_object,
            armature,
            component,
            stage_uuid,
            point_index=index,
            modifier_name=modifier_name,
            bone_name=bone_name,
            point=point,
            helpers=helpers,
        )
        _record_modifier(component, hook_role, curve_object, modifier, helpers)
        hook_bindings.append(
            SplineHookBinding(index, modifier.name, bone_name, pinned)
        )
    curve_object["coa_rig_spline_hook_order"] = "\n".join(
        binding.modifier_name for binding in hook_bindings
    )

    owner = armature.pose.bones[mechanism_names[-1]]
    constraint_role = semantic_stage_role(stage_uuid, "spline_ik_constraint")
    constraint = helpers["managed_constraint"](
        owner,
        component,
        plan.spline_constraint,
        "SPLINE_IK",
        role=constraint_role,
    )
    constraint.target = curve_object
    constraint.chain_count = len(mechanism_names)
    constraint.use_curve_radius = False
    constraint.use_even_divisions = True
    constraint.use_chain_offset = False
    constraint.y_scale_mode = "FIT_CURVE"
    constraint.xz_scale_mode = "BONE_ORIGINAL"
    if hasattr(constraint, "use_original_scale"):
        constraint.use_original_scale = True
    _record_constraint(component, constraint_role, owner, constraint, helpers)

    constraint_stem = plan.spline_constraint.rsplit("_SplineIK", 1)[0]
    for index, projection_name in enumerate(projection_names):
        pose_bone = armature.pose.bones[projection_name]
        source_index = min(index, len(mechanism_names) - 1)
        copy_role = semantic_stage_role(stage_uuid, f"joint_copy:{index}")
        copy = helpers["managed_constraint"](
            pose_bone,
            component,
            f"{constraint_stem}_JointCopy_{index:02d}",
            "COPY_LOCATION",
            role=copy_role,
        )
        copy.target = armature
        copy.subtarget = mechanism_names[source_index]
        copy.head_tail = 1.0 if index == len(mechanism_names) else 0.0
        copy.owner_space = "WORLD"
        copy.target_space = "WORLD"
        copy.use_x = copy.use_y = copy.use_z = True
        copy.use_offset = False
        _record_constraint(component, copy_role, pose_bone, copy, helpers)

        limit_role = semantic_stage_role(
            stage_uuid, f"joint_plane_limit:{index}"
        )
        limit = helpers["managed_constraint"](
            pose_bone,
            component,
            f"{constraint_stem}_JointPlane_{index:02d}",
            "LIMIT_LOCATION",
            role=limit_role,
        )
        limit.owner_space = "CUSTOM"
        limit.space_object = armature
        limit.space_subtarget = art_name
        limit.use_min_x = limit.use_max_x = False
        limit.use_min_y = limit.use_max_y = False
        limit.use_min_z = limit.use_max_z = True
        limit.min_z = limit.max_z = 0.0
        limit.use_transform_limit = True
        _record_constraint(component, limit_role, pose_bone, limit, helpers)

    for index, presentation_name in enumerate(presentation_names):
        pose_bone = armature.pose.bones[presentation_name]
        copy_role = semantic_stage_role(
            stage_uuid, f"presentation_copy:{index}"
        )
        copy = helpers["managed_constraint"](
            pose_bone,
            component,
            f"{constraint_stem}_PresentCopy_{index:02d}",
            "COPY_LOCATION",
            role=copy_role,
        )
        copy.target = armature
        copy.subtarget = projection_names[index]
        copy.owner_space = "WORLD"
        copy.target_space = "WORLD"
        copy.use_offset = False
        _record_constraint(component, copy_role, pose_bone, copy, helpers)

        stretch_role = semantic_stage_role(
            stage_uuid, f"presentation_stretch:{index}"
        )
        stretch = helpers["managed_constraint"](
            pose_bone,
            component,
            f"{constraint_stem}_PresentStretch_{index:02d}",
            "STRETCH_TO",
            role=stretch_role,
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
        if owner_uuid not in {None, "", component_uuid}:
            raise helpers["conflict"](
                f"Source bone '{source_name}' belongs to another pose component."
            )
        source_role = semantic_stage_role(stage_uuid, f"source_bone:{index}")
        _record_bone(
            component,
            source_role,
            source_name,
            helpers,
            owned=False,
        )
        copy_role = semantic_stage_role(
            stage_uuid, f"source_presentation:{index}"
        )
        copy = helpers["managed_constraint"](
            source_pose,
            component,
            f"{constraint_stem}_SourcePresent_{index:02d}",
            "COPY_TRANSFORMS",
            role=copy_role,
        )
        copy.target = armature
        copy.subtarget = presentation_name
        copy.owner_space = "WORLD"
        copy.target_space = "WORLD"
        copy.mix_mode = "REPLACE"
        copy.remove_target_shear = True
        _record_constraint(component, copy_role, source_pose, copy, helpers)

    movable = [
        name for name, pinned in zip(control_names, pin_flags) if not pinned
    ]
    primary = movable[-1] if movable else control_names[-1]
    stage.control_bone = primary
    stage.mechanism_frame_bone = mechanism_names[0]
    stage.art_frame_bone = art_name
    stage.curve_object = curve_object
    bpy.context.view_layer.update()
    return SplineChainArtifacts(
        primary_control_bone=primary,
        control_bones=control_names,
        mechanism_bones=mechanism_names,
        curve_object=curve_object.name,
        source_bones=source_names,
        hook_bindings=tuple(hook_bindings),
        projected_joint_bones=projection_names,
        presentation_bones=presentation_names,
        art_frame_bone=art_name,
        art_frame_owned=owns_art_frame,
    )


__all__ = [
    "SemanticSplineError",
    "SplineArtifactNamePlan",
    "SplineChainArtifacts",
    "SplineHookBinding",
    "ensure_spline_chain_artifacts",
    "retarget_spline_hooks",
    "semantic_spline_name_plan",
]
