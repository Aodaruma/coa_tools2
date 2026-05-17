#!/usr/bin/env python3
"""Sync Blender add-on metadata version from a release tag or version."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INIT_FILE = ROOT / "coa_tools2" / "__init__.py"
MANIFEST_FILE = ROOT / "coa_tools2" / "blender_manifest.toml"

STABLE_TAG_RE = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)$")
PRERELEASE_TAG_RE = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)-b\d+$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
INIT_VERSION_RE = re.compile(
    r'(?m)^\s*"version":\s*\((\d+),\s*(\d+),\s*(\d+)\),\s*$'
)
MANIFEST_VERSION_RE = re.compile(r'(?m)^version\s*=\s*"(\d+\.\d+\.\d+)"\s*$')


def version_from_args(version: str | None, tag: str | None) -> str:
    if bool(version) == bool(tag):
        raise SystemExit("Specify exactly one of --version or --tag.")

    if version is not None:
        if not VERSION_RE.match(version):
            raise SystemExit(f"Unsupported version format: {version}")
        return version

    assert tag is not None
    match = STABLE_TAG_RE.match(tag) or PRERELEASE_TAG_RE.match(tag)
    if not match:
        raise SystemExit(f"Unsupported tag format: {tag}")
    return match.group("version")


def version_tuple_text(version: str) -> str:
    return "(" + ", ".join(version.split(".")) + ")"


def replace_checked(
    text: str,
    pattern: str,
    replacement: str,
    path: Path,
    *,
    expected_count: int | None = 1,
    min_count: int = 1,
) -> str:
    new_text, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
    if expected_count is not None and count != expected_count:
        raise SystemExit(
            f"Expected {expected_count} version field(s) in {path}, found {count}"
        )
    if count < min_count:
        raise SystemExit(f"Could not update expected version field in {path}")
    return new_text


def sync(version: str, check: bool) -> bool:
    tuple_value = version_tuple_text(version)

    init_text = INIT_FILE.read_text(encoding="utf-8")
    manifest_text = MANIFEST_FILE.read_text(encoding="utf-8")

    new_init_text = replace_checked(
        init_text,
        r'(?m)^(\s*"version":\s*)\(\d+,\s*\d+,\s*\d+\)(,\s*)$',
        rf"\g<1>{tuple_value}\g<2>",
        INIT_FILE,
        expected_count=None,
        min_count=2,
    )
    new_manifest_text = replace_checked(
        manifest_text,
        r'(?m)^(version\s*=\s*)"\d+\.\d+\.\d+"(\s*)$',
        rf'\g<1>"{version}"\g<2>',
        MANIFEST_FILE,
    )

    changed = init_text != new_init_text or manifest_text != new_manifest_text
    if check:
        if changed:
            print(f"Blender add-on metadata is not synced to {version}.", file=sys.stderr)
        return not changed

    if init_text != new_init_text:
        INIT_FILE.write_text(new_init_text, encoding="utf-8", newline="")
    if manifest_text != new_manifest_text:
        MANIFEST_FILE.write_text(new_manifest_text, encoding="utf-8", newline="")
    return True


def check_consistent() -> bool:
    init_text = INIT_FILE.read_text(encoding="utf-8")
    manifest_text = MANIFEST_FILE.read_text(encoding="utf-8")

    init_versions = {
        ".".join(match.groups()) for match in INIT_VERSION_RE.finditer(init_text)
    }
    manifest_versions = set(MANIFEST_VERSION_RE.findall(manifest_text))

    versions = init_versions | manifest_versions
    if len(versions) == 1 and init_versions and manifest_versions:
        return True

    print("Blender add-on metadata versions are inconsistent.", file=sys.stderr)
    print(f"{INIT_FILE}: {sorted(init_versions) or 'missing'}", file=sys.stderr)
    print(f"{MANIFEST_FILE}: {sorted(manifest_versions) or 'missing'}", file=sys.stderr)
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version")
    parser.add_argument("--tag")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--check-consistent", action="store_true")
    args = parser.parse_args()

    if args.check_consistent:
        if args.version or args.tag or args.check:
            raise SystemExit("--check-consistent cannot be combined with other options.")
        return 0 if check_consistent() else 1

    version = version_from_args(args.version, args.tag)
    return 0 if sync(version, args.check) else 1


if __name__ == "__main__":
    raise SystemExit(main())
