#!/usr/bin/env bash
# Run this once from the repo root on your EC2 instance.
# Tested on Ubuntu 22.04 LTS.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$APP_DIR/venv"
RUN_USER="$(whoami)"

echo "==> App directory : $APP_DIR"
echo "==> Running as    : $RUN_USER"

# ── System packages ──────────────────────────────────────────────────────────
echo "==> Installing system packages..."
sudo apt-get update -q
sudo apt-get install -y python3 python3-pip python3-venv nginx curl

# ── Python virtualenv ─────────────────────────────────────────────────────────
echo "==> Setting up Python venv..."
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip -q
"$VENV/bin/pip" install -r "$APP_DIR/requirements.txt" -q

# ── Secret key ────────────────────────────────────────────────────────────────
if [ ! -f "$APP_DIR/.env" ]; then
    SK=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    printf "SECRET_KEY=%s\nFLASK_ENV=production\n" "$SK" > "$APP_DIR/.env"
    echo "==> Created .env with a generated SECRET_KEY"
else
    echo "==> .env already exists, skipping"
fi

# ── systemd service ───────────────────────────────────────────────────────────
echo "==> Installing systemd service..."
sed \
    -e "s|{{APP_DIR}}|$APP_DIR|g" \
    -e "s|{{VENV}}|$VENV|g" \
    -e "s|{{USER}}|$RUN_USER|g" \
    "$APP_DIR/deploy/tickettoride.service" \
    | sudo tee /etc/systemd/system/tickettoride.service > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable tickettoride
sudo systemctl restart tickettoride
echo "==> Service: $(sudo systemctl is-active tickettoride)"

# ── nginx ─────────────────────────────────────────────────────────────────────
echo "==> Configuring nginx..."
sudo cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/tickettoride
sudo ln -sf /etc/nginx/sites-available/tickettoride /etc/nginx/sites-enabled/tickettoride
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

# ── Done ──────────────────────────────────────────────────────────────────────
PUBLIC_IP=$(curl -sf http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "<your-ec2-ip>")
echo ""
echo "✓ Deployment complete!"
echo "  → http://$PUBLIC_IP"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status tickettoride   # check app status"
echo "  sudo journalctl -u tickettoride -f   # tail app logs"
echo "  sudo systemctl restart tickettoride  # restart after code changes"
