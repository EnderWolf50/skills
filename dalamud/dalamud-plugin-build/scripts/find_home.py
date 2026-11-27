#!/usr/bin/env python
"""Locate the Dalamud home repo and its machine-local deploy root."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKILL = "dalamud-plugin-build"
CONFIG = Path(".local") / "dalamud.json"


def lists_skill(folder: Path) -> bool:
    try:
        lock = json.loads((folder / "skills-lock.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(lock, dict) and SKILL in lock.get("skills", {})


def find_home(starts: list[Path]) -> Path | None:
    for start in starts:
        for folder in (start, *start.parents):
            if lists_skill(folder):
                return folder
    return None


def read_config(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except ValueError as error:
        raise SystemExit(f"{path} is not valid JSON: {error}")
    if not isinstance(data, dict):
        raise SystemExit(f"{path} must hold a JSON object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set-deploy-root", type=Path, help="record the deploy root in the home repo's local config")
    args = parser.parse_args()

    home = find_home([Path(__file__).resolve().parent, Path.cwd().resolve()])
    if home is None:
        print(
            f"home repo not found: no skills-lock.json listing {SKILL} above this skill or the current directory",
            file=sys.stderr,
        )
        return 1

    config_path = home / CONFIG
    config = read_config(config_path)
    if args.set_deploy_root is not None:
        config["deployRoot"] = str(args.set_deploy_root.resolve())
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"home": str(home), "deployRoot": config.get("deployRoot"), "config": str(config_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
