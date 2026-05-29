"""Renewal data sync service.

Syncs data from the existing IMS fetcher (renewals table) into
the renewal_records table used by the campaign system.

This bridges the existing cron fetcher with the new campaign dashboard.
"""

import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)


def sync_from_renewals_table(config):
    """Sync records from the existing 'renewals' table to 'renewal_records'.

    The existing cron job populates the 'renewals' table.
    This function copies/updates records into 'renewal_records' with
    classification data for the campaign dashboard.

    Args:
        config: Application config with DB credentials.

    Returns:
        Dict with sync stats (inserted, updated, total).
    """
    from renewal_system.models.database import get_db_cursor
    from renewal_system.services.classifier import classify_customer

    today = date.today()
    stats = {"inserted": 0, "updated": 0, "total": 0}

    with get_db_cursor(config) as cursor:
        # Fetch only the latest record per user_id from the renewals table.
        # The renewals table may contain multiple entries per user (different expiry dates).
        # We want the most recent expiry_date for each user to classify correctly.
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

            # Classify
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

    logger.info("Sync complete: %d inserted, %d updated (of %d total)",
                stats["inserted"], stats["updated"], stats["total"])
    return stats
