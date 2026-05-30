#!/bin/bash
# ============================================================
# IMS Cron Job Runner - cPanel
# Schedule: 0 6 * * * (daily at 6:00 AM)
# Command: /bin/bash /home/countrylinks/public_html/ims_automation/cron_run.sh
# ============================================================

# Exit on undefined variables
set -u

# Project directory
PROJECT_DIR="/home/countrylinks/public_html/ims_automation"
VENV_ACTIVATE="/home/countrylinks/virtualenv/public_html/ims_automation/3.13/bin/activate"
LOG_FILE="$PROJECT_DIR/logs/cron.log"

# Ensure log directory exists
mkdir -p "$PROJECT_DIR/logs"

# Redirect all output to log file
exec >> "$LOG_FILE" 2>&1

echo ""
echo "=============================================="
echo "Cron started: $(date '+%Y-%m-%d %H:%M:%S')"
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

# Calculate date range
FROM_DATE=$(date -d 'yesterday' '+%Y/%m/%d')
TO_DATE=$(date -d '+7 days' '+%Y/%m/%d')

# Fallback if date -d is not supported (shouldn't happen on Linux but just in case)
if [ -z "$FROM_DATE" ] || [ -z "$TO_DATE" ]; then
    echo "ERROR: date -d failed. Using Python fallback."
    FROM_DATE=$(python -c "from datetime import date, timedelta; print((date.today() - timedelta(days=1)).strftime('%Y/%m/%d'))")
    TO_DATE=$(python -c "from datetime import date, timedelta; print((date.today() + timedelta(days=7)).strftime('%Y/%m/%d'))")
fi

echo "Date range: $FROM_DATE to $TO_DATE"
echo "Python: $(python --version)"
echo "Working dir: $(pwd)"

# Step 1: Fetch data from IMS
echo ""
echo "--- Step 1: Fetching renewal data from IMS ---"
python -m src.main --from-date "$FROM_DATE" --to-date "$TO_DATE" --page-size 50
FETCH_EXIT=$?

if [ $FETCH_EXIT -ne 0 ]; then
    echo "ERROR: IMS fetch failed with exit code $FETCH_EXIT"
    echo "Attempting sync anyway (using existing data)..."
fi

# Step 2: Sync to campaign dashboard (run even if fetch fails - uses existing DB data)
echo ""
echo "--- Step 2: Syncing to campaign dashboard ---"
python sync_renewals.py
SYNC_EXIT=$?

if [ $SYNC_EXIT -ne 0 ]; then
    echo "ERROR: Sync failed with exit code $SYNC_EXIT"
fi

echo ""
echo "Cron finished: $(date '+%Y-%m-%d %H:%M:%S') (fetch=$FETCH_EXIT, sync=$SYNC_EXIT)"
echo "=============================================="

# Deactivate
deactivate 2>/dev/null

# Exit with fetch code (primary operation)
exit $FETCH_EXIT
