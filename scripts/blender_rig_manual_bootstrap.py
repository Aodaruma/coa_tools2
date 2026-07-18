"""Load the manual-test add-on copy and reject stale installed modules."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys
import traceback

import addon_utils
import bpy


MODULE_NAME = "coa_tools2"


def _remove_old_handlers():
    handler_lists = (
        bpy.app.handlers.depsgraph_update_pre,
        bpy.app.handlers.depsgraph_update_post,
        bpy.app.handlers.frame_change_post,
        bpy.app.handlers.load_post,
    )
    for handler_list in handler_lists:
        for callback in list(handler_list):
            callback_module = getattr(callback, "__module__", "")
            if callback_module == MODULE_NAME or callback_module.startswith(
                f"{MODULE_NAME}."
            ):
                handler_list.remove(callback)


def _fallback_unregister(module):
    """Best-effort cleanup for older versions with incomplete unregister()."""
    unregister_keymaps = getattr(module, "unregister_keymaps", None)
    if unregister_keymaps is not None:
        try:
            unregister_keymaps()
        except Exception:
            traceback.print_exc()

    edit_mesh = sys.modules.get(f"{MODULE_NAME}.operators.edit_mesh")
    tool_class = getattr(edit_mesh, "COATOOLS2_TO_DrawPolygon", None)
    if tool_class is not None:
        try:
            bpy.utils.unregister_tool(tool_class)
        except RuntimeError:
            pass

    for owner_type in (
        bpy.types.Object,
        bpy.types.Scene,
        bpy.types.Mesh,
        bpy.types.Bone,
        bpy.types.WindowManager,
    ):
        if hasattr(owner_type, "coa_tools2"):
            delattr(owner_type, "coa_tools2")

    for cls in reversed(getattr(module, "classes", ())):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    _remove_old_handlers()


def _unload_existing_addon():
    module = sys.modules.get(MODULE_NAME)
    if module is not None:
        try:
            addon_utils.disable(MODULE_NAME, default_set=False)
        except Exception:
            traceback.print_exc()
            _fallback_unregister(module)

    for module_name in list(sys.modules):
        if module_name == MODULE_NAME or module_name.startswith(f"{MODULE_NAME}."):
            sys.modules.pop(module_name, None)


def _verify_object_properties():
    probe = bpy.data.objects.new("COA_RigPropertyProbe", None)
    try:
        properties = probe.coa_tools2
        required = ("rig_controls", "rig_controls_index", "rig_validation_issues")
        missing = [name for name in required if not hasattr(properties, name)]
        if missing:
            raise RuntimeError(
                "Loaded ObjectProperties is stale; missing: " + ", ".join(missing)
            )
    finally:
        bpy.data.objects.remove(probe)


def main():
    addons_root_value = os.environ.get("COA_TOOLS2_TEST_ADDONS")
    if not addons_root_value:
        raise RuntimeError("COA_TOOLS2_TEST_ADDONS is not configured by the launcher.")
    addons_root = Path(addons_root_value).resolve()
    expected_package = (addons_root / MODULE_NAME).resolve()

    _unload_existing_addon()
    sys.path[:] = [path for path in sys.path if Path(path or ".").resolve() != addons_root]
    sys.path.insert(0, str(addons_root))
    importlib.invalidate_caches()
    addon_utils.modules_refresh()

    module = addon_utils.enable(MODULE_NAME, default_set=False, persistent=True)
    if module is None:
        raise RuntimeError("Could not enable the COA Tools 2 manual-test copy.")
    actual_package = Path(module.__file__).resolve().parent
    if actual_package != expected_package:
        raise RuntimeError(
            f"Wrong COA Tools 2 copy loaded: {actual_package}; expected {expected_package}"
        )

    _verify_object_properties()
    print("COA Tools 2 manual-test source and ObjectProperties verified.")


if __name__ == "__main__":
    main()
