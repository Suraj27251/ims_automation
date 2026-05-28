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
    """Application configuration loaded from environment.

    Supports multiple env var naming conventions:
    - DB_HOST / MYSQL_HOST
    - DB_USER / MYSQL_USER
    - DB_PASSWORD / MYSQL_PASSWORD
    - DB_NAME / MYSQL_DATABASE
    """

    # MySQL Database (check DB_* first, then MYSQL_*, then IMS_MYSQL_*)
    MYSQL_HOST: str = field(default_factory=lambda: (
        os.environ.get("DB_HOST")
        or os.environ.get("MYSQL_HOST")
        or os.environ.get("IMS_MYSQL_HOST")
        or "localhost"
    ))
    MYSQL_PORT: int = field(default_factory=lambda: int(
        os.environ.get("DB_PORT")
        or os.environ.get("MYSQL_PORT")
        or os.environ.get("IMS_MYSQL_PORT")
        or "3306"
    ))
    MYSQL_USER: str = field(default_factory=lambda: (
        os.environ.get("DB_USER")
        or os.environ.get("MYSQL_USER")
        or os.environ.get("IMS_MYSQL_USER")
        or ""
    ))
    MYSQL_PASSWORD: str = field(default_factory=lambda: (
        os.environ.get("DB_PASSWORD")
        or os.environ.get("MYSQL_PASSWORD")
        or os.environ.get("IMS_MYSQL_PASSWORD")
        or ""
    ))
    MYSQL_DATABASE: str = field(default_factory=lambda: (
        os.environ.get("DB_NAME")
        or os.environ.get("MYSQL_DATABASE")
        or os.environ.get("IMS_MYSQL_DB")
        or "countrylinks_user_database"
    ))

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
