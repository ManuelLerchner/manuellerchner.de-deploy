# manuellerchner.de — Deploy

[![Build](https://github.com/ManuelLerchner/manuellerchner.de-deploy/actions/workflows/build.yml/badge.svg)](https://github.com/ManuelLerchner/manuellerchner.de-deploy/actions/workflows/build.yml)
[![Domain health](https://github.com/ManuelLerchner/manuellerchner.de-deploy/actions/workflows/health-check-domains.yml/badge.svg)](https://github.com/ManuelLerchner/manuellerchner.de-deploy/actions/workflows/health-check-domains.yml)

Declarative homelab deployment for Raspberry Pi.
Single source of truth: [`apps.yaml`](apps.yaml).
Caddyfile and README are auto-generated — **do not edit by hand**.

## Architecture

```
apps.yaml ──► scripts/gen_caddyfile.py ──► Caddyfile ──► symlinked to /etc/caddy/Caddyfile
         ╰──► deploy.py ──► git pull + build + pm2/caddy per app
```

**Permissions:** `/srv/apps` owned by `pi:deploy` (setgid). Both `pi` and `caddy` are
members of the `deploy` group, so Caddy can read static build output without sudo.

## Domain health (GitHub Actions)

Workflow [`health-check-domains.yml`](.github/workflows/health-check-domains.yml) runs on a schedule.
For each public hostname from `apps.yaml` it requests `https://<domain>/` and **requires a final HTTP 2xx**
after redirects. That catches bad gateways, origin errors, and cases where Cloudflare serves a **403**
block page to automated clients (which the old check incorrectly treated as healthy).

**Cloudflare bypass:** add repo secret **`DOMAIN_HEALTH_CHECK_SECRET`** (same value in Cloudflare),
`openssl rand -hex 32`. Each probe sends **both** the header **`x-domain-health-check: <secret>`** and the query
**`?health_check_token=<secret>`** (so Security Events show the token even when header visibility is limited).
**Do not** share links with this query — it appears in access logs.

In **Security → WAF → Custom rules** (same zone as `manuellerchner.de`), create a rule **above** other custom rules:

- **When:** match **either** channel, same hex string in both places:
  `(any(http.request.headers["x-domain-health-check"][*] eq "<secret>") or any(http.request.uri.args["health_check_token"][*] eq "<secret>"))`
  Values must match the trimmed Actions secret — re-save the GitHub secret as **one line** if you still get 403.
- **Then:** *Skip* — enable **Super Bot Fight Mode**, **Browser Integrity Check**, **All managed rules**,
  and **Rate limiting** at minimum; add more if you still see 403.

Confirm with: `curl -sS -o /dev/null -w '%{http_code}\n' -G 'https://example.manuellerchner.de/' --data-urlencode "health_check_token=YOUR_SECRET" -H "x-domain-health-check: YOUR_SECRET"`
— expect **200** (or 3xx then 200 with `-L`). If curl works locally but Actions does not, the secret or WAF expression differs.

## Env files & persistent data

Paths below are **relative to each app's** `deploy_path` on the Pi (see [`apps.yaml`](apps.yaml)).
Secrets are not stored in this deploy repo — create or copy those files on the Pi.

| App | `env_file` | `data_file` | `post_deploy_cmd` | Notes |
|-----|------------|-------------|-------------------|-------|
| **Monopoly** | `.env` | — | — | Present in the app repo (build-time); override locally if needed. |
| **TilePlanner** | `.env` | — | — | Present in the app repo (build-time); override locally if needed. |
| **PiController** | `config/config.env` | — | `[ -f config/config.env ] \|\| cp /home/pi/Manuel-Lerchner-Website/config/config.env config/config.env` | Manual on the Pi — not in git. Create from app docs / prior machine. |
| **Backend** | `dotenv/.env` | — | `[ -f dotenv/.env ] \|\| cp dotenv/.env.example dotenv/.env` | Manual on the Pi — copy from dotenv/.env.example and fill secrets. |
| **RestaurantApp** | — | `src/main/resources/restaurantDatabase.h2.mv.db` | `mkdir -p src/main/resources && B=/home/pi/RestaurantApp/restaurantDatabase.h2.mv.db && T=src/main/resources/restaurantDatabase.h2.mv.db && [ -f "$B" ] && { [ ! -f "$T" ] \|\| [ "$(stat -c%s "$B")" -gt "$(stat -c%s "$T")" ]; } && cp "$B" "$T"` | H2 stores data under src/main/resources/ (see jdbc URL in application.properties), not the repo root. Copy from ~/RestaurantApp/restaurantDatabase.h2.mv.db if missing or stale after deploy. |
| **DYNDNS** | `config/.env` | — | `[ -f config/.env ] \|\| cp /home/pi/DeinServerHost-DynDNS-Handler/config/.env config/.env` | Manual on the Pi — not in git. |

## Static Sites

| App | Domain | Build |
|-----|--------|-------|
| **Website** | [manuellerchner.de](https://manuellerchner.de) | *(none — pure static)* |
| **Pathfinder** | [pathfinder.manuellerchner.de](https://pathfinder.manuellerchner.de) | `npm install && npm run build` |
| **LambdaCalculus** | [lambdacalculus.manuellerchner.de](https://lambdacalculus.manuellerchner.de) | *(none — pure static)* |
| **Monopoly** | [monopoly.manuellerchner.de](https://monopoly.manuellerchner.de) | `npm install && npm run build` |
| **MinecraftBot** | [minecraft-bot.manuellerchner.de](https://minecraft-bot.manuellerchner.de) | `npm install && npm run build` |
| **TaskPlanner** | [taskplanner.manuellerchner.de](https://taskplanner.manuellerchner.de) | `npm install && npm run build` |
| **MockTrading** | [mocktrading.manuellerchner.de](https://mocktrading.manuellerchner.de) | `npm install && npm run build` |
| **ExpenseTracker** | [expensetracker.manuellerchner.de](https://expensetracker.manuellerchner.de) | `npm install && npm run build` |
| **TilePlanner** | [tile-planner.manuellerchner.de](https://tile-planner.manuellerchner.de) | `npm install && npm run build` |
| **AlgoExplorer** | [algoexplorer.manuellerchner.de](https://algoexplorer.manuellerchner.de) | `npm install && npm run build` |

## Backend Services (PM2)

| App | Domain | Port | Runtime |
|-----|--------|------|---------|
| **PiController** | [pi.manuellerchner.de](https://pi.manuellerchner.de) | `3000` | Node.js |
| **Backend** | [api.manuellerchner.de](https://api.manuellerchner.de) | `4000` | Node.js |
| **RestaurantApp** | [restaurantapp.manuellerchner.de](https://restaurantapp.manuellerchner.de) | `3019` | Java (Spring Boot) |

## Background Services (PM2, no domain)

| App | PM2 name |
|-----|----------|
| **DYNDNS** | `DYNDNS` |

## Redirects (Caddy only)

| From | To |
|------|----|
| `www.manuellerchner.de` | `https://{labels.1}.{labels.0}{uri}` |

## Usage

```bash
# One-time Pi setup
python3 scripts/bootstrap.py

# Deploy everything
python3 deploy.py all

# Deploy one app
python3 deploy.py Website

# Validate apps.yaml
python3 scripts/lint.py

# Check required runtime env/data files from apps.yaml
python3 scripts/check_runtime_files.py

# Regenerate Caddyfile
python3 scripts/gen_caddyfile.py

# Regenerate Readme
python3 scripts/gen_readme.py
```

## Rollback

If a deploy introduces problems, reset an app repo to a known good commit and redeploy that app:

```bash
cd /srv/apps/<AppName>
git fetch --all
git reset --hard <known_good_sha>
cd /srv/deploy
python3 deploy.py <AppName>
```

Use `.deployed-versions.json` in this repo to find previously deployed SHAs.
