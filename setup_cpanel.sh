#!/bin/bash
# ============================================================
# IMS Data Fetcher - cPanel Setup Script
# Run this ONCE after uploading files to your cPanel server
# ============================================================

echo "=== IMS Data Fetcher - cPanel Setup ==="
echo ""

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "[1/4] Creating Python virtual environment..."
python3 -m venv venv
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to create virtual environment."
    echo "Try: python3.9 -m venv venv  (or whatever version your host has)"
    exit 1
fi

echo "[2/4] Installing dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to install dependencies."
    exit 1
fi

echo "[3/4] Creating required directories..."
mkdir -p logs
mkdir -p output
mkdir -p diagnostics

echo "[4/4] Setting permissions..."
chmod +x run_fetcher.sh
chmod 600 .env

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env with your actual XIMS password"
echo "  2. Test manually: ./run_fetcher.sh"
echo "  3. Set up cPanel Cron Job with this command:"
echo "     $SCRIPT_DIR/run_fetcher.sh >> $SCRIPT_DIR/logs/cron.log 2>&1"
echo ""
