#!/usr/bin/env python3
"""Repository-level sanity checks for the COA Tools 2 Blender add-on."""

from __future__ import annotations

import ast
import re
import tempfile
import zipfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Blender/Python 3.10 fallback.
    tomllib = None


ROOT = Path(__file__).resolve().parents[1]
ADDON_DIR = ROOT / "coa_tools2"
MANIFEST_FILE = ADDON_DIR / "blender_manifest.toml"
INIT_FILE = ADDON_DIR / "__init__.py"
RELEASE_DIRS = ("GIMP", "Krita", "coa_tools2", "Photoshop", "Godot")
PYTHON_CHECK_ROOTS = ("coa_tools2", "Krita", "GIMP", "scripts")
ZIP_REQUIRED_FILES = (
    "coa_tools2/__init__.py",
    "coa_tools2/blender_manifest.toml",
    "coa_tools2/icons/coa_tools.draw_bone.dat",
    "coa_tools2/icons/coa_tools.draw_polygon.dat",
)
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def load_manifest() -> dict:
    if tomllib is not None:
        return tomllib.loads(MANIFEST_FILE.read_text(encoding="utf-8"))

    data: dict[str, object] = {}
    for raw_line in MANIFEST_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = [part.strip() for part in line.split("=", 1)]
        if value.startswith('"') and value.endswith('"'):
            data[key] = value[1:-1]
        elif value.startswith("[") and value.endswith("]"):
            data[key] = [
                item.strip().strip('"')
                for item in value[1:-1].split(",")
                if item.strip()
            ]
    return data


def load_bl_info() -> dict:
    tree = ast.parse(INIT_FILE.read_text(encoding="utf-8"), filename=str(INIT_FILE))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "bl_info"
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if isinstance(value, dict):
                return value
    raise SystemExit(f"Missing bl_info in {INIT_FILE}")


def version_tuple_to_text(version: object) -> str:
    if (
        isinstance(version, tuple)
        and len(version) == 3
        and all(isinstance(part, int) for part in version)
    ):
        return ".".join(str(part) for part in version)
    raise SystemExit(f"Invalid bl_info version: {version!r}")


def check_python_syntax() -> None:
    files: list[Path] = []
    for root_name in PYTHON_CHECK_ROOTS:
        root = ROOT / root_name
        if root.exists():
            files.extend(sorted(root.rglob("*.py")))

    for path in files:
        source = path.read_text(encoding="utf-8-sig")
        compile(source, str(path), "exec")

    print(f"Compiled {len(files)} Python files.")


def check_metadata() -> None:
    manifest = load_manifest()
    bl_info = load_bl_info()

    required_manifest = {
        "id": "coa_tools2",
        "type": "add-on",
        "name": "COA Tools 2",
    }
    for key, expected in required_manifest.items():
        actual = manifest.get(key)
        if actual != expected:
            raise SystemExit(
                f"{MANIFEST_FILE}: expected {key}={expected!r}, found {actual!r}"
            )

    manifest_version = manifest.get("version")
    if not isinstance(manifest_version, str) or not VERSION_RE.match(manifest_version):
        raise SystemExit(f"{MANIFEST_FILE}: invalid version {manifest_version!r}")

    bl_info_version = version_tuple_to_text(bl_info.get("version"))
    if bl_info_version != manifest_version:
        raise SystemExit(
            "Version mismatch: "
            f"bl_info={bl_info_version}, manifest={manifest_version}"
        )

    blender_min = manifest.get("blender_version_min")
    if not isinstance(blender_min, str) or not VERSION_RE.match(blender_min):
        raise SystemExit(f"{MANIFEST_FILE}: invalid blender_version_min {blender_min!r}")

    print(
        "Metadata OK: "
        f"version {manifest_version}, Blender minimum {blender_min}."
    )


def check_release_roots() -> None:
    for dirname in RELEASE_DIRS:
        path = ROOT / dirname
        if not path.is_dir():
            raise SystemExit(f"Missing release directory: {path}")
        if not any(path.iterdir()):
            raise SystemExit(f"Release directory is empty: {path}")
    print("Release roots OK.")


def should_skip_from_zip(path: Path) -> bool:
    parts = set(path.parts)
    return (
        "__pycache__" in parts
        or path.suffix in {".pyc", ".pyo"}
        or path.name == "updater_status.json"
    )


def check_addon_zip_layout() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "coa_tools2.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(ADDON_DIR.rglob("*")):
                if path.is_file() and not should_skip_from_zip(path.relative_to(ROOT)):
                    archive.write(path, path.relative_to(ROOT).as_posix())

        with zipfile.ZipFile(zip_path) as archive:
            names = set(archive.namelist())
            for required in ZIP_REQUIRED_FILES:
                if required not in names:
                    raise SystemExit(f"Add-on zip missing required file: {required}")
            if any(name.startswith("/") or ".." in Path(name).parts for name in names):
                raise SystemExit("Add-on zip contains unsafe path entries.")

    print("Add-on zip layout OK.")


def main() -> int:
    check_python_syntax()
    check_metadata()
    check_release_roots()
    check_addon_zip_layout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
