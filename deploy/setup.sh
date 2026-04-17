#!/usr/bin/env bash
# =============================================================================
# deploy/setup.sh — One-command Oracle Cloud Free Tier setup script
#
# Run this ONCE on a fresh Oracle Cloud Ubuntu 22.04 VM:
#   bash <(curl -fsSL https://raw.githubusercontent.com/YOUR_USER/YOUR_REPO/main/deploy/setup.sh)
#
# Or after SSH-ing into the VM:
#   git clone https://github.com/YOUR_USER/YOUR_REPO.git /opt/smarthire
#   cd /opt/smarthire && bash deploy/setup.sh
# =============================================================================
set -euo pipefail

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

APP_DIR="/opt/smarthire"
APP_USER="smarthire"
VENV_DIR="$APP_DIR/venv"
LOG_DIR="/var/log/smarthire"
PYTHON="python3.11"

echo ""
echo "========================================="
echo "  SmartHire Oracle Cloud Setup Script"
echo "========================================="
echo ""

# ── 0. Must run as root ───────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && error "Run as root: sudo bash deploy/setup.sh"

# ── 1. System packages ────────────────────────────────────────────────────────
info "Updating system packages..."
apt-get update -qq
apt-get install -y -qq \
    python3.11 python3.11-venv python3.11-dev \
    python3-pip \
    nginx \
    gcc g++ \
    git curl wget \
    certbot python3-certbot-nginx \
    ufw \
    libpq-dev        # for psycopg2 if PostgreSQL is used
success "System packages installed"

# ── 2. Create dedicated app user ─────────────────────────────────────────────
if ! id "$APP_USER" &>/dev/null; then
    useradd --system --shell /bin/bash --home "$APP_DIR" --create-home "$APP_USER"
    success "Created user: $APP_USER"
else
    success "User $APP_USER already exists"
fi

# ── 3. Copy app to /opt/smarthire (if not already there) ─────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(dirname "$SCRIPT_DIR")"

if [[ "$SRC_DIR" != "$APP_DIR" ]]; then
    info "Copying app source to $APP_DIR..."
    rsync -a --exclude venv --exclude __pycache__ --exclude "*.pyc" \
          --exclude ".git" --exclude "instance/*.db" \
          "$SRC_DIR/" "$APP_DIR/"
fi

# ── 4. Python virtual environment ────────────────────────────────────────────
info "Creating Python virtual environment..."
if [[ ! -d "$VENV_DIR" ]]; then
    $PYTHON -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" -q
success "Python dependencies installed"

# ── 5. Create required directories ───────────────────────────────────────────
info "Creating required directories..."
mkdir -p "$APP_DIR/instance" "$APP_DIR/resumes" "$APP_DIR/results" "$LOG_DIR"
touch "$APP_DIR/resumes/.gitkeep" "$APP_DIR/results/.gitkeep"
chown -R "$APP_USER:$APP_USER" "$APP_DIR" "$LOG_DIR"
success "Directories created and permissions set"

# ── 6. .env file ─────────────────────────────────────────────────────────────
if [[ ! -f "$APP_DIR/.env" ]]; then
    warn ".env file not found! Creating template..."
    cat > "$APP_DIR/.env" << 'EOF'
# ── REQUIRED — fill in before starting the service ─────────────────────────
SECRET_KEY=REPLACE_WITH_STRONG_SECRET_KEY
FIREBASE_API_KEY=REPLACE_WITH_YOUR_FIREBASE_API_KEY

# ── OPTIONAL API Keys ────────────────────────────────────────────────────────
GEMINI_API_KEY=
GROQ_API_KEY=

# ── Database (leave blank to use SQLite, or set a PostgreSQL URL) ────────────
# DATABASE_URL=postgresql://user:password@localhost:5432/smarthire

# ── Upload storage ───────────────────────────────────────────────────────────
UPLOAD_DIR=/opt/smarthire/resumes
EOF
    chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
    chmod 600 "$APP_DIR/.env"
    warn "IMPORTANT: Edit /opt/smarthire/.env and fill in SECRET_KEY and FIREBASE_API_KEY!"
    warn "Then run: sudo systemctl start smarthire"
else
    success ".env file already exists"
fi

# ── 7. Generate SECRET_KEY if placeholder ────────────────────────────────────
if grep -q "REPLACE_WITH_STRONG_SECRET_KEY" "$APP_DIR/.env"; then
    GENERATED_KEY=$(openssl rand -hex 32)
    sed -i "s/REPLACE_WITH_STRONG_SECRET_KEY/$GENERATED_KEY/" "$APP_DIR/.env"
    success "Auto-generated SECRET_KEY"
fi

# ── 8. Install systemd service ────────────────────────────────────────────────
info "Installing systemd service..."
cp "$APP_DIR/deploy/smarthire.service" /etc/systemd/system/smarthire.service
systemctl daemon-reload
systemctl enable smarthire
success "systemd service installed and enabled"

# ── 9. Configure nginx ────────────────────────────────────────────────────────
info "Configuring nginx..."
cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/smarthire
ln -sf /etc/nginx/sites-available/smarthire /etc/nginx/sites-enabled/smarthire
rm -f /etc/nginx/sites-enabled/default  # remove nginx default page
nginx -t && systemctl reload nginx
success "nginx configured"

# ── 10. Firewall (UFW) ────────────────────────────────────────────────────────
info "Configuring firewall..."
ufw allow OpenSSH
ufw allow 'Nginx Full'   # ports 80 and 443
ufw --force enable
success "Firewall configured (SSH + HTTP/HTTPS allowed)"

# ── 11. Oracle Cloud iptables fix ─────────────────────────────────────────────
# Oracle adds iptables rules that block ports by default — we allow HTTP/HTTPS
info "Fixing Oracle Cloud iptables..."
iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80  -j ACCEPT
iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
# Save rules so they persist after reboot
if command -v netfilter-persistent &>/dev/null; then
    netfilter-persistent save
else
    apt-get install -y -qq iptables-persistent
    netfilter-persistent save
fi
success "Oracle Cloud iptables rules applied"

# ── 12. Start the app ─────────────────────────────────────────────────────────
info "Starting SmartHire service..."
systemctl start smarthire || warn "Service failed to start — check: sudo journalctl -u smarthire -n 50"

sleep 2
if systemctl is-active --quiet smarthire; then
    success "Service is running!"
else
    warn "Service not running yet. Check logs: sudo journalctl -u smarthire -n 50"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
VM_IP=$(curl -s ifconfig.me || echo "your-vm-ip")
echo ""
echo "========================================="
echo -e "${GREEN}  Setup Complete!${NC}"
echo "========================================="
echo ""
echo "  App URL   : http://$VM_IP"
echo "  Health    : http://$VM_IP/health"
echo "  Logs      : sudo journalctl -u smarthire -f"
echo "  Restart   : sudo systemctl restart smarthire"
echo "  Edit .env : sudo nano /opt/smarthire/.env"
echo ""
echo "  NEXT STEP: Add your domain and enable HTTPS (free SSL):"
echo "  sudo certbot --nginx -d yourdomain.com"
echo ""
