"""WhatsApp delivery status tracking.

Delivery status updates are handled by the main Countrylink Management System
webhook at https://countrylinks.in/webhook. That webhook receives Meta callbacks
and updates the whatsapp_campaign_logs table directly.

This module provides a status check endpoint for the dashboard to query
delivery statuses without needing a separate webhook registration.
"""

import logging
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

webhook_bp = Blueprint("webhook", __name__)
logger = logging.getLogger(__name__)


@webhook_bp.route("/webhook/status", methods=["GET"])
def webhook_status():
    """Health check endpoint to verify webhook integration is configured.

    Returns info about delivery status tracking configuration.
    """
    return jsonify({
        "success": True,
        "webhook_handler": "countrylinks.in/webhook",
        "description": "Delivery statuses are updated by the main CMS webhook. "
                       "Use /api/renewals/delivery-status?ids=... to query statuses.",
    })
