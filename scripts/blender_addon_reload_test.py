#!/usr/bin/env python3
"""Regression test for loading existing projects after an add-on replacement."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import addon_utils
import bpy


REQUIRED_RIG_PROPERTIES = (
    "rig_controls",
    "rig_controls_index",
    "rig_validation_issues",
)


def assert_rig_properties(obj):
    missing = [
        name for name in REQUIRED_RIG_PROPERTIES if not hasattr(obj.coa_tools2_rig, name)
    ]
    assert not missing, f"Stale ObjectProperties, missing: {missing}"


def main():
    module = addon_utils.enable("coa_tools2", default_set=False, persistent=True)
    assert module is not None

    bpy.ops.object.armature_add()
    legacy_sprite = bpy.context.active_object
    legacy_sprite.name = "ExistingProjectSprite"
    legacy_sprite.coa_tools2["sprite_object"] = True
    assert_rig_properties(legacy_sprite)
    legacy_control = legacy_sprite.coa_tools2.rig_controls.add()
    legacy_control.control_uuid = "legacy-control"
    legacy_control.semantic_id = "control.legacy"
    legacy_control.label = "Legacy Control"

    with tempfile.TemporaryDirectory() as tempdir:
        filepath = Path(tempdir) / "existing_project.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(filepath))

        addon_utils.disable("coa_tools2", default_set=False)
        assert not hasattr(bpy.types.Object, "coa_tools2")
        assert not hasattr(bpy.types.Object, "coa_tools2_rig")
        assert not hasattr(bpy.types.WindowManager, "coa_tools2")

        module = addon_utils.enable(
            "coa_tools2",
            default_set=False,
            persistent=True,
        )
        assert module is not None
        bpy.ops.wm.open_mainfile(filepath=str(filepath))

        loaded_sprite = bpy.data.objects["ExistingProjectSprite"]
        assert_rig_properties(loaded_sprite)
        from coa_tools2.rig_control.blender.properties import get_rig_data

        migrated = get_rig_data(loaded_sprite)
        assert len(migrated.rig_controls) == 1
        assert migrated.rig_controls[0].control_uuid == "legacy-control"

        addon_utils.disable("coa_tools2", default_set=False)
        assert not hasattr(bpy.types.Object, "coa_tools2")
        assert not hasattr(bpy.types.Object, "coa_tools2_rig")
        assert not hasattr(bpy.types.WindowManager, "coa_tools2")

    print("COA Tools 2 existing-project reload test OK.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Existing-project reload test failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
