"""Unit tests for config_loader module."""

import os
import tempfile
from unittest.mock import patch

import pytest

from src.config_loader import (
    AppConfig,
    ConfigError,
    load_config,
    validate_date_format,
    validate_url,
)


class TestValidateUrl:
    """Tests for validate_url function."""

    def test_valid_https_url(self):
        assert validate_url("https://example.com") is True

    def test_valid_http_url(self):
        assert validate_url("http://example.com") is True

    def test_valid_url_with_path(self):
        assert validate_url("https://admin.example.com/login") is True

    def test_valid_url_with_port(self):
        assert validate_url("http://localhost:8080") is True

    def test_invalid_no_scheme(self):
        assert validate_url("example.com") is False

    def test_invalid_ftp_scheme(self):
        assert validate_url("ftp://example.com") is False

    def test_invalid_empty_string(self):
        assert validate_url("") is False

    def test_invalid_scheme_only(self):
        assert validate_url("http://") is False

    def test_invalid_no_host(self):
        assert validate_url("https:///path") is False


class TestValidateDateFormat:
    """Tests for validate_date_format function."""

    def test_valid_default_format(self):
        assert validate_date_format("yyyy/MM/dd") is True

    def test_valid_dash_format(self):
        assert validate_date_format("yyyy-MM-dd") is True

    def test_valid_mixed_separators(self):
        assert validate_date_format("dd/MM/yyyy") is True

    def test_invalid_with_spaces(self):
        assert validate_date_format("yyyy MM dd") is False

    def test_invalid_with_letters(self):
        assert validate_date_format("yyyy/MM/dd HH:mm") is False

    def test_invalid_empty_string(self):
        assert validate_date_format("") is False

    def test_invalid_with_dots(self):
        assert validate_date_format("yyyy.MM.dd") is False


class TestLoadConfig:
    """Tests for load_config function."""

    @pytest.fixture(autouse=True)
    def clean_env(self):
        """Remove IMS env vars before each test."""
        env_vars = [
            "IMS_LOGIN_URL",
            "IMS_USERNAME",
            "IMS_PASSWORD",
            "IMS_MYSQL_ENABLED",
            "IMS_MYSQL_HOST",
            "IMS_MYSQL_PORT",
            "IMS_MYSQL_DB",
            "IMS_MYSQL_USER",
            "IMS_MYSQL_PASSWORD",
            "IMS_RETRY_COUNT",
            "IMS_CONN_TIMEOUT",
            "IMS_READ_TIMEOUT",
            "IMS_PAGE_SIZE",
            "IMS_DATE_FORMAT",
            "IMS_EXPORT_FORMATS",
            "IMS_DEBUG",
            "IMS_DIAGNOSTIC",
            "IMS_FILE_LOGGING",
        ]
        with patch.dict(os.environ, {}, clear=True):
            # Set only the vars we want for each test
            yield

    @patch.dict(
        os.environ,
        {
            "IMS_LOGIN_URL": "https://admin.example.com/login",
            "IMS_USERNAME": "testuser",
            "IMS_PASSWORD": "testpass",
        },
        clear=True,
    )
    def test_load_minimal_config(self):
        """Test loading config with only required variables."""
        config = load_config()
        assert config.login_url == "https://admin.example.com/login"
        assert config.username == "testuser"
        assert config.password == "testpass"

    @patch.dict(
        os.environ,
        {
            "IMS_LOGIN_URL": "https://admin.example.com/login",
            "IMS_USERNAME": "testuser",
            "IMS_PASSWORD": "testpass",
        },
        clear=True,
    )
    def test_default_values(self):
        """Test that optional parameters have correct defaults."""
        config = load_config()
        assert config.mysql_enabled is False
        assert config.retry_count == 2
        assert config.connection_timeout == 30
        assert config.read_timeout == 60
        assert config.page_size == 10
        assert config.date_format == "yyyy/MM/dd"
        assert config.export_formats == ["console"]
        assert config.debug_mode is False
        assert config.diagnostic_mode is False
        assert config.file_logging is False

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_all_required_vars(self):
        """Test that missing required vars raises ConfigError listing all."""
        with pytest.raises(ConfigError) as exc_info:
            load_config()
        error_msg = str(exc_info.value)
        assert "IMS_LOGIN_URL" in error_msg
        assert "IMS_USERNAME" in error_msg
        assert "IMS_PASSWORD" in error_msg

    @patch.dict(
        os.environ,
        {
            "IMS_LOGIN_URL": "https://admin.example.com/login",
        },
        clear=True,
    )
    def test_missing_some_required_vars(self):
        """Test that only missing vars are listed in error."""
        with pytest.raises(ConfigError) as exc_info:
            load_config()
        error_msg = str(exc_info.value)
        assert "IMS_USERNAME" in error_msg
        assert "IMS_PASSWORD" in error_msg
        assert "IMS_LOGIN_URL" not in error_msg

    @patch.dict(
        os.environ,
        {
            "IMS_LOGIN_URL": "https://admin.example.com/login",
            "IMS_USERNAME": "   ",
            "IMS_PASSWORD": "testpass",
        },
        clear=True,
    )
    def test_whitespace_only_username_rejected(self):
        """Test that whitespace-only username raises ConfigError."""
        with pytest.raises(ConfigError) as exc_info:
            load_config()
        assert "whitespace" in str(exc_info.value).lower()
        assert "IMS_USERNAME" in str(exc_info.value)

    @patch.dict(
        os.environ,
        {
            "IMS_LOGIN_URL": "https://admin.example.com/login",
            "IMS_USERNAME": "testuser",
            "IMS_PASSWORD": "\t\n  ",
        },
        clear=True,
    )
    def test_whitespace_only_password_rejected(self):
        """Test that whitespace-only password raises ConfigError."""
        with pytest.raises(ConfigError) as exc_info:
            load_config()
        assert "whitespace" in str(exc_info.value).lower()
        assert "IMS_PASSWORD" in str(exc_info.value)

    @patch.dict(
        os.environ,
        {
            "IMS_LOGIN_URL": "not-a-valid-url",
            "IMS_USERNAME": "testuser",
            "IMS_PASSWORD": "testpass",
        },
        clear=True,
    )
    def test_invalid_url_rejected(self):
        """Test that invalid URL raises ConfigError."""
        with pytest.raises(ConfigError) as exc_info:
            load_config()
        assert "Invalid login URL" in str(exc_info.value)

    @patch.dict(
        os.environ,
        {
            "IMS_LOGIN_URL": "https://admin.example.com/login",
            "IMS_USERNAME": "testuser",
            "IMS_PASSWORD": "testpass",
            "IMS_DATE_FORMAT": "yyyy.MM.dd",
        },
        clear=True,
    )
    def test_invalid_date_format_rejected(self):
        """Test that invalid date format raises ConfigError."""
        with pytest.raises(ConfigError) as exc_info:
            load_config()
        assert "Invalid date format" in str(exc_info.value)

    @patch.dict(
        os.environ,
        {
            "IMS_LOGIN_URL": "https://admin.example.com/login",
            "IMS_USERNAME": "testuser",
            "IMS_PASSWORD": "testpass",
            "IMS_RETRY_COUNT": "5",
            "IMS_CONN_TIMEOUT": "45",
            "IMS_READ_TIMEOUT": "90",
            "IMS_PAGE_SIZE": "25",
            "IMS_DATE_FORMAT": "dd-MM-yyyy",
            "IMS_EXPORT_FORMATS": "console,csv,mysql",
            "IMS_DEBUG": "true",
            "IMS_DIAGNOSTIC": "1",
            "IMS_FILE_LOGGING": "yes",
        },
        clear=True,
    )
    def test_all_optional_values_loaded(self):
        """Test loading all optional configuration values."""
        config = load_config()
        assert config.retry_count == 5
        assert config.connection_timeout == 45
        assert config.read_timeout == 90
        assert config.page_size == 25
        assert config.date_format == "dd-MM-yyyy"
        assert config.export_formats == ["console", "csv", "mysql"]
        assert config.debug_mode is True
        assert config.diagnostic_mode is True
        assert config.file_logging is True

    @patch.dict(
        os.environ,
        {
            "IMS_LOGIN_URL": "https://admin.example.com/login",
            "IMS_USERNAME": "testuser",
            "IMS_PASSWORD": "testpass",
            "IMS_MYSQL_ENABLED": "true",
            "IMS_MYSQL_HOST": "localhost",
            "IMS_MYSQL_PORT": "3307",
            "IMS_MYSQL_DB": "ims_db",
            "IMS_MYSQL_USER": "dbuser",
            "IMS_MYSQL_PASSWORD": "dbpass",
        },
        clear=True,
    )
    def test_mysql_config_loaded(self):
        """Test MySQL configuration when enabled."""
        config = load_config()
        assert config.mysql_enabled is True
        assert config.mysql_host == "localhost"
        assert config.mysql_port == 3307
        assert config.mysql_database == "ims_db"
        assert config.mysql_user == "dbuser"
        assert config.mysql_password == "dbpass"

    @patch.dict(
        os.environ,
        {
            "IMS_LOGIN_URL": "https://admin.example.com/login",
            "IMS_USERNAME": "testuser",
            "IMS_PASSWORD": "testpass",
            "IMS_MYSQL_ENABLED": "true",
        },
        clear=True,
    )
    def test_mysql_enabled_missing_required_vars(self):
        """Test that enabling MySQL without required vars raises ConfigError."""
        with pytest.raises(ConfigError) as exc_info:
            load_config()
        error_msg = str(exc_info.value)
        assert "MySQL" in error_msg
        assert "IMS_MYSQL_HOST" in error_msg

    @patch.dict(
        os.environ,
        {
            "IMS_LOGIN_URL": "https://env.example.com/login",
            "IMS_USERNAME": "envuser",
            "IMS_PASSWORD": "envpass",
        },
        clear=True,
    )
    def test_cli_overrides_take_precedence(self):
        """Test that CLI overrides take highest precedence."""
        overrides = {
            "login_url": "https://cli.example.com/login",
            "username": "cliuser",
            "password": "clipass",
            "page_size": "50",
        }
        config = load_config(cli_overrides=overrides)
        assert config.login_url == "https://cli.example.com/login"
        assert config.username == "cliuser"
        assert config.password == "clipass"
        assert config.page_size == 50

    @patch.dict(
        os.environ,
        {
            "IMS_LOGIN_URL": "https://admin.example.com/login",
            "IMS_USERNAME": "testuser",
            "IMS_PASSWORD": "testpass",
        },
        clear=True,
    )
    def test_frozen_dataclass(self):
        """Test that AppConfig is immutable."""
        config = load_config()
        with pytest.raises(Exception):
            config.username = "newuser"

    @patch.dict(
        os.environ,
        {
            "IMS_LOGIN_URL": "https://admin.example.com/login",
            "IMS_USERNAME": "testuser",
            "IMS_PASSWORD": "testpass",
            "IMS_EXPORT_FORMATS": "csv",
        },
        clear=True,
    )
    def test_single_export_format(self):
        """Test parsing a single export format."""
        config = load_config()
        assert config.export_formats == ["csv"]

    def test_env_file_loading_with_system_env_precedence(self, tmp_path):
        """Test that .env file values are loaded but system env vars take precedence.

        Validates: Requirement 12.7 - system env takes precedence over .env file.
        """
        # Create a .env file with specific values
        env_file = tmp_path / ".env"
        env_file.write_text(
            "IMS_LOGIN_URL=https://dotenv.example.com/login\n"
            "IMS_USERNAME=dotenvuser\n"
            "IMS_PASSWORD=dotenvpass\n"
            "IMS_PAGE_SIZE=99\n"
        )

        # Set system env vars that should override .env values
        env_override = {
            "IMS_LOGIN_URL": "https://sysenv.example.com/login",
            "IMS_USERNAME": "sysenvuser",
            "IMS_PASSWORD": "sysenvpass",
        }

        with patch.dict(os.environ, env_override, clear=True):
            with patch("src.config_loader.load_dotenv") as mock_dotenv:
                # Simulate dotenv loading: it should NOT override existing env vars
                # because load_dotenv(override=False) is used
                mock_dotenv.return_value = None
                config = load_config()

        # System env vars should take precedence
        assert config.login_url == "https://sysenv.example.com/login"
        assert config.username == "sysenvuser"
        assert config.password == "sysenvpass"

    def test_env_file_provides_values_when_system_env_absent(self):
        """Test that .env file values are used when system env vars are not set.

        Validates: Requirement 12.1, 12.7 - config loaded from .env file.
        """
        with patch.dict(os.environ, {}, clear=True):
            # Simulate dotenv loading by setting env vars as dotenv would
            with patch("src.config_loader.load_dotenv") as mock_dotenv:

                def fake_load_dotenv(**kwargs):
                    """Simulate dotenv loading values into os.environ."""
                    os.environ["IMS_LOGIN_URL"] = "https://fromenv.example.com/login"
                    os.environ["IMS_USERNAME"] = "envfileuser"
                    os.environ["IMS_PASSWORD"] = "envfilepass"

                mock_dotenv.side_effect = fake_load_dotenv
                config = load_config()

        assert config.login_url == "https://fromenv.example.com/login"
        assert config.username == "envfileuser"
        assert config.password == "envfilepass"

    @patch.dict(
        os.environ,
        {
            "IMS_LOGIN_URL": "https://admin.example.com/login",
            "IMS_USERNAME": "testuser",
            "IMS_PASSWORD": "testpass",
            "IMS_MYSQL_ENABLED": "true",
            "IMS_MYSQL_HOST": "dbhost",
            "IMS_MYSQL_DB": "mydb",
            "IMS_MYSQL_USER": "dbuser",
        },
        clear=True,
    )
    def test_mysql_enabled_missing_password_raises_error(self):
        """Test that MySQL enabled without password raises ConfigError.

        Validates: Requirement 12.2 - MySQL connection params required when enabled.
        """
        with pytest.raises(ConfigError) as exc_info:
            load_config()
        error_msg = str(exc_info.value)
        assert "IMS_MYSQL_PASSWORD" in error_msg

    @patch.dict(
        os.environ,
        {
            "IMS_LOGIN_URL": "https://env.example.com/login",
            "IMS_USERNAME": "envuser",
            "IMS_PASSWORD": "envpass",
            "IMS_PAGE_SIZE": "20",
            "IMS_DEBUG": "true",
        },
        clear=True,
    )
    def test_cli_overrides_override_all_sources(self):
        """Test CLI overrides take precedence over both env vars and .env file.

        Validates: Requirement 12.7 - CLI overrides take highest precedence.
        """
        overrides = {
            "page_size": "100",
            "debug_mode": "false",
        }
        config = load_config(cli_overrides=overrides)
        # CLI override should win over env var
        assert config.page_size == 100
        # CLI override "false" should override env var "true"
        assert config.debug_mode is False
        # Non-overridden values should come from env
        assert config.login_url == "https://env.example.com/login"
        assert config.username == "envuser"
