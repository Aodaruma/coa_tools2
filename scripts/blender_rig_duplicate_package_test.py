#!/usr/bin/env python3
"""Reproduce a traditional/Extension RNA collision around Add Rig Control."""

from __future__ import annotations

import sys

import addon_utils
import bpy


class ForeignObjectProperties(bpy.types.PropertyGroup):
    """Stand-in for an installed Extension build without rig properties."""


ForeignObjectProperties.__annotations__ = {
    "type": bpy.props.StringProperty(default="MESH"),
    "alpha": bpy.props.FloatProperty(default=1.0),
    "alpha_last": bpy.props.FloatProperty(default=1.0),
}
ForeignObjectProperties.__module__ = "bl_ext.user_default.coa_tools2.properties"


def main():
    if addon_utils.enable("coa_tools2", default_set=False, persistent=False) is None:
        raise RuntimeError("Could not enable coa_tools2.")

    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object
    legacy_control = armature.coa_tools2.rig_controls.add()
    legacy_control.control_uuid = "legacy-hidden-control"
    legacy_control.label = "Legacy Hidden Control"
    legacy_control.control_type = "POINT_2D_RECT"

    # The real Extension class still has the base properties used by these
    # callbacks. Remove them in this reduced stand-in so unrelated callbacks do
    # not obscure the rig-specific regression.
    for handler_list in (
        bpy.app.handlers.depsgraph_update_pre,
        bpy.app.handlers.depsgraph_update_post,
    ):
        for callback in list(handler_list):
            if getattr(callback, "__module__", "").startswith("coa_tools2"):
                handler_list.remove(callback)

    # Simulate the older Extension registering Object.coa_tools2 after the
    # development build. Its UI/operator modules do not own this RNA anymore.
    del bpy.types.Object.coa_tools2
    bpy.utils.register_class(ForeignObjectProperties)
    bpy.types.Object.coa_tools2 = bpy.props.PointerProperty(
        type=ForeignObjectProperties
    )
    armature.coa_tools2["sprite_object"] = True

    assert (
        type(armature.coa_tools2).__module__
        == "bl_ext.user_default.coa_tools2.properties"
    )
    assert not hasattr(armature.coa_tools2, "rig_controls")

    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="POSE")
    result = bpy.ops.coa_tools2.add_rig_control(
        "EXEC_DEFAULT",
        label="Duplicate Package Safe",
        control_type="SLIDER_1D",
    )
    assert result == {"FINISHED"}, result
    assert len(armature.coa_tools2_rig.rig_controls) == 2
    assert (
        armature.coa_tools2_rig.rig_controls[0].control_uuid
        == "legacy-hidden-control"
    )
    assert (
        armature.coa_tools2_rig.rig_controls[0].control_type
        == "POINT_2D_RECT"
    )
    assert (
        armature.coa_tools2_rig.rig_controls[1].label
        == "Duplicate Package Safe"
    )

    # The synthetic legacy entry has no compiled artifacts; remove it before
    # checking that the newly created control itself validates cleanly.
    armature.coa_tools2_rig.rig_controls.remove(0)
    bpy.ops.coa_tools2.validate_rig()
    assert len(armature.coa_tools2_rig.rig_validation_issues) == 0

    del bpy.types.Object.coa_tools2
    bpy.utils.unregister_class(ForeignObjectProperties)
    addon_utils.disable("coa_tools2", default_set=False)
    print("COA rig duplicate-package test OK.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"Duplicate-package test failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise
