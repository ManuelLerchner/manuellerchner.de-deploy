#!/usr/bin/env python3
"""One-time setup on the Raspberry Pi."""

import grp
import os
import platform
import pwd
import shutil
import subprocess
import sys
from pathlib import Path

DEPLOY_DIR = Path(__file__).parent.parent
YQ_VERSION = "v4.44.1"
YQ_BINARY = "yq_linux_arm64"
YQ_URL = f"https://github.com/mikefarah/yq/releases/download/{YQ_VERSION}/{YQ_BINARY}"
YQ_PATH = Path("/usr/local/bin/yq")
SUDOERS_FILE = Path("/etc/sudoers.d/caddy-reload")
SUDOERS_LINE = "pi ALL=(ALL) NOPASSWD: /usr/bin/caddy reload *"


# ── helpers ───────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    print(f"[bootstrap] {msg}", flush=True)


def run(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, check=check)


def sudo(cmd: str) -> None:
    run(f"sudo {cmd}")


# ── steps ─────────────────────────────────────────────────────────────────────

def check_platform() -> None:
    machine = platform.machine()
    if not machine.startswith(("arm", "aarch")):
        answer = input(f"Warning: running on {machine}, not ARM. Continue? [y/N] ")
        if answer.lower() != "y":
            sys.exit(0)


def install_pyyaml() -> None:
    try:
        import yaml  # noqa: F401
        log("PyYAML already installed")
    except ImportError:
        log("Installing PyYAML...")
        run("pip3 install --quiet pyyaml")
        log("PyYAML installed")


def install_yq() -> None:
    if YQ_PATH.exists():
        result = subprocess.run(f"{YQ_PATH} --version", shell=True, capture_output=True, text=True)
        log(f"yq already installed: {result.stdout.strip()}")
        return

    log(f"Installing yq {YQ_VERSION}...")
    sudo(f"wget -qO {YQ_PATH} {YQ_URL}")
    sudo(f"chmod +x {YQ_PATH}")
    result = subprocess.run(f"{YQ_PATH} --version", shell=True, capture_output=True, text=True)
    log(f"yq installed: {result.stdout.strip()}")


def setup_deploy_group() -> None:
    log("Setting up 'deploy' group...")
    if run("getent group deploy", check=False).returncode != 0:
        sudo("groupadd deploy")

    sudo("usermod -aG deploy pi")
    if run("id caddy", check=False).returncode == 0:
        sudo("usermod -aG deploy caddy")
    else:
        log("Warning: caddy user not found — is Caddy installed?")


def setup_srv_apps() -> None:
    log("Creating /srv/apps with correct ownership...")
    sudo("mkdir -p /srv/apps")
    sudo("chown pi:deploy /srv/apps")
    sudo("chmod 2775 /srv/apps")   # setgid so new files inherit 'deploy' group


def symlink_caddyfile() -> None:
    log("Symlinking Caddyfile → /etc/caddy/Caddyfile...")
    sudo("mkdir -p /etc/caddy")
    caddy_path = Path("/etc/caddy/Caddyfile")

    if caddy_path.exists() and not caddy_path.is_symlink():
        from datetime import datetime
        backup = caddy_path.with_suffix(f".bak.{datetime.now():%Y%m%d%H%M%S}")
        sudo(f"mv {caddy_path} {backup}")
        log(f"Backed up existing Caddyfile to {backup}")

    target = DEPLOY_DIR / "Caddyfile"
    sudo(f"ln -sf {target} {caddy_path}")
    log(f"Symlinked: {caddy_path} → {target}")


def setup_caddy_sudoers() -> None:
    if SUDOERS_FILE.exists():
        content = subprocess.run(
            f"sudo cat {SUDOERS_FILE}", shell=True, capture_output=True, text=True
        ).stdout
        if "caddy reload" in content:
            log("sudoers rule already present")
            return

    log("Adding sudoers rule for caddy reload...")
    sudo(f"bash -c \"echo '{SUDOERS_LINE}' | tee {SUDOERS_FILE} > /dev/null\"")
    sudo(f"chmod 440 {SUDOERS_FILE}")


def make_executable() -> None:
    deploy_script = DEPLOY_DIR / "deploy.py"
    deploy_script.chmod(deploy_script.stat().st_mode | 0o111)


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    check_platform()
    install_pyyaml()
    install_yq()
    setup_deploy_group()
    setup_srv_apps()
    symlink_caddyfile()
    setup_caddy_sudoers()
    make_executable()

    log("")
    log("Bootstrap complete. Next steps:")
    log("  1. Re-login (or: newgrp deploy) so group membership takes effect")
    log("  2. python3 deploy.py all")
    log("  3. Stop old PM2 Website process (now served by Caddy directly):")
    log("     pm2 delete Website && pm2 save")


if __name__ == "__main__":
    main()
