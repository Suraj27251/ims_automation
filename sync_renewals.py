"""Standalone script to sync renewal data and classify customers.

Run this after the IMS fetcher cron job to update the campaign dashboard.
Can also be called independently.

Usage:
    python sync_renewals.py
"""

import sys
import os
import logging

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(override=False)

from renewal_system.config import config
from renewal_system.models.database import init_tables
from renewal_system.services.renewal_sync import sync_from_renewals_table
from renewal_system.services.classifier import classify_and_update_records

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


def main():
    """Sync and classify renewal records."""
    logger.info("=" * 50)
    logger.info("Renewal Sync & Classification starting")
    logger.info("=" * 50)

    try:
        # Ensure tables exist
        init_tables(config)

        # Sync from renewals table
        sync_stats = sync_from_renewals_table(config)
        logger.info("Sync: %d inserted, %d updated, %d removed, %d total",
                    sync_stats["inserted"], sync_stats["updated"],
                    sync_stats.get("removed", 0), sync_stats["total"])

        # Re-classify all records
        classify_stats = classify_and_update_records(config)
        logger.info("Classification: %s", classify_stats)

        logger.info("Renewal sync completed successfully")
        return 0

    except Exception as e:
        logger.error("Sync failed: %s", e, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
