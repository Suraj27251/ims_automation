"""Customer classification service.

Automatically classifies renewal records into categories:
- expired: expiry_date < today
- today: expiry_date == today
- upcoming: expiry_date > today

Future expansion support for: tomorrow, 3_days, 7_days
"""

import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)


# Category definitions with template mapping
CATEGORIES = {
    "expired": {
        "label": "Expired",
        "badge": "🔴 EXPIRED",
        "template": "pack_expiry_alert",
        "color": "danger",
    },
    "today": {
        "label": "Expiring Today",
        "badge": "🟠 TODAY",
        "template": "recharge_today1",
        "color": "warning",
    },
    "upcoming": {
        "label": "Upcoming",
        "badge": "🟢 UPCOMING",
        "template": "recharge_reminder",
        "color": "success",
    },
}


def classify_customer(expiry_date: date, reference_date: date = None) -> dict:
    """Classify a customer based on their expiry date.

    Args:
        expiry_date: The plan expiry date.
        reference_date: Date to compare against (defaults to today).

    Returns:
        Dict with category, days_remaining, template, badge, color.
    """
    if reference_date is None:
        reference_date = date.today()

    days_remaining = (expiry_date - reference_date).days

    if days_remaining < 0:
        category = "expired"
    elif days_remaining == 0:
        category = "today"
    else:
        category = "upcoming"

    cat_info = CATEGORIES[category]

    return {
        "category": category,
        "days_remaining": days_remaining,
        "template": cat_info["template"],
        "badge": cat_info["badge"],
        "color": cat_info["color"],
        "label": cat_info["label"],
    }


def classify_and_update_records(config, reference_date: date = None):
    """Re-classify all renewal records in the database.

    Updates the category and days_remaining fields for all records.

    Args:
        config: Application config with DB credentials.
        reference_date: Date to compare against (defaults to today).

    Returns:
        Dict with counts per category.
    """
    from renewal_system.models.database import get_db_cursor

    if reference_date is None:
        reference_date = date.today()

    counts = {"expired": 0, "today": 0, "upcoming": 0}

    with get_db_cursor(config) as cursor:
        # Fetch all records with expiry dates
        cursor.execute("SELECT id, expiry_date FROM renewal_records WHERE expiry_date IS NOT NULL")
        records = cursor.fetchall()

        for record in records:
            expiry = record["expiry_date"]
            if isinstance(expiry, str):
                from datetime import datetime
                expiry = datetime.strptime(expiry, "%Y-%m-%d").date()

            classification = classify_customer(expiry, reference_date)

            cursor.execute(
                "UPDATE renewal_records SET category = %s, days_remaining = %s WHERE id = %s",
                (classification["category"], classification["days_remaining"], record["id"])
            )
            counts[classification["category"]] += 1

    logger.info("Classification complete: %s", counts)
    return counts
