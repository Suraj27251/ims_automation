#!/bin/bash
# ============================================================
# IMS Data Fetcher - cPanel Cron Runner
# Target: XIMS Panel at ims.marvellousfiber.com
# Schedule this via cPanel > Cron Jobs
#
# Environment variables are set in:
#   cPanel > Setup Python App > Environment Variables
# No .env file needed on the server.
# ============================================================

# Navigate to project directory (auto-detect from script location)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Source the Python app's virtual environment activation script
# cPanel Python App creates this at the app root
if [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
elif [ -f "/home/$USER/virtualenv/ims_automation/bin/activate" ]; then
    # cPanel sometimes puts venvs here
    source "/home/$USER/virtualenv/ims_automation/bin/activate"
fi

# Calculate date range (yesterday to 7 days ahead)
FROM_DATE=$(date -d 'yesterday' '+%Y/%m/%d')
TO_DATE=$(date -d '+7 days' '+%Y/%m/%d')

# Log start time
echo "=== IMS Fetch Started: $(date '+%Y-%m-%d %H:%M:%S') ==="
echo "Date range: $FROM_DATE to $TO_DATE"

# Run the fetcher - exports to CSV in output/ directory
python -m src.main \
    --from-date "$FROM_DATE" \
    --to-date "$TO_DATE" \
    --page-size 50 \
    --export csv

# Capture exit code
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "=== Fetch Completed Successfully ==="

    # Sync to campaign dashboard
    echo "=== Running Campaign Sync ==="
    python sync_renewals.py
    SYNC_CODE=$?
    if [ $SYNC_CODE -eq 0 ]; then
        echo "=== Campaign Sync Completed ==="
    else
        echo "=== Campaign Sync FAILED (exit code: $SYNC_CODE) ==="
    fi
else
    echo "=== Fetch FAILED (exit code: $EXIT_CODE) ==="
fi

echo ""

# Deactivate
deactivate 2>/dev/null

exit $EXIT_CODE
