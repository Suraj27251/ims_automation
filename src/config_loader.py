"""Configuration loader for IMS Data Fetcher.

Loads, validates, and provides application configuration from environment
variables, .env files, and CLI overrides.
"""

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urlparse

from dotenv import load_dotenv


class ConfigError(Exception):
    """Raised when configuration is invalid or incomplete."""

    pass


@dataclass(frozen=True)
class AppConfig:
    """Immutable application configuration."""

    login_url: str
    username: str
    password: str

    # Optional MySQL config
    mysql_enabled: bool = False
    mysql_host: Optional[str] = None
    mysql_port: int = 3306
    mysql_database: Optional[str] = None
    mysql_user: Optional[str] = None
    mysql_password: Optional[str] = None

    # Operational settings
    retry_count: int = 2
    connection_timeout: int = 30
    read_timeout: int = 60
    page_size: int = 10
    date_format: str = "yyyy/MM/dd"
    export_formats: List[str] = field(default_factory=lambda: ["console"])

    # Feature flags
    debug_mode: bool = False
    diagnostic_mode: bool = False
    file_logging: bool = False


# Mapping of config fields to environment variable names
_ENV_VAR_MAP: Dict[str, str] = {
    "login_url": "IMS_LOGIN_URL",
    "username": "IMS_USERNAME",
    "password": "IMS_PASSWORD",
    "mysql_enabled": "IMS_MYSQL_ENABLED",
    "mysql_host": "IMS_MYSQL_HOST",
    "mysql_port": "IMS_MYSQL_PORT",
    "mysql_database": "IMS_MYSQL_DB",
    "mysql_user": "IMS_MYSQL_USER",
    "mysql_password": "IMS_MYSQL_PASSWORD",
    "retry_count": "IMS_RETRY_COUNT",
    "connection_timeout": "IMS_CONN_TIMEOUT",
    "read_timeout": "IMS_READ_TIMEOUT",
    "page_size": "IMS_PAGE_SIZE",
    "date_format": "IMS_DATE_FORMAT",
    "export_formats": "IMS_EXPORT_FORMATS",
    "debug_mode": "IMS_DEBUG",
    "diagnostic_mode": "IMS_DIAGNOSTIC",
    "file_logging": "IMS_FILE_LOGGING",
}

# Required environment variables (always required)
_REQUIRED_VARS = ["login_url", "username", "password"]

# Required when MySQL is enabled
_MYSQL_REQUIRED_VARS = [
    "mysql_host",
    "mysql_database",
    "mysql_user",
    "mysql_password",
]

# Valid date format pattern: only y, M, d, /, - allowed
_DATE_FORMAT_PATTERN = re.compile(r"^[yMd/\-]+$")


def validate_url(url: str) -> bool:
    """Validate that URL has HTTP/HTTPS scheme and non-empty host.

    Args:
        url: The URL string to validate.

    Returns:
        True if the URL is valid, False otherwise.
    """
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.hostname)
    except Exception:
        return False


def validate_date_format(fmt: str) -> bool:
    """Validate date format contains only valid specifiers (y, M, d, /, -).

    Args:
        fmt: The date format string to validate.

    Returns:
        True if the format is valid, False otherwise.
    """
    if not fmt:
        return False
    return bool(_DATE_FORMAT_PATTERN.match(fmt))


def _parse_bool(value: str) -> bool:
    """Parse a string value to boolean."""
    return value.lower() in ("true", "1", "yes")


def _parse_export_formats(value: str) -> List[str]:
    """Parse comma-separated export formats string into a list."""
    formats = [f.strip().lower() for f in value.split(",") if f.strip()]
    return formats if formats else ["console"]


def load_config(cli_overrides: Optional[dict] = None) -> AppConfig:
    """Load configuration from environment variables and .env file.

    Priority order (highest to lowest):
    1. CLI overrides
    2. System environment variables
    3. .env file values

    Args:
        cli_overrides: Optional dictionary of CLI argument overrides.

    Returns:
        AppConfig instance with validated configuration.

    Raises:
        ConfigError: If required variables are missing or invalid.
    """
    # Load .env file (does NOT override existing system env vars)
    load_dotenv(override=False)

    overrides = cli_overrides or {}

    def _get_value(field_name: str) -> Optional[str]:
        """Get config value with precedence: CLI > system env > .env."""
        # CLI overrides take highest precedence
        if field_name in overrides and overrides[field_name] is not None:
            return str(overrides[field_name])

        # Environment variable (system env already loaded, .env loaded by dotenv)
        env_var = _ENV_VAR_MAP.get(field_name)
        if env_var:
            value = os.environ.get(env_var)
            if value is not None:
                return value

        return None

    # Check for missing required variables
    missing_vars = []
    for var_name in _REQUIRED_VARS:
        value = _get_value(var_name)
        if value is None:
            missing_vars.append(_ENV_VAR_MAP[var_name])

    if missing_vars:
        raise ConfigError(
            f"Missing required configuration variables: {', '.join(missing_vars)}"
        )

    # Get required values
    login_url = _get_value("login_url")
    username = _get_value("username")
    password = _get_value("password")

    # Reject whitespace-only credential values
    whitespace_vars = []
    if login_url is not None and login_url.strip() == "":
        whitespace_vars.append(_ENV_VAR_MAP["login_url"])
    if username is not None and username.strip() == "":
        whitespace_vars.append(_ENV_VAR_MAP["username"])
    if password is not None and password.strip() == "":
        whitespace_vars.append(_ENV_VAR_MAP["password"])

    if whitespace_vars:
        raise ConfigError(
            f"Configuration variables contain only whitespace: "
            f"{', '.join(whitespace_vars)}"
        )

    # Validate URL
    if not validate_url(login_url):
        raise ConfigError(
            f"Invalid login URL: '{login_url}'. "
            f"URL must have HTTP or HTTPS scheme and a valid host."
        )

    # Parse optional values with defaults
    mysql_enabled = _parse_bool(_get_value("mysql_enabled") or "false")
    mysql_host = _get_value("mysql_host")
    mysql_port_str = _get_value("mysql_port")
    mysql_port = int(mysql_port_str) if mysql_port_str else 3306
    mysql_database = _get_value("mysql_database")
    mysql_user = _get_value("mysql_user")
    mysql_password = _get_value("mysql_password")

    retry_count_str = _get_value("retry_count")
    retry_count = int(retry_count_str) if retry_count_str else 2

    conn_timeout_str = _get_value("connection_timeout")
    connection_timeout = int(conn_timeout_str) if conn_timeout_str else 30

    read_timeout_str = _get_value("read_timeout")
    read_timeout = int(read_timeout_str) if read_timeout_str else 60

    page_size_str = _get_value("page_size")
    page_size = int(page_size_str) if page_size_str else 10

    date_format = _get_value("date_format") or "yyyy/MM/dd"
    export_formats_str = _get_value("export_formats")
    export_formats = (
        _parse_export_formats(export_formats_str)
        if export_formats_str
        else ["console"]
    )

    debug_mode = _parse_bool(_get_value("debug_mode") or "false")
    diagnostic_mode = _parse_bool(_get_value("diagnostic_mode") or "false")
    file_logging = _parse_bool(_get_value("file_logging") or "false")

    # Validate date format
    if not validate_date_format(date_format):
        raise ConfigError(
            f"Invalid date format: '{date_format}'. "
            f"Only valid specifiers (y, M, d) and separators (/, -) are allowed."
        )

    # Check MySQL required vars when enabled
    if mysql_enabled:
        mysql_missing = []
        for var_name in _MYSQL_REQUIRED_VARS:
            value = _get_value(var_name)
            if value is None or value.strip() == "":
                mysql_missing.append(_ENV_VAR_MAP[var_name])

        if mysql_missing:
            raise ConfigError(
                f"MySQL is enabled but missing required variables: "
                f"{', '.join(mysql_missing)}"
            )

    return AppConfig(
        login_url=login_url,
        username=username,
        password=password,
        mysql_enabled=mysql_enabled,
        mysql_host=mysql_host,
        mysql_port=mysql_port,
        mysql_database=mysql_database,
        mysql_user=mysql_user,
        mysql_password=mysql_password,
        retry_count=retry_count,
        connection_timeout=connection_timeout,
        read_timeout=read_timeout,
        page_size=page_size,
        date_format=date_format,
        export_formats=export_formats,
        debug_mode=debug_mode,
        diagnostic_mode=diagnostic_mode,
        file_logging=file_logging,
    )
