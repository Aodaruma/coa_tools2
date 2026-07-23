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


def _addon_root(module_name):
    """Return the add-on root for traditional and Blender Extension imports."""
    parts = module_name.split(".")
    try:
        package_index = parts.index(MODULE_NAME)
    except ValueError:
        return None
    return ".".join(parts[: package_index + 1])


def _loaded_addon_roots():
    return {
        root
        for module_name in sys.modules
        if (root := _addon_root(module_name)) is not None
    }


def _remove_old_handlers(module_name):
    handler_lists = (
        bpy.app.handlers.depsgraph_update_pre,
        bpy.app.handlers.depsgraph_update_post,
        bpy.app.handlers.frame_change_post,
        bpy.app.handlers.load_post,
    )
    for handler_list in handler_lists:
        for callback in list(handler_list):
            callback_module = getattr(callback, "__module__", "")
            if callback_module == module_name or callback_module.startswith(
                f"{module_name}."
            ):
                handler_list.remove(callback)


def _fallback_unregister(module, module_name):
    """Best-effort cleanup for older versions with incomplete unregister()."""
    unregister_keymaps = getattr(module, "unregister_keymaps", None)
    if unregister_keymaps is not None:
        try:
            unregister_keymaps()
        except Exception:
            traceback.print_exc()

    edit_mesh = sys.modules.get(f"{module_name}.operators.edit_mesh")
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
    if hasattr(bpy.types.Object, "coa_tools2_rig"):
        del bpy.types.Object.coa_tools2_rig

    for cls in reversed(getattr(module, "classes", ())):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    _remove_old_handlers(module_name)


def _unload_existing_addons():
    # Unload Extension imports first, then the traditional development import.
    roots = sorted(_loaded_addon_roots(), key=lambda name: name == MODULE_NAME)
    for module_name in roots:
        module = sys.modules.get(module_name)
        if module is None:
            continue
        try:
            addon_utils.disable(module_name, default_set=False)
        except Exception:
            traceback.print_exc()
            _fallback_unregister(module, module_name)

    for module_name in list(sys.modules):
        if _addon_root(module_name) in roots:
            sys.modules.pop(module_name, None)


def _verify_object_properties():
    probe = bpy.data.objects.new("COA_RigPropertyProbe", None)
    try:
        properties = probe.coa_tools2_rig
        required = ("rig_controls", "rig_controls_index", "rig_validation_issues")
        missing = [name for name in required if not hasattr(properties, name)]
        if missing:
            raise RuntimeError(
                "Loaded RigObjectProperties is stale; missing: " + ", ".join(missing)
            )
    finally:
        bpy.data.objects.remove(probe)


def main():
    addons_root_value = os.environ.get("COA_TOOLS2_TEST_ADDONS")
    if not addons_root_value:
        raise RuntimeError("COA_TOOLS2_TEST_ADDONS is not configured by the launcher.")
    addons_root = Path(addons_root_value).resolve()
    expected_package = (addons_root / MODULE_NAME).resolve()

    _unload_existing_addons()
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
    print("COA Tools 2 manual-test source and RigObjectProperties verified.")


if __name__ == "__main__":
    main()
