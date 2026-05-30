"""WhatsApp Cloud API service.

Handles sending template messages via Meta WhatsApp Cloud API.
Includes duplicate protection and logging.
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
            # {{1}} = name, {{2}} = plan_name, {{3}} = expiry_date
        },
        "recharge_today1": {
            "language": "en_US",
            "param_count": 2,
            # {{1}} = name, {{2}} = plan_name
        },
        "recharge_reminder": {
            "language": "en_US",
            "param_count": 3,
            # {{1}} = name, {{2}} = plan_name, {{3}} = expiry_date
        },
        "expiry_to_date": {
            "language": "en",
            "param_count": 2,
            # {{1}} = plan_name, {{2}} = expiry_date
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

        # Log full request/response for debugging
        logger.info("WhatsApp API request: template=%s, to=%s, language=%s, params=%s",
                    template_name, formatted_mobile, language_code, expected_params)
        logger.info("WhatsApp API response: status=%d, body=%s",
                    response.status_code, json.dumps(response_data)[:500])

        # If failed with language code issue, retry with alternate language code
        if response.status_code not in (200, 201):
            error_data = response_data.get("error", {})
            error_code = error_data.get("code", 0)
            # Error 100 = Invalid parameter - could be language mismatch
            if error_code == 100:
                alt_language = "en" if language_code == "en_US" else "en_US"
                logger.info("Retrying with alternate language code: %s", alt_language)
                payload["template"]["language"]["code"] = alt_language
                try:
                    response = requests.post(url, headers=headers, json=payload, timeout=30)
                    response_data = response.json()
                    logger.info("Retry response: status=%d, body=%s",
                                response.status_code, json.dumps(response_data)[:500])
                except requests.RequestException as e:
                    pass  # Fall through to original error handling

        # Process response
        if response.status_code in (200, 201):
            message_id = response_data.get("messages", [{}])[0].get("id", "")
            self._log_send(renewal_id, mobile, template_name, params,
                           "sent", message_id, operator_name)
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

    def _is_duplicate(self, mobile: str, template_name: str, renewal_id: int) -> bool:
        """Check if the same template was sent recently."""
        from renewal_system.models.database import get_db_cursor

        cutoff = datetime.now() - timedelta(hours=self.duplicate_interval)

        with get_db_cursor(self.config) as cursor:
            cursor.execute("""
                SELECT COUNT(*) as cnt FROM whatsapp_campaign_logs
                WHERE mobile = %s COLLATE utf8mb4_general_ci
                AND template_name = %s COLLATE utf8mb4_general_ci
                AND renewal_id = %s
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
