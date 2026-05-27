#!/bin/bash
# ============================================================
# IMS Data Fetcher - cPanel Cron Runner
# Target: XIMS Panel at ims.marvellousfiber.com
# Schedule this via cPanel > Cron Jobs
# ============================================================

# Navigate to project directory (auto-detect from script location)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Activate virtual environment
source venv/bin/activate

# Calculate date range (yesterday to today)
FROM_DATE=$(date -d 'yesterday' '+%Y/%m/%d')
TO_DATE=$(date '+%Y/%m/%d')

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
else
    echo "=== Fetch FAILED (exit code: $EXIT_CODE) ==="
fi

echo ""

# Deactivate
deactivate

exit $EXIT_CODE
