#!/usr/bin/env bash
# ==============================================================================
# MEXC Altcoin Momentum Scanner: 1-Click DigitalOcean Droplet Deploy Script
# Compatible with Ubuntu 22.04 / 24.04 LTS & Debian 11/12
# ==============================================================================

set -e

echo "========================================================="
echo " Deploying MEXC Momentum Scanner to DigitalOcean Droplet"
echo "========================================================="

# 1. Ensure system updates
sudo apt-get update -y
sudo apt-get install -y curl git ufw

# 2. Check and Install Docker & Docker Compose if not present
if ! command -v docker &> /dev/null; then
    echo "[+] Installing Docker Engine..."
    curl -fsSL https://get.docker.com | sh
    sudo systemctl enable --now docker
else
    echo "[✓] Docker is already installed."
fi

if ! docker compose version &> /dev/null; then
    echo "[+] Installing Docker Compose plugin..."
    sudo apt-get install -y docker-compose-plugin
fi

# 3. Create .env if missing
if [ ! -f ".env" ]; then
    echo "[!] .env not found. Copying template from .env.example..."
    cp .env.example .env
    echo "========================================================="
    echo " Please edit .env now with your credentials:"
    echo " nano .env"
    echo " (Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to enable bot)"
    echo "========================================================="
fi

# 4. Build and start background container
echo "[+] Building container and launching scanner daemon..."
docker compose up -d --build

# 5. Show container status
echo ""
echo "========================================================="
echo " [✓] Deployment Complete!"
echo " Scanner is running 24/7 in the background."
echo "========================================================="
echo " Helpful Management Commands:"
echo "   • View Live Logs:       docker compose logs -f"
echo "   • Check Status:         docker compose ps"
echo "   • Stop Scanner:         docker compose down"
echo "   • Restart Scanner:      docker compose restart"
echo "========================================================="
