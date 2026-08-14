"""FK layer and pop-free FK/IK Pose Match for semantic chain stages."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import math
import re

import bpy

from ..semantic_transition import discrete_state_key
from .semantic_artifacts import (
    SemanticArtifactError,
    _assign_collection,
    _component_uuid,
    _ensure_edit_bone,
    _lazy_helpers,
    _owned_bone_names,
    _reconcile_owned_bone_renames,
    _record_bone,
    _record_constraint,
    _source_names,
    _stage_uuid,
    semantic_stage_role,
)
from .semantic_contact import (
    _iter_action_fcurves_for_armature,
    _remove_action_fcurve,
    _restore_action_curves,
    _snapshot_action_curves,
    contact_uses_ik_override,
)


class SemanticFKError(RuntimeError):
    pass


@dataclass(frozen=True)
class SemanticFKArtifacts:
    fk_control_bones: tuple[str, ...]
    mechanism_bones: tuple[str, ...]
    ik_control_bone: str
    pole_bone: str
    bend_center_bone: str
    orientation_bone: str
    ik_constraint_owner: str
    ik_constraint_name: str
    fk_constraint_names: tuple[str, ...]
    end_rotation_constraint_name: str
    contact_end_rotation_owner: str
    contact_end_rotation_constraint_name: str


@dataclass(frozen=True)
class StandaloneFKArtifacts:
    """Independent FK DAG node without an accompanying IK solver."""

    fk_control_bones: tuple[str, ...]
    output_bone: str
    source_bones: tuple[str, ...]
    source_constraint_names: tuple[str, ...]
    output_constraint_name: str

    @property
    def primary_control_bone(self) -> str:
        return self.fk_control_bones[-1] if self.fk_control_bones else ""

    @property
    def mechanism_frame_bone(self) -> str:
        return self.fk_control_bones[0] if self.fk_control_bones else ""


def _short(value):
    return re.sub(r"[^0-9A-Za-z]", "", str(value or ""))[:8]


def _stage_stem(component, stage):
    semantic = str(stage.semantic_id or stage.label or component.semantic_id or "semantic")
    slug = re.sub(r"[^0-9A-Za-z_]+", "_", semantic.strip()).strip("_")
    return f"{(slug or 'semantic')[:32]}_{_short(stage.stage_uuid)}"


def _constraint_for_role(component, armature, role, *, expected_type):
    records = tuple(
        artifact
        for artifact in component.artifacts
        if artifact.owned
        and artifact.role == role
        and artifact.data_type == "CONSTRAINT"
    )
    if len(records) != 1:
        raise SemanticFKError(f"Expected one owned Constraint for role '{role}'.")
    record = records[0]
    pose_bone = armature.pose.bones.get(record.bone_name)
    constraint = (
        pose_bone.constraints.get(record.constraint_name)
        if pose_bone is not None
        else None
    )
    if constraint is None or constraint.type != expected_type:
        raise SemanticFKError(f"Owned Constraint for role '{role}' is missing.")
    return pose_bone, constraint


def _migrate_owned_constraint_owner(
    component,
    armature,
    role,
    destination_bone,
    *,
    expected_type,
):
    """Remove a proven legacy constraint before recreating it on a new owner."""

    records = tuple(
        (index, artifact)
        for index, artifact in enumerate(component.artifacts)
        if artifact.owned
        and artifact.role == role
        and artifact.data_type == "CONSTRAINT"
    )
    if not records:
        return
    if len(records) != 1:
        raise SemanticFKError(f"Expected one owned Constraint for role '{role}'.")
    index, record = records[0]
    if record.bone_name == destination_bone.name:
        return
    old_owner = armature.pose.bones.get(record.bone_name)
    old_constraint = (
        old_owner.constraints.get(record.constraint_name)
        if old_owner is not None
        else None
    )
    if old_constraint is None or old_constraint.type != expected_type:
        raise SemanticFKError(
            f"Cannot migrate missing owned Constraint for role '{role}'."
        )
    old_owner.constraints.remove(old_constraint)
    component.artifacts.remove(index)


def _move_before(pose_bone, first, second):
    constraints = pose_bone.constraints
    first_index = tuple(constraints).index(first)
    second_index = tuple(constraints).index(second)
    if first_index > second_index and hasattr(constraints, "move"):
        constraints.move(first_index, second_index)


def ensure_standalone_fk_solver_layer(
    armature,
    component,
    stage,
) -> StandaloneFKArtifacts:
    """Build an FK-only solver node that owns its source-chain output.

    The generated controls form an independent hierarchy matching the source
    rest chain.  Source bones read that hierarchy through owned world-space
    Copy Transforms constraints, so downstream semantic stages can consume the
    exported tip control without introducing an IK stage or a dependency
    cycle.
    """

    if armature is None or getattr(armature, "type", "") != "ARMATURE":
        raise SemanticFKError("Standalone FK requires an Armature.")
    stage_uuid = _stage_uuid(stage)
    source_names = _source_names(component, stage)
    if len(source_names) < 2:
        raise SemanticFKError("Standalone FK requires at least two source bones.")
    missing = [name for name in source_names if name not in armature.data.bones]
    if missing:
        raise SemanticFKError("Missing FK source bone(s): " + ", ".join(missing))
    for parent_name, child_name in zip(source_names, source_names[1:]):
        child = armature.data.bones[child_name]
        if child.parent is None or child.parent.name != parent_name:
            raise SemanticFKError(
                "Standalone FK source bones must form one ordered parent chain: "
                f"{parent_name} -> {child_name}."
            )

    helpers = _lazy_helpers()
    control_roles = tuple(
        semantic_stage_role(stage_uuid, f"fk_control:{index}")
        for index in range(len(source_names))
    )
    output_role = semantic_stage_role(stage_uuid, "fk_output")
    _reconcile_owned_bone_renames(
        armature,
        component,
        control_roles + (output_role,),
        helpers,
    )
    existing = _owned_bone_names(
        armature,
        component,
        control_roles + (output_role,),
        helpers,
    )
    stem = _stage_stem(component, stage)

    helpers["switch_to_edit_mode"](armature)
    try:
        sources = tuple(armature.data.edit_bones[name] for name in source_names)
        source_parent = sources[0].parent
        controls = []
        for index, (source, role) in enumerate(zip(sources, control_roles)):
            control = _ensure_edit_bone(
                armature,
                component,
                role=role,
                default_name=f"CTRL_{stem}_FK_{index:02d}",
                existing_name=existing[role],
                helpers=helpers,
            )
            control.parent = controls[index - 1] if index else source_parent
            control.use_connect = bool(index and source.use_connect)
            control.use_deform = False
            control.matrix = source.matrix.copy()
            control.length = max(float(source.length), 1.0e-4)
            controls.append(control)
        output = _ensure_edit_bone(
            armature,
            component,
            role=output_role,
            default_name=f"MCH_{stem}_FK_OUTPUT",
            existing_name=existing[output_role],
            helpers=helpers,
        )
        output.parent = source_parent
        output.use_connect = False
        output.use_deform = False
        output.matrix = sources[-1].matrix.copy()
        output.length = max(float(sources[-1].length), 1.0e-4)
        control_names = tuple(control.name for control in controls)
        output_name = output.name
    finally:
        if armature.mode == "EDIT":
            bpy.ops.object.mode_set(mode="POSE")

    for role, name in zip(control_roles, control_names):
        pose_bone = armature.pose.bones[name]
        helpers["tag_owned_bone"](
            armature,
            pose_bone.bone,
            component,
            role,
        )
        _record_bone(component, role, name, helpers)
        pose_bone.bone.hide_select = False
        pose_bone.rotation_mode = "XYZ"
        pose_bone.lock_location = (True, True, True)
        pose_bone.lock_rotation = (False, False, False)
        pose_bone.lock_scale = (True, True, True)
        _assign_collection(
            armature,
            pose_bone,
            helpers["control_collection"],
            helpers,
            visible=True,
        )
    output_pose = armature.pose.bones[output_name]
    helpers["tag_owned_bone"](
        armature,
        output_pose.bone,
        component,
        output_role,
    )
    _record_bone(component, output_role, output_name, helpers)
    _assign_collection(
        armature,
        output_pose,
        helpers["mechanism_collection"],
        helpers,
        visible=False,
    )

    short_component = _short(_component_uuid(component))
    short_stage = _short(stage_uuid)
    output_follow_role = semantic_stage_role(stage_uuid, "fk_output_follow")
    output_follow = helpers["managed_constraint"](
        output_pose,
        component,
        f"COA_SEM_{short_component}_{short_stage}_FK_Output",
        "COPY_TRANSFORMS",
        role=output_follow_role,
    )
    output_follow.target = armature
    output_follow.subtarget = control_names[-1]
    output_follow.owner_space = "WORLD"
    output_follow.target_space = "WORLD"
    output_follow.mix_mode = "REPLACE"
    output_follow.remove_target_shear = True
    _record_constraint(
        component,
        output_follow_role,
        output_pose,
        output_follow,
        helpers,
    )
    constraint_names = []
    for index, (source_name, control_name) in enumerate(
        zip(source_names, control_names)
    ):
        source = armature.pose.bones[source_name]
        owner_uuid = source.bone.get("coa_rig_component_uuid")
        if owner_uuid not in {None, "", _component_uuid(component)}:
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
        follow_role = semantic_stage_role(
            stage_uuid,
            f"source_presentation:{index}",
        )
        follow = helpers["managed_constraint"](
            source,
            component,
            f"COA_SEM_{short_component}_{short_stage}_FK_Source_{index:02d}",
            "COPY_TRANSFORMS",
            role=follow_role,
        )
        follow.target = armature
        follow.subtarget = (
            output_name if index == len(source_names) - 1 else control_name
        )
        follow.owner_space = "WORLD"
        follow.target_space = "WORLD"
        follow.mix_mode = "REPLACE"
        follow.remove_target_shear = True
        _record_constraint(component, follow_role, source, follow, helpers)
        constraint_names.append(follow.name)

    stage.control_bone = control_names[-1]
    stage.mechanism_frame_bone = control_names[0]
    stage.display_frame_bone = ""
    stage.art_frame_bone = ""
    bpy.context.view_layer.update()
    return StandaloneFKArtifacts(
        fk_control_bones=control_names,
        output_bone=output_name,
        source_bones=source_names,
        source_constraint_names=tuple(constraint_names),
        output_constraint_name=output_follow.name,
    )


def ensure_fk_solver_layer(
    armature,
    component,
    stage,
    ik_artifacts,
) -> SemanticFKArtifacts:
    """Reconcile FK controls that feed the existing projected IK mechanism."""

    if armature is None or getattr(armature, "type", "") != "ARMATURE":
        raise SemanticFKError("FK/IK switching requires an Armature.")
    stage_uuid = _stage_uuid(stage)
    source_names = _source_names(component, stage)
    mechanism_names = tuple(ik_artifacts.mechanism_bones)
    if len(source_names) < 2 or len(source_names) != len(mechanism_names):
        raise SemanticFKError("FK controls require the complete projected IK chain.")

    helpers = _lazy_helpers()
    fk_roles = tuple(
        semantic_stage_role(stage_uuid, f"fk_control:{index}")
        for index in range(len(source_names))
    )
    orientation_role = semantic_stage_role(stage_uuid, "ik_orientation")
    _reconcile_owned_bone_renames(
        armature,
        component,
        fk_roles + (orientation_role,),
        helpers,
    )
    existing = _owned_bone_names(
        armature,
        component,
        fk_roles + (orientation_role,),
        helpers,
    )
    stem = _stage_stem(component, stage)

    helpers["switch_to_edit_mode"](armature)
    try:
        sources = tuple(armature.data.edit_bones[name] for name in source_names)
        source_parent = sources[0].parent
        fk_controls = []
        for index, (source, role) in enumerate(zip(sources, fk_roles)):
            bone = _ensure_edit_bone(
                armature,
                component,
                role=role,
                default_name=f"CTRL_{stem}_FK_{index:02d}",
                existing_name=existing[role],
                helpers=helpers,
            )
            bone.parent = fk_controls[index - 1] if index else source_parent
            bone.use_connect = bool(index and source.use_connect)
            bone.use_deform = False
            bone.matrix = source.matrix.copy()
            bone.length = max(float(source.length), 1.0e-4)
            fk_controls.append(bone)

        ik_control = armature.data.edit_bones.get(ik_artifacts.frames.control_bone)
        if ik_control is None:
            raise SemanticFKError("The projected IK control is missing.")
        orientation = _ensure_edit_bone(
            armature,
            component,
            role=orientation_role,
            default_name=f"MCH_{stem}_IK_ORIENT",
            existing_name=existing[orientation_role],
            helpers=helpers,
        )
        orientation.parent = ik_control
        orientation.use_connect = False
        orientation.use_deform = False
        orientation.matrix = sources[-1].matrix.copy()
        orientation.length = max(float(sources[-1].length), 1.0e-4)
        fk_names = tuple(bone.name for bone in fk_controls)
        orientation_name = orientation.name
    finally:
        if armature.mode == "EDIT":
            bpy.ops.object.mode_set(mode="POSE")

    for role, name in zip(fk_roles, fk_names):
        pose_bone = armature.pose.bones[name]
        helpers["tag_owned_bone"](armature, pose_bone.bone, component, role)
        _record_bone(component, role, name, helpers)
        pose_bone.bone.hide_select = False
        pose_bone.rotation_mode = "XYZ"
        pose_bone.lock_location = (True, True, True)
        pose_bone.lock_rotation = (False, False, False)
        pose_bone.lock_scale = (True, True, True)
        _assign_collection(
            armature,
            pose_bone,
            helpers["control_collection"],
            helpers,
            visible=True,
        )
    orientation_pose = armature.pose.bones[orientation_name]
    helpers["tag_owned_bone"](
        armature,
        orientation_pose.bone,
        component,
        orientation_role,
    )
    _record_bone(component, orientation_role, orientation_name, helpers)
    orientation_pose.bone.hide_select = True
    _assign_collection(
        armature,
        orientation_pose,
        helpers["mechanism_collection"],
        helpers,
        visible=False,
    )
    short_component = _short(_component_uuid(component))
    short_stage = _short(stage_uuid)
    constraint_stem = f"COA_SEM_{short_component}_{short_stage}"
    follow_constraints = []
    for index, (mechanism_name, fk_name) in enumerate(
        zip(mechanism_names, fk_names)
    ):
        mechanism = armature.pose.bones[mechanism_name]
        role = semantic_stage_role(stage_uuid, f"fk_follow:{index}")
        follow = helpers["managed_constraint"](
            mechanism,
            component,
            f"{constraint_stem}_FK_{index:02d}",
            "COPY_TRANSFORMS",
            role=role,
        )
        follow.target = armature
        follow.subtarget = fk_name
        follow.owner_space = "WORLD"
        follow.target_space = "WORLD"
        follow.mix_mode = "REPLACE"
        follow.remove_target_shear = True
        _record_constraint(component, role, mechanism, follow, helpers)
        follow_constraints.append(follow)

    ik_owner, ik = _constraint_for_role(
        component,
        armature,
        semantic_stage_role(stage_uuid, "ik_constraint"),
        expected_type="IK",
    )
    _move_before(
        ik_owner,
        follow_constraints[mechanism_names.index(ik_owner.name)],
        ik,
    )

    final_mechanism = armature.pose.bones[mechanism_names[-1]]
    end_rotation_role = semantic_stage_role(stage_uuid, "ik_end_rotation")
    end_rotation = helpers["managed_constraint"](
        final_mechanism,
        component,
        f"{constraint_stem}_IK_EndRotation",
        "COPY_ROTATION",
        role=end_rotation_role,
    )
    end_rotation.target = armature
    end_rotation.subtarget = orientation_name
    end_rotation.owner_space = "WORLD"
    end_rotation.target_space = "WORLD"
    end_rotation.mix_mode = "REPLACE"
    _record_constraint(
        component,
        end_rotation_role,
        final_mechanism,
        end_rotation,
        helpers,
    )
    _move_before(final_mechanism, follow_constraints[-1], end_rotation)

    # Position-only Contact still needs animator-controlled wrist/end rotation
    # after 3D mechanism motion has been projected onto the 2D art plane.  A
    # mechanism-space override is mostly discarded by the projection chain,
    # so apply only the art-plane-normal component on the final presentation
    # bone, after its Copy Location / Stretch To constraints.  This preserves
    # the plane normal while allowing the visible wrist to rotate about its
    # fixed head.
    final_presentation = armature.pose.bones[ik_artifacts.presentation_bones[-1]]
    contact_end_role = semantic_stage_role(
        stage_uuid,
        "fk_contact_end_rotation",
    )
    _migrate_owned_constraint_owner(
        component,
        armature,
        contact_end_role,
        final_presentation,
        expected_type="COPY_ROTATION",
    )
    contact_end_rotation = helpers["managed_constraint"](
        final_presentation,
        component,
        f"{constraint_stem}_FK_ContactEndRotation",
        "COPY_ROTATION",
        role=contact_end_role,
    )
    contact_end_rotation.target = armature
    contact_end_rotation.subtarget = fk_names[-1]
    contact_end_rotation.owner_space = "CUSTOM"
    contact_end_rotation.target_space = "CUSTOM"
    contact_end_rotation.space_object = armature
    contact_end_rotation.space_subtarget = ik_artifacts.frames.art_frame_bone
    contact_end_rotation.use_x = False
    contact_end_rotation.use_y = False
    contact_end_rotation.use_z = True
    contact_end_rotation.mix_mode = "REPLACE"
    _record_constraint(
        component,
        contact_end_role,
        final_presentation,
        contact_end_rotation,
        helpers,
    )

    mode = str(getattr(stage, "rig_mode", "IK") or "IK")
    fk_value = 1.0 if mode == "FK" else 0.0
    for constraint in follow_constraints:
        constraint.influence = fk_value
    ik.influence = 1.0 - fk_value
    end_rotation.influence = 1.0 - fk_value
    contact_end_rotation.influence = 0.0
    artifacts = SemanticFKArtifacts(
        fk_control_bones=fk_names,
        mechanism_bones=mechanism_names,
        ik_control_bone=ik_artifacts.frames.control_bone,
        pole_bone=ik_artifacts.pole_bone,
        bend_center_bone=ik_artifacts.bend_center_bone,
        orientation_bone=orientation_name,
        ik_constraint_owner=ik_owner.name,
        ik_constraint_name=ik.name,
        fk_constraint_names=tuple(item.name for item in follow_constraints),
        end_rotation_constraint_name=end_rotation.name,
        contact_end_rotation_owner=final_presentation.name,
        contact_end_rotation_constraint_name=contact_end_rotation.name,
    )
    ensure_fk_solver_drivers(armature, component, stage, artifacts=artifacts)
    bpy.context.view_layer.update()
    return artifacts


def resolve_fk_solver_layer(armature, component, stage) -> SemanticFKArtifacts:
    """Resolve a compiled FK/IK layer exclusively through owned artifacts."""

    stage_uuid = _stage_uuid(stage)
    source_names = _source_names(component, stage)
    helpers = _lazy_helpers()

    def owned_bone(detail):
        role = semantic_stage_role(stage_uuid, detail)
        bone = helpers["find_component_bone"](
            armature,
            _component_uuid(component),
            role,
        )
        if bone is None:
            raise SemanticFKError(f"Compiled FK/IK bone '{detail}' is missing.")
        return bone.name

    fk_names = tuple(owned_bone(f"fk_control:{index}") for index in range(len(source_names)))
    mechanism_names = tuple(
        owned_bone(f"mechanism_bone:{index}") for index in range(len(source_names))
    )
    ik_owner, ik = _constraint_for_role(
        component,
        armature,
        semantic_stage_role(stage_uuid, "ik_constraint"),
        expected_type="IK",
    )
    follows = tuple(
        _constraint_for_role(
            component,
            armature,
            semantic_stage_role(stage_uuid, f"fk_follow:{index}"),
            expected_type="COPY_TRANSFORMS",
        )[1]
        for index in range(len(source_names))
    )
    _end_owner, end_rotation = _constraint_for_role(
        component,
        armature,
        semantic_stage_role(stage_uuid, "ik_end_rotation"),
        expected_type="COPY_ROTATION",
    )
    contact_end_owner, contact_end_rotation = _constraint_for_role(
        component,
        armature,
        semantic_stage_role(stage_uuid, "fk_contact_end_rotation"),
        expected_type="COPY_ROTATION",
    )
    pole = ""
    bend_center = ""
    if bool(getattr(stage, "use_pole", False)):
        pole = owned_bone("pole_control")
        bend_center = owned_bone("pole_bend_center")
    return SemanticFKArtifacts(
        fk_control_bones=fk_names,
        mechanism_bones=mechanism_names,
        ik_control_bone=owned_bone("control_bone"),
        pole_bone=pole,
        bend_center_bone=bend_center,
        orientation_bone=owned_bone("ik_orientation"),
        ik_constraint_owner=ik_owner.name,
        ik_constraint_name=ik.name,
        fk_constraint_names=tuple(item.name for item in follows),
        end_rotation_constraint_name=end_rotation.name,
        contact_end_rotation_owner=contact_end_owner.name,
        contact_end_rotation_constraint_name=contact_end_rotation.name,
    )


def _layer_constraints(armature, artifacts):
    follows = tuple(
        armature.pose.bones[mechanism_name].constraints[name]
        for mechanism_name, name in zip(
            artifacts.mechanism_bones,
            artifacts.fk_constraint_names,
        )
    )
    ik = armature.pose.bones[artifacts.ik_constraint_owner].constraints[
        artifacts.ik_constraint_name
    ]
    end = armature.pose.bones[artifacts.mechanism_bones[-1]].constraints[
        artifacts.end_rotation_constraint_name
    ]
    contact_end = armature.pose.bones[artifacts.contact_end_rotation_owner].constraints[
        artifacts.contact_end_rotation_constraint_name
    ]
    return follows, ik, end, contact_end


def _solver_contact_stage(component, stage):
    stage_uuid = str(stage.stage_uuid or "")
    matches = []
    for candidate in component.semantic_stages:
        if (
            not bool(getattr(candidate, "enabled", True))
            or candidate.stage_type != "CONTACT_PIN"
            or not contact_uses_ik_override(candidate)
        ):
            continue
        dependencies = {
            value.strip()
            for value in str(getattr(candidate, "depends_on", "") or "").split(",")
            if value.strip()
        }
        provider_uuid = str(
            getattr(candidate, "pin_driven_stage_uuid", "") or ""
        )
        if provider_uuid == stage_uuid or (
            not provider_uuid and dependencies == {stage_uuid}
        ):
            matches.append(candidate)
    if len(matches) > 1:
        raise SemanticFKError(
            "A CHAIN_IK stage supports one automatic Contact / Pin stage."
        )
    return matches[0] if matches else None


def _has_solver_action_curve(armature, constraint):
    action = armature.animation_data.action if armature.animation_data else None
    path = constraint.path_from_id("influence")
    return any(
        fcurve.data_path == path
        for fcurve in _iter_action_fcurves_for_armature(armature, action)
    )


def _configure_solver_driver(
    armature,
    stage,
    constraint,
    expression,
    *,
    contact_stage=None,
):
    """Install one owned solver driver from public Mode and Contact weight."""

    # Blender treats an Action curve and a driver on the same RNA property as
    # competing animation owners.  Legacy curves are removed only by the
    # successful-compile commit step below; until then leave this constraint
    # untouched so rollback cannot lose animator keys.
    if _has_solver_action_curve(armature, constraint):
        return None
    fcurve = constraint.driver_add("influence")
    fcurve.mute = False
    driver = fcurve.driver
    driver.type = "SCRIPTED"
    while driver.variables:
        driver.variables.remove(driver.variables[0])
    mode_variable = driver.variables.new()
    mode_variable.name = f"md_{_short(stage.stage_uuid)}"
    mode_variable.type = "SINGLE_PROP"
    mode_target = mode_variable.targets[0]
    mode_target.id = armature
    # Blender exposes an EnumProperty to driver evaluation through its stable
    # numeric item value (FK=0, IK=1), while animation remains on the single
    # public keyframeable Mode property.
    mode_target.data_path = stage.path_from_id("rig_mode")
    if contact_stage is not None:
        contact_pose = armature.pose.bones.get(contact_stage.pin_driven_bone)
        if contact_pose is None or not contact_stage.pin_property:
            raise SemanticFKError("Compiled Contact weight source is missing.")
        contact_variable = driver.variables.new()
        contact_variable.name = f"ct_{_short(contact_stage.stage_uuid)}"
        contact_variable.type = "SINGLE_PROP"
        contact_target = contact_variable.targets[0]
        contact_target.id = armature
        contact_target.data_path = contact_pose.path_from_id(
            f"[{json.dumps(str(contact_stage.pin_property))}]"
        )
    driver.expression = expression
    return fcurve


def ensure_fk_solver_drivers(
    armature,
    component,
    stage,
    *,
    artifacts=None,
    contact_stage=None,
):
    """Compose public FK/IK Mode with one private Contact compensation.

    Constraint influence Action curves are migrated away because two
    independent animator states cannot safely author the same property.  The
    public enum and private smooth Contact weight instead remain the sole
    animation sources for a deterministic driver composition.
    """

    if artifacts is None:
        artifacts = resolve_fk_solver_layer(armature, component, stage)
    follows, ik, end_rotation, contact_end_rotation = _layer_constraints(
        armature,
        artifacts,
    )
    if contact_stage is None:
        candidate = _solver_contact_stage(component, stage)
        if (
            candidate is not None
            and candidate.pin_property
            and candidate.pin_driven_bone in armature.pose.bones
        ):
            contact_stage = candidate

    mode_name = f"md_{_short(stage.stage_uuid)}"
    contact_name = (
        f"ct_{_short(contact_stage.stage_uuid)}"
        if contact_stage is not None
        else ""
    )
    mode_value = f"min(max({mode_name},0.0),1.0)"
    contact_value = (
        f"min(max({contact_name},0.0),1.0)" if contact_name else "0.0"
    )
    position_value = (
        contact_value
        if contact_stage is not None and bool(contact_stage.pin_position)
        else "0.0"
    )
    orientation_value = (
        contact_value
        if contact_stage is not None and bool(contact_stage.pin_orientation)
        else "0.0"
    )
    for constraint in follows:
        _configure_solver_driver(
            armature,
            stage,
            constraint,
            f"(1.0-({mode_value}))*(1.0-({position_value}))",
            contact_stage=contact_stage,
        )
    _configure_solver_driver(
        armature,
        stage,
        ik,
        f"({mode_value})+(1.0-({mode_value}))*({position_value})",
        contact_stage=contact_stage,
    )
    _configure_solver_driver(
        armature,
        stage,
        end_rotation,
        f"({mode_value})+(1.0-({mode_value}))*({orientation_value})",
        contact_stage=contact_stage,
    )
    _configure_solver_driver(
        armature,
        stage,
        contact_end_rotation,
        (
            f"(1.0-({mode_value}))*({position_value})*"
            f"(1.0-({orientation_value}))"
        ),
        contact_stage=contact_stage,
    )
    return artifacts


def finalize_fk_solver_action_migration(armature, component, stages):
    """Drop legacy direct influence keys only after a successful compile.

    Driver reconciliation happens while the structural transaction is still
    open.  Deleting the old Action curves there would make a later compile
    failure lossy, because Blender's structural rollback owns drivers and
    constraints but not animator Action data.  Treat removal as a best-effort
    commit step instead: until this point the new drivers already have
    authority, and an individual stale curve can safely remain for a retry if
    Blender refuses to remove it.
    """

    action = armature.animation_data.action if armature.animation_data else None
    if action is None:
        return
    stage_constraints = []
    paths = set()
    for stage in stages:
        if stage.stage_type != "CHAIN_IK":
            continue
        try:
            artifacts = resolve_fk_solver_layer(armature, component, stage)
            follows, ik, end_rotation, contact_end_rotation = _layer_constraints(
                armature,
                artifacts,
            )
        except SemanticFKError:
            continue
        constraints = follows + (ik, end_rotation, contact_end_rotation)
        stage_constraints.append((stage, constraints))
        paths.update(
            constraint.path_from_id("influence")
            for constraint in constraints
        )
    for fcurve in tuple(_iter_action_fcurves_for_armature(armature, action)):
        if fcurve.data_path not in paths:
            continue
        try:
            _remove_action_fcurve(action, fcurve)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            # The driver is authoritative.  Keeping an ignored legacy curve is
            # safer than turning a successful build into a lossy rollback.
            continue
    remaining = {
        fcurve.data_path
        for fcurve in _iter_action_fcurves_for_armature(armature, action)
        if fcurve.data_path in paths
    }
    for stage, constraints in stage_constraints:
        if any(
            constraint.path_from_id("influence") in remaining
            for constraint in constraints
        ):
            continue
        # Deferred constraints can now acquire the same composed drivers as a
        # clean build.  Existing drivers are reconciled idempotently as well.
        ensure_fk_solver_drivers(armature, component, stage)


def _rotation_path(pose_bone):
    if pose_bone.rotation_mode == "QUATERNION":
        return "rotation_quaternion"
    if pose_bone.rotation_mode == "AXIS_ANGLE":
        return "rotation_axis_angle"
    return "rotation_euler"


def _key_pose(pose_bone, frame):
    paths = ("location", _rotation_path(pose_bone), "scale")
    for path in paths:
        if not pose_bone.keyframe_insert(
            data_path=path,
            frame=frame,
            group=pose_bone.name,
        ):
            raise SemanticFKError(
                f"Could not key Pose Match control '{pose_bone.name}'."
            )
    return tuple(pose_bone.path_from_id(path) for path in paths)


def _set_interpolation(armature, data_path, frame, interpolation):
    action = armature.animation_data.action if armature.animation_data else None
    for fcurve in _iter_action_fcurves_for_armature(armature, action):
        if fcurve.data_path != data_path:
            continue
        for point in fcurve.keyframe_points:
            if abs(float(point.co.x) - float(frame)) > 1.0e-5:
                continue
            point.interpolation = interpolation
            if interpolation == "BEZIER":
                point.handle_left_type = "AUTO_CLAMPED"
                point.handle_right_type = "AUTO_CLAMPED"
        fcurve.update()


def _mode_paths(stage):
    return (stage.path_from_id("rig_mode"),)


def _pose_transform_paths(pose_bones):
    return tuple(
        pose_bone.path_from_id(path)
        for pose_bone in pose_bones
        for path in (
            "location",
            _rotation_path(pose_bone),
            "scale",
        )
    )


@contextmanager
def _mute_action_paths(armature, paths):
    """Prevent existing transform keys from overwriting an atomic Pose Match."""

    action = armature.animation_data.action if armature.animation_data else None
    requested = set(paths)
    affected = tuple(
        (fcurve, bool(fcurve.mute))
        for fcurve in _iter_action_fcurves_for_armature(armature, action)
        if fcurve.data_path in requested
    )
    for fcurve, _mute in affected:
        fcurve.mute = True
    try:
        yield
    finally:
        for fcurve, mute in affected:
            fcurve.mute = mute


def _snapshot_paths(armature, paths):
    animation_data = armature.animation_data
    action = animation_data.action if animation_data else None
    return action, {
        path: _snapshot_action_curves(armature, action, path) for path in paths
    }


def _restore_paths(armature, previous_action, snapshots):
    current_action = armature.animation_data.action if armature.animation_data else None
    if previous_action is not None:
        if armature.animation_data is None:
            armature.animation_data_create()
        armature.animation_data.action = previous_action
        for path, curves in snapshots.items():
            _restore_action_curves(armature, previous_action, path, curves)
    elif armature.animation_data is not None:
        armature.animation_data.action = None
    if (
        current_action is not None
        and current_action != previous_action
        and current_action.users == 0
    ):
        bpy.data.actions.remove(current_action)


def _match_fk_controls(armature, artifacts, mechanism_matrices):
    for name, matrix in zip(artifacts.fk_control_bones, mechanism_matrices):
        armature.pose.bones[name].matrix = matrix
        bpy.context.view_layer.update()


def _matrix_score(current, desired):
    return sum(
        (float(left) - float(right)) ** 2
        for current_row, desired_row in zip(current, desired)
        for left, right in zip(current_row, desired_row)
    )


def _fit_pole_to_pose(
    armature,
    stage,
    artifacts,
    mechanism_matrices,
    follows,
    ik,
    end_rotation,
):
    """Numerically fit the pole rail to the authored FK bend plane.

    Blender's pole angle includes rest-roll and mirrored-chain corrections, so
    projecting the FK knee directly onto the visible pole circle is not
    generally its inverse.  A deterministic one-dimensional fit around the
    pole rail preserves the full mechanism matrices without exposing another
    animator weight.
    """

    if not artifacts.pole_bone:
        return
    pole = armature.pose.bones[artifacts.pole_bone]
    center = armature.pose.bones[artifacts.bend_center_bone]
    owner_index = len(artifacts.mechanism_bones) - 2
    chain_count = min(
        max(int(getattr(stage, "chain_length", 2)), 1),
        owner_index + 1,
    )
    root_index = owner_index - chain_count + 1
    scored_indices = tuple(range(root_index, owner_index + 1))
    world = armature.matrix_world
    world_inverse = world.inverted_safe()
    root = world @ mechanism_matrices[root_index].translation
    joint = world @ mechanism_matrices[owner_index].translation
    end = world @ mechanism_matrices[-1].translation
    axis = end - root
    if axis.length < 1.0e-8:
        return
    axis.normalize()
    bend = joint - root
    bend -= axis * bend.dot(axis)
    center_world = world @ center.matrix.translation
    pole_world = world @ pole.matrix.translation
    current_vector = pole_world - center_world
    radius = current_vector.length
    if radius < 1.0e-8:
        return
    if bend.length < 1.0e-8:
        bend = current_vector - axis * current_vector.dot(axis)
    if bend.length < 1.0e-8:
        bend = world.to_3x3() @ pole.matrix.to_3x3().col[0]
        bend -= axis * bend.dot(axis)
    if bend.length < 1.0e-8:
        return
    basis_u = bend.normalized()
    basis_v = axis.cross(basis_u).normalized()

    contact_end_rotation = armature.pose.bones[
        artifacts.contact_end_rotation_owner
    ].constraints[artifacts.contact_end_rotation_constraint_name]
    constraints = follows + (ik, end_rotation, contact_end_rotation)
    saved_influences = tuple(item.influence for item in constraints)
    saved_mutes = tuple(item.mute for item in constraints)
    driver_curves = []
    animation_data = armature.animation_data
    for constraint in constraints:
        path = constraint.path_from_id("influence")
        curve = next(
            (
                candidate
                for candidate in (
                    tuple(animation_data.drivers) if animation_data else ()
                )
                if candidate.data_path == path
            ),
            None,
        )
        driver_curves.append(curve)
    saved_driver_mutes = tuple(
        bool(curve.mute) if curve is not None else False
        for curve in driver_curves
    )
    source_basis = pole.matrix_basis.copy()
    best_basis = source_basis.copy()
    best_score = math.inf
    best_angle = None

    def score_current():
        return sum(
            _matrix_score(
                armature.pose.bones[artifacts.mechanism_bones[index]].matrix,
                mechanism_matrices[index],
            )
            for index in scored_indices
        )

    def evaluate(angle):
        direction = basis_u * math.cos(angle) + basis_v * math.sin(angle)
        candidate = center_world + direction * radius
        matrix = pole.matrix.copy()
        matrix.translation = world_inverse @ candidate
        pole.matrix = matrix
        bpy.context.view_layer.update()
        return score_current(), pole.matrix_basis.copy()

    try:
        for curve in driver_curves:
            if curve is not None:
                curve.mute = True
        for follow in follows:
            follow.mute = True
            follow.influence = 0.0
        ik.mute = False
        ik.influence = 1.0
        end_rotation.mute = True
        end_rotation.influence = 0.0
        contact_end_rotation.mute = True
        contact_end_rotation.influence = 0.0
        bpy.context.view_layer.update()

        # Retain an already-correct pole exactly.  This is common when an IK
        # pose was switched to FK, held, and then switched back unchanged.
        best_score = score_current()
        best_basis = pole.matrix_basis.copy()
        coarse_count = 48
        for index in range(coarse_count):
            angle = math.tau * index / coarse_count
            score, candidate_basis = evaluate(angle)
            if score < best_score:
                best_score = score
                best_basis = candidate_basis
                best_angle = angle

        if best_angle is not None:
            step = math.tau / coarse_count
            for _iteration in range(7):
                candidates = (best_angle - step, best_angle, best_angle + step)
                for angle in candidates:
                    score, candidate_basis = evaluate(angle)
                    if score < best_score:
                        best_score = score
                        best_basis = candidate_basis
                        best_angle = angle
                step *= 0.5
        pole.matrix_basis = best_basis
    finally:
        for constraint, influence, mute in zip(
            constraints,
            saved_influences,
            saved_mutes,
        ):
            constraint.influence = influence
            constraint.mute = mute
        for curve, mute in zip(driver_curves, saved_driver_mutes):
            if curve is not None:
                curve.mute = mute
        bpy.context.view_layer.update()


def _match_ik_controls(
    armature,
    stage,
    artifacts,
    mechanism_matrices,
    follows,
    ik,
    end_rotation,
):
    control = armature.pose.bones[artifacts.ik_control_bone]
    orientation = armature.pose.bones[artifacts.orientation_bone]
    desired_end = mechanism_matrices[-1]
    # The IK constraint targets the control head, so its translation must be
    # the exact mechanism endpoint.  Its art-facing display axes are an
    # independent presentation concern and must not receive the orientation
    # carrier's rest offset; applying that inverse offset here shifted the IK
    # target whenever Contact acquired an FK pose.
    control_matrix = control.matrix.copy()
    control_matrix.translation = desired_end.translation
    control.matrix = control_matrix
    bpy.context.view_layer.update()

    # The IK target and the end-orientation carrier deliberately have
    # different rest axes (art plane versus source bone).  Assign the carrier
    # explicitly after positioning the target so Pose Match does not depend on
    # Blender reconstructing the child basis through those rest axes.  The
    # resulting local compensation remains a child of the animator control,
    # so subsequent control rotations still drive the end normally.
    orientation.matrix = desired_end
    bpy.context.view_layer.update()

    _fit_pole_to_pose(
        armature,
        stage,
        artifacts,
        mechanism_matrices,
        follows,
        ik,
        end_rotation,
    )


def switch_ik_fk_mode(
    armature,
    component,
    stage,
    mode,
    *,
    frame=None,
    key=True,
):
    """Pose-match then switch the public FK/IK state without blending it."""

    mode = str(mode).upper()
    if mode not in {"FK", "IK"}:
        raise SemanticFKError(f"Unsupported rig mode: {mode}")
    artifacts = resolve_fk_solver_layer(armature, component, stage)
    follows, ik, end_rotation, contact_end_rotation = _layer_constraints(
        armature,
        artifacts,
    )
    frame = bpy.context.scene.frame_current if frame is None else float(frame)
    bpy.context.view_layer.update()
    mechanism_matrices = tuple(
        armature.pose.bones[name].matrix.copy()
        for name in artifacts.mechanism_bones
    )
    control_names = artifacts.fk_control_bones + (
        artifacts.ik_control_bone,
        artifacts.orientation_bone,
    ) + ((artifacts.pole_bone,) if artifacts.pole_bone else ())
    previous_control_matrices = {
        name: armature.pose.bones[name].matrix.copy() for name in control_names
    }
    previous_mode = stage.rig_mode
    mode_paths = _mode_paths(stage)
    pose_paths = tuple(
        armature.pose.bones[name].path_from_id(path)
        for name in control_names
        for path in (
            "location",
            _rotation_path(armature.pose.bones[name]),
            "scale",
        )
    )
    previous_action, curve_snapshots = _snapshot_paths(
        armature,
        mode_paths + pose_paths,
    )
    try:
        matched = (
            tuple(
                armature.pose.bones[name] for name in artifacts.fk_control_bones
            )
            if mode == "FK"
            else (
                armature.pose.bones[artifacts.ik_control_bone],
                armature.pose.bones[artifacts.orientation_bone],
            )
        )
        if mode == "IK" and artifacts.pole_bone:
            matched += (armature.pose.bones[artifacts.pole_bone],)

        keyed_paths = []
        matched_paths = _pose_transform_paths(matched)
        with _mute_action_paths(armature, matched_paths):
            if mode == "FK":
                _match_fk_controls(armature, artifacts, mechanism_matrices)
            else:
                _match_ik_controls(
                    armature,
                    stage,
                    artifacts,
                    mechanism_matrices,
                    follows,
                    ik,
                    end_rotation,
                )
            if key:
                # Key while prior control curves remain muted.  Pole fitting
                # requires dependency updates, which would otherwise restore
                # the previous animation before these keys can be authored.
                for pose_bone in matched:
                    keyed_paths.extend(_key_pose(pose_bone, frame))
            stage.rig_mode = mode
            if key and not stage.keyframe_insert(data_path="rig_mode", frame=frame):
                raise SemanticFKError("Could not key the public FK/IK Mode.")
        # Re-evaluate the just-authored controls after restoring their curves.
        bpy.context.scene.frame_set(bpy.context.scene.frame_current)
        bpy.context.view_layer.update()
        if key:
            key_plan = discrete_state_key(frame, 1.0 if mode == "IK" else 0.0)
            for path in mode_paths:
                _set_interpolation(
                    armature,
                    path,
                    key_plan.frame,
                    key_plan.interpolation,
                )
            for path in keyed_paths:
                _set_interpolation(armature, path, frame, "BEZIER")

        # Contact can keep effective IK active while this public label says FK.
    except Exception:
        stage.rig_mode = previous_mode
        for name, matrix in previous_control_matrices.items():
            armature.pose.bones[name].matrix = matrix
        _restore_paths(armature, previous_action, curve_snapshots)
        bpy.context.view_layer.update()
        raise
    return artifacts


__all__ = [
    "SemanticFKArtifacts",
    "SemanticFKError",
    "StandaloneFKArtifacts",
    "ensure_fk_solver_layer",
    "ensure_fk_solver_drivers",
    "ensure_standalone_fk_solver_layer",
    "finalize_fk_solver_action_migration",
    "resolve_fk_solver_layer",
    "switch_ik_fk_mode",
]
