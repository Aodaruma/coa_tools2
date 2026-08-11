"""Contact / Pin layer for semantic character rigs."""

from __future__ import annotations

from dataclasses import dataclass
import re

import bpy

from ... import functions
from .artifacts import ensure_rig_instance_id
from .component_artifacts import (
    ComponentArtifactConflict,
    _managed_constraint,
    _record_artifact,
    find_component_object,
)
from .semantic_artifacts import semantic_stage_role


class SemanticContactError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContactPinArtifacts:
    driven_bone: str
    anchor_object: str
    constraint_name: str
    property_name: str


def _short(value):
    return re.sub(r"[^0-9A-Za-z]", "", str(value or ""))[:8]


def _mechanism_collection(scene):
    name = "COA Semantic Mechanisms"
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
    if collection.name not in scene.collection.children:
        scene.collection.children.link(collection)
    collection.hide_render = True
    return collection


def _tag_object(armature, component, obj, role):
    instance_id = ensure_rig_instance_id(armature)
    owner = obj.get("coa_rig_component_uuid")
    if owner not in {None, "", component.component_uuid}:
        raise ComponentArtifactConflict(
            f"Object '{obj.name}' belongs to another rig component."
        )
    obj["coa_rig_instance_id"] = instance_id
    obj["coa_rig_component_uuid"] = component.component_uuid
    obj["coa_rig_component_role"] = role
    obj["coa_rig_managed"] = True


def _ensure_anchor(armature, component, stage, driven_pose):
    role = semantic_stage_role(stage.stage_uuid, "pin_anchor")
    anchor = find_component_object(armature, component.component_uuid, role)
    created = anchor is None
    if anchor is None:
        name = f"MCH_PIN_{_short(component.component_uuid)}_{_short(stage.stage_uuid)}"
        if bpy.data.objects.get(name) is not None:
            raise ComponentArtifactConflict(f"Object '{name}' already exists and is unmanaged.")
        anchor = bpy.data.objects.new(name, None)
        _mechanism_collection(bpy.context.scene).objects.link(anchor)
        anchor.empty_display_type = "PLAIN_AXES"
        anchor.empty_display_size = max(driven_pose.length * 0.2, 0.05)
        anchor.hide_viewport = True
    _tag_object(armature, component, anchor, role)
    if created:
        anchor.matrix_world = armature.matrix_world @ driven_pose.matrix

    world = anchor.matrix_world.copy()
    if stage.pin_space == "WORLD":
        anchor.parent = None
        anchor.parent_type = "OBJECT"
        anchor.parent_bone = ""
    elif stage.pin_space == "CHARACTER":
        anchor.parent = armature
        anchor.parent_type = "OBJECT"
        anchor.parent_bone = ""
    elif stage.pin_space == "TARGET":
        if stage.pin_target_object is None:
            raise SemanticContactError("Target-space Pin requires a target object.")
        anchor.parent = stage.pin_target_object
        if stage.pin_target_bone and stage.pin_target_object.type == "ARMATURE":
            if stage.pin_target_bone not in stage.pin_target_object.data.bones:
                raise SemanticContactError(
                    f"Pin target bone not found: {stage.pin_target_bone}"
                )
            anchor.parent_type = "BONE"
            anchor.parent_bone = stage.pin_target_bone
        else:
            anchor.parent_type = "OBJECT"
            anchor.parent_bone = ""
    else:
        raise SemanticContactError(f"Unsupported Pin space: {stage.pin_space}")
    anchor.matrix_world = world
    _record_artifact(
        component,
        role,
        "OBJECT",
        object_name=anchor.name,
        owned=True,
    )
    return anchor


def _constraint_type(stage):
    if stage.pin_position and stage.pin_orientation:
        return "COPY_TRANSFORMS"
    if stage.pin_position:
        return "COPY_LOCATION"
    if stage.pin_orientation:
        return "COPY_ROTATION"
    raise SemanticContactError("Pin must affect position, orientation, or both.")


def _ensure_influence_driver(armature, component, stage, driven_pose, constraint, property_name):
    if property_name not in driven_pose:
        driven_pose[property_name] = 0.0
    try:
        driven_pose.id_properties_ui(property_name).update(
            min=0.0, max=1.0, soft_min=0.0, soft_max=1.0
        )
    except (AttributeError, TypeError):
        pass
    fcurve = constraint.driver_add("influence")
    driver = fcurve.driver
    driver.type = "SCRIPTED"
    while driver.variables:
        driver.variables.remove(driver.variables[0])
    variable = driver.variables.new()
    variable.name = f"cp_{_short(stage.stage_uuid)}"
    variable.type = "SINGLE_PROP"
    target = variable.targets[0]
    target.id = armature
    target.data_path = driven_pose.path_from_id(f'["{property_name}"]')
    driver.expression = variable.name
    role = semantic_stage_role(stage.stage_uuid, "pin_influence_driver")
    _record_artifact(
        component,
        role,
        "DRIVER",
        object_name=armature.name,
        bone_name=driven_pose.name,
        constraint_name=constraint.name,
        data_path=constraint.path_from_id("influence"),
        binding_uuid=stage.stage_uuid,
        owned=True,
    )


def ensure_contact_pin_artifacts(armature, component, stage, *, default_driven_bone=""):
    driven_name = stage.pin_driven_bone or default_driven_bone
    driven_pose = armature.pose.bones.get(driven_name)
    if driven_pose is None:
        raise SemanticContactError("Pin layer needs a generated or existing driven bone.")
    stage.pin_driven_bone = driven_pose.name
    property_name = stage.pin_property or f"pin_{_short(stage.stage_uuid)}"
    stage.pin_property = property_name
    anchor = _ensure_anchor(armature, component, stage, driven_pose)
    constraint_name = f"COA_PIN_{_short(component.component_uuid)}_{_short(stage.stage_uuid)}"
    constraint = _managed_constraint(
        driven_pose, component, constraint_name, _constraint_type(stage)
    )
    constraint.target = anchor
    constraint.owner_space = "WORLD"
    constraint.target_space = "WORLD"
    if hasattr(constraint, "mix_mode"):
        constraint.mix_mode = "REPLACE"
    role = semantic_stage_role(stage.stage_uuid, "pin_constraint")
    _record_artifact(
        component,
        role,
        "CONSTRAINT",
        bone_name=driven_pose.name,
        constraint_name=constraint.name,
        owned=True,
    )
    _ensure_influence_driver(
        armature, component, stage, driven_pose, constraint, property_name
    )
    return ContactPinArtifacts(
        driven_bone=driven_pose.name,
        anchor_object=anchor.name,
        constraint_name=constraint.name,
        property_name=property_name,
    )


def _range_support(stage):
    return stage.pin_start - stage.blend_in, stage.pin_end + stage.blend_out


def validate_pin_ranges(component):
    stages = [
        stage
        for stage in component.semantic_stages
        if stage.enabled and stage.stage_type == "CONTACT_PIN"
    ]
    for stage in stages:
        if stage.pin_end < stage.pin_start:
            raise SemanticContactError("Pin end frame must not precede its start.")
    for index, left in enumerate(stages):
        left_start, left_end = _range_support(left)
        for right in stages[index + 1 :]:
            if (left.pin_driven_bone or component.control_bone) != (
                right.pin_driven_bone or component.control_bone
            ):
                continue
            right_start, right_end = _range_support(right)
            if max(left_start, right_start) <= min(left_end, right_end):
                raise SemanticContactError(
                    f"Pin ranges overlap on '{left.pin_driven_bone or component.control_bone}'."
                )


def key_pin_range(armature, component, stage):
    validate_pin_ranges(component)
    pose_bone = armature.pose.bones.get(stage.pin_driven_bone)
    if pose_bone is None or not stage.pin_property:
        raise SemanticContactError("Build the Pin layer before keying its range.")
    anchor_role = semantic_stage_role(stage.stage_uuid, "pin_anchor")
    anchor = find_component_object(armature, component.component_uuid, anchor_role)
    if anchor is None:
        raise SemanticContactError("Pin anchor is missing.")

    scene = bpy.context.scene
    previous_frame = scene.frame_current
    try:
        pose_bone[stage.pin_property] = 0.0
        scene.frame_set(stage.pin_start)
        bpy.context.view_layer.update()
        anchor.matrix_world = armature.matrix_world @ pose_bone.matrix
        values = (
            (stage.pin_start - stage.blend_in, 0.0),
            (stage.pin_start, 1.0),
            (stage.pin_end, 1.0),
            (stage.pin_end + stage.blend_out, 0.0),
        )
        data_path = f'["{stage.pin_property}"]'
        for frame, value in values:
            pose_bone[stage.pin_property] = value
            pose_bone.keyframe_insert(data_path=data_path, frame=frame, group=pose_bone.name)
        action = armature.animation_data.action if armature.animation_data else None
        full_path = pose_bone.path_from_id(data_path)
        if action is not None:
            for fcurve in functions.iter_action_fcurves(action):
                if fcurve.data_path == full_path:
                    for point in fcurve.keyframe_points:
                        point.interpolation = "LINEAR"
        pose_bone[stage.pin_property] = 0.0
    finally:
        scene.frame_set(previous_frame)
        bpy.context.view_layer.update()
    return values


__all__ = [
    "ContactPinArtifacts",
    "SemanticContactError",
    "ensure_contact_pin_artifacts",
    "key_pin_range",
    "validate_pin_ranges",
]
