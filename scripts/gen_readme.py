#!/usr/bin/env python3
"""Generate README.md from apps.yaml — always reflects current state."""

import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML not found — run: pip3 install pyyaml")

REPO_ROOT = Path(__file__).parent.parent
APPS_YAML = REPO_ROOT / "apps.yaml"
README = REPO_ROOT / "README.md"

BADGE = "[![Build](https://github.com/ManuelLerchner/manuellerchner.de-deploy/actions/workflows/build.yml/badge.svg)](https://github.com/ManuelLerchner/manuellerchner.de-deploy/actions/workflows/build.yml)"


def domain_link(domain: str | None) -> str:
    if not domain or domain == "null":
        return "—"
    return f"[{domain}](https://{domain})"


def build_badge(name: str) -> str:
    return f"`{name}`"


def render(config: dict) -> str:
    apps: list[dict] = config["apps"]
    redirects: list[dict] = config.get("redirects", [])
    passthroughs: list[dict] = config.get("passthrough", [])

    static_apps   = [a for a in apps if a["type"] == "static"]
    service_apps  = [a for a in apps if a["type"] == "service" and a.get("domain") and a["domain"] != "null"]
    bg_services   = [a for a in apps if a["type"] == "service" and (not a.get("domain") or a["domain"] == "null")]

    lines = [
        "# manuellerchner.de — Deploy",
        "",
        BADGE,
        "",
        "Declarative homelab deployment for Raspberry Pi.",
        "Single source of truth: [`apps.yaml`](apps.yaml).",
        "Caddyfile and README are auto-generated — **do not edit by hand**.",
        "",
        "## Architecture",
        "",
        "```",
        "apps.yaml ──► scripts/gen_caddyfile.py ──► Caddyfile ──► symlinked to /etc/caddy/Caddyfile",
        "         ╰──► deploy.py ──► git pull + build + pm2/caddy per app",
        "```",
        "",
        "**Permissions:** `/srv/apps` owned by `pi:deploy` (setgid). Both `pi` and `caddy` are",
        "members of the `deploy` group, so Caddy can read static build output without sudo.",
        "",
        "## Static Sites",
        "",
        "| App | Domain | Build |",
        "|-----|--------|-------|",
    ]

    for a in static_apps:
        build = f"`{a['build']}`" if a.get("build") else "*(none — pure static)*"
        lines.append(f"| **{a['name']}** | {domain_link(a.get('domain'))} | {build} |")

    lines += [
        "",
        "## Backend Services (PM2)",
        "",
        "| App | Domain | Port | Runtime |",
        "|-----|--------|------|---------|",
    ]

    for a in service_apps:
        runtime = "Java (Spring Boot)" if a.get("start_cmd") else "Node.js"
        lines.append(f"| **{a['name']}** | {domain_link(a.get('domain'))} | `{a.get('port', '—')}` | {runtime} |")

    if bg_services:
        lines += [
            "",
            "## Background Services (PM2, no domain)",
            "",
            "| App | PM2 name |",
            "|-----|----------|",
        ]
        for a in bg_services:
            lines.append(f"| **{a['name']}** | `{a.get('pm2_name', a['name'])}` |")

    if redirects:
        lines += [
            "",
            "## Redirects (Caddy only)",
            "",
            "| From | To |",
            "|------|----|",
        ]
        for r in redirects:
            lines.append(f"| `{r['from']}` | `{r['to']}` |")

    if passthroughs:
        lines += [
            "",
            "## Passthroughs (external, Caddy only)",
            "",
            "| Name | Domain | Proxy |",
            "|------|--------|-------|",
        ]
        for p in passthroughs:
            lines.append(f"| **{p['name']}** | {domain_link(p['domain'])} | `{p['proxy']}` |")

    lines += [
        "",
        "## Usage",
        "",
        "```bash",
        "# One-time Pi setup",
        "python3 scripts/bootstrap.py",
        "",
        "# Deploy everything",
        "python3 deploy.py all",
        "",
        "# Deploy one app",
        "python3 deploy.py Website",
        "",
        "# Validate apps.yaml",
        "python3 scripts/lint.py",
        "",
        "# Regenerate Caddyfile",
        "python3 scripts/gen_caddyfile.py",
        "",
        "# Regenerate Readme",
        "python3 scripts/gen_readme.py",
        "```",
        "",
        "## Rollback",
        "",
        "If a deploy introduces problems, reset an app repo to a known good commit and redeploy that app:",
        "",
        "```bash",
        "cd /srv/apps/<AppName>",
        "git fetch --all",
        "git reset --hard <known_good_sha>",
        "cd /srv/deploy",
        "python3 deploy.py <AppName>",
        "```",
        "",
        "Use `.deployed-versions.json` in this repo to find previously deployed SHAs.",
        "",
    ]

    return "\n".join(lines)


def main() -> None:
    config = yaml.safe_load(APPS_YAML.read_text())
    output = render(config)
    README.write_text(output)
    print(f"Written: {README}")


if __name__ == "__main__":
    main()
