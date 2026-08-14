#!/usr/bin/env python3
"""Check that the manual bootstrap purges Blender Extension import roots."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType


EXTENSION_ROOT = "bl_ext.user_default.coa_tools2"


def load_bootstrap():
    path = Path(__file__).with_name("blender_rig_manual_bootstrap.py")
    spec = importlib.util.spec_from_file_location("coa_rig_bootstrap_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main():
    bootstrap = load_bootstrap()
    assert bootstrap._addon_root(EXTENSION_ROOT) == EXTENSION_ROOT
    assert (
        bootstrap._addon_root(f"{EXTENSION_ROOT}.rig_control.blender")
        == EXTENSION_ROOT
    )

    extension = ModuleType(EXTENSION_ROOT)
    extension.__file__ = __file__
    extension.__path__ = []
    extension.unregister = lambda: None
    sys.modules[EXTENSION_ROOT] = extension
    sys.modules[f"{EXTENSION_ROOT}.properties"] = ModuleType(
        f"{EXTENSION_ROOT}.properties"
    )

    bootstrap.main()

    assert EXTENSION_ROOT not in sys.modules
    assert f"{EXTENSION_ROOT}.properties" not in sys.modules
    assert "coa_tools2" in sys.modules
    bootstrap._verify_object_properties()
    print("COA rig bootstrap Extension-namespace test OK.")


if __name__ == "__main__":
    main()
