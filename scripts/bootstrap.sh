#!/usr/bin/env bash
# One-time setup on the Raspberry Pi.
# Run as pi user: bash scripts/bootstrap.sh
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "$0")/.." && pwd)"

log() { echo "[bootstrap] $*"; }
err() { echo "[ERROR] $*" >&2; exit 1; }

[[ "$(uname -m)" == arm* || "$(uname -m)" == aarch64 ]] || {
  echo "Warning: not running on ARM — are you on the Pi?"
  read -rp "Continue anyway? [y/N] " yn; [[ "$yn" == [yY] ]] || exit 1
}

# ── 1. Install yq ─────────────────────────────────────────────────────────────
if ! command -v yq &>/dev/null; then
  log "Installing yq..."
  YQ_VERSION="v4.44.1"
  YQ_BINARY="yq_linux_arm64"
  sudo wget -qO /usr/local/bin/yq \
    "https://github.com/mikefarah/yq/releases/download/${YQ_VERSION}/${YQ_BINARY}"
  sudo chmod +x /usr/local/bin/yq
  log "yq $(yq --version) installed"
else
  log "yq already installed: $(yq --version)"
fi

# ── 2. Create deploy group and add users ──────────────────────────────────────
log "Setting up 'deploy' group..."
if ! getent group deploy &>/dev/null; then
  sudo groupadd deploy
fi
sudo usermod -aG deploy pi
sudo usermod -aG deploy caddy 2>/dev/null || log "Warning: caddy user not found (is Caddy installed?)"

# ── 3. Create /srv/apps with correct ownership ────────────────────────────────
log "Creating /srv/apps..."
sudo mkdir -p /srv/apps
sudo chown pi:deploy /srv/apps
sudo chmod 2775 /srv/apps           # setgid: new files inherit deploy group

# ── 4. Symlink Caddyfile ──────────────────────────────────────────────────────
log "Symlinking Caddyfile → /etc/caddy/Caddyfile..."
sudo mkdir -p /etc/caddy
if [[ -f /etc/caddy/Caddyfile && ! -L /etc/caddy/Caddyfile ]]; then
  sudo mv /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.bak.$(date +%Y%m%d%H%M%S)"
  log "Backed up existing Caddyfile"
fi
sudo ln -sf "$DEPLOY_DIR/Caddyfile" /etc/caddy/Caddyfile
log "Symlinked: /etc/caddy/Caddyfile → $DEPLOY_DIR/Caddyfile"

# ── 5. Allow pi to reload Caddy without password ──────────────────────────────
SUDOERS_LINE="pi ALL=(ALL) NOPASSWD: /usr/bin/caddy reload *"
SUDOERS_FILE="/etc/sudoers.d/caddy-reload"
if ! sudo grep -qF "caddy reload" "$SUDOERS_FILE" 2>/dev/null; then
  echo "$SUDOERS_LINE" | sudo tee "$SUDOERS_FILE" > /dev/null
  sudo chmod 440 "$SUDOERS_FILE"
  log "Added sudoers rule for caddy reload"
fi

# ── 6. Make deploy.sh executable ─────────────────────────────────────────────
chmod +x "$DEPLOY_DIR/deploy.sh"

log ""
log "Bootstrap complete. Next steps:"
log "  1. Re-login (or run: newgrp deploy) so group membership takes effect"
log "  2. Run: $DEPLOY_DIR/deploy.sh all"
log "  3. Stop old PM2 'Website' process (now served by Caddy directly):"
log "     pm2 delete Website && pm2 save"
