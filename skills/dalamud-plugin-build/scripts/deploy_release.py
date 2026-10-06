#!/usr/bin/env python
"""Deploy a Dalamud Release directory while skipping its package subdirectory."""

from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-dir", required=True, type=Path)
    parser.add_argument("--plugin-name", required=True)
    parser.add_argument(
        "--destination-root",
        type=Path,
        default=Path(r"D:\Games\FFXIV Plugins"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    release_dir = args.release_dir.resolve()
    plugin_name = args.plugin_name.strip()

    if not release_dir.is_dir():
        raise SystemExit(f"Release directory does not exist: {release_dir}")
    if not plugin_name or plugin_name in {".", ".."} or Path(plugin_name).name != plugin_name:
        raise SystemExit(f"Invalid plugin name: {plugin_name!r}")

    destination_root = args.destination_root.resolve()
    destination = destination_root / plugin_name
    destination.mkdir(parents=True, exist_ok=True)

    copied_files: list[tuple[Path, Path]] = []
    skipped: list[Path] = []

    for source in release_dir.iterdir():
        if source.name.casefold() == plugin_name.casefold():
            skipped.append(source)
            continue

        target = destination / source.name
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
            copied_files.extend(
                (file, target / file.relative_to(source))
                for file in source.rglob("*")
                if file.is_file()
            )
        elif source.is_file():
            shutil.copy2(source, target)
            copied_files.append((source, target))

    if not copied_files:
        raise SystemExit(f"No deployable files found in: {release_dir}")

    mismatches = [
        (source, target)
        for source, target in copied_files
        if not target.is_file()
        or source.stat().st_size != target.stat().st_size
        or file_hash(source) != file_hash(target)
    ]
    if mismatches:
        for source, target in mismatches:
            print(f"MISMATCH {source} -> {target}")
        return 1

    for path in skipped:
        print(f"SKIPPED package directory: {path}")
    print(f"DEPLOYED {len(copied_files)} files to: {destination}")
    print("VERIFIED SHA-256 equality for every deployed file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
