#!/usr/bin/env python3
"""Check runtime env/data files declared in apps.yaml."""

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML not found — run: pip3 install pyyaml")


REPO_ROOT = Path(__file__).parent.parent
APPS_YAML = REPO_ROOT / "apps.yaml"


def print_missing(app: str, field: str, absolute_path: Path) -> None:
    print(f"[missing] {app}: {field} -> {absolute_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate env_file/data_file paths from apps.yaml")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with non-zero status when files are missing",
    )
    args = parser.parse_args()

    config = yaml.safe_load(APPS_YAML.read_text())
    apps = config.get("apps", [])
    missing = 0
    checked = 0

    for app in apps:
        app_name = app.get("name", "?")
        deploy_path = app.get("deploy_path")
        if not deploy_path:
            continue

        deploy_dir = Path(deploy_path)
        for field in ("env_file", "data_file"):
            rel = app.get(field)
            if not rel:
                continue
            checked += 1
            target = deploy_dir / rel
            if not target.exists():
                missing += 1
                print_missing(app_name, field, target)

    if missing:
        print(f"Runtime file check: {missing} missing / {checked} declared.")
        print("Create/copy missing files before deploying affected apps.")
        if args.strict:
            sys.exit(1)
    else:
        print(f"Runtime file check: all {checked} declared files are present.")


if __name__ == "__main__":
    main()
