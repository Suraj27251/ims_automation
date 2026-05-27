"""Integration tests for MySQL export functionality.

Tests the DataExporter.export_mysql() method with mocked PyMySQL to verify:
- INSERT IGNORE SQL is used (skips existing UserIds)
- Correct number of execute calls for records
- Commit is called after inserts
- Duplicate UserId handling via INSERT IGNORE behavior
- ExportError raised on connection failure

Uses patch.dict("sys.modules", ...) to mock pymysql since it's imported
locally inside export_mysql().

Requirements: 11.3, 11.5
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from src.config_loader import AppConfig
from src.data_exporter import DataExporter, ExportError
from src.data_parser import RenewalRecord


@pytest.fixture
def mysql_config():
    """Create an AppConfig with MySQL enabled."""
    return AppConfig(
        login_url="https://admin.example.com/login",
        username="operator",
        password="secret123",
        mysql_enabled=True,
        mysql_host="db.example.com",
        mysql_port=3306,
        mysql_database="ims_renewals",
        mysql_user="ims_writer",
        mysql_password="db_secret",
    )


@pytest.fixture
def exporter(mysql_config):
    """Create a DataExporter with MySQL-enabled config."""
    return DataExporter(mysql_config)


@pytest.fixture
def sample_records():
    """Create sample RenewalRecord objects for testing."""
    return [
        RenewalRecord(
            user_id="1001",
            cust_name="Alice Smith",
            mobile_no="9876543210",
            plan_name="Premium 100Mbps",
            amount="999",
            plan_expiry_date=datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc),
            zone_name="Zone-A",
        ),
        RenewalRecord(
            user_id="1002",
            cust_name="Bob Jones",
            mobile_no="9123456789",
            plan_name="Basic 50Mbps",
            amount="499",
            plan_expiry_date=datetime(2024, 7, 20, 14, 0, 0, tzinfo=timezone.utc),
            zone_name="Zone-B",
        ),
        RenewalRecord(
            user_id="1003",
            cust_name="Charlie Brown",
            mobile_no="9555123456",
            plan_name="Ultra 200Mbps",
            amount="1499",
            plan_expiry_date=None,
            zone_name="Zone-C",
        ),
    ]


@pytest.fixture
def mock_pymysql():
    """Create a fully configured mock pymysql module with connection and cursor."""
    mock_module = MagicMock()
    mock_connection = MagicMock()
    mock_cursor = MagicMock()

    # Configure pymysql.connect to return mock connection
    mock_module.connect.return_value = mock_connection
    mock_module.cursors.DictCursor = "DictCursor"

    # Configure connection context manager
    mock_connection.__enter__ = MagicMock(return_value=mock_connection)
    mock_connection.__exit__ = MagicMock(return_value=False)

    # Configure cursor context manager
    mock_cursor_ctx = MagicMock()
    mock_connection.cursor.return_value = mock_cursor_ctx
    mock_cursor_ctx.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor_ctx.__exit__ = MagicMock(return_value=False)

    return {
        "module": mock_module,
        "connection": mock_connection,
        "cursor": mock_cursor,
    }


class TestMySQLExportIntegration:
    """Integration tests for MySQL export with mocked PyMySQL."""

    def test_export_mysql_uses_insert_ignore(self, exporter, sample_records, mock_pymysql):
        """Verify INSERT IGNORE SQL is used to skip existing UserIds.

        Requirements: 11.3 - skipping records whose UserId already exists.
        """
        with patch.dict(
            "sys.modules",
            {
                "pymysql": mock_pymysql["module"],
                "pymysql.cursors": mock_pymysql["module"].cursors,
            },
        ):
            exporter.export_mysql(sample_records)

        # Every execute call should use INSERT IGNORE
        cursor = mock_pymysql["cursor"]
        for execute_call in cursor.execute.call_args_list:
            sql = execute_call[0][0]
            assert "INSERT IGNORE" in sql, (
                f"Expected INSERT IGNORE in SQL, got: {sql}"
            )

    def test_export_mysql_correct_number_of_execute_calls(
        self, exporter, sample_records, mock_pymysql
    ):
        """Verify one execute call per record.

        Requirements: 11.3 - insert all RenewalRecords.
        """
        with patch.dict(
            "sys.modules",
            {
                "pymysql": mock_pymysql["module"],
                "pymysql.cursors": mock_pymysql["module"].cursors,
            },
        ):
            exporter.export_mysql(sample_records)

        cursor = mock_pymysql["cursor"]
        assert cursor.execute.call_count == len(sample_records)

    def test_export_mysql_commit_called(self, exporter, sample_records, mock_pymysql):
        """Verify commit is called after all inserts.

        Requirements: 11.3 - records are persisted to database.
        """
        with patch.dict(
            "sys.modules",
            {
                "pymysql": mock_pymysql["module"],
                "pymysql.cursors": mock_pymysql["module"].cursors,
            },
        ):
            exporter.export_mysql(sample_records)

        mock_pymysql["connection"].commit.assert_called_once()

    def test_export_mysql_correct_values_passed(
        self, exporter, sample_records, mock_pymysql
    ):
        """Verify correct record values are passed to execute.

        Requirements: 11.3 - insert all RenewalRecords into configured table.
        """
        with patch.dict(
            "sys.modules",
            {
                "pymysql": mock_pymysql["module"],
                "pymysql.cursors": mock_pymysql["module"].cursors,
            },
        ):
            exporter.export_mysql(sample_records)

        cursor = mock_pymysql["cursor"]
        calls = cursor.execute.call_args_list

        # First record: Alice Smith with datetime
        _, params_1 = calls[0][0]
        assert params_1[0] == "1001"
        assert params_1[1] == "Alice Smith"
        assert params_1[2] == "9876543210"
        assert params_1[3] == "Premium 100Mbps"
        assert params_1[4] == "999"
        assert params_1[5] == "2024-06-15 10:30:00"
        assert params_1[6] == "Zone-A"

        # Second record: Bob Jones
        _, params_2 = calls[1][0]
        assert params_2[0] == "1002"
        assert params_2[1] == "Bob Jones"

        # Third record: Charlie Brown with None expiry date
        _, params_3 = calls[2][0]
        assert params_3[0] == "1003"
        assert params_3[1] == "Charlie Brown"
        assert params_3[5] is None  # plan_expiry_date is None

    def test_export_mysql_connection_params_from_config(
        self, exporter, sample_records, mock_pymysql
    ):
        """Verify connection uses parameters from AppConfig.

        Requirements: 11.6 - read MySQL connection parameters from config.
        """
        with patch.dict(
            "sys.modules",
            {
                "pymysql": mock_pymysql["module"],
                "pymysql.cursors": mock_pymysql["module"].cursors,
            },
        ):
            exporter.export_mysql(sample_records)

        connect_call = mock_pymysql["module"].connect.call_args
        assert connect_call.kwargs["host"] == "db.example.com"
        assert connect_call.kwargs["port"] == 3306
        assert connect_call.kwargs["database"] == "ims_renewals"
        assert connect_call.kwargs["user"] == "ims_writer"
        assert connect_call.kwargs["password"] == "db_secret"


class TestMySQLDuplicateHandling:
    """Tests for duplicate UserId handling via INSERT IGNORE.

    Requirements: 11.3, 11.5 - skip records whose UserId already exists.
    """

    def test_duplicate_user_ids_all_sent_with_insert_ignore(
        self, exporter, mock_pymysql
    ):
        """When records contain duplicate UserIds, all are sent with INSERT IGNORE.

        The database handles deduplication via the UNIQUE constraint on user_id.
        INSERT IGNORE silently skips duplicates without raising errors.
        """
        records_with_duplicates = [
            RenewalRecord(
                user_id="2001",
                cust_name="First Entry",
                mobile_no="1111111111",
                plan_name="Plan A",
                amount="100",
                plan_expiry_date=datetime(2024, 3, 1, 0, 0, 0, tzinfo=timezone.utc),
                zone_name="Zone-X",
            ),
            RenewalRecord(
                user_id="2001",  # Duplicate UserId
                cust_name="Duplicate Entry",
                mobile_no="2222222222",
                plan_name="Plan B",
                amount="200",
                plan_expiry_date=datetime(2024, 4, 1, 0, 0, 0, tzinfo=timezone.utc),
                zone_name="Zone-Y",
            ),
            RenewalRecord(
                user_id="2002",
                cust_name="Unique Entry",
                mobile_no="3333333333",
                plan_name="Plan C",
                amount="300",
                plan_expiry_date=datetime(2024, 5, 1, 0, 0, 0, tzinfo=timezone.utc),
                zone_name="Zone-Z",
            ),
        ]

        with patch.dict(
            "sys.modules",
            {
                "pymysql": mock_pymysql["module"],
                "pymysql.cursors": mock_pymysql["module"].cursors,
            },
        ):
            exporter.export_mysql(records_with_duplicates)

        cursor = mock_pymysql["cursor"]

        # All 3 records are sent to the database (INSERT IGNORE handles dedup)
        assert cursor.execute.call_count == 3

        # All use INSERT IGNORE
        for execute_call in cursor.execute.call_args_list:
            sql = execute_call[0][0]
            assert "INSERT IGNORE" in sql

        # Verify the duplicate UserId was sent
        _, params_1 = cursor.execute.call_args_list[0][0]
        _, params_2 = cursor.execute.call_args_list[1][0]
        assert params_1[0] == "2001"
        assert params_2[0] == "2001"  # Same UserId, DB will skip via UNIQUE constraint

    def test_insert_ignore_does_not_raise_on_existing_records(
        self, exporter, mock_pymysql
    ):
        """INSERT IGNORE means no error is raised even if UserId exists in DB.

        The database silently ignores the duplicate insert rather than
        raising an IntegrityError.
        """
        records = [
            RenewalRecord(
                user_id="3001",
                cust_name="Existing User",
                mobile_no="4444444444",
                plan_name="Plan D",
                amount="400",
                plan_expiry_date=datetime(2024, 8, 1, 0, 0, 0, tzinfo=timezone.utc),
                zone_name="Zone-W",
            ),
        ]

        with patch.dict(
            "sys.modules",
            {
                "pymysql": mock_pymysql["module"],
                "pymysql.cursors": mock_pymysql["module"].cursors,
            },
        ):
            # Should not raise even though the record "already exists"
            # (INSERT IGNORE handles this at the DB level)
            exporter.export_mysql(records)

        # Verify the operation completed successfully
        mock_pymysql["connection"].commit.assert_called_once()


class TestMySQLExportErrors:
    """Tests for error handling in MySQL export.

    Requirements: 11.5 - raise error with connection details on failure.
    """

    def test_connection_failure_raises_export_error(self, exporter, sample_records):
        """ExportError raised when pymysql.connect fails.

        Requirements: 11.5 - error includes connection details (excluding password).
        """
        mock_module = MagicMock()
        mock_module.connect.side_effect = Exception(
            "Can't connect to MySQL server on 'db.example.com' (111)"
        )
        mock_module.cursors.DictCursor = "DictCursor"

        with pytest.raises(ExportError) as exc_info:
            with patch.dict(
                "sys.modules",
                {
                    "pymysql": mock_module,
                    "pymysql.cursors": mock_module.cursors,
                },
            ):
                exporter.export_mysql(sample_records)

        error_msg = str(exc_info.value)
        # Error should include connection details
        assert "db.example.com" in error_msg
        assert "3306" in error_msg
        assert "ims_renewals" in error_msg
        assert "ims_writer" in error_msg
        # Password should NOT be in the error message
        assert "db_secret" not in error_msg

    def test_query_failure_raises_export_error(self, exporter, sample_records):
        """ExportError raised when cursor.execute fails during insert.

        Requirements: 11.5 - error includes connection details on query error.
        """
        mock_module = MagicMock()
        mock_connection = MagicMock()
        mock_cursor = MagicMock()

        mock_module.connect.return_value = mock_connection
        mock_module.cursors.DictCursor = "DictCursor"
        mock_connection.__enter__ = MagicMock(return_value=mock_connection)
        mock_connection.__exit__ = MagicMock(return_value=False)

        mock_cursor_ctx = MagicMock()
        mock_connection.cursor.return_value = mock_cursor_ctx
        mock_cursor_ctx.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor_ctx.__exit__ = MagicMock(return_value=False)

        # Simulate query failure
        mock_cursor.execute.side_effect = Exception(
            "Table 'ims_renewals.renewals' doesn't exist"
        )

        with pytest.raises(ExportError) as exc_info:
            with patch.dict(
                "sys.modules",
                {
                    "pymysql": mock_module,
                    "pymysql.cursors": mock_module.cursors,
                },
            ):
                exporter.export_mysql(sample_records)

        error_msg = str(exc_info.value)
        assert "db.example.com" in error_msg
        assert "ims_renewals" in error_msg

    def test_empty_records_no_connection_attempt(self, exporter):
        """Empty records list does not attempt database connection.

        Requirements: 11.7 - no database inserts for empty list.
        """
        mock_module = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "pymysql": mock_module,
                "pymysql.cursors": mock_module.cursors,
            },
        ):
            exporter.export_mysql([])

        # No connection should be attempted for empty records
        mock_module.connect.assert_not_called()
