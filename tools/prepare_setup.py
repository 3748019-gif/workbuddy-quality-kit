"""Prepare the unchanged 4.4 installer in a new, explicitly selected directory.

Python 3.9+, standard library only. Does not install or change WorkBuddy settings.
The source repository remains unchanged. Existing output paths are refused.
"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import os
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).absolute().parent.parent
NAME = "workbuddy-quality-kit"


def no_symlinks(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("Symbolic links are not accepted: " + str(part))


def source_path(name):
    rel = PurePosixPath(name)
    if (not rel.parts or rel.is_absolute() or ".." in rel.parts
            or "\\" in name or rel.as_posix() != name):
        raise ValueError("Unsafe source path: " + name)
    path = ROOT.joinpath(*rel.parts)
    no_symlinks(path)
    if not path.is_file():
        raise ValueError("Missing source file: " + name)
    return path


def prepare(output):
    no_symlinks(ROOT)
    manifest = json.loads(source_path("release-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != "4.4" or not isinstance(manifest.get("files"), dict):
        raise ValueError("Invalid release manifest")
    verified = {}
    for name, expected in manifest["files"].items():
        data = source_path(name).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("Source hash mismatch: " + name)
        verified[name] = data
    if "bundle-manifest.json" not in verified:
        raise ValueError("Missing core manifest")
    core = json.loads(verified["bundle-manifest.json"])
    if (core.get("skill") != NAME or core.get("version") != "4.4"
            or len(core.get("files", {})) != 12 or "LICENSE" not in core["files"]):
        raise ValueError("Expected the 11 original 4.4 core files and MIT LICENSE")

    mapping = {"bundle-manifest.json": "bundle-manifest.json",
               "tools/setup-policy.json": "配置策略.json"}
    for name in ("install_skill.py", "install_entry.py", "selftest.py"):
        mapping["tools/" + name] = name
    for name, digest in core["files"].items():
        if name not in verified or hashlib.sha256(verified[name]).hexdigest() != digest:
            raise ValueError("Core source mismatch: " + name)
        mapping[name] = "skills/" + NAME + "/" + name
    fixtures = [name for name in verified if name.startswith("tests/fixtures/")]
    if len(fixtures) != 8:
        raise ValueError("Expected the eight synthetic 4.4 test fixtures")
    for name in fixtures:
        mapping[name] = "验收材料/" + PurePosixPath(name).name
    if any(name not in verified for name in mapping):
        raise ValueError("Setup payload is missing from release manifest")

    target = Path(os.path.abspath(os.path.expanduser(output)))
    no_symlinks(target)
    if target == ROOT or ROOT in target.parents:
        raise ValueError("Choose an output directory outside this repository")
    if target.exists():
        raise FileExistsError("Output already exists; choose a new directory")
    if not target.parent.is_dir():
        raise ValueError("Output parent must already exist")
    target.mkdir(exist_ok=False)
    for name, destination in mapping.items():
        path = target.joinpath(*PurePosixPath(destination).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(verified[name])
        if path.read_bytes() != verified[name]:
            raise ValueError("Written payload verification failed: " + destination)
    return {"ok": True, "version": "4.4", "setup_directory": str(target),
            "files": len(mapping), "installed": False,
            "next": "Run selftest.py in the prepared directory; inspect plan before any actual installation."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New directory outside the repository; parent must exist")
    args = parser.parse_args()
    try:
        result = prepare(args.output)
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error), "installed": False}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
