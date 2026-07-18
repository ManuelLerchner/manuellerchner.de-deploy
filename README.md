# manuellerchner.de — Deploy

[![Build](https://github.com/ManuelLerchner/manuellerchner.de-deploy/actions/workflows/build.yml/badge.svg)](https://github.com/ManuelLerchner/manuellerchner.de-deploy/actions/workflows/build.yml)
[![Domain health](https://github.com/ManuelLerchner/manuellerchner.de-deploy/actions/workflows/health-check-domains.yml/badge.svg)](https://github.com/ManuelLerchner/manuellerchner.de-deploy/actions/workflows/health-check-domains.yml)

Declarative homelab deployment for Raspberry Pi.
Single source of truth: [`apps.yaml`](apps.yaml).
Caddyfile and README are auto-generated — **do not edit by hand**.

## Architecture

```
apps.yaml ──► scripts/gen_caddyfile.py ──► Caddyfile ──► symlinked to /etc/caddy/Caddyfile
         ╰──► deploy.py ──► git pull + PM2/Docker Compose + Caddy per app
```

**Permissions:** `/srv/apps` owned by `pi:deploy` (setgid). Both `pi` and `caddy` are
members of the `deploy` group, so Caddy can read static build output without sudo.

## Domain health (GitHub Actions)

Workflow [`health-check-domains.yml`](.github/workflows/health-check-domains.yml) runs on a schedule.
For each public hostname from `apps.yaml` it requests `https://<domain>/` and **requires a final HTTP 2xx**
after redirects. That catches bad gateways, origin errors, and cases where Cloudflare serves a **403**
block page to automated clients (which the old check incorrectly treated as healthy).

**Cloudflare bypass:** add repo secret **`DOMAIN_HEALTH_CHECK_SECRET`** (same value in Cloudflare),
`openssl rand -hex 32`. Each probe sends the header **`x-domain-health-check: <secret>`**.

In **Security → WAF → Custom rules** (same zone as `manuellerchner.de`), create a rule **above** other custom rules:

- **When:** match the header value:
  `(any(http.request.headers["x-domain-health-check"][*] eq "<secret>"))`
  Values must match the trimmed Actions secret — re-save the GitHub secret as **one line** if you still get 403.
- **Then:** *Skip* — enable **Super Bot Fight Mode**, **Browser Integrity Check**, **All managed rules**,
  and **Rate limiting** at minimum; add more if you still see 403.

Confirm with: `curl -sS -o /dev/null -w '%{http_code}\n' -H "x-domain-health-check: YOUR_SECRET" 'https://example.manuellerchner.de/'`
— expect **200** (or 3xx then 200 with `-L`). If curl works locally but Actions does not, the secret or WAF expression differs.

## Env files & persistent data

Paths below are **relative to each app's** `deploy_path` on the Pi (see [`apps.yaml`](apps.yaml)).
Compose environment values can be stored in `apps.yaml`; only use that for public/demo deployments.

| App | `env_file` | `data_file` | `post_deploy_cmd` | Notes |
|-----|------------|-------------|-------------------|-------|
| **Monopoly** | `.env` | — | — | Present in the app repo (build-time); override locally if needed. |
| **TilePlanner** | `.env` | — | — | Present in the app repo (build-time); override locally if needed. |
| **PiController** | `config/config.env` | — | `[ -f config/config.env ] \|\| cp /home/pi/Manuel-Lerchner-Website/config/config.env config/config.env` | Manual on the Pi — not in git. Create from app docs / prior machine. |
| **Backend** | `dotenv/.env` | — | `[ -f dotenv/.env ] \|\| cp dotenv/.env.example dotenv/.env` | Manual on the Pi — copy from dotenv/.env.example and fill secrets. |
| **RestaurantApp** | — | `src/main/resources/restaurantDatabase.h2.mv.db` | `mkdir -p src/main/resources \|\| exit $?; B=/home/pi/RestaurantApp/restaurantDatabase.h2.mv.db; T=src/main/resources/restaurantDatabase.h2.mv.db; if [ -f "$B" ] && { [ ! -f "$T" ] \|\| [ "$(stat -c%s "$B")" -gt "$(stat -c%s "$T")" ]; }; then cp "$B" "$T"; fi` | H2 stores data under src/main/resources/ (see jdbc URL in application.properties), not the repo root. Copy from ~/RestaurantApp/restaurantDatabase.h2.mv.db if missing or stale after deploy. |
| **PanicAtTheConsole** | `.env` | — | — | Public deployment configuration managed in apps.yaml; Ollama only. |
| **DYNDNS** | `config/.env` | — | `[ -f config/.env ] \|\| cp /home/pi/DeinServerHost-DynDNS-Handler/config/.env config/.env` | Manual on the Pi — not in git. |

## Static Sites

| App | Domain | Build |
|-----|--------|-------|
| **Website** | [manuellerchner.de](https://manuellerchner.de) | *(none — pure static)* |
| **Pathfinder** | [pathfinder.manuellerchner.de](https://pathfinder.manuellerchner.de) | `npm ci && npm run build` |
| **LambdaCalculus** | [lambdacalculus.manuellerchner.de](https://lambdacalculus.manuellerchner.de) | *(none — pure static)* |
| **Monopoly** | [monopoly.manuellerchner.de](https://monopoly.manuellerchner.de) | `npm ci && npm run build` |
| **MinecraftBot** | [minecraft-bot.manuellerchner.de](https://minecraft-bot.manuellerchner.de) | `npm ci && npm run build` |
| **TaskPlanner** | [taskplanner.manuellerchner.de](https://taskplanner.manuellerchner.de) | `npm ci && npm run build` |
| **MockTrading** | [mocktrading.manuellerchner.de](https://mocktrading.manuellerchner.de) | `npm ci && npm run build` |
| **ExpenseTracker** | [expensetracker.manuellerchner.de](https://expensetracker.manuellerchner.de) | `npm ci && npm run build` |
| **TilePlanner** | [tile-planner.manuellerchner.de](https://tile-planner.manuellerchner.de) | `npm ci && npm run build` |
| **AlgoExplorer** | [algoexplorer.manuellerchner.de](https://algoexplorer.manuellerchner.de) | `npm ci && npm run build` |

## Pi Build Limits

`deploy.py build` runs configured builds in a user systemd scope. GitHub Actions runs the portable build command above without these limits.
For unattended deployments, enable the Pi user's systemd manager once: `sudo loginctl enable-linger pi`.

| App | CPU quota | Memory high/max/swap | Node heap | Nice | I/O priority | Install output |
|-----|-----------|----------------------|-----------|------|--------------|----------------|
| **Pathfinder** | `200%` | `1200M` / `1500M` / `0` | `1024 MiB` | `10` | class `2`, level `5` | `--foreground-scripts --no-progress` |
| **Monopoly** | `200%` | `1200M` / `1500M` / `0` | `1024 MiB` | `10` | class `2`, level `5` | `--foreground-scripts --no-progress` |
| **MinecraftBot** | `200%` | `1200M` / `1500M` / `0` | `1024 MiB` | `10` | class `2`, level `5` | `--foreground-scripts --no-progress` |
| **TaskPlanner** | `200%` | `1200M` / `1500M` / `0` | `1024 MiB` | `10` | class `2`, level `5` | `--foreground-scripts --no-progress` |
| **MockTrading** | `200%` | `1200M` / `1500M` / `0` | `1024 MiB` | `10` | class `2`, level `5` | `--foreground-scripts --no-progress` |
| **ExpenseTracker** | `200%` | `1200M` / `1500M` / `0` | `1024 MiB` | `10` | class `2`, level `5` | `--foreground-scripts --no-progress` |
| **TilePlanner** | `200%` | `1200M` / `1500M` / `0` | `1024 MiB` | `10` | class `2`, level `5` | `--foreground-scripts --no-progress` |
| **AlgoExplorer** | `200%` | `1200M` / `1500M` / `0` | `1024 MiB` | `10` | class `2`, level `5` | `--foreground-scripts --no-progress` |
| **PiController** | `200%` | `1200M` / `1500M` / `0` | `1024 MiB` | `10` | class `2`, level `5` | `--foreground-scripts --no-progress` |
| **Backend** | `200%` | `1200M` / `1500M` / `0` | `1024 MiB` | `10` | class `2`, level `5` | `--foreground-scripts --no-progress` |
| **RestaurantApp** | `200%` | `1200M` / `1500M` / `0` | `1024 MiB` | `10` | class `2`, level `5` | `--foreground-scripts --no-progress` |
| **DYNDNS** | `200%` | `1200M` / `1500M` / `0` | `1024 MiB` | `10` | class `2`, level `5` | `--foreground-scripts --no-progress` |

## Backend Services (PM2)

| App | Domain | Port | Runtime |
|-----|--------|------|---------|
| **PiController** | [pi.manuellerchner.de](https://pi.manuellerchner.de) | `3000` | Node.js |
| **Backend** | [api.manuellerchner.de](https://api.manuellerchner.de) | `4000` | Node.js |
| **RestaurantApp** | [restaurantapp.manuellerchner.de](https://restaurantapp.manuellerchner.de) | `3019` | Java (Spring Boot) |

## Docker Compose Services

| App | Domain | Port | Compose project | Overrides |
|-----|--------|------|-----------------|-----------|
| **PanicAtTheConsole** | [panic.manuellerchner.de](https://panic.manuellerchner.de) | `18080` | `panic-at-the-console` | `compose-overrides/panic-at-the-console.yml` |

## Background Services (PM2, no domain)

| App | PM2 name |
|-----|----------|
| **DYNDNS** | `DYNDNS` |

## Redirects (Caddy only)

| From | To |
|------|----|
| `www.manuellerchner.de` | `https://{labels.1}.{labels.0}{uri}` |

## Passthroughs (external, Caddy only)

| Name | Domain | Proxy |
|------|--------|-------|
| **n8n** | [n8n.manuellerchner.de](https://n8n.manuellerchner.de) | `http://localhost:5678` |

## Usage

```bash
# One-time Pi setup
python3 scripts/bootstrap.py

# Stop managed PM2 and Docker Compose apps (leaves Caddy and networking running)
python3 deploy.py stop

# Pull and build every app without starting services, then start them in apps.yaml order
python3 deploy.py build
python3 deploy.py start

# Validate apps.yaml
python3 scripts/lint.py

# Check required runtime env/data files from apps.yaml
python3 scripts/check_runtime_files.py

# Regenerate Caddyfile
python3 scripts/gen_caddyfile.py

# Regenerate Readme
python3 scripts/gen_readme.py
```
