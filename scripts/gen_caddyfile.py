#!/usr/bin/env python3
"""Generate /Caddyfile from apps.yaml."""

import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML not found — run: pip3 install pyyaml")

REPO_ROOT = Path(__file__).parent.parent
APPS_YAML = REPO_ROOT / "apps.yaml"
CADDYFILE = REPO_ROOT / "Caddyfile"

HEADER = """\
# AUTO-GENERATED — do not edit by hand.
# Source: apps.yaml  |  Generator: scripts/gen_caddyfile.py
# Managed by: github.com/ManuelLerchner/manuellerchner.de-deploy
# Location on Pi: /srv/deploy/Caddyfile  |  Symlinked from: /etc/caddy/Caddyfile
"""


def block(domain: str, *lines: str) -> str:
    body = "\n".join(f"\t{l}" for l in lines)
    return f"{domain} {{\n{body}\n}}\n"


def generate(config: dict) -> str:
    parts = [HEADER]

    # ── Redirects ──────────────────────────────────────────────────────────────
    parts.append("# ── Redirects ─────────────────────────────────────────────────────────────────\n")
    for r in config.get("redirects", []):
        parts.append(block(r["from"], f'redir {r["to"]} permanent'))

    # ── Apps ───────────────────────────────────────────────────────────────────
    static_apps = [a for a in config["apps"] if a["type"] == "static" and a.get("domain")]
    service_apps = [a for a in config["apps"] if a["type"] == "service" and a.get("domain")]

    parts.append("# ── Static apps ───────────────────────────────────────────────────────────────\n")
    for app in static_apps:
        serve_path = f"{app['deploy_path']}/{app.get('output', '.')}"
        serve_path = serve_path.rstrip("/.")
        lines = [f"root * {serve_path}"]
        if app.get("spa"):
            lines.append("try_files {path} /index.html")
        lines += ["encode gzip", "file_server"]
        parts.append(block(app["domain"], *lines))

    parts.append("# ── Node / backend services ───────────────────────────────────────────────────\n")
    for app in service_apps:
        parts.append(block(app["domain"], f"reverse_proxy localhost:{app['port']}", "encode gzip"))

    # ── Passthroughs ───────────────────────────────────────────────────────────
    parts.append("# ── Passthroughs (external services, not deployed by this repo) ───────────────\n")
    for pt in config.get("passthrough", []):
        lines = [f"reverse_proxy {pt['proxy']}"]
        if pt.get("tls"):
            lines.append(f"tls {pt['tls']}")
        parts.append(block(pt["domain"], *lines))

    return "\n".join(parts)


def main() -> None:
    config = yaml.safe_load(APPS_YAML.read_text())
    output = generate(config)
    CADDYFILE.write_text(output)
    print(f"Written: {CADDYFILE}")


if __name__ == "__main__":
    main()
