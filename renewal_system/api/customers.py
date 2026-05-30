"""Customer API routes for filtering and WhatsApp automation.

Provides endpoints for:
- Listing customers with filters (zone, plan, status, category, etc.)
- Customer stats/counts
- Filtered exports for WhatsApp campaigns
"""

import logging
from datetime import date, timedelta

from flask import Blueprint, jsonify, request

from renewal_system.config import config
from renewal_system.models.database import get_db_cursor

logger = logging.getLogger(__name__)

customers_bp = Blueprint("customers", __name__, url_prefix="/api/customers")


@customers_bp.route("/", methods=["GET"])
def list_customers():
    """List customers with optional filters.

    Query params:
        category: expired|today|upcoming
        status: active|inactive|expired|...
        zone: zone name
        plan: plan name (partial match)
        network_type: fiber|wireless|...
        kyc: approved|pending
        days_min: minimum days_remaining
        days_max: maximum days_remaining
        search: search customer_name or mobile
        page: page number (default 1)
        per_page: records per page (default 50)
        sort: field to sort by (default expiry_date)
        order: asc|desc (default asc)
    """
    # Parse filters
    category = request.args.get("category")
    status = request.args.get("status")
    zone = request.args.get("zone")
    plan = request.args.get("plan")
    network_type = request.args.get("network_type")
    kyc = request.args.get("kyc")
    days_min = request.args.get("days_min", type=int)
    days_max = request.args.get("days_max", type=int)
    search = request.args.get("search")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    sort = request.args.get("sort", "expiry_date")
    order = request.args.get("order", "asc")

    # Validate sort field
    allowed_sorts = [
        "customer_name", "mobile", "plan_name", "expiry_date",
        "days_remaining", "zone_name", "status", "category", "updated_at"
    ]
    if sort not in allowed_sorts:
        sort = "expiry_date"
    if order not in ("asc", "desc"):
        order = "asc"

    # Build query
    conditions = []
    params = []

    if category:
        conditions.append("category = %s")
        params.append(category)
    if status:
        conditions.append("status = %s")
        params.append(status)
    if zone:
        conditions.append("zone_name = %s")
        params.append(zone)
    if plan:
        conditions.append("plan_name LIKE %s")
        params.append(f"%{plan}%")
    if network_type:
        conditions.append("network_type = %s")
        params.append(network_type)
    if kyc:
        conditions.append("kyc_approved = %s")
        params.append(kyc)
    if days_min is not None:
        conditions.append("days_remaining >= %s")
        params.append(days_min)
    if days_max is not None:
        conditions.append("days_remaining <= %s")
        params.append(days_max)
    if search:
        conditions.append("(customer_name LIKE %s OR mobile LIKE %s)")
        params.append(f"%{search}%")
        params.append(f"%{search}%")

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    # Count total
    count_sql = f"SELECT COUNT(*) as total FROM customers WHERE {where_clause}"

    # Fetch page
    offset = (page - 1) * per_page
    data_sql = (
        f"SELECT * FROM customers WHERE {where_clause} "
        f"ORDER BY {sort} {order} LIMIT %s OFFSET %s"
    )

    with get_db_cursor(config) as cursor:
        cursor.execute(count_sql, params)
        total = cursor.fetchone()["total"]

        cursor.execute(data_sql, params + [per_page, offset])
        rows = cursor.fetchall()

    # Serialize dates
    for row in rows:
        for key in ("expiry_date", "activation_date", "data_reset_date", "reg_date"):
            if row.get(key) and hasattr(row[key], "isoformat"):
                row[key] = row[key].isoformat()
        for key in ("created_at", "updated_at", "last_synced_at"):
            if row.get(key) and hasattr(row[key], "isoformat"):
                row[key] = row[key].isoformat()

    return jsonify({
        "data": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if per_page > 0 else 0,
    })


@customers_bp.route("/stats", methods=["GET"])
def customer_stats():
    """Get customer statistics and counts by category."""
    with get_db_cursor(config) as cursor:
        # Category counts
        cursor.execute("""
            SELECT category, COUNT(*) as count
            FROM customers
            GROUP BY category
        """)
        category_counts = {row["category"]: row["count"] for row in cursor.fetchall()}

        # Total
        cursor.execute("SELECT COUNT(*) as total FROM customers")
        total = cursor.fetchone()["total"]

        # Status counts
        cursor.execute("""
            SELECT status, COUNT(*) as count
            FROM customers
            GROUP BY status
        """)
        status_counts = {row["status"]: row["count"] for row in cursor.fetchall()}

        # Zone counts
        cursor.execute("""
            SELECT zone_name, COUNT(*) as count
            FROM customers
            WHERE zone_name IS NOT NULL
            GROUP BY zone_name
            ORDER BY count DESC
        """)
        zone_counts = {row["zone_name"]: row["count"] for row in cursor.fetchall()}

        # Expiring soon (next 7 days)
        cursor.execute("""
            SELECT COUNT(*) as count FROM customers
            WHERE days_remaining BETWEEN 0 AND 7
        """)
        expiring_soon = cursor.fetchone()["count"]

        # KYC pending
        cursor.execute("""
            SELECT COUNT(*) as count FROM customers
            WHERE kyc_approved IS NULL OR kyc_approved != 'Approved'
        """)
        kyc_pending = cursor.fetchone()["count"]

    return jsonify({
        "total": total,
        "categories": category_counts,
        "statuses": status_counts,
        "zones": zone_counts,
        "expiring_soon_7d": expiring_soon,
        "kyc_pending": kyc_pending,
    })


@customers_bp.route("/filters", methods=["GET"])
def available_filters():
    """Get available filter values (zones, plans, statuses, etc.)."""
    with get_db_cursor(config) as cursor:
        cursor.execute("SELECT DISTINCT zone_name FROM customers WHERE zone_name IS NOT NULL ORDER BY zone_name")
        zones = [row["zone_name"] for row in cursor.fetchall()]

        cursor.execute("SELECT DISTINCT plan_name FROM customers WHERE plan_name IS NOT NULL ORDER BY plan_name")
        plans = [row["plan_name"] for row in cursor.fetchall()]

        cursor.execute("SELECT DISTINCT status FROM customers WHERE status IS NOT NULL ORDER BY status")
        statuses = [row["status"] for row in cursor.fetchall()]

        cursor.execute("SELECT DISTINCT network_type FROM customers WHERE network_type IS NOT NULL ORDER BY network_type")
        network_types = [row["network_type"] for row in cursor.fetchall()]

        cursor.execute("SELECT DISTINCT connectivity_mode FROM customers WHERE connectivity_mode IS NOT NULL ORDER BY connectivity_mode")
        connectivity_modes = [row["connectivity_mode"] for row in cursor.fetchall()]

    return jsonify({
        "zones": zones,
        "plans": plans,
        "statuses": statuses,
        "network_types": network_types,
        "connectivity_modes": connectivity_modes,
        "categories": ["expired", "today", "upcoming", "unknown"],
    })


@customers_bp.route("/expiring", methods=["GET"])
def expiring_customers():
    """Get customers expiring within a specific timeframe.

    Query params:
        days: number of days ahead (default 7)
        zone: filter by zone
        include_expired: include already expired (default false)
    """
    days = request.args.get("days", 7, type=int)
    zone = request.args.get("zone")
    include_expired = request.args.get("include_expired", "false").lower() == "true"

    conditions = []
    params = []

    if include_expired:
        conditions.append("days_remaining <= %s")
        params.append(days)
    else:
        conditions.append("days_remaining BETWEEN 0 AND %s")
        params.append(days)

    if zone:
        conditions.append("zone_name = %s")
        params.append(zone)

    where_clause = " AND ".join(conditions)

    with get_db_cursor(config) as cursor:
        cursor.execute(
            f"SELECT * FROM customers WHERE {where_clause} ORDER BY expiry_date ASC",
            params
        )
        rows = cursor.fetchall()

    for row in rows:
        for key in ("expiry_date", "activation_date", "data_reset_date", "reg_date"):
            if row.get(key) and hasattr(row[key], "isoformat"):
                row[key] = row[key].isoformat()
        for key in ("created_at", "updated_at", "last_synced_at"):
            if row.get(key) and hasattr(row[key], "isoformat"):
                row[key] = row[key].isoformat()

    return jsonify({
        "data": rows,
        "total": len(rows),
        "filter": {
            "days": days,
            "zone": zone,
            "include_expired": include_expired,
        }
    })


@customers_bp.route("/whatsapp-targets", methods=["GET"])
def whatsapp_targets():
    """Get customers eligible for WhatsApp campaigns.

    Query params:
        campaign: expired|today|tomorrow|7days|inactive|kyc_pending|monthly
        zone: filter by zone
        plan: filter by plan (partial match)
        limit: max records (default 500)
    """
    campaign = request.args.get("campaign", "today")
    zone = request.args.get("zone")
    plan = request.args.get("plan")
    limit = request.args.get("limit", 500, type=int)

    conditions = ["mobile IS NOT NULL", "mobile != ''"]
    params = []

    # Campaign type filters
    if campaign == "expired":
        conditions.append("category = 'expired'")
    elif campaign == "today":
        conditions.append("category = 'today'")
    elif campaign == "tomorrow":
        conditions.append("days_remaining = 1")
    elif campaign == "7days":
        conditions.append("days_remaining BETWEEN 1 AND 7")
    elif campaign == "inactive":
        conditions.append("status = 'Inactive'")
    elif campaign == "kyc_pending":
        conditions.append("(kyc_approved IS NULL OR kyc_approved != 'Approved')")
    elif campaign == "monthly":
        conditions.append("validity LIKE '%month%' OR validity LIKE '%30%'")
    else:
        conditions.append("category = %s")
        params.append(campaign)

    if zone:
        conditions.append("zone_name = %s")
        params.append(zone)
    if plan:
        conditions.append("plan_name LIKE %s")
        params.append(f"%{plan}%")

    where_clause = " AND ".join(conditions)

    with get_db_cursor(config) as cursor:
        cursor.execute(
            f"SELECT user_id, customer_name, mobile, plan_name, expiry_date, "
            f"days_remaining, category, zone_name, status "
            f"FROM customers WHERE {where_clause} "
            f"ORDER BY expiry_date ASC LIMIT %s",
            params + [limit]
        )
        rows = cursor.fetchall()

    for row in rows:
        if row.get("expiry_date") and hasattr(row["expiry_date"], "isoformat"):
            row["expiry_date"] = row["expiry_date"].isoformat()

    return jsonify({
        "data": rows,
        "total": len(rows),
        "campaign": campaign,
        "filters": {"zone": zone, "plan": plan},
    })
