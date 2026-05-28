"""API routes for the Renewal Campaign System.

All endpoints are prefixed with /api/renewals/
"""

import csv
import io
import json
import logging
from datetime import date, datetime

from flask import Blueprint, current_app, jsonify, request, Response

api_bp = Blueprint("api", __name__)
logger = logging.getLogger(__name__)


@api_bp.route("/", methods=["GET"])
def get_renewals():
    """Get renewal records with filtering, pagination, and search.

    Query params:
        category: expired|today|upcoming (optional)
        search: search term for name/mobile/account (optional)
        page: page number (default 1)
        per_page: records per page (default 50)
        sort_by: column to sort by (default expiry_date)
        sort_dir: asc|desc (default asc)
        zone: filter by zone name (optional)
        plan: filter by plan name (optional)
        date_from: filter expiry date from (optional, YYYY-MM-DD)
        date_to: filter expiry date to (optional, YYYY-MM-DD)
    """
    from renewal_system.models.database import get_db_cursor

    config = current_app.renewal_config

    # Parse params
    category = request.args.get("category")
    search = request.args.get("search", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    per_page = min(200, max(1, int(request.args.get("per_page", 50))))
    sort_by = request.args.get("sort_by", "expiry_date")
    sort_dir = request.args.get("sort_dir", "asc")
    zone = request.args.get("zone")
    plan = request.args.get("plan")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    # Validate sort column
    allowed_sorts = ["expiry_date", "customer_name", "days_remaining", "plan_name", "category"]
    if sort_by not in allowed_sorts:
        sort_by = "expiry_date"
    if sort_dir not in ("asc", "desc"):
        sort_dir = "asc"

    # Build query
    conditions = []
    params = []

    if category:
        conditions.append("r.category = %s")
        params.append(category)

    if search:
        conditions.append(
            "(r.customer_name LIKE %s OR r.mobile LIKE %s OR r.account_id LIKE %s)"
        )
        search_term = f"%{search}%"
        params.extend([search_term, search_term, search_term])

    if zone:
        conditions.append("r.zone_name = %s")
        params.append(zone)

    if plan:
        conditions.append("r.plan_name LIKE %s")
        params.append(f"%{plan}%")

    if date_from:
        conditions.append("r.expiry_date >= %s")
        params.append(date_from)

    if date_to:
        conditions.append("r.expiry_date <= %s")
        params.append(date_to)

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    with get_db_cursor(config) as cursor:
        # Get total count
        cursor.execute(f"SELECT COUNT(*) as total FROM renewal_records r WHERE {where_clause}", params)
        total = cursor.fetchone()["total"]

        # Get paginated records with last message info
        offset = (page - 1) * per_page
        cursor.execute(f"""
            SELECT r.*,
                   (SELECT MAX(sent_at) FROM whatsapp_campaign_logs wcl
                    WHERE wcl.renewal_id = r.id AND wcl.status = 'sent') as last_sent_at,
                   (SELECT template_name FROM whatsapp_campaign_logs wcl
                    WHERE wcl.renewal_id = r.id AND wcl.status = 'sent'
                    ORDER BY sent_at DESC LIMIT 1) as last_template_sent
            FROM renewal_records r
            WHERE {where_clause}
            ORDER BY r.{sort_by} {sort_dir}
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])
        records = cursor.fetchall()

    # Serialize dates
    for r in records:
        if r.get("expiry_date") and isinstance(r["expiry_date"], (date, datetime)):
            r["expiry_date"] = r["expiry_date"].strftime("%Y-%m-%d")
        if r.get("created_at") and isinstance(r["created_at"], datetime):
            r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M:%S")
        if r.get("updated_at") and isinstance(r["updated_at"], datetime):
            r["updated_at"] = r["updated_at"].strftime("%Y-%m-%d %H:%M:%S")
        if r.get("last_sent_at") and isinstance(r["last_sent_at"], datetime):
            r["last_sent_at"] = r["last_sent_at"].strftime("%Y-%m-%d %H:%M:%S")

    return jsonify({
        "success": True,
        "data": records,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": (total + per_page - 1) // per_page,
        },
    })


@api_bp.route("/stats", methods=["GET"])
def get_stats():
    """Get renewal statistics by category."""
    from renewal_system.models.database import get_db_cursor

    config = current_app.renewal_config

    with get_db_cursor(config) as cursor:
        cursor.execute("""
            SELECT
                category,
                COUNT(*) as count
            FROM renewal_records
            GROUP BY category
        """)
        category_counts = {row["category"]: row["count"] for row in cursor.fetchall()}

        # Get total sent today
        cursor.execute("""
            SELECT COUNT(*) as sent_today
            FROM whatsapp_campaign_logs
            WHERE DATE(sent_at) = CURDATE() AND status = 'sent'
        """)
        sent_today = cursor.fetchone()["sent_today"]

        # Get total failed today
        cursor.execute("""
            SELECT COUNT(*) as failed_today
            FROM whatsapp_campaign_logs
            WHERE DATE(sent_at) = CURDATE() AND status = 'failed'
        """)
        failed_today = cursor.fetchone()["failed_today"]

        # Get total records
        cursor.execute("SELECT COUNT(*) as total FROM renewal_records")
        total = cursor.fetchone()["total"]

    return jsonify({
        "success": True,
        "stats": {
            "total": total,
            "expired": category_counts.get("expired", 0),
            "today": category_counts.get("today", 0),
            "upcoming": category_counts.get("upcoming", 0),
            "sent_today": sent_today,
            "failed_today": failed_today,
        },
    })


@api_bp.route("/category/<category>", methods=["GET"])
def get_by_category(category):
    """Get renewals filtered by category."""
    valid_categories = ["expired", "today", "upcoming"]
    if category not in valid_categories:
        return jsonify({"success": False, "error": f"Invalid category. Use: {valid_categories}"}), 400

    # Delegate to main endpoint with category filter
    request.args = request.args.copy()
    # Just redirect internally
    from renewal_system.models.database import get_db_cursor
    config = current_app.renewal_config

    page = max(1, int(request.args.get("page", 1)))
    per_page = min(200, max(1, int(request.args.get("per_page", 50))))
    offset = (page - 1) * per_page

    with get_db_cursor(config) as cursor:
        cursor.execute("SELECT COUNT(*) as total FROM renewal_records WHERE category = %s", (category,))
        total = cursor.fetchone()["total"]

        cursor.execute("""
            SELECT r.*,
                   (SELECT MAX(sent_at) FROM whatsapp_campaign_logs wcl
                    WHERE wcl.renewal_id = r.id AND wcl.status = 'sent') as last_sent_at
            FROM renewal_records r
            WHERE r.category = %s
            ORDER BY r.expiry_date ASC
            LIMIT %s OFFSET %s
        """, (category, per_page, offset))
        records = cursor.fetchall()

    for r in records:
        if r.get("expiry_date") and isinstance(r["expiry_date"], (date, datetime)):
            r["expiry_date"] = r["expiry_date"].strftime("%Y-%m-%d")
        if r.get("last_sent_at") and isinstance(r["last_sent_at"], datetime):
            r["last_sent_at"] = r["last_sent_at"].strftime("%Y-%m-%d %H:%M:%S")

    return jsonify({
        "success": True,
        "category": category,
        "data": records,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": (total + per_page - 1) // per_page,
        },
    })


@api_bp.route("/send", methods=["POST"])
def send_message():
    """Send a WhatsApp template message to a single customer.

    JSON body:
        renewal_id: int (required)
        template_name: str (required)
        params: list of str (required)
        operator_name: str (required)
        override_duplicate: bool (optional, default false)
    """
    from renewal_system.services.whatsapp import WhatsAppService, WhatsAppError
    from renewal_system.services.operator_log import log_action

    config = current_app.renewal_config
    data = request.get_json()

    if not data:
        return jsonify({"success": False, "error": "Request body required"}), 400

    renewal_id = data.get("renewal_id")
    template_name = data.get("template_name")
    params = data.get("params", [])
    operator_name = data.get("operator_name", "unknown")
    override_duplicate = data.get("override_duplicate", False)

    if not renewal_id or not template_name:
        return jsonify({"success": False, "error": "renewal_id and template_name required"}), 400

    # Get renewal record
    from renewal_system.models.database import get_db_cursor

    with get_db_cursor(config) as cursor:
        cursor.execute("SELECT * FROM renewal_records WHERE id = %s", (renewal_id,))
        record = cursor.fetchone()

    if not record:
        return jsonify({"success": False, "error": "Renewal record not found"}), 404

    mobile = record["mobile"]
    if not mobile:
        return jsonify({"success": False, "error": "No mobile number for this customer"}), 400

    # Send via WhatsApp
    wa_service = WhatsAppService(config)

    try:
        if override_duplicate:
            # Skip duplicate check by directly sending
            result = wa_service.send_template(mobile, template_name, params, renewal_id, operator_name)
        else:
            result = wa_service.send_template(mobile, template_name, params, renewal_id, operator_name)
    except WhatsAppError as e:
        return jsonify({"success": False, "error": str(e)}), 409

    # Log operator action
    log_action(config, operator_name, "send_message", renewal_id, {
        "template": template_name,
        "mobile": mobile,
    })

    return jsonify({"success": True, "result": result})


@api_bp.route("/bulk-send", methods=["POST"])
def bulk_send():
    """Send WhatsApp messages to multiple customers.

    JSON body:
        renewal_ids: list of int (required)
        operator_name: str (required)
        override_duplicate: bool (optional)
    """
    from renewal_system.services.whatsapp import WhatsAppService, WhatsAppError
    from renewal_system.services.classifier import CATEGORIES
    from renewal_system.services.operator_log import log_action
    from renewal_system.models.database import get_db_cursor

    config = current_app.renewal_config
    data = request.get_json()

    if not data:
        return jsonify({"success": False, "error": "Request body required"}), 400

    renewal_ids = data.get("renewal_ids", [])
    operator_name = data.get("operator_name", "unknown")
    override_duplicate = data.get("override_duplicate", False)

    if not renewal_ids:
        return jsonify({"success": False, "error": "renewal_ids required"}), 400

    if len(renewal_ids) > 500:
        return jsonify({"success": False, "error": "Maximum 500 records per bulk send"}), 400

    wa_service = WhatsAppService(config)
    results = {"sent": 0, "failed": 0, "skipped": 0, "errors": []}

    with get_db_cursor(config) as cursor:
        placeholders = ",".join(["%s"] * len(renewal_ids))
        cursor.execute(
            f"SELECT * FROM renewal_records WHERE id IN ({placeholders})",
            renewal_ids
        )
        records = cursor.fetchall()

    for record in records:
        if not record.get("mobile"):
            results["skipped"] += 1
            continue

        # Determine template from category
        category = record.get("category", "upcoming")
        cat_info = CATEGORIES.get(category, CATEGORIES["upcoming"])
        template_name = cat_info["template"]

        # Build params based on template requirements
        # pack_expiry_alert: {{1}}=name, {{2}}=account_id, {{3}}=expiry_date
        # recharge_today1: {{1}}=name, {{2}}=plan_name
        # recharge_reminder: {{1}}=name, {{2}}=plan_name
        if template_name == "pack_expiry_alert":
            params = [
                record.get("customer_name", "Customer"),
                record.get("account_id", ""),
                str(record.get("expiry_date", "")),
            ]
        else:
            params = [
                record.get("customer_name", "Customer"),
                record.get("plan_name", ""),
            ]

        try:
            wa_service.send_template(
                record["mobile"], template_name, params,
                record["id"], operator_name
            )
            results["sent"] += 1
        except WhatsAppError as e:
            results["failed"] += 1
            results["errors"].append({
                "renewal_id": record["id"],
                "mobile": record["mobile"],
                "error": str(e),
            })

    # Log bulk action
    log_action(config, operator_name, "bulk_send", None, {
        "count": len(renewal_ids),
        "sent": results["sent"],
        "failed": results["failed"],
    })

    return jsonify({"success": True, "results": results})


@api_bp.route("/logs", methods=["GET"])
def get_logs():
    """Get WhatsApp campaign send logs.

    Query params:
        page: page number (default 1)
        per_page: records per page (default 50)
        status: filter by status (optional)
        renewal_id: filter by renewal record (optional)
    """
    from renewal_system.models.database import get_db_cursor

    config = current_app.renewal_config

    page = max(1, int(request.args.get("page", 1)))
    per_page = min(200, max(1, int(request.args.get("per_page", 50))))
    status = request.args.get("status")
    renewal_id = request.args.get("renewal_id")

    conditions = []
    params = []

    if status:
        conditions.append("status = %s")
        params.append(status)

    if renewal_id:
        conditions.append("renewal_id = %s")
        params.append(renewal_id)

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    offset = (page - 1) * per_page

    with get_db_cursor(config) as cursor:
        cursor.execute(f"SELECT COUNT(*) as total FROM whatsapp_campaign_logs WHERE {where_clause}", params)
        total = cursor.fetchone()["total"]

        cursor.execute(f"""
            SELECT * FROM whatsapp_campaign_logs
            WHERE {where_clause}
            ORDER BY sent_at DESC
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])
        logs = cursor.fetchall()

    for log in logs:
        if log.get("sent_at") and isinstance(log["sent_at"], datetime):
            log["sent_at"] = log["sent_at"].strftime("%Y-%m-%d %H:%M:%S")
        if log.get("template_params") and isinstance(log["template_params"], str):
            try:
                log["template_params"] = json.loads(log["template_params"])
            except (json.JSONDecodeError, TypeError):
                pass

    return jsonify({
        "success": True,
        "data": logs,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": (total + per_page - 1) // per_page,
        },
    })


@api_bp.route("/sync", methods=["POST"])
def sync_data():
    """Trigger a sync from the renewals table to renewal_records.

    This re-classifies all records based on today's date.
    """
    from renewal_system.services.renewal_sync import sync_from_renewals_table
    from renewal_system.services.classifier import classify_and_update_records

    config = current_app.renewal_config

    try:
        sync_stats = sync_from_renewals_table(config)
        classify_stats = classify_and_update_records(config)
        return jsonify({
            "success": True,
            "sync": sync_stats,
            "classification": classify_stats,
        })
    except Exception as e:
        logger.error("Sync failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@api_bp.route("/export", methods=["GET"])
def export_csv():
    """Export renewal records as CSV.

    Query params: same as GET /api/renewals/ for filtering.
    """
    from renewal_system.models.database import get_db_cursor

    config = current_app.renewal_config

    category = request.args.get("category")
    search = request.args.get("search", "").strip()

    conditions = []
    params = []

    if category:
        conditions.append("category = %s")
        params.append(category)

    if search:
        conditions.append("(customer_name LIKE %s OR mobile LIKE %s OR account_id LIKE %s)")
        search_term = f"%{search}%"
        params.extend([search_term, search_term, search_term])

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    with get_db_cursor(config) as cursor:
        cursor.execute(f"""
            SELECT customer_name, mobile, account_id, plan_name,
                   expiry_date, days_remaining, category, zone_name, amount
            FROM renewal_records
            WHERE {where_clause}
            ORDER BY expiry_date ASC
        """, params)
        records = cursor.fetchall()

    # Build CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Customer Name", "Mobile", "Account ID", "Plan Name",
                     "Expiry Date", "Days Remaining", "Category", "Zone", "Amount"])

    for r in records:
        expiry = r.get("expiry_date", "")
        if isinstance(expiry, (date, datetime)):
            expiry = expiry.strftime("%Y-%m-%d")
        writer.writerow([
            r.get("customer_name", ""),
            r.get("mobile", ""),
            r.get("account_id", ""),
            r.get("plan_name", ""),
            expiry,
            r.get("days_remaining", ""),
            r.get("category", ""),
            r.get("zone_name", ""),
            r.get("amount", ""),
        ])

    csv_content = output.getvalue()
    return Response(
        csv_content,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=renewals_export_{date.today()}.csv"}
    )


@api_bp.route("/filters", methods=["GET"])
def get_filter_options():
    """Get available filter options (zones, plans)."""
    from renewal_system.models.database import get_db_cursor

    config = current_app.renewal_config

    with get_db_cursor(config) as cursor:
        cursor.execute("SELECT DISTINCT zone_name FROM renewal_records WHERE zone_name IS NOT NULL ORDER BY zone_name")
        zones = [row["zone_name"] for row in cursor.fetchall()]

        cursor.execute("SELECT DISTINCT plan_name FROM renewal_records WHERE plan_name IS NOT NULL ORDER BY plan_name")
        plans = [row["plan_name"] for row in cursor.fetchall()]

    return jsonify({
        "success": True,
        "zones": zones,
        "plans": plans,
    })
