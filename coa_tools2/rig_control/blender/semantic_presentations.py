"""Compile replaceable Semantic/Character Rig widget presentations.

Presentation is deliberately evaluated separately from the solver graph.  A
Geometry Nodes source object stores the editable parameters while a small,
evaluated edge-only Mesh is assigned to ``PoseBone.custom_shape``.  This keeps
viewport drawing predictable without making widget edits rebuild IK, pose-map
drivers, or secondary motion.
"""

from __future__ import annotations

import math
import time
import traceback

import bpy
try:
    from bpy.props import StringProperty
except (ImportError, AttributeError):  # Pure compiler tests use a minimal bpy stub.
    def StringProperty(**_kwargs):
        return None

from ... import functions
from .artifacts import ensure_rig_instance_id, slugify
from .component_artifacts import (
    ComponentArtifactConflict,
    _record_artifact,
    ensure_component_widget,
    ensure_widget_collection,
)
from .component_safety import (
    ComponentPreflightError,
    capture_component_build_state,
    ensure_unique_component_instance,
    preflight_component_artifacts,
    preserve_component_context,
    rollback_component_build,
)
from .properties import get_rig_data
from .semantic_artifacts import semantic_stage_role
from .semantic_widgets import (
    SemanticWidgetShape,
    ensure_semantic_widget_modifier,
    semantic_widget_family,
)


AUTO_PRESENTATION_DELAY = 0.25
WIDGET_ROLE_MARKER = ":widget:"
_PENDING_PRESENTATIONS: dict[tuple[str, str, str, str], float] = {}
_PRESENTATION_REBUILD_ACTIVE = False


class SemanticPresentationError(RuntimeError):
    pass


def semantic_widget_object_role(
    stage_uuid: str,
    target_role: str,
    artifact_role: str,
) -> str:
    return semantic_stage_role(
        stage_uuid,
        f"widget:{target_role.lower()}:{artifact_role.lower()}",
    )


def _component_widget_object_role(target_role: str, artifact_role: str) -> str:
    return (
        "component_widget_presentation:"
        f"{target_role.lower()}:{artifact_role.lower()}"
    )


def _is_generated_shape(shape: str) -> bool:
    try:
        SemanticWidgetShape(str(shape))
    except ValueError:
        return False
    return True


def _presentation_parameters(presentation, shape: str) -> dict[str, float | int]:
    values = {
        "Width": presentation.width,
        "Height": presentation.height,
        "Corner Radius": presentation.corner_radius,
        "Bar Width": presentation.bar_width,
        "Arrow Head Length": presentation.head_length,
        "Arrow Head Width": presentation.head_width,
        "Radius": presentation.radius,
        "Arc Angle": presentation.arc_angle,
        "Inner Radius": presentation.sector_inner_radius,
        "Outer Radius": presentation.sector_outer_radius,
        "Start Angle": presentation.sector_start_angle,
        "Sweep Angle": presentation.sector_sweep_angle,
        # Compatibility with the first production prototype.  Once an older
        # Sector group is rebuilt, only the current public names are selected.
        "Angle": presentation.sector_sweep_angle,
        "Segments": presentation.segments,
    }
    family = semantic_widget_family(shape)
    return {
        parameter.name: values[parameter.name]
        for parameter in family.parameters
    }


def _matches_owner(owner, armature, component, role: str) -> bool:
    return bool(
        owner is not None
        and owner.get("coa_rig_managed")
        and owner.get("coa_rig_instance_id") == ensure_rig_instance_id(armature)
        and owner.get("coa_rig_component_uuid") == component.component_uuid
        and owner.get("coa_rig_component_role") == role
    )


def _owned_objects(armature, component, role: str):
    return tuple(
        obj
        for obj in bpy.data.objects
        if _matches_owner(obj, armature, component, role)
    )


def _record_owned_object(component, role: str, obj) -> None:
    record_indices = [
        index
        for index, artifact in enumerate(component.artifacts)
        if artifact.role == role and artifact.data_type == "OBJECT"
    ]
    if len(record_indices) > 1:
        # Keep the first stable artifact UUID while removing duplicate records
        # produced by an older rename-unaware implementation.
        for index in reversed(record_indices[1:]):
            component.artifacts.remove(index)
        record_indices = record_indices[:1]
    if record_indices:
        artifact = component.artifacts[record_indices[0]]
        artifact.object_name = obj.name
        artifact.bone_name = ""
        artifact.constraint_name = ""
        artifact.data_path = ""
        artifact.binding_uuid = ""
        artifact.owned = True
        return
    _record_artifact(
        component,
        role,
        "OBJECT",
        object_name=obj.name,
        owned=True,
    )


def _tag_widget_object(
    obj,
    armature,
    component,
    role: str,
    *,
    shape: str,
    target_role: str,
) -> None:
    tags = {
        "coa_rig_managed": True,
        "coa_rig_instance_id": ensure_rig_instance_id(armature),
        "coa_rig_component_uuid": component.component_uuid,
        "coa_rig_component_role": role,
        "coa_semantic_widget_shape": shape,
        "coa_semantic_widget_target_role": target_role,
    }
    for key, value in tags.items():
        obj[key] = value
        if obj.data is not None:
            obj.data[key] = value
    obj.hide_render = True
    obj.hide_select = True
    obj.display_type = "WIRE"


def _ensure_widget_object(
    armature,
    component,
    role: str,
    *,
    name: str,
    shape: str,
    target_role: str,
):
    candidates = _owned_objects(armature, component, role)
    if len(candidates) > 1:
        raise SemanticPresentationError(
            f"Multiple generated widget objects use role '{role}'."
        )
    obj = candidates[0] if candidates else None
    if obj is not None and obj.type != "MESH":
        raise SemanticPresentationError(
            f"Generated widget '{obj.name}' is not a Mesh object."
        )
    if obj is None:
        mesh = bpy.data.meshes.new(f"{name}_Mesh")
        obj = bpy.data.objects.new(name, mesh)
        ensure_widget_collection().objects.link(obj)
    _tag_widget_object(
        obj,
        armature,
        component,
        role,
        shape=shape,
        target_role=target_role,
    )
    _record_owned_object(component, role, obj)
    return obj


def _validate_evaluated_widget(mesh, shape: str) -> None:
    if not mesh.vertices or not mesh.edges:
        raise SemanticPresentationError(
            f"{shape} Geometry Nodes produced an empty custom shape."
        )
    if mesh.polygons:
        raise SemanticPresentationError(
            f"{shape} custom shapes must contain edges only, not faces."
        )
    if any(
        not all(math.isfinite(value) for value in vertex.co)
        for vertex in mesh.vertices
    ):
        raise SemanticPresentationError(
            f"{shape} Geometry Nodes produced non-finite coordinates."
        )


def _sync_widget_cache(
    source,
    cache,
    armature,
    component,
    cache_role: str,
    *,
    shape: str,
    target_role: str,
) -> None:
    was_hidden = source.hide_get()
    new_mesh = None
    try:
        source.hide_set(False)
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = source.evaluated_get(depsgraph)
        new_mesh = bpy.data.meshes.new_from_object(
            evaluated,
            preserve_all_data_layers=False,
            depsgraph=depsgraph,
        )
        _validate_evaluated_widget(new_mesh, shape)
    except Exception:
        if new_mesh is not None and new_mesh.users == 0:
            bpy.data.meshes.remove(new_mesh)
        raise
    finally:
        source.hide_set(was_hidden)
    old_mesh = cache.data
    cache.data = new_mesh
    new_mesh = None
    _tag_widget_object(
        cache,
        armature,
        component,
        cache_role,
        shape=shape,
        target_role=target_role,
    )
    _record_owned_object(component, cache_role, cache)
    if old_mesh is not None and old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)


def _ensure_generated_widget(
    armature,
    component,
    presentation,
    *,
    stage_uuid: str,
    target_role: str,
):
    shape = presentation.shape
    if stage_uuid:
        source_role = semantic_widget_object_role(
            stage_uuid, target_role, "source"
        )
        cache_role = semantic_widget_object_role(
            stage_uuid, target_role, "cache"
        )
        suffix = f"{stage_uuid[:8]}_{target_role}"
    else:
        source_role = _component_widget_object_role(target_role, "source")
        cache_role = _component_widget_object_role(target_role, "cache")
        suffix = f"{component.component_uuid[:8]}_{target_role}"
    stem = slugify(component.semantic_id or component.label)
    source = _ensure_widget_object(
        armature,
        component,
        source_role,
        name=f"WGT_{stem}_{suffix}_Source",
        shape=shape,
        target_role=target_role,
    )
    ensure_semantic_widget_modifier(
        source,
        shape,
        parameters=_presentation_parameters(presentation, shape),
    )
    cache = _ensure_widget_object(
        armature,
        component,
        cache_role,
        name=f"WGT_{stem}_{suffix}",
        shape=shape,
        target_role=target_role,
    )
    _sync_widget_cache(
        source,
        cache,
        armature,
        component,
        cache_role,
        shape=shape,
        target_role=target_role,
    )
    source.hide_set(True)
    cache.hide_set(True)
    return cache, {source_role, cache_role}


def _assign_custom_shape(pose_bones, shape_object, presentation) -> None:
    for pose_bone in pose_bones:
        pose_bone.custom_shape = shape_object
        pose_bone.use_custom_shape_bone_size = False
        if hasattr(pose_bone, "custom_shape_scale_xyz"):
            pose_bone.custom_shape_scale_xyz = (1.0, 1.0, 1.0)
        if hasattr(pose_bone, "custom_shape_wire_width"):
            pose_bone.custom_shape_wire_width = presentation.wire_width


def _validate_presentation_definition(presentation, subject_id: str) -> None:
    from ..component_validation import validate_widget_presentation
    from .properties import widget_presentation_to_spec

    issues = validate_widget_presentation(
        widget_presentation_to_spec(presentation),
        subject_id,
    )
    if issues:
        raise SemanticPresentationError(
            "; ".join(issue.message for issue in issues)
        )


def _apply_presentation(
    armature,
    component,
    presentation,
    pose_bone_names,
    *,
    stage_uuid: str,
    target_role: str,
) -> set[str]:
    _validate_presentation_definition(
        presentation,
        f"{component.component_uuid}:{stage_uuid}:{target_role}",
    )
    pose_bones = []
    for bone_name in pose_bone_names:
        pose_bone = armature.pose.bones.get(bone_name)
        if pose_bone is None:
            raise SemanticPresentationError(
                f"Presentation target bone '{bone_name}' was not found."
            )
        pose_bones.append(pose_bone)
    if not pose_bones:
        if presentation.shape != "NONE":
            raise SemanticPresentationError(
                "Build the control stage before applying its presentation."
            )
        return set()

    shape = presentation.shape
    if shape == "NONE":
        _assign_custom_shape(pose_bones, None, presentation)
        return set()
    if shape == "CUSTOM_OBJECT":
        custom_object = presentation.custom_object
        if custom_object is None:
            raise SemanticPresentationError(
                "Choose a Custom Object before applying this presentation."
            )
        if custom_object.type != "MESH":
            raise SemanticPresentationError(
                f"Custom shape '{custom_object.name}' must be a Mesh object."
            )
        _assign_custom_shape(pose_bones, custom_object, presentation)
        return set()
    if not _is_generated_shape(shape):
        raise SemanticPresentationError(f"Unknown widget shape '{shape}'.")
    shape_object, expected = _ensure_generated_widget(
        armature,
        component,
        presentation,
        stage_uuid=stage_uuid,
        target_role=target_role,
    )
    _assign_custom_shape(pose_bones, shape_object, presentation)
    return expected


def _find_owned_bone(armature, component, role: str):
    candidates = [
        bone
        for bone in armature.data.bones
        if _matches_owner(bone, armature, component, role)
    ]
    if len(candidates) > 1:
        raise SemanticPresentationError(
            f"Multiple generated bones use role '{role}'."
        )
    return candidates[0] if candidates else None


def _semantic_stage_targets(armature, component, stage, result=None):
    if stage.stage_type == "PROJECTED_TRANSFORM":
        name = result.primary_control_bone if result is not None else ""
        if not name:
            bone = _find_owned_bone(
                armature,
                component,
                semantic_stage_role(stage.stage_uuid, "control_bone"),
            )
            name = bone.name if bone is not None else stage.control_bone
        return (("PRIMARY", stage.presentation, (name,) if name else ()),)
    if stage.stage_type in {"CHAIN_FK", "CHAIN_IK"}:
        targets = []
        if stage.stage_type == "CHAIN_IK":
            name = result.primary_control_bone if result is not None else ""
            if not name:
                bone = _find_owned_bone(
                    armature,
                    component,
                    semantic_stage_role(stage.stage_uuid, "control_bone"),
                )
                name = bone.name if bone is not None else stage.control_bone
            targets.append(
                ("PRIMARY", stage.presentation, (name,) if name else ())
            )
        count = len(stage.source_bones) or len(component.source_bones)
        fk_names = tuple(
            bone.name
            for index in range(count)
            if (
                bone := _find_owned_bone(
                    armature,
                    component,
                    semantic_stage_role(
                        stage.stage_uuid,
                        f"fk_control:{index}",
                    ),
                )
            )
            is not None
        )
        presentation = (
            stage.presentation
            if stage.stage_type == "CHAIN_FK"
            else stage.fk_presentation
        )
        targets.append(("FK_CONTROL", presentation, fk_names))
        return tuple(targets)
    if stage.stage_type == "SPLINE":
        names = ()
        spline = result.spline_info if result is not None else None
        if spline is not None:
            names = tuple(spline.control_bones)
        if not names:
            resolved = []
            for index in range(int(stage.spline_control_count)):
                bone = _find_owned_bone(
                    armature,
                    component,
                    semantic_stage_role(
                        stage.stage_uuid,
                        f"spline_control:{index}",
                    ),
                )
                if bone is not None:
                    resolved.append(bone.name)
            names = tuple(resolved)
        return (("SPLINE_CONTROL", stage.presentation, names),)
    if stage.stage_type == "BBONE_BEZIER":
        point_names = ()
        handle_names = ()
        bbone = result.bbone_info if result is not None else None
        if bbone is not None:
            point_names = tuple(bbone.point_control_bones)
            handle_names = tuple(bbone.handle_control_bones)
        if not point_names:
            point_roles = ["bbone_point:start", "bbone_point:end"]
            if stage.bbone_use_mid_control:
                point_roles.append("bbone_point:mid")
            point_names = tuple(
                bone.name
                for leaf in point_roles
                if (
                    bone := _find_owned_bone(
                        armature,
                        component,
                        semantic_stage_role(stage.stage_uuid, leaf),
                    )
                )
                is not None
            )
        if not handle_names:
            handle_names = tuple(
                bone.name
                for leaf in ("bbone_handle:out", "bbone_handle:in")
                if (
                    bone := _find_owned_bone(
                        armature,
                        component,
                        semantic_stage_role(stage.stage_uuid, leaf),
                    )
                )
                is not None
            )
        return (
            ("BBONE_POINT", stage.presentation, point_names),
            ("BBONE_HANDLE", stage.handle_presentation, handle_names),
        )
    return ()


def _stage_presentations(armature, component, stage, result=None):
    targets = list(_semantic_stage_targets(armature, component, stage, result))
    if stage.stage_type == "CHAIN_IK" and stage.use_pole:
        pole_name = stage.pole_bone
        if result is not None and getattr(result, "spline_info", None) is not None:
            pole_name = getattr(result.spline_info, "pole_bone", pole_name)
        if not pole_name:
            pole = _find_owned_bone(
                armature,
                component,
                semantic_stage_role(stage.stage_uuid, "pole_control"),
            )
            pole_name = pole.name if pole is not None else ""
        targets.append(
            (
                "POLE",
                stage.pole_presentation,
                (pole_name,) if pole_name else (),
            )
        )
    return tuple(targets)


def _expected_stage_roles_without_bones(stage) -> tuple[tuple[str, object], ...]:
    values = []
    if stage.stage_type == "CHAIN_FK":
        values.append(("FK_CONTROL", stage.presentation))
    elif stage.stage_type in {"PROJECTED_TRANSFORM", "CHAIN_IK"}:
        values.append(("PRIMARY", stage.presentation))
        if stage.stage_type == "CHAIN_IK":
            values.append(("FK_CONTROL", stage.fk_presentation))
    elif stage.stage_type == "SPLINE":
        values.append(("SPLINE_CONTROL", stage.presentation))
    elif stage.stage_type == "BBONE_BEZIER":
        values.extend(
            (
                ("BBONE_POINT", stage.presentation),
                ("BBONE_HANDLE", stage.handle_presentation),
            )
        )
    if stage.stage_type == "CHAIN_IK" and stage.use_pole:
        values.append(("POLE", stage.pole_presentation))
    return tuple(values)


def expected_semantic_presentation_roles(component, stages) -> set[str]:
    expected = set()
    for stage in stages:
        if not stage.enabled:
            continue
        for target_role, presentation in _expected_stage_roles_without_bones(stage):
            if not _is_generated_shape(presentation.shape):
                continue
            expected.update(
                {
                    semantic_widget_object_role(
                        stage.stage_uuid, target_role, "source"
                    ),
                    semantic_widget_object_role(
                        stage.stage_uuid, target_role, "cache"
                    ),
                }
            )
    return expected


def _remove_widget_object(obj) -> None:
    mesh = obj.data if obj.type == "MESH" else None
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def _cleanup_widget_artifacts(
    armature,
    component,
    expected: set[str],
    *,
    limited_roles: set[str] | None = None,
) -> None:
    obsolete = []
    for index in range(len(component.artifacts) - 1, -1, -1):
        artifact = component.artifacts[index]
        role = artifact.role
        is_semantic_widget = WIDGET_ROLE_MARKER in role
        is_component_widget = role.startswith("component_widget_presentation:")
        if not (is_semantic_widget or is_component_widget):
            continue
        if limited_roles is not None and role not in limited_roles:
            continue
        if role in expected:
            continue
        candidates = ()
        if artifact.owned and artifact.data_type == "OBJECT":
            candidates = _owned_objects(armature, component, role)
            if len(candidates) > 1:
                raise SemanticPresentationError(
                    f"Multiple generated widget objects use role '{role}'."
                )
        obsolete.append((index, candidates[0] if candidates else None))
    # All ownership conflicts are rejected before deleting the first object,
    # so cleanup itself cannot leave a half-removed presentation set.
    for index, obj in obsolete:
        if obj is not None:
            _remove_widget_object(obj)
        component.artifacts.remove(index)


def reconcile_semantic_presentations(
    armature,
    component,
    stages,
    built_stages=None,
    *,
    only_target: tuple[str, str] | None = None,
    cleanup: bool = True,
) -> set[str]:
    expected = expected_semantic_presentation_roles(component, stages)
    limited_roles = None
    if only_target is not None:
        stage_uuid, target_role = only_target
        limited_roles = {
            semantic_widget_object_role(stage_uuid, target_role, "source"),
            semantic_widget_object_role(stage_uuid, target_role, "cache"),
        }
    for stage in stages:
        if not stage.enabled:
            continue
        result = (built_stages or {}).get(stage.stage_uuid)
        for target_role, presentation, bone_names in _stage_presentations(
            armature, component, stage, result
        ):
            if only_target is not None and only_target != (
                stage.stage_uuid,
                target_role,
            ):
                continue
            _apply_presentation(
                armature,
                component,
                presentation,
                bone_names,
                stage_uuid=stage.stage_uuid,
                target_role=target_role,
            )
    if cleanup:
        _cleanup_widget_artifacts(
            armature,
            component,
            expected,
            limited_roles=limited_roles,
        )
    return expected


def reconcile_component_presentation(
    armature,
    component,
    primary_bone_name: str,
    *,
    cleanup: bool = True,
) -> set[str]:
    presentation = component.presentation
    target_role = "PRIMARY"
    if presentation.shape == "NONE":
        legacy = ensure_component_widget(armature, component)
        pose_bone = armature.pose.bones.get(primary_bone_name)
        if pose_bone is not None:
            pose_bone.custom_shape = legacy
            pose_bone.use_custom_shape_bone_size = False
        expected = set()
    else:
        expected = _apply_presentation(
            armature,
            component,
            presentation,
            (primary_bone_name,),
            stage_uuid="",
            target_role=target_role,
        )
    all_roles = {
        _component_widget_object_role(target_role, "source"),
        _component_widget_object_role(target_role, "cache"),
    }
    if cleanup:
        _cleanup_widget_artifacts(
            armature,
            component,
            expected,
            limited_roles=all_roles,
        )
    return expected


def mark_semantic_presentations_reconciled(
    stages,
    *,
    only_target: tuple[str, str] | None = None,
) -> None:
    """Commit UI state only after the surrounding transaction succeeds."""

    for stage in stages:
        if not stage.enabled:
            continue
        for target_role, presentation in _expected_stage_roles_without_bones(stage):
            if only_target is not None and only_target != (
                stage.stage_uuid,
                target_role,
            ):
                continue
            presentation.needs_rebuild = False
            presentation.last_error = ""


def mark_component_presentation_reconciled(component) -> None:
    """Commit a legacy Character component's visual-only UI state."""

    component.presentation.needs_rebuild = False
    component.presentation.last_error = ""


def cleanup_component_presentation_artifacts(
    armature,
    component,
    expected: set[str],
) -> None:
    target_role = "PRIMARY"
    _cleanup_widget_artifacts(
        armature,
        component,
        expected,
        limited_roles={
            _component_widget_object_role(target_role, "source"),
            _component_widget_object_role(target_role, "cache"),
        },
    )


def _active_component(context, *, migrate=True):
    armature = functions.get_sprite_object(context.active_object)
    if armature is None or armature.type != "ARMATURE":
        return None, None
    rig_data = get_rig_data(armature, migrate=migrate)
    if not rig_data.rig_components:
        return armature, None
    index = min(rig_data.rig_components_index, len(rig_data.rig_components) - 1)
    return armature, rig_data.rig_components[index]


def _semantic_stages_for_preview(component):
    indexed = [
        (index, stage)
        for index, stage in enumerate(component.semantic_stages)
        if stage.enabled
    ]
    indexed.sort(key=lambda item: (item[1].order, item[0]))
    return tuple(stage for _index, stage in indexed)


def compile_component_presentations(
    armature,
    component,
    *,
    only_target: tuple[str, str] | None = None,
):
    if armature is None or armature.type != "ARMATURE":
        raise SemanticPresentationError("Rig presentation requires an Armature.")
    with preserve_component_context(armature):
        try:
            preflight_component_artifacts(armature, component)
        except ComponentPreflightError as exc:
            raise SemanticPresentationError(str(exc)) from exc
        ensure_unique_component_instance(armature)
        snapshot = capture_component_build_state(armature, component)
        try:
            if component.component_type == "SEMANTIC":
                reconcile_semantic_presentations(
                    armature,
                    component,
                    _semantic_stages_for_preview(component),
                    only_target=only_target,
                )
            else:
                reconcile_component_presentation(
                    armature,
                    component,
                    component.control_bone,
                )
        except Exception as exc:
            try:
                rollback_component_build(armature, component, snapshot)
            except Exception as rollback_error:
                raise SemanticPresentationError(
                    f"{exc}; presentation rollback failed: {rollback_error}"
                ) from exc
            if isinstance(exc, SemanticPresentationError):
                raise
            if isinstance(exc, ComponentArtifactConflict):
                raise SemanticPresentationError(str(exc)) from exc
            raise SemanticPresentationError(str(exc)) from exc
    if component.component_type == "SEMANTIC":
        mark_semantic_presentations_reconciled(
            _semantic_stages_for_preview(component),
            only_target=only_target,
        )
    else:
        mark_component_presentation_reconciled(component)
    return True


def _presentation_owner(presentation):
    armature = getattr(presentation, "id_data", None)
    rig_data = getattr(armature, "coa_tools2_rig", None)
    if armature is None or rig_data is None:
        return None
    pointer = presentation.as_pointer()
    for component in rig_data.rig_components:
        if component.presentation.as_pointer() == pointer:
            return armature, component, "", "COMPONENT"
        for stage in component.semantic_stages:
            if stage.presentation.as_pointer() == pointer:
                target_role = (
                    "SPLINE_CONTROL"
                    if stage.stage_type == "SPLINE"
                    else (
                        "BBONE_POINT"
                        if stage.stage_type == "BBONE_BEZIER"
                        else (
                            "FK_CONTROL"
                            if stage.stage_type == "CHAIN_FK"
                            else "PRIMARY"
                        )
                    )
                )
                return armature, component, stage.stage_uuid, target_role
            if stage.fk_presentation.as_pointer() == pointer:
                return armature, component, stage.stage_uuid, "FK_CONTROL"
            if stage.pole_presentation.as_pointer() == pointer:
                return armature, component, stage.stage_uuid, "POLE"
            if stage.handle_presentation.as_pointer() == pointer:
                return armature, component, stage.stage_uuid, "BBONE_HANDLE"
    return None


def schedule_semantic_presentation_update(presentation) -> None:
    owner = _presentation_owner(presentation)
    if owner is None or not presentation.live_preview:
        return
    armature, component, stage_uuid, target_role = owner
    key = (armature.name, component.component_uuid, stage_uuid, target_role)
    _PENDING_PRESENTATIONS[key] = time.monotonic()
    if not bpy.app.timers.is_registered(_flush_semantic_presentation_updates):
        bpy.app.timers.register(
            _flush_semantic_presentation_updates,
            first_interval=AUTO_PRESENTATION_DELAY,
        )


def cancel_semantic_presentation_update(presentation=None) -> None:
    if presentation is None:
        _PENDING_PRESENTATIONS.clear()
        if bpy.app.timers.is_registered(_flush_semantic_presentation_updates):
            bpy.app.timers.unregister(_flush_semantic_presentation_updates)
        return
    owner = _presentation_owner(presentation)
    if owner is None:
        return
    armature, component, stage_uuid, target_role = owner
    _PENDING_PRESENTATIONS.pop(
        (armature.name, component.component_uuid, stage_uuid, target_role),
        None,
    )


def _presentation_from_target(component, stage_uuid: str, target_role: str):
    if not stage_uuid:
        return component.presentation
    stage = next(
        (
            candidate
            for candidate in component.semantic_stages
            if candidate.stage_uuid == stage_uuid
        ),
        None,
    )
    if stage is None:
        return None
    if target_role == "POLE":
        return stage.pole_presentation
    if target_role == "FK_CONTROL" and stage.stage_type == "CHAIN_IK":
        return stage.fk_presentation
    if target_role == "BBONE_HANDLE":
        return stage.handle_presentation
    return stage.presentation


def _flush_semantic_presentation_updates():
    global _PRESENTATION_REBUILD_ACTIVE

    now = time.monotonic()
    due = [
        key
        for key, changed_at in _PENDING_PRESENTATIONS.items()
        if now - changed_at >= AUTO_PRESENTATION_DELAY
    ]
    for key in due:
        _PENDING_PRESENTATIONS.pop(key, None)
        armature_name, component_uuid, stage_uuid, target_role = key
        armature = bpy.data.objects.get(armature_name)
        rig_data = getattr(armature, "coa_tools2_rig", None)
        if armature is None or armature.type != "ARMATURE" or rig_data is None:
            continue
        component = next(
            (
                candidate
                for candidate in rig_data.rig_components
                if candidate.component_uuid == component_uuid
            ),
            None,
        )
        if component is None:
            continue
        presentation = _presentation_from_target(
            component, stage_uuid, target_role
        )
        if (
            presentation is None
            or not presentation.needs_rebuild
            or not presentation.live_preview
            or component.needs_rebuild
        ):
            continue
        try:
            _PRESENTATION_REBUILD_ACTIVE = True
            compile_component_presentations(
                armature,
                component,
                only_target=(stage_uuid, target_role) if stage_uuid else None,
            )
        except Exception as exc:
            traceback.print_exc()
            presentation.last_error = str(exc)
            presentation.needs_rebuild = True
        finally:
            _PRESENTATION_REBUILD_ACTIVE = False
    return 0.1 if _PENDING_PRESENTATIONS else None


def flush_semantic_presentation_updates_now():
    for key in tuple(_PENDING_PRESENTATIONS):
        _PENDING_PRESENTATIONS[key] = 0.0
    return _flush_semantic_presentation_updates()


_OperatorBase = getattr(getattr(bpy, "types", None), "Operator", object)


class COATOOLS2_OT_UpdateRigPresentation(_OperatorBase):
    bl_idname = "coa_tools2.update_rig_presentation"
    bl_label = "Apply Rig Presentation"
    bl_description = "Apply custom-shape settings without rebuilding the solver"
    bl_options = {"REGISTER", "UNDO"}

    stage_uuid: StringProperty(default="", options={"HIDDEN"})
    target_role: StringProperty(default="", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        _armature, component = _active_component(context, migrate=False)
        return component is not None

    def execute(self, context):
        armature, component = _active_component(context)
        try:
            only_target = (
                (self.stage_uuid, self.target_role)
                if self.stage_uuid and self.target_role
                else None
            )
            compile_component_presentations(
                armature,
                component,
                only_target=only_target,
            )
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


CLASSES = (COATOOLS2_OT_UpdateRigPresentation,)


__all__ = (
    "CLASSES",
    "SemanticPresentationError",
    "cancel_semantic_presentation_update",
    "cleanup_component_presentation_artifacts",
    "compile_component_presentations",
    "expected_semantic_presentation_roles",
    "flush_semantic_presentation_updates_now",
    "mark_component_presentation_reconciled",
    "mark_semantic_presentations_reconciled",
    "reconcile_component_presentation",
    "reconcile_semantic_presentations",
    "schedule_semantic_presentation_update",
    "semantic_widget_object_role",
)
