#!/usr/bin/env bash
# =============================================================================
# deploy/update.sh — Pull latest code & restart the service (runs on the VM)
#
# Usage (on the Oracle Cloud VM):
#   cd /opt/smarthire && sudo bash deploy/update.sh
# =============================================================================
set -euo pipefail

GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }

APP_DIR="/opt/smarthire"
VENV_DIR="$APP_DIR/venv"

info "Pulling latest code from git..."
git -C "$APP_DIR" pull

info "Updating Python dependencies..."
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" -q

info "Clearing stale bytecode..."
find "$APP_DIR" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

info "Restarting service..."
systemctl restart smarthire
sleep 2
systemctl is-active --quiet smarthire && success "Service restarted OK" || echo "Check: sudo journalctl -u smarthire -n 30"
