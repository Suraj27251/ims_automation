"""Configuration for the Renewal Campaign System.

Loads settings from environment variables / .env file.
"""

import os
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

load_dotenv(override=False)


@dataclass
class Config:
    """Application configuration loaded from environment."""

    # MySQL Database
    MYSQL_HOST: str = field(default_factory=lambda: os.environ.get("MYSQL_HOST", "localhost"))
    MYSQL_PORT: int = field(default_factory=lambda: int(os.environ.get("MYSQL_PORT", "3306")))
    MYSQL_USER: str = field(default_factory=lambda: os.environ.get("MYSQL_USER", ""))
    MYSQL_PASSWORD: str = field(default_factory=lambda: os.environ.get("MYSQL_PASSWORD", ""))
    MYSQL_DATABASE: str = field(default_factory=lambda: os.environ.get("MYSQL_DATABASE", "countrylinks_user_database"))

    # WhatsApp Cloud API
    WHATSAPP_TOKEN: str = field(default_factory=lambda: os.environ.get("WHATSAPP_TOKEN", ""))
    WHATSAPP_PHONE_ID: str = field(default_factory=lambda: os.environ.get("WHATSAPP_PHONE_ID", ""))
    WHATSAPP_API_VERSION: str = field(default_factory=lambda: os.environ.get("WHATSAPP_API_VERSION", "v18.0"))

    # Duplicate protection
    DUPLICATE_INTERVAL_HOURS: int = field(
        default_factory=lambda: int(os.environ.get("DUPLICATE_INTERVAL_HOURS", "24"))
    )

    # App settings
    SECRET_KEY: str = field(default_factory=lambda: os.environ.get("SECRET_KEY", "change-me-in-production"))
    DEBUG: bool = field(default_factory=lambda: os.environ.get("DEBUG", "false").lower() == "true")

    # Templates mapping
    TEMPLATE_MAP: dict = field(default_factory=lambda: {
        "expired": "pack_expiry_alert",
        "today": "recharge_today1",
        "upcoming": "recharge_reminder",
    })


config = Config()
