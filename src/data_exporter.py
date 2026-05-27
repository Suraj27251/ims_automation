"""
Data exporter module.

Exports RenewalRecord lists to console (JSON), CSV files, or MySQL database.
Handles serialization, file I/O, and database operations with proper error handling.
"""

import csv
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from src.config_loader import AppConfig
from src.data_parser import RenewalRecord

logger = logging.getLogger(__name__)


class ExportError(Exception):
    """Raised when export operation fails."""

    pass


class DataExporter:
    """Exports RenewalRecord data to configured targets."""

    FIELD_ORDER = [
        "UserId",
        "CustName",
        "MobileNo",
        "PlanName",
        "Amount",
        "PlanExpiryDate",
        "ZoneName",
    ]

    def __init__(self, config: AppConfig):
        """Initialize DataExporter with application configuration.

        Args:
            config: AppConfig instance containing export settings and
                    MySQL connection parameters.
        """
        self._config = config

    def _record_to_dict(self, record: RenewalRecord) -> Dict[str, Any]:
        """Convert a RenewalRecord to a dictionary with FIELD_ORDER keys.

        Handles datetime serialization by converting to ISO format string.

        Args:
            record: A RenewalRecord instance.

        Returns:
            Dictionary with keys matching FIELD_ORDER.
        """
        expiry_date = None
        if record.plan_expiry_date is not None:
            expiry_date = record.plan_expiry_date.isoformat()

        return {
            "UserId": record.user_id,
            "CustName": record.cust_name,
            "MobileNo": record.mobile_no,
            "PlanName": record.plan_name,
            "Amount": record.amount,
            "PlanExpiryDate": expiry_date,
            "ZoneName": record.zone_name,
        }

    def export_console(self, records: List[RenewalRecord]) -> None:
        """Print records as JSON with 2-space indentation to stdout.

        Empty records list outputs "[]".

        Args:
            records: List of RenewalRecord objects to export.
        """
        data = [self._record_to_dict(r) for r in records]
        output = json.dumps(data, indent=2, ensure_ascii=False)
        print(output)

    def export_csv(self, records: List[RenewalRecord], file_path: Path) -> None:
        """Write records to CSV file with header row.

        The header row uses FIELD_ORDER column names. Empty records list
        produces a header-only file.

        Args:
            records: List of RenewalRecord objects to export.
            file_path: Path where the CSV file will be written.

        Raises:
            ExportError: If file write fails due to filesystem error.
        """
        try:
            with open(file_path, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=self.FIELD_ORDER)
                writer.writeheader()

                for record in records:
                    row = self._record_to_dict(record)
                    writer.writerow(row)

            logger.info("CSV export complete: %s (%d records)", file_path, len(records))

        except OSError as e:
            raise ExportError(
                f"Failed to write CSV file '{file_path}': {e}"
            ) from e

    def export_mysql(self, records: List[RenewalRecord]) -> None:
        """Insert records into MySQL table, skipping existing UserIds.

        Uses INSERT IGNORE to skip records whose UserId already exists.
        Empty records list performs no database operations.

        Reads connection parameters from config:
            mysql_host, mysql_port, mysql_database, mysql_user, mysql_password

        Args:
            records: List of RenewalRecord objects to export.

        Raises:
            ExportError: If connection or query fails.
        """
        if not records:
            logger.info("MySQL export: no records to insert.")
            return

        try:
            import pymysql
        except ImportError as e:
            raise ExportError(
                "PyMySQL is not installed. Install it with: pip install PyMySQL"
            ) from e

        host = self._config.mysql_host
        port = self._config.mysql_port
        database = self._config.mysql_database
        user = self._config.mysql_user
        password = self._config.mysql_password

        try:
            connection = pymysql.connect(
                host=host,
                port=port,
                database=database,
                user=user,
                password=password,
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
            )
        except Exception as e:
            raise ExportError(
                f"Failed to connect to MySQL at {host}:{port}/{database} "
                f"(user: {user}): {e}"
            ) from e

        try:
            with connection:
                with connection.cursor() as cursor:
                    sql = (
                        "INSERT IGNORE INTO renewals "
                        "(user_id, cust_name, mobile_no, plan_name, "
                        "amount, plan_expiry_date, zone_name) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)"
                    )

                    for record in records:
                        expiry_date = None
                        if record.plan_expiry_date is not None:
                            expiry_date = record.plan_expiry_date.strftime(
                                "%Y-%m-%d %H:%M:%S"
                            )

                        cursor.execute(
                            sql,
                            (
                                record.user_id,
                                record.cust_name,
                                record.mobile_no,
                                record.plan_name,
                                record.amount,
                                expiry_date,
                                record.zone_name,
                            ),
                        )

                connection.commit()

            logger.info(
                "MySQL export complete: %d records processed.", len(records)
            )

        except Exception as e:
            raise ExportError(
                f"MySQL query failed on {host}:{port}/{database} "
                f"(user: {user}): {e}"
            ) from e
