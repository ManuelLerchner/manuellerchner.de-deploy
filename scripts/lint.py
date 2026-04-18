#!/usr/bin/env python3
"""Validate apps.yaml for config errors: duplicate ports, domains, missing fields."""

import sys
from collections import defaultdict
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML not found — run: pip3 install pyyaml")

APPS_YAML = Path(__file__).parent.parent / "apps.yaml"

REQUIRED_STATIC  = {"name", "repo", "type", "output", "domain", "deploy_path"}
REQUIRED_SERVICE = {"name", "repo", "type", "deploy_path", "pm2_name"}

errors: list[str] = []
warnings: list[str] = []


def err(msg: str) -> None:
    errors.append(f"  ERROR   {msg}")


def warn(msg: str) -> None:
    warnings.append(f"  WARN    {msg}")


def check_required_fields(app: dict) -> None:
    required = REQUIRED_STATIC if app["type"] == "static" else REQUIRED_SERVICE
    missing = required - app.keys()
    if missing:
        err(f"[{app.get('name', '?')}] missing fields: {', '.join(sorted(missing))}")


def check_duplicates(apps: list[dict]) -> None:
    ports: dict[int, list[str]] = defaultdict(list)
    domains: dict[str, list[str]] = defaultdict(list)
    deploy_paths: dict[str, list[str]] = defaultdict(list)
    pm2_names: dict[str, list[str]] = defaultdict(list)

    for app in apps:
        name = app.get("name", "?")
        if app.get("port") and app["port"] != "null":
            ports[app["port"]].append(name)
        if app.get("domain") and app["domain"] != "null":
            domains[app["domain"]].append(name)
        if app.get("deploy_path"):
            deploy_paths[app["deploy_path"]].append(name)
        if app.get("pm2_name"):
            pm2_names[app["pm2_name"]].append(name)

    for port, names in ports.items():
        if len(names) > 1:
            err(f"Duplicate port {port}: {names}")

    for domain, names in domains.items():
        if len(names) > 1:
            err(f"Duplicate domain '{domain}': {names}")

    for path, names in deploy_paths.items():
        if len(names) > 1:
            err(f"Duplicate deploy_path '{path}': {names}")

    for pm2_name, names in pm2_names.items():
        if len(names) > 1:
            err(f"Duplicate pm2_name '{pm2_name}': {names}")


def check_service_has_entry_or_cmd(app: dict) -> None:
    if app["type"] != "service":
        return
    has_entry = app.get("entry") and app["entry"] != "null"
    has_cmd   = app.get("start_cmd") and app["start_cmd"] != "null"
    if not has_entry and not has_cmd:
        err(f"[{app['name']}] service needs either 'entry' or 'start_cmd'")


def check_no_build_but_output(app: dict) -> None:
    if app["type"] != "static":
        return
    if not app.get("build") and app.get("output") not in (".", None):
        warn(f"[{app['name']}] no build step but output='{app['output']}' — ensure files already exist")


def main() -> None:
    config = yaml.safe_load(APPS_YAML.read_text())
    apps: list[dict] = config.get("apps", [])

    for app in apps:
        if "type" not in app:
            err(f"[{app.get('name', '?')}] missing 'type' field")
            continue
        check_required_fields(app)
        check_service_has_entry_or_cmd(app)
        check_no_build_but_output(app)

    check_duplicates(apps)

    if warnings:
        print("Warnings:")
        print("\n".join(warnings))

    if errors:
        print("Errors:")
        print("\n".join(errors))
        sys.exit(1)

    print(f"OK — {len(apps)} apps validated, no errors.")


if __name__ == "__main__":
    main()
