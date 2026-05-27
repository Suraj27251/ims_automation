"""Database module for IMS.

Saves renewal records to MySQL using mysql-connector-python.
Creates the table if it doesn't exist.
"""

import logging
from typing import List

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Raised when database operations fail."""
    pass


class Database:
    """MySQL database handler for renewal records.

    Creates the renewals table if needed and inserts records
    using INSERT IGNORE to skip duplicates.
    """

    CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS renewals (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id VARCHAR(50),
        cust_name VARCHAR(200),
        mobile_no VARCHAR(20),
        plan_name VARCHAR(200),
        amount VARCHAR(50),
        plan_expiry_date DATETIME NULL,
        zone_name VARCHAR(100),
        fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY unique_user_expiry (user_id, plan_expiry_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """

    INSERT_SQL = """
    INSERT IGNORE INTO renewals
        (user_id, cust_name, mobile_no, plan_name, amount, plan_expiry_date, zone_name)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    """

    def __init__(self, host: str, user: str, password: str, database: str, port: int = 3306):
        self.host = host
        self.user = user
        self.password = password
        self.database = database
        self.port = port
        self._connection = None

    def connect(self) -> None:
        """Establish database connection and ensure table exists.

        Raises:
            DatabaseError: If connection fails.
        """
        # Try mysql-connector-python first, fall back to PyMySQL
        try:
            import mysql.connector
            self._driver = "mysql.connector"
        except ImportError:
            try:
                import pymysql
                self._driver = "pymysql"
            except ImportError as e:
                raise DatabaseError(
                    "No MySQL driver found. Install one of:\n"
                    "  pip install mysql-connector-python\n"
                    "  pip install PyMySQL"
                ) from e

        try:
            if self._driver == "mysql.connector":
                import mysql.connector
                self._connection = mysql.connector.connect(
                    host=self.host,
                    port=self.port,
                    user=self.user,
                    password=self.password,
                    database=self.database,
                    charset="utf8mb4",
                    autocommit=False,
                )
            else:
                import pymysql
                self._connection = pymysql.connect(
                    host=self.host,
                    port=self.port,
                    user=self.user,
                    password=self.password,
                    database=self.database,
                    charset="utf8mb4",
                    autocommit=False,
                )

            logger.info("Connected to MySQL: %s@%s:%d/%s", self.user, self.host, self.port, self.database)

            # Ensure table exists
            self._ensure_table()

        except Exception as e:
            raise DatabaseError(
                f"Failed to connect to MySQL {self.user}@{self.host}:{self.port}/{self.database}: {e}"
            ) from e

    def save_records(self, records: list) -> int:
        """Insert renewal records into the database.

        Uses INSERT IGNORE to skip records that already exist
        (based on user_id + plan_expiry_date unique key).

        Args:
            records: List of RenewalRecord objects.

        Returns:
            Number of new records inserted.

        Raises:
            DatabaseError: If insert fails.
        """
        if not records:
            logger.info("No records to save.")
            return 0

        if not self._connection:
            raise DatabaseError("Not connected to database. Call connect() first.")

        try:
            cursor = self._connection.cursor()
            inserted = 0

            for record in records:
                expiry_date = None
                if record.plan_expiry_date is not None:
                    expiry_date = record.plan_expiry_date.strftime("%Y-%m-%d %H:%M:%S")

                cursor.execute(self.INSERT_SQL, (
                    record.user_id,
                    record.cust_name,
                    record.mobile_no,
                    record.plan_name,
                    record.amount,
                    expiry_date,
                    record.zone_name,
                ))
                inserted += cursor.rowcount

            self._connection.commit()
            logger.info("Database: %d new records inserted (of %d total)", inserted, len(records))
            return inserted

        except Exception as e:
            self._connection.rollback()
            raise DatabaseError(f"Failed to insert records: {e}") from e

    def close(self) -> None:
        """Close database connection."""
        if self._connection:
            try:
                self._connection.close()
                logger.info("Database connection closed.")
            except Exception:
                pass

    def _ensure_table(self) -> None:
        """Create renewals table if it doesn't exist."""
        cursor = self._connection.cursor()
        cursor.execute(self.CREATE_TABLE_SQL)
        self._connection.commit()
        logger.debug("Ensured renewals table exists.")
