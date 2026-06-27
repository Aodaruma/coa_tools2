import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "coa_tools2" / "dependency_manager.py"


def load_dependency_manager():
    spec = importlib.util.spec_from_file_location(
        "dependency_manager_under_test", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DependencyManagerTests(unittest.TestCase):
    def test_dependency_state_checks_new_vendor_modules_after_initial_miss(self):
        manager = load_dependency_manager()
        manager.REQUIRED_MODULES = (
            "fake_numpy_for_coa_tools2",
            "fake_cv2_for_coa_tools2",
        )
        original_modules = {
            name: sys.modules.get(name) for name in manager.REQUIRED_MODULES
        }
        try:
            for name in manager.REQUIRED_MODULES:
                sys.modules.pop(name, None)

            with tempfile.TemporaryDirectory() as tmpdir:
                vendor_path = Path(tmpdir)
                manager.get_vendor_path = lambda: str(vendor_path)

                state, errors = manager.dependency_state_with_errors()
                self.assertFalse(state["fake_cv2_for_coa_tools2"])
                self.assertIn("fake_cv2_for_coa_tools2", errors)

                (vendor_path / "fake_cv2_for_coa_tools2.py").write_text(
                    "VALUE = 'cv2'\n", encoding="utf-8"
                )
                (vendor_path / "fake_numpy_for_coa_tools2.py").write_text(
                    "VALUE = 'numpy'\n", encoding="utf-8"
                )

                state, errors = manager.dependency_state_with_errors()

                self.assertEqual(
                    {
                        "fake_numpy_for_coa_tools2": True,
                        "fake_cv2_for_coa_tools2": True,
                    },
                    state,
                )
                self.assertEqual({}, errors)
        finally:
            for name in manager.REQUIRED_MODULES:
                sys.modules.pop(name, None)
                original = original_modules[name]
                if original is not None:
                    sys.modules[name] = original


if __name__ == "__main__":
    unittest.main()
