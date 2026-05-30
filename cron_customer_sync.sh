#!/bin/bash
# ============================================================
# IMS Full Customer Sync - cPanel Cron Runner
# Schedule: 0 */4 * * * (every 4 hours)
# Command: /bin/bash /home/countrylinks/public_html/ims_automation/cron_customer_sync.sh
# ============================================================

set -u

# Project directory
PROJECT_DIR="/home/countrylinks/public_html/ims_automation"
VENV_ACTIVATE="/home/countrylinks/virtualenv/public_html/ims_automation/3.13/bin/activate"
LOG_FILE="$PROJECT_DIR/logs/customer_sync_cron.log"

# Ensure log directory exists
mkdir -p "$PROJECT_DIR/logs"

# Redirect all output to log file
exec >> "$LOG_FILE" 2>&1

echo ""
echo "=============================================="
echo "Customer Sync Cron started: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=============================================="

# Activate virtual environment
if [ -f "$VENV_ACTIVATE" ]; then
    source "$VENV_ACTIVATE"
    echo "Virtualenv activated: $(which python)"
else
    echo "ERROR: Virtualenv not found at $VENV_ACTIVATE"
    exit 1
fi

# Change to project directory
cd "$PROJECT_DIR" || { echo "ERROR: Cannot cd to $PROJECT_DIR"; exit 1; }

echo "Python: $(python --version)"
echo "Working dir: $(pwd)"

# Run full customer sync
echo ""
echo "--- Running full customer sync ---"
python sync_customers.py --page-size 100
SYNC_EXIT=$?

if [ $SYNC_EXIT -ne 0 ]; then
    echo "ERROR: Customer sync failed with exit code $SYNC_EXIT"
fi

echo ""
echo "Customer Sync Cron finished: $(date '+%Y-%m-%d %H:%M:%S') (exit=$SYNC_EXIT)"
echo "=============================================="

deactivate 2>/dev/null
exit $SYNC_EXIT
