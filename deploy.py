#!/usr/bin/env python3
"""Deploy apps defined in apps.yaml to the Raspberry Pi."""

import argparse
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML not found — run: pip3 install pyyaml")

DEPLOY_DIR = Path(__file__).parent
APPS_YAML = DEPLOY_DIR / "apps.yaml"
CADDYFILE = DEPLOY_DIR / "Caddyfile"


# ── helpers ───────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    print(f"  {msg}", flush=True)


def header(name: str, kind: str) -> None:
    print(f"\n━━━ {name} ({kind}) ━━━", flush=True)


def run(cmd: str, cwd: Path | None = None) -> None:
    result = subprocess.run(cmd, shell=True, cwd=cwd)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed (exit {result.returncode}): {cmd}")


def require(*cmds: str) -> None:
    missing = [c for c in cmds if subprocess.run(
        f"command -v {c}", shell=True, capture_output=True
    ).returncode != 0]
    if missing:
        sys.exit(f"Missing tools: {', '.join(missing)} — run scripts/bootstrap.py first")


# ── git ───────────────────────────────────────────────────────────────────────

def pull_or_clone(repo: str, path: Path) -> None:
    if (path / ".git").exists():
        log(f"pulling {path}")
        run("git pull --ff-only", cwd=path)
    else:
        log(f"cloning {repo} → {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        run(f"git clone {repo} {path}")


# ── deploy types ──────────────────────────────────────────────────────────────

def deploy_static(app: dict) -> None:
    name = app["name"]
    deploy_path = Path(app["deploy_path"])
    output = app.get("output", ".")
    build = app.get("build")

    pull_or_clone(app["repo"], deploy_path)

    if build:
        log(f"building: {build}")
        run(build, cwd=deploy_path)

    served_path = deploy_path / output
    run(f"chmod -R g+rX {served_path}")
    log(f"✓ serving from {served_path}")


def deploy_service(app: dict) -> None:
    name = app["name"]
    deploy_path = Path(app["deploy_path"])
    pm2_name = app.get("pm2_name", name)
    build = app.get("build")
    entry = app.get("entry")
    start_cmd = app.get("start_cmd")

    pull_or_clone(app["repo"], deploy_path)

    if build:
        log(f"building: {build}")
        run(build, cwd=deploy_path)

    log(f"restarting PM2 process '{pm2_name}'")
    is_running = subprocess.run(
        f"pm2 describe {pm2_name}",
        shell=True, capture_output=True
    ).returncode == 0

    if is_running:
        run(f"pm2 restart {pm2_name}")
    elif start_cmd:
        run(f"pm2 start --name {pm2_name} --interpreter bash -- -c 'cd {deploy_path} && {start_cmd}'")
    else:
        run(f"pm2 start {deploy_path / entry} --name {pm2_name}")

    run("pm2 save --force")
    log("✓ service running")


DEPLOY_FN = {
    "static": deploy_static,
    "service": deploy_service,
}


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy apps from apps.yaml")
    parser.add_argument("app", nargs="?", default="all",
                        help="App name to deploy, or 'all' (default)")
    args = parser.parse_args()

    require("git", "pm2")

    config = yaml.safe_load(APPS_YAML.read_text())
    apps: list[dict] = config["apps"]

    target = args.app
    if target != "all" and not any(a["name"] == target for a in apps):
        sys.exit(f"App '{target}' not found in apps.yaml")

    selected = apps if target == "all" else [a for a in apps if a["name"] == target]
    failed: list[str] = []
    any_static = False

    for app in selected:
        kind = app["type"]
        header(app["name"], kind)
        try:
            DEPLOY_FN[kind](app)
            if kind == "static":
                any_static = True
        except Exception as exc:
            print(f"  [FAILED] {exc}", file=sys.stderr)
            failed.append(app["name"])

    if any_static or target == "all":
        print("\nReloading Caddy...")
        result = subprocess.run(
            f"sudo caddy reload --config {CADDYFILE}",
            shell=True
        )
        if result.returncode == 0:
            print("✓ Caddy reloaded")
        else:
            print("⚠ Caddy reload failed (is Caddy running?)")

    print(f"\nDeployed: {len(selected) - len(failed)}  Failed: {len(failed)}")
    if failed:
        print(f"Failed: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
