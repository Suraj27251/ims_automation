"""WhatsApp Cloud API service.

Handles sending template messages via Meta WhatsApp Cloud API.
Includes duplicate protection, logging, and integration with the
WhatsApp Inbox system (Countrylink Management System) for delivery tracking.

When a template is sent:
1. Message is sent via Meta Cloud API
2. Logged in whatsapp_campaign_logs (IMS tracking)
3. Inserted into whatsapp_conversations + whatsapp_messages (Inbox integration)
4. The Inbox system's webhook automatically updates delivery status
5. IMS dashboard reads status from whatsapp_messages via whatsapp_message_id
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class WhatsAppError(Exception):
    """Raised when WhatsApp API call fails."""
    pass


class WhatsAppService:
    """Sends WhatsApp template messages via Meta Cloud API."""

    API_BASE = "https://graph.facebook.com"

    # Template configuration: param count and language code per template
    TEMPLATE_CONFIG = {
        "pack_expiry_alert": {
            "language": "en",
            "param_count": 3,
            # {{1}} = name, {{2}} = account_id, {{3}} = expiry_date
        },
        "recharge_today1": {
            "language": "en_US",
            "param_count": 2,
            # {{1}} = name, {{2}} = plan_name
        },
        "recharge_reminder": {
            "language": "en_US",
            "param_count": 3,
            # {{1}} = name, {{2}} = account_id, {{3}} = expiry_date
        },
    }

    def __init__(self, config):
        self.config = config
        self.token = config.WHATSAPP_TOKEN
        self.phone_id = config.WHATSAPP_PHONE_ID
        self.api_version = config.WHATSAPP_API_VERSION
        self.duplicate_interval = config.DUPLICATE_INTERVAL_HOURS

    def send_template(self, mobile: str, template_name: str,
                      params: list, renewal_id: int,
                      operator_name: str = "system",
                      skip_duplicate_check: bool = False) -> dict:
        """Send a WhatsApp template message.

        Args:
            mobile: Recipient phone number (with country code).
            template_name: Name of the approved template.
            params: List of parameter values for template placeholders.
            renewal_id: ID of the renewal record.
            operator_name: Name of the operator sending.
            skip_duplicate_check: If True, skip the 24hr duplicate check.

        Returns:
            Dict with message_id, status, and log details.

        Raises:
            WhatsAppError: If API call fails or duplicate detected.
        """
        # Check for duplicates (unless overridden)
        if not skip_duplicate_check and self._is_duplicate(mobile, template_name, renewal_id):
            raise WhatsAppError(
                f"Duplicate: Template '{template_name}' already sent to {mobile} "
                f"within the last {self.duplicate_interval} hours."
            )

        # Format phone number
        formatted_mobile = self._format_phone(mobile)

        # Build API payload
        url = f"{self.API_BASE}/{self.api_version}/{self.phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        # Build template components with parameters
        # Trim params to match template's expected count
        tmpl_config = self.TEMPLATE_CONFIG.get(template_name, {"language": "en_US", "param_count": len(params)})
        language_code = tmpl_config["language"]
        expected_params = params[:tmpl_config["param_count"]]

        components = []
        if expected_params:
            body_params = [{"type": "text", "text": str(p)} for p in expected_params]
            components.append({
                "type": "body",
                "parameters": body_params,
            })

        payload = {
            "messaging_product": "whatsapp",
            "to": formatted_mobile,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
                "components": components,
            },
        }

        # Send request
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response_data = response.json()
        except requests.RequestException as e:
            # Log failure
            self._log_send(renewal_id, mobile, template_name, params,
                           "failed", None, operator_name, str(e))
            raise WhatsAppError(f"API request failed: {e}") from e

        # Process response
        if response.status_code in (200, 201):
            message_id = response_data.get("messages", [{}])[0].get("id", "")
            self._log_send(renewal_id, mobile, template_name, params,
                           "sent", message_id, operator_name)

            # Insert into WhatsApp Inbox system for delivery tracking
            self._sync_to_inbox(mobile, message_id, template_name, expected_params, operator_name)

            return {
                "success": True,
                "message_id": message_id,
                "status": "sent",
            }
        else:
            error_msg = response_data.get("error", {}).get("message", "Unknown error")
            self._log_send(renewal_id, mobile, template_name, params,
                           "failed", None, operator_name, error_msg)
            raise WhatsAppError(f"WhatsApp API error: {error_msg}")

    def _sync_to_inbox(self, mobile: str, message_id: str, template_name: str,
                       params: list, operator_name: str):
        """Insert the sent template into the WhatsApp Inbox system.

        This creates/finds a conversation and inserts the message into
        whatsapp_messages so it appears in the Inbox UI. The Inbox webhook
        will then update the status (delivered/read) automatically.

        Note: The Countrylink Inbox stores phone numbers as 10-digit format
        (without country code prefix), matching their normalize_mobile() logic.
        """
        from renewal_system.models.database import get_db_cursor

        # The Inbox system stores phones as 10 digits (no country code)
        inbox_mobile = self._normalize_for_inbox(mobile)
        # The WhatsApp API needs 91-prefixed number
        formatted_mobile = self._format_phone(mobile)

        # Build a readable message text for the inbox
        message_text = f"[Template: {template_name}] " + " | ".join(str(p) for p in params)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            with get_db_cursor(self.config) as cursor:
                # Find existing conversation using 10-digit format (Inbox standard)
                cursor.execute(
                    "SELECT id FROM whatsapp_conversations WHERE phone = %s LIMIT 1",
                    (inbox_mobile,)
                )
                conversation = cursor.fetchone()

                if conversation:
                    conversation_id = conversation["id"]
                else:
                    # Create new conversation with 10-digit phone (Inbox standard)
                    cursor.execute("""
                        INSERT INTO whatsapp_conversations (
                            phone, customer_name, last_message, last_message_at,
                            unread_count, ai_enabled, human_takeover, created_at, updated_at
                        ) VALUES (%s, %s, %s, NOW(), 0, 1, 0, NOW(), NOW())
                    """, (inbox_mobile, inbox_mobile, message_text))
                    conversation_id = cursor.lastrowid

                # Insert message into whatsapp_messages
                # Use 10-digit phone to match Inbox convention
                cursor.execute("""
                    INSERT INTO whatsapp_messages (
                        conversation_id, whatsapp_message_id, sender_type, phone,
                        message_text, message_type, media_url, status, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    conversation_id,
                    message_id,
                    "human",  # sent by operator/system, not AI
                    inbox_mobile,
                    message_text,
                    "template",
                    None,
                    "sent",
                    now,
                ))

                # Update conversation last message
                cursor.execute("""
                    UPDATE whatsapp_conversations
                    SET last_message = %s, last_message_at = NOW(), updated_at = NOW()
                    WHERE id = %s
                """, (message_text, conversation_id))

            logger.info("Synced template to inbox: conversation_id=%s, wamid=%s, phone=%s",
                        conversation_id, message_id, inbox_mobile)
        except Exception as e:
            # Don't fail the send if inbox sync fails — just log it
            logger.warning("Failed to sync template to inbox (non-fatal): %s", e)

    def get_delivery_status(self, whatsapp_message_id: str) -> Optional[str]:
        """Get delivery status from the WhatsApp Inbox system.

        Reads the status from whatsapp_messages table which is updated
        by the Countrylink Management System's webhook.

        Args:
            whatsapp_message_id: The wamid returned by Meta API.

        Returns:
            Status string: 'sent', 'delivered', 'read', 'failed', or None.
        """
        if not whatsapp_message_id:
            return None

        from renewal_system.models.database import get_db_cursor

        try:
            with get_db_cursor(self.config) as cursor:
                cursor.execute("""
                    SELECT status FROM whatsapp_messages
                    WHERE whatsapp_message_id = %s
                    LIMIT 1
                """, (whatsapp_message_id,))
                row = cursor.fetchone()
                return row["status"] if row else None
        except Exception as e:
            logger.warning("Failed to get delivery status for %s: %s", whatsapp_message_id, e)
            return None

    def bulk_get_delivery_status(self, message_ids: list) -> dict:
        """Get delivery status for multiple messages at once.

        Args:
            message_ids: List of whatsapp_message_id strings.

        Returns:
            Dict mapping whatsapp_message_id -> status.
        """
        if not message_ids:
            return {}

        from renewal_system.models.database import get_db_cursor

        # Filter out None/empty values
        valid_ids = [mid for mid in message_ids if mid]
        if not valid_ids:
            return {}

        try:
            with get_db_cursor(self.config) as cursor:
                placeholders = ",".join(["%s"] * len(valid_ids))
                cursor.execute(f"""
                    SELECT whatsapp_message_id, status FROM whatsapp_messages
                    WHERE whatsapp_message_id IN ({placeholders})
                """, valid_ids)
                rows = cursor.fetchall()
                return {row["whatsapp_message_id"]: row["status"] for row in rows}
        except Exception as e:
            logger.warning("Failed to bulk get delivery status: %s", e)
            return {}

    def _is_duplicate(self, mobile: str, template_name: str, renewal_id: int) -> bool:
        """Check if the same template was sent recently."""
        from renewal_system.models.database import get_db_cursor

        cutoff = datetime.now() - timedelta(hours=self.duplicate_interval)

        with get_db_cursor(self.config) as cursor:
            cursor.execute("""
                SELECT COUNT(*) as cnt FROM whatsapp_campaign_logs
                WHERE mobile = %s AND template_name = %s AND renewal_id = %s
                AND status = 'sent' AND sent_at > %s
            """, (mobile, template_name, renewal_id, cutoff))
            result = cursor.fetchone()
            return result["cnt"] > 0

    def _log_send(self, renewal_id: int, mobile: str, template_name: str,
                  params: list, status: str, message_id: Optional[str],
                  operator_name: str, error_message: str = None):
        """Log the send attempt to whatsapp_campaign_logs."""
        from renewal_system.models.database import get_db_cursor

        # Set delivery_status: 'sent' on success, 'failed' on failure
        delivery_status = 'sent' if status == 'sent' else ('failed' if status == 'failed' else None)

        with get_db_cursor(self.config) as cursor:
            cursor.execute("""
                INSERT INTO whatsapp_campaign_logs
                    (renewal_id, mobile, template_name, template_params,
                     status, delivery_status, whatsapp_message_id, operator_name, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                renewal_id, mobile, template_name,
                json.dumps(params), status, delivery_status, message_id,
                operator_name, error_message,
            ))

    def _format_phone(self, mobile: str) -> str:
        """Format phone number for WhatsApp API (add 91 country code if needed)."""
        # Remove spaces, dashes, plus signs
        clean = mobile.strip().replace(" ", "").replace("-", "").replace("+", "")

        # Add India country code if 10 digits
        if len(clean) == 10 and clean.isdigit():
            return f"91{clean}"

        return clean

    def _normalize_for_inbox(self, mobile: str) -> str:
        """Normalize phone number to 10-digit format for the WhatsApp Inbox system.

        The Countrylink Management System stores phones as 10 digits
        (without country code), matching their normalize_mobile() logic.
        """
        # Remove spaces, dashes, plus signs
        digits = "".join(ch for ch in str(mobile).strip() if ch.isdigit())

        # Strip 91 prefix if 12 digits (India country code)
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]

        return digits

    def get_send_history(self, renewal_id: int) -> list:
        """Get send history for a specific renewal record."""
        from renewal_system.models.database import get_db_cursor

        with get_db_cursor(self.config) as cursor:
            cursor.execute("""
                SELECT * FROM whatsapp_campaign_logs
                WHERE renewal_id = %s
                ORDER BY sent_at DESC
                LIMIT 10
            """, (renewal_id,))
            return cursor.fetchall()
