"""Operator action logging service.

Tracks all operator actions for audit trail.
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def log_action(config, operator_name: str, action_type: str,
               target_id: int = None, details: dict = None):
    """Log an operator action.

    Args:
        config: Application config.
        operator_name: Name of the operator.
        action_type: Type of action (send_message, bulk_send, export, etc.)
        target_id: ID of the target record.
        details: Additional details as dict.
    """
    from renewal_system.models.database import get_db_cursor

    with get_db_cursor(config) as cursor:
        cursor.execute("""
            INSERT INTO operator_actions (operator_name, action_type, target_id, details)
            VALUES (%s, %s, %s, %s)
        """, (
            operator_name, action_type, target_id,
            json.dumps(details) if details else None,
        ))

    logger.info("Operator action: %s performed '%s' on target %s",
                operator_name, action_type, target_id)
