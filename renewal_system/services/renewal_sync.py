"""Renewal data sync service.

Syncs data from the existing IMS fetcher (renewals table) into
the renewal_records table used by the campaign system.

This bridges the existing cron fetcher with the new campaign dashboard.

Strategy:
- Only sync records from the LATEST fetch (based on fetched_at timestamp).
- Remove stale records from renewal_records that are no longer in the latest data.
- This ensures the dashboard always reflects the current IMS data.
"""

import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)


def sync_from_renewals_table(config):
    """Sync records from the existing 'renewals' table to 'renewal_records'.

    Only uses records from the most recent fetch run (latest fetched_at).
    Removes records from renewal_records that are no longer present in
    the latest IMS data.

    Args:
        config: Application config with DB credentials.

    Returns:
        Dict with sync stats (inserted, updated, removed, total).
    """
    from renewal_system.models.database import get_db_cursor
    from renewal_system.services.classifier import classify_customer

    today = date.today()
    stats = {"inserted": 0, "updated": 0, "removed": 0, "total": 0}

    with get_db_cursor(config) as cursor:
        # Get the latest fetch timestamp to only use fresh data
        cursor.execute("""
            SELECT MAX(fetched_at) AS latest_fetch FROM renewals
        """)
        row = cursor.fetchone()
        if not row or not row["latest_fetch"]:
            logger.warning("No records found in renewals table.")
            return stats

        latest_fetch = row["latest_fetch"]
        # Use records fetched within the same batch (within 5 minutes of the latest)
        if isinstance(latest_fetch, str):
            latest_fetch = datetime.strptime(latest_fetch, "%Y-%m-%d %H:%M:%S")

        logger.info("Latest fetch timestamp: %s", latest_fetch)

        # Fetch only records from the latest fetch batch
        # Also get the latest record per user_id in case of duplicates
        cursor.execute("""
            SELECT r.user_id, r.cust_name, r.mobile_no, r.plan_name, r.amount,
                   r.plan_expiry_date, r.zone_name
            FROM renewals r
            INNER JOIN (
                SELECT user_id, MAX(plan_expiry_date) AS max_expiry
                FROM renewals
                WHERE plan_expiry_date IS NOT NULL
                  AND fetched_at >= DATE_SUB(%s, INTERVAL 5 MINUTE)
                GROUP BY user_id
            ) latest ON r.user_id = latest.user_id AND r.plan_expiry_date = latest.max_expiry
            WHERE r.fetched_at >= DATE_SUB(%s, INTERVAL 5 MINUTE)
        """, (latest_fetch, latest_fetch))
        source_records = cursor.fetchall()
        stats["total"] = len(source_records)

        # Track which account_ids are in the current sync
        synced_account_ids = set()

        for record in source_records:
            expiry_date = record["plan_expiry_date"]
            if isinstance(expiry_date, datetime):
                expiry_date = expiry_date.date()
            elif isinstance(expiry_date, str):
                expiry_date = datetime.strptime(expiry_date[:10], "%Y-%m-%d").date()

            # Classify based on today's date
            classification = classify_customer(expiry_date, today)

            synced_account_ids.add(record["user_id"])

            # Upsert into renewal_records
            cursor.execute("""
                INSERT INTO renewal_records
                    (account_id, customer_name, mobile, plan_name, amount,
                     expiry_date, zone_name, days_remaining, category)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    customer_name = VALUES(customer_name),
                    mobile = VALUES(mobile),
                    plan_name = VALUES(plan_name),
                    amount = VALUES(amount),
                    expiry_date = VALUES(expiry_date),
                    zone_name = VALUES(zone_name),
                    days_remaining = VALUES(days_remaining),
                    category = VALUES(category),
                    updated_at = CURRENT_TIMESTAMP
            """, (
                record["user_id"],
                record["cust_name"],
                record["mobile_no"],
                record["plan_name"],
                record.get("amount"),
                expiry_date,
                record.get("zone_name"),
                classification["days_remaining"],
                classification["category"],
            ))

            if cursor.rowcount == 1:
                stats["inserted"] += 1
            elif cursor.rowcount == 2:
                stats["updated"] += 1

        # Remove stale records that are no longer in the latest fetch
        if synced_account_ids:
            placeholders = ",".join(["%s"] * len(synced_account_ids))
            cursor.execute(
                f"DELETE FROM renewal_records WHERE account_id NOT IN ({placeholders})",
                list(synced_account_ids)
            )
            stats["removed"] = cursor.rowcount
            if stats["removed"] > 0:
                logger.info("Removed %d stale records from renewal_records", stats["removed"])

    logger.info("Sync complete: %d inserted, %d updated, %d removed (of %d total from latest fetch)",
                stats["inserted"], stats["updated"], stats["removed"], stats["total"])
    return stats
