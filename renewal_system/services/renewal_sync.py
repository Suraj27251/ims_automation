"""Renewal data sync service.

Syncs data from the existing IMS fetcher (renewals table) into
the renewal_records table used by the campaign system.

This bridges the existing cron fetcher with the new campaign dashboard.

Strategy:
- Sync the latest record per user from the renewals table.
- Cross-reference with customers table to check active status.
- If a customer is Active and their expiry is in the future (in customers table),
  they have renewed — skip showing them as expired.
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
    Cross-references with customers table to filter out renewed (Active) users.
    Removes records that expired more than EXPIRED_RETENTION_DAYS ago.

    Args:
        config: Application config with DB credentials.

    Returns:
        Dict with sync stats (inserted, updated, removed, skipped_active, total).
    """
    from renewal_system.models.database import get_db_cursor
    from renewal_system.services.classifier import classify_customer

    today = date.today()
    cutoff_date = today - timedelta(days=EXPIRED_RETENTION_DAYS)
    stats = {"inserted": 0, "updated": 0, "removed": 0, "skipped_active": 0, "total": 0}

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

        # Build a lookup of active customers from the customers table
        # These are users who have renewed (status=1 means Active, 0 means Inactive)
        active_customers = {}
        try:
            cursor.execute("""
                SELECT user_id, status, expiry_date
                FROM customers
                WHERE status = 1 AND expiry_date IS NOT NULL
            """)
            for row in cursor.fetchall():
                active_customers[row["user_id"]] = row
        except Exception as e:
            # customers table might not exist yet - that's fine, skip the check
            logger.debug("Could not query customers table: %s", e)

        for record in source_records:
            expiry_date = record["plan_expiry_date"]
            if isinstance(expiry_date, datetime):
                expiry_date = expiry_date.date()
            elif isinstance(expiry_date, str):
                expiry_date = datetime.strptime(expiry_date[:10], "%Y-%m-%d").date()

            # Check if this user is Active in the customers table with a newer expiry
            user_id = record["user_id"]
            if user_id in active_customers:
                cust = active_customers[user_id]
                cust_expiry = cust["expiry_date"]
                if isinstance(cust_expiry, datetime):
                    cust_expiry = cust_expiry.date()
                elif isinstance(cust_expiry, str):
                    cust_expiry = datetime.strptime(str(cust_expiry)[:10], "%Y-%m-%d").date()

                # If customer is Active and their current expiry is in the future,
                # use the customers table expiry (they renewed)
                if cust_expiry and cust_expiry >= today:
                    if expiry_date < today:
                        # This user shows as expired in renewals but is actually Active
                        # Remove them from renewal_records if they exist
                        cursor.execute(
                            "DELETE FROM renewal_records WHERE account_id = %s",
                            (user_id,)
                        )
                        if cursor.rowcount > 0:
                            stats["skipped_active"] += 1
                            logger.debug("Skipped active customer %s (renewed, expiry=%s)",
                                         user_id, cust_expiry)
                        continue
                    else:
                        # Use the more recent expiry from customers table
                        expiry_date = cust_expiry

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

    logger.info("Sync complete: %d inserted, %d updated, %d removed, %d skipped (active) of %d total",
                stats["inserted"], stats["updated"], stats["removed"],
                stats["skipped_active"], stats["total"])
    return stats
