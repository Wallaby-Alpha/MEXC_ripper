#!/usr/bin/env bash
# ==============================================================================
# MEXC Momentum Scanner (OPTIMIZED EDITION v2.0)
# 1-Click DigitalOcean Droplet Automated Deployment Script
# Compatible with Ubuntu 22.04 / 24.04 LTS (PEP 668 compliant) & Debian 11/12
# ==============================================================================

set -e

echo "=================================================================="
echo " 🚀 Deploying MEXC Momentum Scanner (Optimized v2.0) to Droplet"
echo "=================================================================="

# 1. System Package Updates & Essential Tools
echo "[+] Installing core system dependencies..."
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip python3-venv git curl ufw

# 2. Setup Working Directory
APP_DIR="/opt/mexc-momentum-scanner-optimized"
if [ "$PWD" != "$APP_DIR" ]; then
    echo "[+] Ensuring application directory exists at $APP_DIR..."
    sudo mkdir -p "$APP_DIR"
    if [ -d ".git" ] || [ -f "run_scanner.py" ]; then
        sudo cp -r ./* "$APP_DIR"/ 2>/dev/null || true
    fi
    cd "$APP_DIR"
fi

# 3. Environment Configuration Check
if [ ! -f ".env" ]; then
    echo "[!] .env configuration file missing. Creating from template..."
    cat << 'EOF' > .env
# Telegram Bot Credentials
TELEGRAM_BOT_TOKEN="YOUR_BOT_TOKEN_FROM_BOTFATHER"
TELEGRAM_CHAT_ID="YOUR_TELEGRAM_CHAT_ID"

# WEEX Live Futures API
WEEX_API_KEY="YOUR_WEEX_API_KEY"
WEEX_API_SECRET="YOUR_WEEX_API_SECRET"
WEEX_PASSPHRASE="YOUR_WEEX_PASSPHRASE"
WEEX_BASE_URL="https://api-contract.weex.com"

# Execution & Risk Parameters
WEEX_LIVE_TRADING_ENABLED=true
WEEX_TRADE_SIZE_USDT=1.0
WEEX_LEVERAGE=10
WEEX_MAX_MARGIN_MULTIPLIER=1.30
EOF
    echo "=================================================================="
    echo " ⚠️ IMPORTANT: Please edit .env now with your API keys!"
    echo " Run: nano .env"
    echo "=================================================================="
fi

# 4. Create Virtual Environment & Install Python Dependencies (PEP 668 Compliant)
echo "[+] Creating Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

echo "[+] Installing Python requirements inside virtual environment..."
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# 5. Configure Systemd 24/7 Daemon
echo "[+] Installing systemd background service..."
sudo cp mexc-scanner-optimized.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable mexc-scanner-optimized
sudo systemctl restart mexc-scanner-optimized

echo "=================================================================="
echo " ✅ Deployment Complete!"
echo " The Optimized Scanner is now running 24/7 in the background."
echo "=================================================================="
echo " Useful Droplet Management Commands:"
echo "   • Stream Live Logs:   journalctl -u mexc-scanner-optimized -f"
echo "   • Check Service Status: systemctl status mexc-scanner-optimized"
echo "   • Restart Bot:        sudo systemctl restart mexc-scanner-optimized"
echo "   • Stop Bot:           sudo systemctl stop mexc-scanner-optimized"
echo "=================================================================="
