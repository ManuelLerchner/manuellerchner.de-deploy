#!/usr/bin/env python3
"""Deploy apps defined in apps.yaml to the Raspberry Pi."""

import json
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

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


def run(cmd: str, cwd: Optional[Path] = None) -> None:
    result = subprocess.run(cmd, shell=True, cwd=cwd)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed (exit {result.returncode}): {cmd}")


def pi_build_command(app: dict) -> Optional[str]:
    """Return the Pi-specific build command, preserving the CI command unchanged."""
    build = app.get("build")
    limits = app.get("pi_build_limits")
    if not build or not limits:
        return build
    if limits["npm_ci_foreground_scripts"]:
        build = build.replace("npm ci", "npm ci --foreground-scripts --no-progress", 1)

    return " ".join([
        "systemd-run", "--user", "--scope",
        "-p", shlex.quote(f"CPUQuota={limits['cpu_quota']}"),
        "-p", shlex.quote(f"MemoryHigh={limits['memory_high']}"),
        "-p", shlex.quote(f"MemoryMax={limits['memory_max']}"),
        "-p", shlex.quote(f"MemorySwapMax={limits['memory_swap_max']}"),
        "nice", "-n", str(limits["nice"]),
        "ionice", "-c", str(limits["ionice_class"]), "-n", str(limits["ionice_level"]),
        "env", shlex.quote(f"NODE_OPTIONS=--max-old-space-size={limits['node_max_old_space_size']}"),
        "sh", "-c", shlex.quote(build),
    ])


def run_post_deploy(app: dict, deploy_path: Path) -> None:
    cmd = app.get("post_deploy_cmd")
    if not cmd:
        return
    log(f"post-deploy: {cmd}")
    run(cmd, cwd=deploy_path)


def write_env_file(app: dict, deploy_path: Path) -> Path:
    env_file = deploy_path / app["env_file"]
    values = app["env"]
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
    env_file.chmod(0o600)
    return env_file


def require(*cmds: str) -> None:
    missing = [c for c in cmds if subprocess.run(
        f"command -v {c}", shell=True, capture_output=True
    ).returncode != 0]
    if missing:
        sys.exit(f"Missing tools: {', '.join(missing)} — run scripts/bootstrap.py first")


def require_docker_compose() -> None:
    result = subprocess.run("docker compose version", shell=True, capture_output=True)
    if result.returncode != 0:
        sys.exit("Docker Compose plugin missing — install Docker Engine with the Compose plugin")


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
        # Deploy clones should be reproducible; discard tracked local drift (e.g. lockfile churn).
        run("git reset --hard HEAD", cwd=path)
        run("git pull --ff-only", cwd=path)
    else:
        log(f"cloning {repo} → {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        run(f"git clone {repo} {path}")


# ── deploy types ──────────────────────────────────────────────────────────────

def pull_and_build(app: dict) -> Path:
    deploy_path = Path(app["deploy_path"])
    pull_or_clone(app["repo"], deploy_path)

    build = pi_build_command(app)
    if build:
        log(f"building: {build}")
        run(build, cwd=deploy_path)

    return deploy_path


def start_static(app: dict, deploy_path: Path) -> None:
    run_post_deploy(app, deploy_path)
    served_path = deploy_path / app.get("output", ".")
    run(f"chmod -R g+rX {served_path}")
    log(f"✓ serving from {served_path}")
    record_version(app["name"], deploy_path)


def deploy_static(app: dict) -> None:
    start_static(app, pull_and_build(app))


def start_service(app: dict, deploy_path: Path) -> None:
    pm2_name = app.get("pm2_name", app["name"])
    entry = app.get("entry")
    start_cmd = app.get("start_cmd")

    run_post_deploy(app, deploy_path)

    log(f"restarting PM2 process '{pm2_name}'")
    # PM2 must use the app's deploy_path as cwd (dotenv uses ./config/config.env, etc.)
    run(f"pm2 delete {pm2_name} || true")
    cwd_q = shlex.quote(str(deploy_path))
    if start_cmd:
        quoted = shlex.quote(f"cd {deploy_path} && {start_cmd}")
        run(f"pm2 start bash --name {pm2_name} --cwd {cwd_q} -- -lc {quoted}")
    else:
        run(
            f"pm2 start {shlex.quote(str(deploy_path / entry))} "
            f"--name {pm2_name} --cwd {cwd_q}"
        )

    run("pm2 save --force")
    log("✓ service running")
    record_version(app["name"], deploy_path)


def deploy_service(app: dict) -> None:
    start_service(app, pull_and_build(app))


def deploy_compose(app: dict) -> None:
    deploy_path = Path(app["deploy_path"])
    pull_or_clone(app["repo"], deploy_path)
    compose = compose_command(app, write_env_file(app, deploy_path))
    log("pulling Compose images")
    run(f"{compose} pull")
    start_compose(app, deploy_path)


def start_compose(app: dict, deploy_path: Path) -> None:
    compose = compose_command(app, write_env_file(app, deploy_path))

    log("starting Compose stack")
    run(f"{compose} up -d --remove-orphans")
    log("✓ Compose stack running")

    record_version(app["name"], deploy_path)


def compose_command(app: dict, env_file: Path) -> str:
    deploy_path = Path(app["deploy_path"])
    compose_file = shlex.quote(str(deploy_path / app["compose_file"]))
    override_files = " ".join(
        f"-f {shlex.quote(str(DEPLOY_DIR / override))}"
        for override in app.get("compose_overrides", [])
    )
    project_dir = shlex.quote(str(deploy_path))
    project_name = shlex.quote(app["compose_project"])
    env_file_q = shlex.quote(str(env_file))
    return (
        f"docker compose --project-name {project_name} --project-directory {project_dir} "
        f"--env-file {env_file_q} -f {compose_file} {override_files}"
    )


DEPLOY_FN = {
    "static": deploy_static,
    "service": deploy_service,
    "compose": deploy_compose,
}


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_deploy(target: str, apps: list[dict]) -> None:
    require("git")

    if target != "all" and not any(a["name"] == target for a in apps):
        sys.exit(f"App '{target}' not found in apps.yaml")

    selected = apps if target == "all" else [a for a in apps if a["name"] == target]
    if any(app.get("pi_build_limits") for app in selected):
        require("systemd-run", "ionice")
    if any(app["type"] == "service" for app in selected):
        require("pm2")
    if any(app["type"] == "compose" for app in selected):
        require_docker_compose()
    failed: list[str] = []
    any_web_app = False

    for app in selected:
        kind = app["type"]
        header(app["name"], kind)
        try:
            DEPLOY_FN[kind](app)
            if app.get("domain"):
                any_web_app = True
        except Exception as exc:
            print(f"  [FAILED] {exc}", file=sys.stderr)
            failed.append(app["name"])

    if any_web_app:
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
    require("git")
    if any(app["type"] == "service" for app in apps):
        require("pm2")
    if any(app["type"] == "compose" for app in apps):
        require_docker_compose()

    versions = load_versions()
    up_to_date: list[str] = []
    updated: list[str] = []
    failed: list[str] = []
    any_web_app_updated = False

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
                if app.get("domain"):
                    any_web_app_updated = True
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
            if app.get("domain"):
                any_web_app_updated = True
        except Exception as exc:
            print(f"  [FAILED] {exc}", file=sys.stderr)
            failed.append(name)

    if any_web_app_updated:
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


def cmd_stop(apps: list[dict], extra_pm2_processes: list[str]) -> None:
    """Stop application processes managed by this repository without changing boot state."""
    managed = [app for app in apps if app["type"] in {"service", "compose"}]
    if any(app["type"] == "service" for app in managed) or extra_pm2_processes:
        require("pm2")
    if any(app["type"] == "compose" for app in managed):
        require_docker_compose()

    failed: list[str] = []
    for app in managed:
        header(app["name"], app["type"])
        try:
            if app["type"] == "service":
                pm2_name = shlex.quote(app.get("pm2_name", app["name"]))
                run(f"pm2 stop {pm2_name} || true")
            else:
                deploy_path = Path(app["deploy_path"])
                env_file = deploy_path / app["env_file"]
                run(f"{compose_command(app, env_file)} stop")
            log("✓ stopped")
        except Exception as exc:
            print(f"  [FAILED] {exc}", file=sys.stderr)
            failed.append(app["name"])

    for pm2_name in extra_pm2_processes:
        header(pm2_name, "pm2")
        try:
            run(f"pm2 stop {shlex.quote(pm2_name)} || true")
            log("✓ stopped")
        except Exception as exc:
            print(f"  [FAILED] {exc}", file=sys.stderr)
            failed.append(pm2_name)

    total = len(managed) + len(extra_pm2_processes)
    print(f"\nStopped: {total - len(failed)}  Failed: {len(failed)}")
    if failed:
        print(f"Failed: {', '.join(failed)}")
        sys.exit(1)


def cmd_build(apps: list[dict]) -> None:
    """Pull and build every app without starting application processes."""
    require("git")
    if any(app.get("pi_build_limits") for app in apps):
        require("systemd-run", "ionice")
    if any(app["type"] == "compose" for app in apps):
        require_docker_compose()

    failed: list[str] = []
    for app in apps:
        header(app["name"], app["type"])
        try:
            deploy_path = pull_and_build(app)
            if app["type"] == "compose":
                compose = compose_command(app, write_env_file(app, deploy_path))
                log("pulling Compose images")
                run(f"{compose} pull")
            log("✓ built")
        except Exception as exc:
            print(f"  [FAILED] {exc}", file=sys.stderr)
            failed.append(app["name"])

    print(f"\nBuilt: {len(apps) - len(failed)}  Failed: {len(failed)}")
    if failed:
        print(f"Failed: {', '.join(failed)}")
        sys.exit(1)


def cmd_start(apps: list[dict], extra_pm2_processes: list[str]) -> None:
    """Start apps after a separate build phase, in apps.yaml order."""
    if any(app["type"] == "service" for app in apps) or extra_pm2_processes:
        require("pm2")
    if any(app["type"] == "compose" for app in apps):
        require_docker_compose()

    failed: list[str] = []
    for app in apps:
        header(app["name"], app["type"])
        deploy_path = Path(app["deploy_path"])
        try:
            if app["type"] == "static":
                start_static(app, deploy_path)
            elif app["type"] == "service":
                start_service(app, deploy_path)
            else:
                start_compose(app, deploy_path)
        except Exception as exc:
            print(f"  [FAILED] {exc}", file=sys.stderr)
            failed.append(app["name"])

    for pm2_name in extra_pm2_processes:
        header(pm2_name, "pm2")
        try:
            run(f"pm2 start {shlex.quote(pm2_name)}")
            run("pm2 save --force")
            log("✓ service running")
        except Exception as exc:
            print(f"  [FAILED] {exc}", file=sys.stderr)
            failed.append(pm2_name)

    total = len(apps) + len(extra_pm2_processes)
    print(f"\nStarted: {total - len(failed)}  Failed: {len(failed)}")
    if failed:
        print(f"Failed: {', '.join(failed)}")
        sys.exit(1)


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    config = yaml.safe_load(APPS_YAML.read_text())
    apps: list[dict] = config["apps"]
    extra_pm2_processes: list[str] = config.get("maintenance", {}).get("stop_pm2_processes", [])
    command = sys.argv[1] if len(sys.argv) > 1 else ""

    if command == "stop":
        cmd_stop(apps, extra_pm2_processes)
    elif command == "build":
        cmd_build(apps)
    elif command == "start":
        cmd_start(apps, extra_pm2_processes)
    else:
        sys.exit("Usage: python3 deploy.py {stop|build|start}")


if __name__ == "__main__":
    main()
