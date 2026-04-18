#!/usr/bin/env bash
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
APPS_YAML="$DEPLOY_DIR/apps.yaml"

# ── helpers ──────────────────────────────────────────────────────────────────

log()  { echo "[$(date '+%H:%M:%S')] $*"; }
err()  { echo "[ERROR] $*" >&2; exit 1; }
info() { echo ""; echo "━━━ $* ━━━"; }

require() {
  command -v "$1" &>/dev/null || err "'$1' not found — run scripts/bootstrap.sh first"
}

yq_app() {
  # Usage: yq_app <name> <field>
  yq e ".apps[] | select(.name == \"$1\") | .$2" "$APPS_YAML"
}

# ── git helpers ───────────────────────────────────────────────────────────────

pull_or_clone() {
  local repo=$1 path=$2
  if [[ -d "$path/.git" ]]; then
    git -C "$path" pull --ff-only
  else
    git clone "$repo" "$path"
  fi
}

# ── deploy types ──────────────────────────────────────────────────────────────

deploy_static() {
  local name=$1
  local repo;        repo=$(yq_app "$name" repo)
  local build;       build=$(yq_app "$name" "build // \"\"")
  local output;      output=$(yq_app "$name" "output // \".\"")
  local deploy_path; deploy_path=$(yq_app "$name" deploy_path)

  log "[$name] pulling $repo → $deploy_path"
  pull_or_clone "$repo" "$deploy_path"

  if [[ "$build" != "null" && -n "$build" ]]; then
    log "[$name] building: $build"
    (cd "$deploy_path" && eval "$build")
  fi

  # Ensure caddy group can read the output
  chmod -R g+rX "$deploy_path/$output"
  log "[$name] ✓ serving from $deploy_path/$output"
}

deploy_service() {
  local name=$1
  local repo;        repo=$(yq_app "$name" repo)
  local build;       build=$(yq_app "$name" "build // \"\"")
  local deploy_path; deploy_path=$(yq_app "$name" deploy_path)
  local pm2_name;    pm2_name=$(yq_app "$name" "pm2_name // \"$name\"")
  local entry;       entry=$(yq_app "$name" "entry // \"null\"")
  local start_cmd;   start_cmd=$(yq_app "$name" "start_cmd // \"null\"")

  log "[$name] pulling $repo → $deploy_path"
  pull_or_clone "$repo" "$deploy_path"

  if [[ "$build" != "null" && -n "$build" ]]; then
    log "[$name] building: $build"
    (cd "$deploy_path" && eval "$build")
  fi

  log "[$name] restarting PM2 process '$pm2_name'"
  if pm2 describe "$pm2_name" &>/dev/null; then
    pm2 restart "$pm2_name"
  else
    if [[ "$start_cmd" != "null" ]]; then
      # Non-Node service (e.g., Java) — run arbitrary command via bash
      pm2 start --name "$pm2_name" --interpreter bash -- \
        -c "cd '$deploy_path' && $start_cmd"
    else
      pm2 start "$deploy_path/$entry" --name "$pm2_name"
    fi
  fi
  pm2 save --force

  log "[$name] ✓ service running"
}

# ── main ──────────────────────────────────────────────────────────────────────

require yq
require pm2
require git

TARGET="${1:-all}"
DEPLOYED=0
FAILED=()

ALL_NAMES=$(yq e '.apps[].name' "$APPS_YAML")

for name in $ALL_NAMES; do
  if [[ "$TARGET" != "all" && "$TARGET" != "$name" ]]; then
    continue
  fi

  type=$(yq_app "$name" type)
  info "$name ($type)"

  if deploy_"$type" "$name"; then
    DEPLOYED=$((DEPLOYED + 1))
  else
    FAILED+=("$name")
  fi
done

if [[ "$DEPLOYED" -eq 0 && "$TARGET" != "all" ]]; then
  err "App '$TARGET' not found in apps.yaml"
fi

# Reload Caddy only if any static app was (re)deployed or deploying all
if [[ "${#FAILED[@]}" -eq 0 && ("$TARGET" == "all" || "$(yq_app "$TARGET" type 2>/dev/null)" == "static") ]]; then
  log "Reloading Caddy..."
  sudo caddy reload --config /etc/caddy/Caddyfile 2>/dev/null && log "✓ Caddy reloaded" || log "⚠ Caddy reload skipped (not running?)"
fi

echo ""
echo "Deployed: $DEPLOYED  Failed: ${#FAILED[@]}"
if [[ "${#FAILED[@]}" -gt 0 ]]; then
  echo "Failed apps: ${FAILED[*]}"
  exit 1
fi
