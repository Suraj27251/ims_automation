"""Unit tests for data_exporter module."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config_loader import AppConfig
from src.data_exporter import DataExporter, ExportError
from src.data_parser import RenewalRecord


@pytest.fixture
def mock_config():
    """Create a minimal AppConfig for DataExporter tests."""
    return AppConfig(
        login_url="https://example.com/login",
        username="testuser",
        password="testpass",
        mysql_enabled=True,
        mysql_host="localhost",
        mysql_port=3306,
        mysql_database="testdb",
        mysql_user="dbuser",
        mysql_password="dbpass",
    )


@pytest.fixture
def exporter(mock_config):
    """Create a DataExporter instance with mock config."""
    return DataExporter(mock_config)


@pytest.fixture
def sample_records():
    """Create sample RenewalRecord instances for testing."""
    return [
        RenewalRecord(
            user_id="1001",
            cust_name="Alice Smith",
            mobile_no="9876543210",
            plan_name="Premium 100Mbps",
            amount="999",
            plan_expiry_date=datetime(2024, 6, 15, 0, 0, 0, tzinfo=timezone.utc),
            zone_name="Zone-A",
        ),
        RenewalRecord(
            user_id="1002",
            cust_name="Bob Jones",
            mobile_no="9123456789",
            plan_name="Basic 50Mbps",
            amount="499",
            plan_expiry_date=datetime(2024, 7, 20, 12, 30, 0, tzinfo=timezone.utc),
            zone_name="Zone-B",
        ),
    ]


class TestConsoleExport:
    """Tests for export_console method."""

    def test_console_export_valid_json_with_2_space_indent(self, exporter, sample_records, capsys):
        """Console export outputs valid JSON with 2-space indentation."""
        exporter.export_console(sample_records)

        captured = capsys.readouterr()
        output = captured.out.strip()

        # Must be valid JSON
        parsed = json.loads(output)
        assert isinstance(parsed, list)
        assert len(parsed) == 2

        # Verify 2-space indentation by checking the raw output format
        lines = output.split("\n")
        # Second line should start with 2 spaces (first element of array)
        assert lines[1].startswith("  {")

        # Verify field values
        assert parsed[0]["UserId"] == "1001"
        assert parsed[0]["CustName"] == "Alice Smith"
        assert parsed[1]["UserId"] == "1002"

    def test_console_export_empty_records(self, exporter, capsys):
        """Empty records list outputs '[]' as valid JSON."""
        exporter.export_console([])

        captured = capsys.readouterr()
        output = captured.out.strip()

        parsed = json.loads(output)
        assert parsed == []

    def test_console_export_none_fields_as_null(self, exporter, capsys):
        """Records with None fields serialize as JSON null."""
        records = [RenewalRecord(user_id="2001")]
        exporter.export_console(records)

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)

        assert parsed[0]["UserId"] == "2001"
        assert parsed[0]["CustName"] is None
        assert parsed[0]["PlanExpiryDate"] is None


class TestCsvExport:
    """Tests for export_csv method."""

    def test_csv_header_row_and_field_order(self, exporter, sample_records, tmp_path):
        """CSV export has header row with correct field order."""
        csv_file = tmp_path / "output.csv"
        exporter.export_csv(sample_records, csv_file)

        content = csv_file.read_text(encoding="utf-8")
        lines = content.strip().split("\n")

        # Header row must match FIELD_ORDER
        expected_header = "UserId,CustName,MobileNo,PlanName,Amount,PlanExpiryDate,ZoneName"
        assert lines[0] == expected_header

        # Should have header + 2 data rows
        assert len(lines) == 3

        # Verify first data row values
        fields = lines[1].split(",")
        assert fields[0] == "1001"
        assert fields[1] == "Alice Smith"
        assert fields[2] == "9876543210"
        assert fields[3] == "Premium 100Mbps"
        assert fields[4] == "999"
        assert fields[6] == "Zone-A"

    def test_csv_empty_records_header_only(self, exporter, tmp_path):
        """Empty records list produces a CSV file with only the header row."""
        csv_file = tmp_path / "empty.csv"
        exporter.export_csv([], csv_file)

        content = csv_file.read_text(encoding="utf-8")
        lines = [line for line in content.split("\n") if line.strip()]

        assert len(lines) == 1
        expected_header = "UserId,CustName,MobileNo,PlanName,Amount,PlanExpiryDate,ZoneName"
        assert lines[0] == expected_header

    def test_csv_export_error_on_write_failure(self, exporter, sample_records):
        """ExportError raised when file write fails due to filesystem error."""
        # Use a path that cannot be written to (non-existent directory)
        bad_path = Path("/nonexistent_dir_xyz/impossible/output.csv")

        with pytest.raises(ExportError) as exc_info:
            exporter.export_csv(sample_records, bad_path)

        assert str(bad_path) in str(exc_info.value)


class TestMysqlExport:
    """Tests for export_mysql method."""

    def test_mysql_export_skips_existing_user_ids(self, exporter, sample_records):
        """MySQL export uses INSERT IGNORE to skip existing UserIds."""
        mock_pymysql = MagicMock()
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_pymysql.connect.return_value = mock_connection
        mock_pymysql.cursors.DictCursor = "DictCursor"
        mock_connection.__enter__ = MagicMock(return_value=mock_connection)
        mock_connection.__exit__ = MagicMock(return_value=False)
        mock_cursor_ctx = MagicMock()
        mock_connection.cursor.return_value = mock_cursor_ctx
        mock_cursor_ctx.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor_ctx.__exit__ = MagicMock(return_value=False)

        with patch.dict("sys.modules", {"pymysql": mock_pymysql, "pymysql.cursors": mock_pymysql.cursors}):
            exporter.export_mysql(sample_records)

        # Verify INSERT IGNORE is used (skips existing UserIds)
        calls = mock_cursor.execute.call_args_list
        assert len(calls) == 2
        for call in calls:
            sql = call[0][0]
            assert "INSERT IGNORE" in sql

        # Verify commit was called
        mock_connection.commit.assert_called_once()

    def test_mysql_export_empty_records_no_operations(self, exporter):
        """Empty records list performs no database operations."""
        mock_pymysql = MagicMock()

        with patch.dict("sys.modules", {"pymysql": mock_pymysql, "pymysql.cursors": mock_pymysql.cursors}):
            exporter.export_mysql([])

        # pymysql.connect should not be called for empty records
        mock_pymysql.connect.assert_not_called()

    def test_mysql_export_connection_failure_raises_export_error(self, exporter, sample_records):
        """ExportError raised on MySQL connection failure."""
        mock_pymysql = MagicMock()
        mock_pymysql.connect.side_effect = Exception("Connection refused")
        mock_pymysql.cursors.DictCursor = "DictCursor"

        with pytest.raises(ExportError) as exc_info:
            with patch.dict("sys.modules", {"pymysql": mock_pymysql, "pymysql.cursors": mock_pymysql.cursors}):
                exporter.export_mysql(sample_records)

        error_msg = str(exc_info.value)
        assert "localhost" in error_msg
        assert "3306" in error_msg
        assert "testdb" in error_msg
        assert "dbuser" in error_msg
        # Password should NOT be in the error message
        assert "dbpass" not in error_msg
