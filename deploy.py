#!/usr/bin/env python3
"""Deploy apps defined in apps.yaml to the Raspberry Pi."""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML not found — run: pip3 install pyyaml")

DEPLOY_DIR = Path(__file__).parent
APPS_YAML = DEPLOY_DIR / "apps.yaml"
CADDYFILE = DEPLOY_DIR / "Caddyfile"
VERSIONS_FILE = DEPLOY_DIR / ".deployed-versions.json"


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


# ── version tracking ──────────────────────────────────────────────────────────

def load_versions() -> dict:
    if VERSIONS_FILE.exists():
        return json.loads(VERSIONS_FILE.read_text())
    return {}


def save_versions(versions: dict) -> None:
    VERSIONS_FILE.write_text(json.dumps(versions, indent=2) + "\n")


def record_version(name: str, path: Path) -> str:
    """Capture HEAD sha of the deployed repo and persist it. Returns the sha."""
    result = subprocess.run(
        "git rev-parse HEAD", shell=True, cwd=path, capture_output=True, text=True
    )
    sha = result.stdout.strip()
    if not sha:
        return ""
    versions = load_versions()
    versions[name] = {
        "sha": sha,
        "deployed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
    }
    save_versions(versions)
    log(f"recorded version {sha[:7]}")
    return sha


def get_remote_sha(path: Path) -> str:
    """Return the sha of origin's default branch (after a fetch)."""
    result = subprocess.run(
        "git rev-parse origin/HEAD",
        shell=True, cwd=path, capture_output=True, text=True
    )
    sha = result.stdout.strip()
    if sha:
        return sha
    for branch in ("origin/main", "origin/master"):
        r = subprocess.run(
            f"git rev-parse {branch}",
            shell=True, cwd=path, capture_output=True, text=True
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    return ""


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

    record_version(name, deploy_path)


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

    record_version(name, deploy_path)


DEPLOY_FN = {
    "static": deploy_static,
    "service": deploy_service,
}


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_deploy(args: argparse.Namespace, apps: list[dict]) -> None:
    require("git", "pm2")

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


def cmd_update(apps: list[dict]) -> None:
    require("git", "pm2")

    versions = load_versions()
    up_to_date: list[str] = []
    updated: list[str] = []
    failed: list[str] = []
    any_static_updated = False

    for app in apps:
        name = app["name"]
        deploy_path = Path(app["deploy_path"])
        kind = app["type"]

        header(name, kind)

        if not (deploy_path / ".git").exists():
            log("not cloned yet — deploying fresh")
            try:
                DEPLOY_FN[kind](app)
                updated.append(name)
                if kind == "static":
                    any_static_updated = True
            except Exception as exc:
                print(f"  [FAILED] {exc}", file=sys.stderr)
                failed.append(name)
            continue

        log("fetching remote…")
        fetch_result = subprocess.run(
            "git fetch --quiet", shell=True, cwd=deploy_path, capture_output=True
        )
        if fetch_result.returncode != 0:
            print("  [FAILED] git fetch failed", file=sys.stderr)
            failed.append(name)
            continue

        remote_sha = get_remote_sha(deploy_path)
        deployed_sha = versions.get(name, {}).get("sha", "")

        if not deployed_sha:
            log("not in .deployed-versions.json — deploying")
        elif remote_sha == deployed_sha:
            log(f"up-to-date ({deployed_sha[:7]})")
            up_to_date.append(name)
            continue
        else:
            log(f"update available {deployed_sha[:7]} → {remote_sha[:7]}")

        try:
            DEPLOY_FN[kind](app)
            updated.append(name)
            if kind == "static":
                any_static_updated = True
        except Exception as exc:
            print(f"  [FAILED] {exc}", file=sys.stderr)
            failed.append(name)

    if any_static_updated:
        print("\nReloading Caddy...")
        result = subprocess.run(
            f"sudo caddy reload --config {CADDYFILE}",
            shell=True
        )
        if result.returncode == 0:
            print("✓ Caddy reloaded")
        else:
            print("⚠ Caddy reload failed (is Caddy running?)")

    print("\n── update summary ──────────────────────────────")
    if up_to_date:
        print(f"  up-to-date ({len(up_to_date)}): {', '.join(up_to_date)}")
    if updated:
        print(f"  updated    ({len(updated)}): {', '.join(updated)}")
    if failed:
        print(f"  failed     ({len(failed)}): {', '.join(failed)}")
    if not up_to_date and not updated and not failed:
        print("  nothing to do")

    if failed:
        sys.exit(1)


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy apps from apps.yaml")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("update", help="Fetch remotes and redeploy apps with new commits")

    # positional for bare: deploy.py [app|all]
    parser.add_argument("app", nargs="?", default="all",
                        help="App name to deploy, or 'all' (default). "
                             "Use 'update' subcommand to check for remote changes.")

    args = parser.parse_args()

    config = yaml.safe_load(APPS_YAML.read_text())
    apps: list[dict] = config["apps"]

    if args.command == "update":
        cmd_update(apps)
    else:
        cmd_deploy(args, apps)


if __name__ == "__main__":
    main()
