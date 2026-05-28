"""Flask application factory for the Renewal Campaign System.

Creates and configures the Flask app with all API routes.
"""

import logging
import os
from datetime import date
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask

from renewal_system.config import config


def create_app():
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    app.config["SECRET_KEY"] = config.SECRET_KEY
    app.config["JSON_SORT_KEYS"] = False

    # Setup logging
    _setup_logging(app)

    # Initialize database tables
    from renewal_system.models.database import init_tables
    try:
        init_tables(config)
    except Exception as e:
        app.logger.error("Failed to initialize tables: %s", e)

    # Register blueprints
    from renewal_system.api.routes import api_bp
    from renewal_system.api.views import views_bp
    from renewal_system.api.webhook import webhook_bp

    app.register_blueprint(api_bp, url_prefix="/api/renewals")
    app.register_blueprint(webhook_bp, url_prefix="/api/renewals")
    app.register_blueprint(views_bp)

    # Store config on app
    app.renewal_config = config

    # Error handlers
    @app.errorhandler(500)
    def internal_error(error):
        return {"success": False, "error": "Internal server error. Check database connection."}, 500

    @app.errorhandler(404)
    def not_found(error):
        return {"success": False, "error": "Endpoint not found."}, 404

    return app


def _setup_logging(app):
    """Configure application logging."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # WhatsApp send log
    wa_handler = RotatingFileHandler(
        log_dir / "whatsapp_send.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    wa_handler.setLevel(logging.INFO)
    wa_handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s"
    ))

    # Operator actions log
    op_handler = RotatingFileHandler(
        log_dir / "operator_actions.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    op_handler.setLevel(logging.INFO)

    # API errors log
    err_handler = RotatingFileHandler(
        log_dir / "api_errors.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    err_handler.setLevel(logging.ERROR)
    err_handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    ))

    app.logger.addHandler(err_handler)

    # Configure module loggers
    logging.getLogger("renewal_system.services.whatsapp").addHandler(wa_handler)
    logging.getLogger("renewal_system.services.operator_log").addHandler(op_handler)
