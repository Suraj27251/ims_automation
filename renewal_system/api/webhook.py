"""WhatsApp delivery status webhook handling.

Receives Meta WhatsApp Cloud API callbacks and updates the dashboard's
message lifecycle status using the WhatsApp message ID (WAMID).
"""

import json
import logging
from typing import Any, Dict, Optional, Tuple

from flask import Blueprint, current_app, jsonify, request

webhook_bp = Blueprint("webhook", __name__)
logger = logging.getLogger(__name__)

SUPPORTED_STATUSES = {"sent", "delivered", "read", "failed"}
STATUS_RANK = {
    None: 0,
    "": 0,
    "pending": 0,
    "failed": 1,
    "sent": 2,
    "delivered": 3,
    "read": 4,
}


def _json_dumps(payload: Dict[str, Any]) -> str:
    """Serialize webhook payload for storage without raising on odd values."""
    return json.dumps(payload, default=str, ensure_ascii=False)


def _extract_error_message(status_event: Dict[str, Any]) -> Optional[str]:
    """Return a concise Meta error description for failed status events."""
    errors = status_event.get("errors") or []
    if not errors:
        return None

    parts = []
    for error in errors:
        code = error.get("code")
        title = error.get("title") or error.get("message")
        details = error.get("error_data", {}).get("details") or error.get("details")
        part = " | ".join(str(x) for x in (code, title, details) if x)
        if part:
            parts.append(part)

    return "; ".join(parts) if parts else _json_dumps({"errors": errors})


def _should_apply_status(current_status: Optional[str], incoming_status: str) -> bool:
    """Keep lifecycle updates idempotent and prevent status downgrades."""
    current = (current_status or "pending").lower()

    if incoming_status == current:
        return True

    # A failed callback can replace an earlier send state, but should not clobber
    # statuses that prove the customer already received/read the message.
    if incoming_status == "failed":
        return current not in {"delivered", "read"}

    # Treat failed as terminal for this WAMID unless the duplicate event is also failed.
    if current == "failed":
        return False

    return STATUS_RANK.get(incoming_status, 0) >= STATUS_RANK.get(current, 0)


def _update_campaign_log(config, wamid: str, status_event: Dict[str, Any], raw_payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Update whatsapp_campaign_logs by WAMID.

    The send workflow depends on ``status = 'sent'`` for duplicate protection and
    dashboard counts, so lifecycle events are stored in ``delivery_status`` while
    preserving the existing send status except for failures.
    """
    from renewal_system.models.database import get_db_connection

    incoming_status = (status_event.get("status") or "").lower()
    payload_json = _json_dumps(raw_payload)
    error_message = _extract_error_message(status_event)

    with get_db_connection(config) as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT id, status, delivery_status
                FROM whatsapp_campaign_logs
                WHERE whatsapp_message_id = %s
                ORDER BY id DESC
                LIMIT 1
                FOR UPDATE
            """, (wamid,))
            row = cursor.fetchone()
            if not row:
                conn.rollback()
                return False, "not_found"

            current_delivery_status = row.get("delivery_status") or row.get("status")
            if not _should_apply_status(current_delivery_status, incoming_status):
                cursor.execute("""
                    UPDATE whatsapp_campaign_logs
                    SET webhook_payload = %s
                    WHERE id = %s
                """, (payload_json, row["id"]))
                conn.commit()
                return True, "ignored_downgrade"

            fields = ["delivery_status = %s", "webhook_payload = %s"]
            params = [incoming_status, payload_json]

            if incoming_status == "delivered":
                fields.append("delivered_at = COALESCE(delivered_at, NOW())")
            elif incoming_status == "read":
                fields.append("read_at = COALESCE(read_at, NOW())")
                fields.append("delivered_at = COALESCE(delivered_at, NOW())")
            elif incoming_status == "failed":
                fields.append("status = 'failed'")
                fields.append("failed_at = COALESCE(failed_at, NOW())")
                fields.append("error_message = COALESCE(%s, error_message)")
                params.append(error_message)
            elif incoming_status == "sent":
                fields.append("status = CASE WHEN status = 'pending' THEN 'sent' ELSE status END")

            params.append(row["id"])
            cursor.execute(f"""
                UPDATE whatsapp_campaign_logs
                SET {', '.join(fields)}
                WHERE id = %s
            """, params)
            conn.commit()
            return True, "updated"
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()


def _update_legacy_whatsapp_log(config, wamid: str, status_event: Dict[str, Any], raw_payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Best-effort update for production deployments with whatsapp_logs.

    Some deployments use whatsapp_logs.message_id instead of the renewal dashboard
    table. This path is intentionally optional: if the table does not exist, the
    dashboard table update above remains authoritative for this app.
    """
    from renewal_system.models.database import get_db_connection

    incoming_status = (status_event.get("status") or "").lower()
    payload_json = _json_dumps(raw_payload)
    error_message = _extract_error_message(status_event)

    with get_db_connection(config) as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT id, status
                FROM whatsapp_logs
                WHERE message_id = %s
                ORDER BY id DESC
                LIMIT 1
                FOR UPDATE
            """, (wamid,))
            row = cursor.fetchone()
            if not row:
                conn.rollback()
                return False, "not_found"

            if not _should_apply_status(row.get("status"), incoming_status):
                cursor.execute("""
                    UPDATE whatsapp_logs
                    SET webhook_payload = %s
                    WHERE id = %s
                """, (payload_json, row["id"]))
                conn.commit()
                return True, "ignored_downgrade"

            fields = ["status = %s", "webhook_payload = %s"]
            params = [incoming_status, payload_json]

            if incoming_status == "delivered":
                fields.append("delivered_at = COALESCE(delivered_at, NOW())")
            elif incoming_status == "read":
                fields.append("read_at = COALESCE(read_at, NOW())")
                fields.append("delivered_at = COALESCE(delivered_at, NOW())")
            elif incoming_status == "failed":
                fields.append("failed_at = COALESCE(failed_at, NOW())")
                fields.append("error_message = COALESCE(%s, error_message)")
                params.append(error_message)
            elif incoming_status == "sent":
                fields.append("sent_at = COALESCE(sent_at, NOW())")

            params.append(row["id"])
            cursor.execute(f"""
                UPDATE whatsapp_logs
                SET {', '.join(fields)}
                WHERE id = %s
            """, params)
            conn.commit()
            return True, "updated"
        except Exception as exc:
            # Missing legacy table/columns should not break the dashboard webhook.
            conn.rollback()
            if getattr(exc, "errno", None) in {1054, 1146}:
                logger.debug("Legacy whatsapp_logs update skipped: %s", exc)
                return False, "unavailable"
            raise
        finally:
            cursor.close()


def _handle_status_event(status_event: Dict[str, Any], raw_payload: Dict[str, Any]) -> Dict[str, Any]:
    config = current_app.renewal_config
    wamid = status_event.get("id")
    incoming_status = (status_event.get("status") or "").lower()

    if not wamid or incoming_status not in SUPPORTED_STATUSES:
        return {"wamid": wamid, "status": incoming_status, "result": "skipped"}

    campaign_updated, campaign_result = _update_campaign_log(config, wamid, status_event, raw_payload)
    legacy_updated, legacy_result = _update_legacy_whatsapp_log(config, wamid, status_event, raw_payload)

    if campaign_updated or legacy_updated:
        logger.info(
            "WhatsApp webhook status processed: wamid=%s status=%s campaign=%s legacy=%s",
            wamid,
            incoming_status,
            campaign_result,
            legacy_result,
        )
    else:
        logger.warning("WhatsApp webhook WAMID not found: wamid=%s status=%s", wamid, incoming_status)

    return {
        "wamid": wamid,
        "status": incoming_status,
        "campaign_result": campaign_result,
        "legacy_result": legacy_result,
    }


@webhook_bp.route("/webhook", methods=["GET"])
def verify_webhook():
    """Verify Meta webhook subscription without exposing tokens in logs."""
    config = current_app.renewal_config
    mode = request.args.get("hub.mode")
    verify_token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    expected_token = getattr(config, "WHATSAPP_VERIFY_TOKEN", "")
    if mode == "subscribe" and challenge and expected_token and verify_token == expected_token:
        logger.info("WhatsApp webhook verification succeeded")
        return challenge, 200, {"Content-Type": "text/plain"}

    logger.warning("WhatsApp webhook verification failed: mode=%s token_configured=%s", mode, bool(expected_token))
    return jsonify({"success": False, "error": "Webhook verification failed"}), 403


@webhook_bp.route("/webhook", methods=["POST"])
def receive_webhook():
    """Receive Meta WhatsApp status callbacks and update message logs."""
    payload = request.get_json(silent=True) or {}
    logger.debug("Incoming WhatsApp webhook payload: %s", _json_dumps(payload)[:4000])

    processed = []
    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value") or {}
                for status_event in value.get("statuses", []):
                    processed.append(_handle_status_event(status_event, payload))
    except Exception:
        logger.exception("WhatsApp webhook processing failed")
        return jsonify({"success": False, "error": "Webhook processing failed"}), 500

    return jsonify({"success": True, "processed": processed}), 200


@webhook_bp.route("/webhook/status", methods=["GET"])
def webhook_status():
    """Health check endpoint to verify webhook integration is configured."""
    return jsonify({
        "success": True,
        "webhook_handler": "Meta WhatsApp Cloud API",
        "description": "POST Meta status callbacks to /api/renewals/webhook. "
                       "Use /api/renewals/delivery-status?ids=... to query statuses.",
        "supported_statuses": sorted(SUPPORTED_STATUSES),
    })
