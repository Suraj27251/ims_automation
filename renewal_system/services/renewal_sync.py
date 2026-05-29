"""Renewal data sync service.

Syncs data from the existing IMS fetcher (renewals table) into
the renewal_records table used by the campaign system.

This bridges the existing cron fetcher with the new campaign dashboard.

Strategy:
- Sync the latest record per user from the renewals table.
- Classify each record as expired/today/upcoming based on today's date.
- Remove very old records (expired more than 7 days) to keep dashboard clean.
- Preserve recently expired records so operators can still see/contact them.
"""

import logging
from datetime import date, datetime, timedelta

logger = logging.getLogger(__name__)

# How many days to keep expired records visible on the dashboard
EXPIRED_RETENTION_DAYS = 7


def sync_from_renewals_table(config):
    """Sync records from the existing 'renewals' table to 'renewal_records'.

    Uses the latest expiry date per user from the renewals table.
    Removes records that expired more than EXPIRED_RETENTION_DAYS ago.

    Args:
        config: Application config with DB credentials.

    Returns:
        Dict with sync stats (inserted, updated, removed, total).
    """
    from renewal_system.models.database import get_db_cursor
    from renewal_system.services.classifier import classify_customer

    today = date.today()
    cutoff_date = today - timedelta(days=EXPIRED_RETENTION_DAYS)
    stats = {"inserted": 0, "updated": 0, "removed": 0, "total": 0}

    with get_db_cursor(config) as cursor:
        # Fetch the latest record per user_id from the renewals table.
        # Uses MAX(plan_expiry_date) to get the most recent plan per user.
        cursor.execute("""
            SELECT r.user_id, r.cust_name, r.mobile_no, r.plan_name, r.amount,
                   r.plan_expiry_date, r.zone_name
            FROM renewals r
            INNER JOIN (
                SELECT user_id, MAX(plan_expiry_date) AS max_expiry
                FROM renewals
                WHERE plan_expiry_date IS NOT NULL
                GROUP BY user_id
            ) latest ON r.user_id = latest.user_id AND r.plan_expiry_date = latest.max_expiry
        """)
        source_records = cursor.fetchall()
        stats["total"] = len(source_records)

        for record in source_records:
            expiry_date = record["plan_expiry_date"]
            if isinstance(expiry_date, datetime):
                expiry_date = expiry_date.date()
            elif isinstance(expiry_date, str):
                expiry_date = datetime.strptime(expiry_date[:10], "%Y-%m-%d").date()

            # Classify based on today's date
            classification = classify_customer(expiry_date, today)

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

        # Remove records that expired more than 7 days ago (no longer actionable)
        cursor.execute(
            "DELETE FROM renewal_records WHERE expiry_date < %s",
            (cutoff_date,)
        )
        stats["removed"] = cursor.rowcount
        if stats["removed"] > 0:
            logger.info("Removed %d records expired before %s", stats["removed"], cutoff_date)

    logger.info("Sync complete: %d inserted, %d updated, %d removed (of %d total)",
                stats["inserted"], stats["updated"], stats["removed"], stats["total"])
    return stats
