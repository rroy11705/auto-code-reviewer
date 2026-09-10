#!/usr/bin/env bash
# ==============================================================================
# auto-code-reviewer: 1-Click Vultr VPS Provisioning & Deployment Script
# Tested on Ubuntu 22.04 / 24.04 LTS
# ==============================================================================

set -euo pipefail

echo "=========================================================="
echo "🚀 Setting up auto-code-reviewer on Vultr VPS..."
echo "=========================================================="

# 1. Ensure script is run as root or with sudo
if [ "$EUID" -ne 0 ]; then
  echo "❌ Please run this script as root or with sudo: sudo bash setup_vultr.sh"
  exit 1
fi

# 2. Update system packages
echo "📦 Updating apt packages..."
apt-get update -y
apt-get upgrade -y
apt-get install -y curl git ufw ca-certificates gnupg lsb-release

# 3. Install Docker and Docker Compose Plugin if not already present
if ! command -v docker &> /dev/null; then
  echo "🐳 Installing Docker..."
  mkdir -p /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
    $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
  systemctl enable docker
  systemctl start docker
  echo "✅ Docker installed successfully."
else
  echo "✅ Docker is already installed."
fi

# 4. Configure UFW Firewall
echo "🛡️ Configuring firewall rules..."
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP'
ufw allow 443/tcp comment 'HTTPS'
ufw allow 8000/tcp comment 'Reviewer Direct Port'
ufw --force enable
echo "✅ Firewall configured."

# 5. Check for .env file
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

if [ ! -f .env ]; then
  echo "⚠️ .env file not found. Copying .env.example -> .env..."
  cp .env.example .env
  echo "❗ Please edit .env with your GITHUB_TOKEN, WEBHOOK_SECRET, and OPENHANDS_ENDPOINT:"
  echo "   nano .env"
fi

# 6. Prompt or check deployment mode
echo ""
echo "Choose deployment mode:"
echo "1) Direct Port 8000 (Local / Behind Cloudflare / Test)"
echo "2) Production with Automatic HTTPS via Caddy (Recommended for GitHub Webhooks)"
read -rp "Enter choice [1 or 2, default: 1]: " DEPLOY_CHOICE
DEPLOY_CHOICE=${DEPLOY_CHOICE:-1}

if [ "$DEPLOY_CHOICE" = "2" ]; then
  read -rp "Enter your domain or subdomain (e.g. reviewer.yourdomain.com): " USER_DOMAIN
  export DOMAIN="$USER_DOMAIN"
  echo "DOMAIN=$USER_DOMAIN" >> .env
  echo "🚀 Launching auto-code-reviewer with Caddy HTTPS reverse proxy..."
  docker compose --profile with-proxy up -d --build
else
  echo "🚀 Launching auto-code-reviewer directly on port 8000..."
  docker compose up -d --build
fi

echo ""
echo "=========================================================="
echo "🎉 Deployment Complete!"
echo "=========================================================="
SERVER_IP=$(curl -s https://api.ipify.org || hostname -I | awk '{print $1}')
echo "Server Public IP: $SERVER_IP"
if [ "$DEPLOY_CHOICE" = "2" ]; then
  echo "Webhook URL: https://$USER_DOMAIN/webhook/github"
else
  echo "Webhook URL: http://$SERVER_IP:8000/webhook/github"
fi
echo ""
echo "Next Steps:"
echo "1. Go to your GitHub Repository -> Settings -> Webhooks -> Add webhook"
echo "2. Payload URL: (URL shown above)"
echo "3. Content type: application/json"
echo "4. Secret: (Same value as GITHUB_WEBHOOK_SECRET in .env)"
echo "5. Events: Select 'Pull requests'"
echo "6. Click 'Add webhook' and check container logs with: docker compose logs -f"
