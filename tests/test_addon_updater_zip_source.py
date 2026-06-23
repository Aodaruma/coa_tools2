import importlib.util
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ADDON_UPDATER_PATH = REPO_ROOT / "coa_tools2" / "addon_updater.py"


def load_addon_updater_module():
    sys.modules.setdefault("bpy", types.ModuleType("bpy"))
    sys.modules.setdefault("addon_utils", types.ModuleType("addon_utils"))

    module_name = "addon_updater_under_test"
    spec = importlib.util.spec_from_file_location(module_name, ADDON_UPDATER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AddonUpdaterZipSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.addon_updater = load_addon_updater_module()

    def make_updater(self, tempdir, zip_entries):
        tempdir = Path(tempdir)
        stage_path = tempdir / "stage"
        staging_path = stage_path / "update_staging"
        addon_root = tempdir / "installed" / "coa_tools2"
        source_zip = staging_path / "source.zip"

        staging_path.mkdir(parents=True)
        addon_root.mkdir(parents=True)
        with zipfile.ZipFile(source_zip, "w") as zf:
            for entry in zip_entries:
                zf.writestr(entry, "")

        updater = self.addon_updater.Singleton_updater()
        updater._addon = "coa_tools2"
        updater._subfolder_path = "Blender/coa_tools2"
        updater._updater_path = str(stage_path)
        updater._addon_root = str(addon_root)
        updater._source_zip = str(source_zip)
        updater._json = {}

        calls = {}

        def fake_merge(base, merger, clean=False):
            calls["base"] = base
            calls["merger"] = merger
            calls["clean"] = clean

        updater.deepMergeDirectory = fake_merge
        updater.save_updater_json = lambda: None
        updater.reload_addon = lambda: None

        return updater, calls

    def test_falls_back_to_addon_folder_in_github_zip(self):
        with tempfile.TemporaryDirectory() as tempdir:
            updater, calls = self.make_updater(
                tempdir,
                [
                    "Aodaruma-coa_tools2-1234567/coa_tools2/__init__.py",
                    "Aodaruma-coa_tools2-1234567/coa_tools2/addon_updater.py",
                ],
            )

            updater.unpack_staged_zip(clean=True)

            self.assertEqual(
                Path(calls["merger"]).parts[-2:],
                ("Aodaruma-coa_tools2-1234567", "coa_tools2"),
            )
            self.assertTrue(calls["clean"])

    def test_prefers_configured_subfolder_when_present(self):
        with tempfile.TemporaryDirectory() as tempdir:
            updater, calls = self.make_updater(
                tempdir,
                [
                    "Aodaruma-coa_tools2-1234567/Blender/coa_tools2/__init__.py",
                    "Aodaruma-coa_tools2-1234567/coa_tools2/__init__.py",
                ],
            )

            updater.unpack_staged_zip()

            self.assertEqual(
                Path(calls["merger"]).parts[-2:],
                ("Blender", "coa_tools2"),
            )

    def test_rejects_multiple_addon_folder_matches(self):
        with tempfile.TemporaryDirectory() as tempdir:
            updater, calls = self.make_updater(
                tempdir,
                [
                    "root-a/coa_tools2/__init__.py",
                    "root-b/coa_tools2/__init__.py",
                ],
            )

            with self.assertRaises(ValueError):
                updater.unpack_staged_zip()

            self.assertEqual(calls, {})

    def test_rejects_multiple_configured_subfolder_matches(self):
        with tempfile.TemporaryDirectory() as tempdir:
            updater, calls = self.make_updater(
                tempdir,
                [
                    "root-a/Blender/coa_tools2/__init__.py",
                    "root-b/Blender/coa_tools2/__init__.py",
                ],
            )

            with self.assertRaises(ValueError):
                updater.unpack_staged_zip()

            self.assertEqual(calls, {})

    def test_ignores_unsafe_relative_subfolder_candidates(self):
        with tempfile.TemporaryDirectory() as tempdir:
            updater, _calls = self.make_updater(
                tempdir,
                ["root-a/coa_tools2/__init__.py"],
            )
            updater._subfolder_path = "../coa_tools2"

            self.assertEqual(updater._source_subfolder_candidates(), ["coa_tools2"])


if __name__ == "__main__":
    unittest.main()
