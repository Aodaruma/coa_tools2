#!/usr/bin/env python3
"""Blender 5.1 ownership/rollback regression for Semantic Spline rigs."""

from __future__ import annotations

from pathlib import Path
import sys
import uuid

import bpy


def _add_bone(edit_bones, name, head, tail, parent=None):
    bone = edit_bones.new(name)
    bone.head = head
    bone.tail = tail
    bone.parent = parent
    bone.use_connect = parent is not None
    return bone


def _expect_compile_conflict(compile_semantic_component, armature, component):
    try:
        compile_semantic_component(armature, component)
    except Exception as exc:
        message = str(exc).lower()
        assert "constraint" in message or "hook" in message, str(exc)
        return str(exc)
    raise AssertionError("Ambiguous ownership did not stop compilation.")


def main():
    import coa_tools2
    from coa_tools2.rig_control.blender.component_safety import (
        ensure_unique_component_instance,
    )
    from coa_tools2.rig_control.blender.semantic_compiler import (
        compile_semantic_component,
    )

    coa_tools2.register()
    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object
    armature.name = "Phase7F_Ownership"

    bpy.ops.object.mode_set(mode="EDIT")
    chain = []
    for index in range(3):
        chain.append(
            _add_bone(
                armature.data.edit_bones,
                f"ownership.{index:03d}",
                (0.0, 0.0, float(index)),
                (0.0, 0.0, float(index + 1)),
                chain[-1] if chain else None,
            )
        )
    source_names = tuple(bone.name for bone in chain)
    bpy.ops.object.mode_set(mode="POSE")

    rig_data = armature.coa_tools2_rig
    rig_data.rig_instance_id = str(uuid.uuid4())
    component = rig_data.rig_components.add()
    component.component_uuid = str(uuid.uuid4())
    component.semantic_id = "ownership.spline"
    component.display_name = "Ownership Spline"
    component.component_type = "SEMANTIC"
    component.deformation_mode = "PARAMETRIC"
    for name in source_names:
        reference = component.source_bones.add()
        reference.bone_name = name

    stage = component.semantic_stages.add()
    stage.stage_uuid = str(uuid.uuid4())
    stage.semantic_id = "ownership.spline.stage"
    stage.label = "Spline"
    stage.stage_type = "SPLINE"
    stage.spline_control_count = 3
    for name in source_names:
        reference = stage.source_bones.add()
        reference.bone_name = name

    compiled = compile_semantic_component(armature, component)
    spline = compiled["stage_results"][stage.stage_uuid].spline_info
    curve_object = bpy.data.objects[spline.curve_object]

    # Bone ID properties are authoritative. A generated bone can be renamed
    # while a plain user bone reuses its old name; recompilation must update
    # generated references without modifying the user bone.
    old_control_name = spline.control_bones[1]
    renamed_control_name = f"{old_control_name}_RENAMED"
    armature.data.bones[old_control_name].name = renamed_control_name
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.mode_set(mode="EDIT")
    user_bone = _add_bone(
        armature.data.edit_bones,
        old_control_name,
        (3.0, 0.0, 0.0),
        (3.0, 0.0, 0.75),
    )
    user_head = user_bone.head.copy()
    bpy.ops.object.mode_set(mode="POSE")
    compiled = compile_semantic_component(armature, component)
    spline = compiled["stage_results"][stage.stage_uuid].spline_info
    assert renamed_control_name in spline.control_bones
    assert armature.data.bones[old_control_name].get("coa_rig_managed") is None
    assert (armature.data.bones[old_control_name].head_local - user_head).length < 1.0e-8
    assert any(
        modifier.subtarget == renamed_control_name
        for modifier in curve_object.modifiers
        if modifier.type == "HOOK"
    )

    # A copied Armature gets isolated data/Curve artifacts and can compile
    # without Constraint/Modifier ID properties (unsupported in Blender 5.1).
    bpy.ops.object.mode_set(mode="OBJECT")
    duplicate = armature.copy()
    duplicate.data = armature.data
    duplicate.name = "Phase7F_Ownership_Copy"
    bpy.context.scene.collection.objects.link(duplicate)
    old_instance_id = armature.coa_tools2_rig.rig_instance_id
    assert duplicate.coa_tools2_rig.rig_instance_id == old_instance_id
    assert ensure_unique_component_instance(duplicate)
    assert duplicate.coa_tools2_rig.rig_instance_id != old_instance_id
    assert duplicate.data != armature.data
    duplicate_component = duplicate.coa_tools2_rig.rig_components[0]
    duplicate_compiled = compile_semantic_component(duplicate, duplicate_component)
    duplicate_spline = duplicate_compiled["stage_results"][stage.stage_uuid].spline_info
    assert duplicate_spline.curve_object != spline.curve_object
    assert bpy.data.objects[duplicate_spline.curve_object] is not curve_object

    # Constraint rename + old-name reuse is ambiguous because Constraint RNA
    # has no ID properties. Compilation must stop and rollback without touching
    # either the renamed generated Constraint or the user Constraint.
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="POSE")
    constraint_artifact = next(
        artifact
        for artifact in component.artifacts
        if artifact.role.endswith(":spline_ik_constraint")
    )
    constraint_owner = armature.pose.bones[constraint_artifact.bone_name]
    saved_constraint_name = constraint_artifact.constraint_name
    generated_constraint = constraint_owner.constraints[saved_constraint_name]
    generated_constraint.name = f"{saved_constraint_name}_RENAMED"
    user_constraint = constraint_owner.constraints.new("COPY_ROTATION")
    user_constraint.name = saved_constraint_name
    user_constraint.influence = 0.375
    generated_pointer = generated_constraint.as_pointer()
    user_pointer = user_constraint.as_pointer()
    _expect_compile_conflict(compile_semantic_component, armature, component)
    assert generated_constraint.as_pointer() == generated_pointer
    assert user_constraint.as_pointer() == user_pointer
    assert user_constraint.type == "COPY_ROTATION"
    assert abs(user_constraint.influence - 0.375) < 1.0e-8
    assert constraint_owner.constraints[saved_constraint_name] == user_constraint

    constraint_owner.constraints.remove(user_constraint)
    generated_constraint.name = saved_constraint_name
    compile_semantic_component(armature, component)

    # Hook modifiers follow the same conservative rule. Pointer-based rollback
    # restores all pre-existing Hook state and never follows a stale name into
    # the user modifier that reused it.
    hook_artifact = next(
        artifact
        for artifact in component.artifacts
        if artifact.role.endswith(":spline_hook:0")
    )
    saved_hook_name = hook_artifact.constraint_name
    generated_hook = curve_object.modifiers[saved_hook_name]
    generated_hook.name = f"{saved_hook_name}_RENAMED"
    user_hook = curve_object.modifiers.new(saved_hook_name, "HOOK")
    user_hook.object = armature
    user_hook.subtarget = spline.control_bones[0]
    user_hook.strength = 0.425
    user_hook.vertex_indices_set([0])
    generated_hook_pointer = generated_hook.as_pointer()
    user_hook_pointer = user_hook.as_pointer()
    _expect_compile_conflict(compile_semantic_component, armature, component)
    assert generated_hook.as_pointer() == generated_hook_pointer
    assert user_hook.as_pointer() == user_hook_pointer
    assert abs(user_hook.strength - 0.425) < 1.0e-6
    assert curve_object.modifiers[saved_hook_name] == user_hook

    print(
        "PHASE7F_OWNERSHIP_ROLLBACK_OK",
        renamed_control_name,
        duplicate_spline.curve_object,
        saved_constraint_name,
        saved_hook_name,
    )


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
