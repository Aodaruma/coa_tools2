#!/usr/bin/env python3
"""Enable and disable the add-on inside Blender using an isolated user path."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import addon_utils
import bpy


MODULE_NAME = "coa_tools2"
ROOT = Path(__file__).resolve().parents[1]
CHECKOUT_ADDON_DIR = (ROOT / MODULE_NAME).resolve()


def load_required_blender_version() -> tuple[int, int, int]:
    init_file = ROOT / MODULE_NAME / "__init__.py"
    tree = ast.parse(init_file.read_text(encoding="utf-8"), filename=str(init_file))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "bl_info"
            for target in node.targets
        ):
            continue
        bl_info = ast.literal_eval(node.value)
        version = bl_info.get("blender")
        if (
            isinstance(version, tuple)
            and len(version) == 3
            and all(isinstance(part, int) for part in version)
        ):
            return version
    raise RuntimeError("Could not read bl_info['blender'].")


def path_is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent)
        return True
    except ValueError:
        return False


def main() -> int:
    required_version = load_required_blender_version()
    if bpy.app.version < required_version:
        print(
            "Skipping add-on enable smoke: "
            f"Blender {bpy.app.version_string} is older than {required_version}."
        )
        return 0

    module = addon_utils.enable(MODULE_NAME, default_set=True, persistent=False)
    if module is None:
        raise RuntimeError(f"addon_utils.enable({MODULE_NAME!r}) returned None.")

    module_file = Path(module.__file__).resolve()
    if path_is_inside(module_file, CHECKOUT_ADDON_DIR):
        raise RuntimeError(
            "Smoke test loaded the checkout add-on directly. "
            "Copy it to an isolated BLENDER_USER_SCRIPTS/addons path first."
        )

    loaded, enabled = addon_utils.check(MODULE_NAME)
    if not loaded or not enabled:
        raise RuntimeError(
            f"Add-on did not enable cleanly: loaded={loaded}, enabled={enabled}"
        )

    if MODULE_NAME not in {addon.module for addon in bpy.context.preferences.addons}:
        raise RuntimeError("Add-on preferences entry was not registered.")

    addon_utils.disable(MODULE_NAME, default_set=True)
    loaded, enabled = addon_utils.check(MODULE_NAME)
    if loaded or enabled:
        raise RuntimeError(
            f"Add-on did not disable cleanly: loaded={loaded}, enabled={enabled}"
        )

    print(f"{MODULE_NAME} Blender enable/disable smoke OK.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Blender smoke failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
