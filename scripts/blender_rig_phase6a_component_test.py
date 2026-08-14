#!/usr/bin/env python3
"""Background Blender persistence test for Phase 6A rig components."""

from __future__ import annotations

import os
import sys
import tempfile
import uuid

import addon_utils
import bpy


def main():
    if not addon_utils.check("coa_tools2")[1]:
        if addon_utils.enable("coa_tools2", default_set=False, persistent=False) is None:
            raise RuntimeError("Could not enable coa_tools2.")

    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object
    assert armature is not None and armature.type == "ARMATURE"
    rig_data = armature.coa_tools2_rig
    assert hasattr(rig_data, "rig_components")

    component = rig_data.rig_components.add()
    component.component_uuid = str(uuid.uuid4())
    component.semantic_id = "limb.arm.l"
    component.label = "Arm.L"
    component.component_type = "LIMB_IK"
    component.side = "LEFT"
    component.orientation_mode = "SOURCE_BONE"
    component.orientation_reference = "hand.L"
    component.depth_mode = "LIMITED"
    component.depth_min = -0.4
    component.depth_max = 0.6
    component.widget = "HAND"
    component.widget_size = 1.25
    for bone_name in ("upper_arm.L", "forearm.L", "hand.L"):
        ref = component.source_bones.add()
        ref.bone_name = bone_name
    artifact = component.artifacts.add()
    artifact.artifact_uuid = str(uuid.uuid4())
    artifact.role = "CONTROL_BONE"
    artifact.data_type = "BONE"
    artifact.bone_name = "CTRL_hand_ik.L"
    artifact.owned = True

    from coa_tools2.rig_control.blender.properties import component_to_spec
    from coa_tools2.rig_control.component_validation import validate_component_spec

    spec = component_to_spec(component)
    assert not validate_component_spec(spec)
    component_uuid = component.component_uuid

    file_descriptor, blend_path = tempfile.mkstemp(
        prefix="coa_phase6a_",
        suffix=".blend",
    )
    os.close(file_descriptor)
    try:
        bpy.ops.wm.save_as_mainfile(filepath=blend_path)
        bpy.ops.wm.open_mainfile(filepath=blend_path)
        armature = bpy.data.objects.get("SpriteObject")
        assert armature is not None
        components = armature.coa_tools2_rig.rig_components
        assert len(components) == 1
        restored = components[0]
        assert restored.component_uuid == component_uuid
        assert restored.orientation_mode == "SOURCE_BONE"
        assert restored.depth_mode == "LIMITED"
        assert tuple(ref.bone_name for ref in restored.source_bones) == (
            "upper_arm.L",
            "forearm.L",
            "hand.L",
        )
        assert restored.artifacts[0].bone_name == "CTRL_hand_ik.L"
    finally:
        if os.path.exists(blend_path):
            os.unlink(blend_path)

    print("COA rig Phase 6A component persistence test OK.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"Rig Phase 6A test failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise
