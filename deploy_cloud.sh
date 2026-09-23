#!/usr/bin/env bash
# ==========================================================
# Upwork Lead Scraper - Cloud VPS / CloudPanel Setup Script
# ==========================================================

set -e

echo "[+] Updating system packages..."
sudo apt-get update -y
sudo apt-get install -y python3-pip python3-venv wget curl git google-chrome-stable || true

# Check Chrome installation
if ! command -v google-chrome &> /dev/null; then
    echo "[+] Installing Google Chrome..."
    wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
    sudo apt-get install -y ./google-chrome-stable_current_amd64.deb
    rm google-chrome-stable_current_amd64.deb
fi

echo "[+] Setting up Python Virtual Environment..."
cd "$(dirname "$0")/Script"
python3 -m venv venv
source venv/bin/activate

echo "[+] Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt gunicorn

echo "[+] Checking environment..."
python deploy_check.py

echo "=========================================================="
echo "🎉 Setup Complete!"
echo "To start the Web Dashboard server in background:"
echo "  nohup python app.py > ../logs/web_app.log 2>&1 &"
echo "To run daily scraper cron job at 7 AM:"
echo "  0 7 * * * cd $(pwd) && ./venv/bin/python daily_run.py >> ../logs/cron.log 2>&1"
echo "=========================================================="
