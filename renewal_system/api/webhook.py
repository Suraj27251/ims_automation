"""WhatsApp webhook for delivery status updates.

Receives status callbacks from Meta WhatsApp Cloud API
and updates the delivery_status in whatsapp_campaign_logs.

Status flow: sent → delivered → read (or failed)
"""

import logging
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

webhook_bp = Blueprint("webhook", __name__)
logger = logging.getLogger(__name__)


@webhook_bp.route("/webhook", methods=["GET"])
def verify_webhook():
    """Webhook verification (Meta sends GET to verify)."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    verify_token = current_app.renewal_config.SECRET_KEY

    if mode == "subscribe" and token == verify_token:
        return challenge, 200
    return "Forbidden", 403


@webhook_bp.route("/webhook", methods=["POST"])
def receive_webhook():
    """Receive delivery status updates from Meta.

    Meta sends statuses: sent, delivered, read, failed
    We update the whatsapp_campaign_logs table accordingly.
    """
    from renewal_system.models.database import get_db_cursor

    config = current_app.renewal_config
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"status": "ok"}), 200

    try:
        entries = data.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                statuses = value.get("statuses", [])

                for status_update in statuses:
                    message_id = status_update.get("id")
                    status = status_update.get("status")  # sent, delivered, read, failed
                    timestamp = status_update.get("timestamp")

                    if not message_id or not status:
                        continue

                    _update_delivery_status(config, message_id, status, timestamp)

    except Exception as e:
        logger.error("Webhook processing error: %s", e)

    # Always return 200 to Meta
    return jsonify({"status": "ok"}), 200


def _update_delivery_status(config, message_id: str, status: str, timestamp: str = None):
    """Update delivery status for a campaign log entry.

    Args:
        config: App config.
        message_id: WhatsApp message ID (wamid.xxx).
        status: New status (sent, delivered, read, failed).
        timestamp: Unix timestamp from Meta.
    """
    from renewal_system.models.database import get_db_cursor

    # Convert timestamp
    ts = None
    if timestamp:
        try:
            ts = datetime.fromtimestamp(int(timestamp))
        except (ValueError, TypeError):
            ts = datetime.now()

    with get_db_cursor(config) as cursor:
        # Only update if the new status is "higher" in the chain
        # sent < delivered < read (don't downgrade)
        status_priority = {"sent": 1, "delivered": 2, "read": 3, "failed": 0}
        new_priority = status_priority.get(status, 0)

        # Get current status
        cursor.execute("""
            SELECT id, delivery_status FROM whatsapp_campaign_logs
            WHERE whatsapp_message_id = %s
            LIMIT 1
        """, (message_id,))
        row = cursor.fetchone()

        if not row:
            return  # Not our message

        current_priority = status_priority.get(row.get("delivery_status"), -1)

        if new_priority <= current_priority:
            return  # Don't downgrade status

        # Update
        update_fields = ["delivery_status = %s"]
        update_params = [status]

        if status == "delivered" and ts:
            update_fields.append("delivered_at = %s")
            update_params.append(ts)
        elif status == "read" and ts:
            update_fields.append("read_at = %s")
            update_params.append(ts)
        elif status == "failed":
            update_fields.append("status = 'failed'")

        update_params.append(row["id"])

        cursor.execute(f"""
            UPDATE whatsapp_campaign_logs
            SET {', '.join(update_fields)}
            WHERE id = %s
        """, update_params)

    logger.info("Delivery status updated: msg=%s status=%s", message_id[:20], status)
