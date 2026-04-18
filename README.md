# manuellerchner.de — Deploy

[![Build](https://github.com/ManuelLerchner/manuellerchner.de-deploy/actions/workflows/build.yml/badge.svg)](https://github.com/ManuelLerchner/manuellerchner.de-deploy/actions/workflows/build.yml)

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

## Passthroughs (external, Caddy only)

| Name | Domain | Proxy |
|------|--------|-------|
| **pihole** | [pihole.manuellerchner.de](https://pihole.manuellerchner.de) | `localhost:8080` |

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

# Regenerate Caddyfile
python3 scripts/gen_caddyfile.py
# Regenerate Readme
python3 scripts/gen_caddyfile.py```
