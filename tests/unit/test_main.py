"""Unit tests for main.py CLI entry point and orchestration."""

import os
import sys
from unittest.mock import MagicMock, patch, call

import pytest

from src.config_loader import AppConfig, ConfigError
from src.main import build_argument_parser, main


class TestBuildArgumentParser:
    """Tests for build_argument_parser function."""

    def test_parser_accepts_from_date(self):
        """Test --from-date argument is parsed correctly."""
        parser = build_argument_parser()
        args = parser.parse_args(["--from-date", "2024/01/01", "--to-date", "2024/12/31"])
        assert args.from_date == "2024/01/01"

    def test_parser_accepts_to_date(self):
        """Test --to-date argument is parsed correctly."""
        parser = build_argument_parser()
        args = parser.parse_args(["--from-date", "2024/01/01", "--to-date", "2024/12/31"])
        assert args.to_date == "2024/12/31"

    def test_parser_accepts_page_size(self):
        """Test --page-size argument is parsed correctly."""
        parser = build_argument_parser()
        args = parser.parse_args(
            ["--from-date", "2024/01/01", "--to-date", "2024/12/31", "--page-size", "50"]
        )
        assert args.page_size == 50

    def test_parser_default_page_size(self):
        """Test --page-size defaults to 10."""
        parser = build_argument_parser()
        args = parser.parse_args(["--from-date", "2024/01/01", "--to-date", "2024/12/31"])
        assert args.page_size == 10

    def test_parser_accepts_debug_flag(self):
        """Test --debug flag is parsed correctly."""
        parser = build_argument_parser()
        args = parser.parse_args(
            ["--from-date", "2024/01/01", "--to-date", "2024/12/31", "--debug"]
        )
        assert args.debug is True

    def test_parser_debug_default_false(self):
        """Test --debug defaults to False."""
        parser = build_argument_parser()
        args = parser.parse_args(["--from-date", "2024/01/01", "--to-date", "2024/12/31"])
        assert args.debug is False

    def test_parser_accepts_export(self):
        """Test --export argument is parsed correctly."""
        parser = build_argument_parser()
        args = parser.parse_args(
            ["--from-date", "2024/01/01", "--to-date", "2024/12/31", "--export", "csv,console"]
        )
        assert args.export == "csv,console"

    def test_parser_default_export(self):
        """Test --export defaults to 'console'."""
        parser = build_argument_parser()
        args = parser.parse_args(["--from-date", "2024/01/01", "--to-date", "2024/12/31"])
        assert args.export == "console"

    def test_parser_from_date_not_required(self):
        """Test --from-date is not required by argparse (validated in main)."""
        parser = build_argument_parser()
        args = parser.parse_args([])
        assert args.from_date is None

    def test_parser_to_date_not_required(self):
        """Test --to-date is not required by argparse (validated in main)."""
        parser = build_argument_parser()
        args = parser.parse_args([])
        assert args.to_date is None

    def test_parser_all_arguments_together(self):
        """Test all arguments parsed together correctly."""
        parser = build_argument_parser()
        args = parser.parse_args([
            "--from-date", "2024/06/01",
            "--to-date", "2024/06/30",
            "--page-size", "25",
            "--debug",
            "--export", "csv,mysql",
        ])
        assert args.from_date == "2024/06/01"
        assert args.to_date == "2024/06/30"
        assert args.page_size == 25
        assert args.debug is True
        assert args.export == "csv,mysql"


def _make_config(**overrides):
    """Helper to create an AppConfig with sensible defaults for testing."""
    defaults = {
        "login_url": "https://admin.example.com/login",
        "username": "testuser",
        "password": "testpass",
        "date_format": "yyyy/MM/dd",
        "page_size": 10,
        "debug_mode": False,
        "diagnostic_mode": False,
        "file_logging": False,
        "export_formats": ["console"],
        "connection_timeout": 30,
        "read_timeout": 60,
        "retry_count": 2,
        "mysql_enabled": False,
    }
    defaults.update(overrides)
    return AppConfig(**defaults)


class TestMainMissingDates:
    """Tests for main() when date arguments are missing."""

    @patch("src.main.load_config")
    @patch("sys.argv", ["main.py"])
    def test_missing_both_dates_returns_1(self, mock_load_config):
        """Test main returns 1 when --from-date and --to-date are missing.

        Validates: Requirement 16.6
        """
        mock_load_config.return_value = _make_config()
        result = main()
        assert result == 1

    @patch("src.main.load_config")
    @patch("sys.argv", ["main.py", "--from-date", "2024/01/01"])
    def test_missing_to_date_returns_1(self, mock_load_config):
        """Test main returns 1 when --to-date is missing.

        Validates: Requirement 16.6
        """
        mock_load_config.return_value = _make_config()
        result = main()
        assert result == 1

    @patch("src.main.load_config")
    @patch("sys.argv", ["main.py", "--to-date", "2024/12/31"])
    def test_missing_from_date_returns_1(self, mock_load_config):
        """Test main returns 1 when --from-date is missing.

        Validates: Requirement 16.6
        """
        mock_load_config.return_value = _make_config()
        result = main()
        assert result == 1


class TestMainInvalidDateFormat:
    """Tests for main() when date format is invalid."""

    @patch("src.main.load_config")
    @patch("sys.argv", ["main.py", "--from-date", "01-01-2024", "--to-date", "2024/12/31"])
    def test_invalid_from_date_format_returns_1(self, mock_load_config):
        """Test main returns 1 when --from-date doesn't match configured format.

        Validates: Requirement 16.5
        """
        mock_load_config.return_value = _make_config(date_format="yyyy/MM/dd")
        result = main()
        assert result == 1

    @patch("src.main.load_config")
    @patch("sys.argv", ["main.py", "--from-date", "2024/01/01", "--to-date", "31-12-2024"])
    def test_invalid_to_date_format_returns_1(self, mock_load_config):
        """Test main returns 1 when --to-date doesn't match configured format.

        Validates: Requirement 16.5
        """
        mock_load_config.return_value = _make_config(date_format="yyyy/MM/dd")
        result = main()
        assert result == 1

    @patch("src.main.load_config")
    @patch("sys.argv", ["main.py", "--from-date", "not-a-date", "--to-date", "2024/12/31"])
    def test_completely_invalid_date_returns_1(self, mock_load_config):
        """Test main returns 1 when date is completely invalid.

        Validates: Requirement 16.5
        """
        mock_load_config.return_value = _make_config(date_format="yyyy/MM/dd")
        result = main()
        assert result == 1


class TestMainDebugMode:
    """Tests for main() --debug flag behavior."""

    @patch("src.main.load_config")
    @patch("sys.argv", ["main.py", "--debug"])
    def test_debug_flag_sets_cli_overrides(self, mock_load_config):
        """Test --debug enables debug_mode and diagnostic_mode in CLI overrides.

        Validates: Requirement 16.4
        """
        mock_load_config.return_value = _make_config(
            debug_mode=True, diagnostic_mode=True
        )

        # main() will return 1 because no dates provided, but we can verify
        # that load_config was called with the correct overrides
        result = main()

        # Verify load_config was called with debug overrides
        mock_load_config.assert_called_once()
        call_args = mock_load_config.call_args
        cli_overrides = call_args[0][0] if call_args[0] else call_args[1].get("cli_overrides", {})

        # The overrides dict should contain debug_mode and diagnostic_mode
        assert cli_overrides.get("debug_mode") is True
        assert cli_overrides.get("diagnostic_mode") is True


class TestMainOrchestrationSuccess:
    """Tests for main() successful orchestration flow with mocked modules."""

    @patch("src.main.DataExporter")
    @patch("src.main.RenewalAPI")
    @patch("src.main.LoginHandler")
    @patch("src.main.SessionManager")
    @patch("src.main.DiagnosticsManager")
    @patch("src.main.load_config")
    @patch("sys.argv", ["main.py", "--from-date", "2024/01/01", "--to-date", "2024/12/31"])
    def test_successful_execution_returns_0(
        self,
        mock_load_config,
        mock_diagnostics,
        mock_session_manager,
        mock_login_handler,
        mock_renewal_api,
        mock_data_exporter,
    ):
        """Test main returns 0 on successful execution.

        Validates: Requirement 16.1, 16.2, 16.3
        """
        # Setup config
        mock_load_config.return_value = _make_config()

        # Setup mocks
        mock_session_instance = MagicMock()
        mock_session_manager.return_value = mock_session_instance

        mock_login_instance = MagicMock()
        mock_login_handler.return_value = mock_login_instance

        mock_api_instance = MagicMock()
        mock_api_instance.fetch_all_renewals.return_value = []
        mock_renewal_api.return_value = mock_api_instance

        mock_exporter_instance = MagicMock()
        mock_data_exporter.return_value = mock_exporter_instance

        result = main()
        assert result == 0

    @patch("src.main.DataExporter")
    @patch("src.main.RenewalAPI")
    @patch("src.main.LoginHandler")
    @patch("src.main.SessionManager")
    @patch("src.main.DiagnosticsManager")
    @patch("src.main.load_config")
    @patch("sys.argv", ["main.py", "--from-date", "2024/01/01", "--to-date", "2024/12/31"])
    def test_login_handler_authenticate_called(
        self,
        mock_load_config,
        mock_diagnostics,
        mock_session_manager,
        mock_login_handler,
        mock_renewal_api,
        mock_data_exporter,
    ):
        """Test that LoginHandler.authenticate() is called during orchestration."""
        mock_load_config.return_value = _make_config()

        mock_session_instance = MagicMock()
        mock_session_manager.return_value = mock_session_instance

        mock_login_instance = MagicMock()
        mock_login_handler.return_value = mock_login_instance

        mock_api_instance = MagicMock()
        mock_api_instance.fetch_all_renewals.return_value = []
        mock_renewal_api.return_value = mock_api_instance

        mock_exporter_instance = MagicMock()
        mock_data_exporter.return_value = mock_exporter_instance

        main()
        mock_login_instance.authenticate.assert_called_once()

    @patch("src.main.DataExporter")
    @patch("src.main.RenewalAPI")
    @patch("src.main.LoginHandler")
    @patch("src.main.SessionManager")
    @patch("src.main.DiagnosticsManager")
    @patch("src.main.load_config")
    @patch("sys.argv", ["main.py", "--from-date", "2024/01/01", "--to-date", "2024/12/31"])
    def test_renewal_api_fetch_called_with_dates(
        self,
        mock_load_config,
        mock_diagnostics,
        mock_session_manager,
        mock_login_handler,
        mock_renewal_api,
        mock_data_exporter,
    ):
        """Test that RenewalAPI.fetch_all_renewals() is called with parsed dates."""
        mock_load_config.return_value = _make_config()

        mock_session_instance = MagicMock()
        mock_session_manager.return_value = mock_session_instance

        mock_login_instance = MagicMock()
        mock_login_handler.return_value = mock_login_instance

        mock_api_instance = MagicMock()
        mock_api_instance.fetch_all_renewals.return_value = []
        mock_renewal_api.return_value = mock_api_instance

        mock_exporter_instance = MagicMock()
        mock_data_exporter.return_value = mock_exporter_instance

        main()

        mock_api_instance.fetch_all_renewals.assert_called_once()
        call_kwargs = mock_api_instance.fetch_all_renewals.call_args[1]
        from datetime import date
        assert call_kwargs["from_date"] == date(2024, 1, 1)
        assert call_kwargs["to_date"] == date(2024, 12, 31)

    @patch("src.main.DataExporter")
    @patch("src.main.RenewalAPI")
    @patch("src.main.LoginHandler")
    @patch("src.main.SessionManager")
    @patch("src.main.DiagnosticsManager")
    @patch("src.main.load_config")
    @patch("sys.argv", ["main.py", "--from-date", "2024/01/01", "--to-date", "2024/12/31"])
    def test_data_exporter_export_console_called(
        self,
        mock_load_config,
        mock_diagnostics,
        mock_session_manager,
        mock_login_handler,
        mock_renewal_api,
        mock_data_exporter,
    ):
        """Test that DataExporter.export_console() is called for console export."""
        mock_load_config.return_value = _make_config(export_formats=["console"])

        mock_session_instance = MagicMock()
        mock_session_manager.return_value = mock_session_instance

        mock_login_instance = MagicMock()
        mock_login_handler.return_value = mock_login_instance

        mock_api_instance = MagicMock()
        mock_api_instance.fetch_all_renewals.return_value = []
        mock_renewal_api.return_value = mock_api_instance

        mock_exporter_instance = MagicMock()
        mock_data_exporter.return_value = mock_exporter_instance

        main()
        mock_exporter_instance.export_console.assert_called_once_with([])


class TestMainErrorHandling:
    """Tests for main() error handling and exit codes."""

    @patch("src.main.load_config")
    @patch("sys.argv", ["main.py", "--from-date", "2024/01/01", "--to-date", "2024/12/31"])
    def test_config_error_returns_1(self, mock_load_config):
        """Test main returns 1 when ConfigError is raised.

        Validates: Requirement 16.1
        """
        mock_load_config.side_effect = ConfigError("Missing IMS_LOGIN_URL")
        result = main()
        assert result == 1

    @patch("src.main.LoginHandler")
    @patch("src.main.SessionManager")
    @patch("src.main.DiagnosticsManager")
    @patch("src.main.load_config")
    @patch("sys.argv", ["main.py", "--from-date", "2024/01/01", "--to-date", "2024/12/31"])
    def test_login_error_returns_1(
        self,
        mock_load_config,
        mock_diagnostics,
        mock_session_manager,
        mock_login_handler,
    ):
        """Test main returns 1 when LoginError is raised."""
        from src.login_handler import LoginError

        mock_load_config.return_value = _make_config()
        mock_session_instance = MagicMock()
        mock_session_manager.return_value = mock_session_instance

        mock_login_instance = MagicMock()
        mock_login_instance.authenticate.side_effect = LoginError("Auth failed")
        mock_login_handler.return_value = mock_login_instance

        result = main()
        assert result == 1

    @patch("src.main.RenewalAPI")
    @patch("src.main.LoginHandler")
    @patch("src.main.SessionManager")
    @patch("src.main.DiagnosticsManager")
    @patch("src.main.load_config")
    @patch("sys.argv", ["main.py", "--from-date", "2024/01/01", "--to-date", "2024/12/31"])
    def test_authentication_error_returns_1(
        self,
        mock_load_config,
        mock_diagnostics,
        mock_session_manager,
        mock_login_handler,
        mock_renewal_api,
    ):
        """Test main returns 1 when AuthenticationError is raised."""
        from src.session_manager import AuthenticationError

        mock_load_config.return_value = _make_config()
        mock_session_instance = MagicMock()
        mock_session_manager.return_value = mock_session_instance

        mock_login_instance = MagicMock()
        mock_login_handler.return_value = mock_login_instance

        mock_api_instance = MagicMock()
        mock_api_instance.fetch_all_renewals.side_effect = AuthenticationError("Session expired")
        mock_renewal_api.return_value = mock_api_instance

        result = main()
        assert result == 1

    @patch("src.main.RenewalAPI")
    @patch("src.main.LoginHandler")
    @patch("src.main.SessionManager")
    @patch("src.main.DiagnosticsManager")
    @patch("src.main.load_config")
    @patch("sys.argv", ["main.py", "--from-date", "2024/01/01", "--to-date", "2024/12/31"])
    def test_unexpected_exception_returns_1(
        self,
        mock_load_config,
        mock_diagnostics,
        mock_session_manager,
        mock_login_handler,
        mock_renewal_api,
    ):
        """Test main returns 1 on unexpected exceptions."""
        mock_load_config.return_value = _make_config()
        mock_session_instance = MagicMock()
        mock_session_manager.return_value = mock_session_instance

        mock_login_instance = MagicMock()
        mock_login_handler.return_value = mock_login_instance

        mock_api_instance = MagicMock()
        mock_api_instance.fetch_all_renewals.side_effect = RuntimeError("Unexpected")
        mock_renewal_api.return_value = mock_api_instance

        result = main()
        assert result == 1
