from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
READ_ONLY_CALLBACKS = {"poll", "draw"}
READ_ONLY_HELPERS = {
    "_active_component",
    "_active_control",
    "_active_state_point",
    "get_rig_data",
}
AUDITED_MODULES = (
    "coa_tools2/rig_control/blender/operators.py",
    "coa_tools2/rig_control/blender/component_operators.py",
    "coa_tools2/rig_control/blender/semantic_operators.py",
    "coa_tools2/rig_control/blender/semantic_presentations.py",
    "coa_tools2/rig_control/blender/ui.py",
    "coa_tools2/rig_control/blender/component_ui.py",
    "coa_tools2/rig_control/blender/semantic_ui.py",
    "coa_tools2/rig_control/blender/workspace_ui.py",
)


def _called_name(call: ast.Call) -> str:
    return call.func.id if isinstance(call.func, ast.Name) else ""


def _migration_keyword(call: ast.Call):
    return next((keyword.value for keyword in call.keywords if keyword.arg == "migrate"), None)


class RigPollMigrationTests(unittest.TestCase):
    def test_read_only_callbacks_never_request_lazy_migration(self):
        failures = []
        for relative in AUDITED_MODULES:
            path = ROOT / relative
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for function in (
                node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
            ):
                is_read_only = (
                    function.name in READ_ONLY_CALLBACKS
                    or function.name.endswith("_items")
                )
                if not is_read_only:
                    continue
                for call in (
                    node for node in ast.walk(function) if isinstance(node, ast.Call)
                ):
                    if _called_name(call) not in READ_ONLY_HELPERS:
                        continue
                    keyword = _migration_keyword(call)
                    if not (
                        isinstance(keyword, ast.Constant)
                        and keyword.value is False
                    ):
                        failures.append(
                            f"{relative}:{call.lineno} {function.name} calls "
                            f"{_called_name(call)} without migrate=False"
                        )
        self.assertEqual([], failures, "\n".join(failures))

    def test_writable_operator_callbacks_keep_migration_enabled(self):
        failures = []
        for relative in AUDITED_MODULES:
            path = ROOT / relative
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for function in (
                node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
            ):
                if function.name not in {"execute", "invoke"}:
                    continue
                for call in (
                    node for node in ast.walk(function) if isinstance(node, ast.Call)
                ):
                    if _called_name(call) not in READ_ONLY_HELPERS:
                        continue
                    keyword = _migration_keyword(call)
                    if isinstance(keyword, ast.Constant) and keyword.value is False:
                        failures.append(
                            f"{relative}:{call.lineno} {function.name} disables "
                            f"migration through {_called_name(call)}"
                        )
        self.assertEqual([], failures, "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
