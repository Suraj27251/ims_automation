"""Customer database repository.

Handles all MySQL operations for the customers table:
- Table creation/migration
- Upsert (insert or update)
- Category/days_remaining calculation
- Bulk sync operations
"""

import logging
from datetime import date, datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class CustomerRepositoryError(Exception):
    """Raised when database operations fail."""
    pass


CREATE_CUSTOMERS_TABLE = """
CREATE TABLE IF NOT EXISTS customers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL,
    customer_name VARCHAR(255),
    mobile VARCHAR(20),
    plan_name VARCHAR(255),
    plan_category VARCHAR(100),
    validity VARCHAR(100),
    status VARCHAR(50),
    activation_date DATE NULL,
    expiry_date DATE NULL,
    data_reset_date DATE NULL,
    reg_date DATE NULL,
    zone_name VARCHAR(100),
    area VARCHAR(200),
    building VARCHAR(200),
    flat_no VARCHAR(100),
    address TEXT,
    network_type VARCHAR(100),
    connectivity_mode VARCHAR(100),
    mac VARCHAR(100),
    mac_free VARCHAR(100),
    onu_no VARCHAR(100),
    static_ip VARCHAR(50),
    radius_password VARCHAR(255),
    email VARCHAR(255),
    company_name VARCHAR(255),
    owner_tenant VARCHAR(100),
    payment_id VARCHAR(100),
    created_by VARCHAR(255),
    adv_renew VARCHAR(100),
    kyc_approved VARCHAR(50),
    roaming VARCHAR(50),
    password_plain VARCHAR(255),
    id_no VARCHAR(100),
    category VARCHAR(50),
    days_remaining INT,
    last_synced_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_user_id (user_id),
    INDEX idx_category (category),
    INDEX idx_expiry_date (expiry_date),
    INDEX idx_status (status),
    INDEX idx_zone_name (zone_name),
    INDEX idx_mobile (mobile),
    INDEX idx_plan_name (plan_name),
    INDEX idx_network_type (network_type),
    INDEX idx_kyc_approved (kyc_approved)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


UPSERT_CUSTOMER_SQL = """
INSERT INTO customers (
    user_id, customer_name, mobile, plan_name, plan_category,
    validity, status, activation_date, expiry_date, data_reset_date,
    reg_date, zone_name, area, building, flat_no, address,
    network_type, connectivity_mode, mac, mac_free, onu_no,
    static_ip, radius_password, email, company_name, owner_tenant,
    payment_id, created_by, adv_renew, kyc_approved, roaming,
    password_plain, id_no, category, days_remaining, last_synced_at
) VALUES (
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s
) ON DUPLICATE KEY UPDATE
    customer_name = VALUES(customer_name),
    mobile = VALUES(mobile),
    plan_name = VALUES(plan_name),
    plan_category = VALUES(plan_category),
    validity = VALUES(validity),
    status = VALUES(status),
    activation_date = VALUES(activation_date),
    expiry_date = VALUES(expiry_date),
    data_reset_date = VALUES(data_reset_date),
    reg_date = VALUES(reg_date),
    zone_name = VALUES(zone_name),
    area = VALUES(area),
    building = VALUES(building),
    flat_no = VALUES(flat_no),
    address = VALUES(address),
    network_type = VALUES(network_type),
    connectivity_mode = VALUES(connectivity_mode),
    mac = VALUES(mac),
    mac_free = VALUES(mac_free),
    onu_no = VALUES(onu_no),
    static_ip = VALUES(static_ip),
    radius_password = VALUES(radius_password),
    email = VALUES(email),
    company_name = VALUES(company_name),
    owner_tenant = VALUES(owner_tenant),
    payment_id = VALUES(payment_id),
    created_by = VALUES(created_by),
    adv_renew = VALUES(adv_renew),
    kyc_approved = VALUES(kyc_approved),
    roaming = VALUES(roaming),
    password_plain = VALUES(password_plain),
    id_no = VALUES(id_no),
    category = VALUES(category),
    days_remaining = VALUES(days_remaining),
    last_synced_at = VALUES(last_synced_at),
    updated_at = CURRENT_TIMESTAMP
"""


class CustomerRepository:
    """MySQL repository for customer records.

    Handles table creation, upserts, and category classification.
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
            CustomerRepositoryError: If connection fails.
        """
        try:
            import mysql.connector
            self._driver = "mysql.connector"
        except ImportError:
            try:
                import pymysql
                self._driver = "pymysql"
            except ImportError as e:
                raise CustomerRepositoryError(
                    "No MySQL driver found. Install mysql-connector-python or PyMySQL."
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

            logger.info("Connected to MySQL: %s@%s:%d/%s",
                        self.user, self.host, self.port, self.database)
            self._ensure_table()

        except CustomerRepositoryError:
            raise
        except Exception as e:
            raise CustomerRepositoryError(
                f"Failed to connect to MySQL {self.user}@{self.host}:{self.port}/{self.database}: {e}"
            ) from e

    def _ensure_table(self) -> None:
        """Create customers table if it doesn't exist."""
        cursor = self._connection.cursor()
        cursor.execute(CREATE_CUSTOMERS_TABLE)
        self._connection.commit()
        cursor.close()
        logger.info("Ensured customers table exists.")

    def sync_records(self, records: list) -> Dict[str, int]:
        """Sync a list of CustomerRecord objects to the database.

        Uses INSERT ... ON DUPLICATE KEY UPDATE for atomic upserts.
        Calculates category and days_remaining for each record.

        Args:
            records: List of CustomerRecord objects from the fetcher.

        Returns:
            Dict with sync stats: inserted, updated, unchanged, total.

        Raises:
            CustomerRepositoryError: If database operation fails.
        """
        if not records:
            logger.info("No records to sync.")
            return {"inserted": 0, "updated": 0, "unchanged": 0, "total": 0}

        if not self._connection:
            raise CustomerRepositoryError("Not connected. Call connect() first.")

        stats = {"inserted": 0, "updated": 0, "unchanged": 0, "total": len(records)}
        now = datetime.now()
        today = date.today()

        try:
            cursor = self._connection.cursor()

            for record in records:
                if not record.user_id:
                    continue

                # Calculate category and days_remaining
                category, days_remaining = self._classify(record.expiry_date, today)

                # Convert dates to MySQL format
                activation_date = self._to_date(record.activation_date)
                expiry_date = self._to_date(record.expiry_date)
                data_reset_date = self._to_date(record.data_reset_date)
                reg_date = self._to_date(record.reg_date)

                params = (
                    record.user_id, record.customer_name, record.mobile,
                    record.plan_name, record.plan_category, record.validity,
                    record.status, activation_date, expiry_date,
                    data_reset_date, reg_date, record.zone_name,
                    record.area, record.building, record.flat_no, record.address,
                    record.network_type, record.connectivity_mode,
                    record.mac, record.mac_free, record.onu_no,
                    record.static_ip, record.radius_password, record.email,
                    record.company_name, record.owner_tenant, record.payment_id,
                    record.created_by, record.adv_renew, record.kyc_approved,
                    record.roaming, record.password_plain, record.id_no,
                    category, days_remaining, now,
                )

                cursor.execute(UPSERT_CUSTOMER_SQL, params)

                # rowcount: 1 = inserted, 2 = updated, 0 = unchanged
                if cursor.rowcount == 1:
                    stats["inserted"] += 1
                elif cursor.rowcount == 2:
                    stats["updated"] += 1
                else:
                    stats["unchanged"] += 1

            self._connection.commit()
            cursor.close()

            logger.info(
                "Sync complete: %d inserted, %d updated, %d unchanged (of %d total)",
                stats["inserted"], stats["updated"], stats["unchanged"], stats["total"]
            )
            return stats

        except Exception as e:
            self._connection.rollback()
            raise CustomerRepositoryError(f"Failed to sync records: {e}") from e

    def reclassify_all(self) -> Dict[str, int]:
        """Recalculate category and days_remaining for all customers.

        Useful for daily cron to update classifications without re-fetching.

        Returns:
            Dict with category counts.
        """
        if not self._connection:
            raise CustomerRepositoryError("Not connected. Call connect() first.")

        today = date.today()
        stats = {"expired": 0, "today": 0, "upcoming": 0, "unknown": 0}

        try:
            cursor = self._connection.cursor(dictionary=True) if self._driver == "mysql.connector" else self._connection.cursor()

            # Fetch all records with expiry dates
            cursor.execute("SELECT id, expiry_date FROM customers")
            rows = cursor.fetchall()

            for row in rows:
                if self._driver == "mysql.connector":
                    record_id = row["id"]
                    expiry = row["expiry_date"]
                else:
                    record_id = row[0]
                    expiry = row[1]

                category, days_remaining = self._classify(expiry, today)
                stats[category] = stats.get(category, 0) + 1

                cursor.execute(
                    "UPDATE customers SET category = %s, days_remaining = %s WHERE id = %s",
                    (category, days_remaining, record_id)
                )

            self._connection.commit()
            cursor.close()

            logger.info("Reclassification complete: %s", stats)
            return stats

        except Exception as e:
            self._connection.rollback()
            raise CustomerRepositoryError(f"Reclassification failed: {e}") from e

    def close(self) -> None:
        """Close database connection."""
        if self._connection:
            try:
                self._connection.close()
                logger.info("Database connection closed.")
            except Exception:
                pass

    @staticmethod
    def _classify(expiry_date, today: date) -> tuple:
        """Classify a customer based on expiry date.

        Returns:
            Tuple of (category, days_remaining).
        """
        if expiry_date is None:
            return "unknown", None

        if isinstance(expiry_date, datetime):
            expiry = expiry_date.date()
        elif isinstance(expiry_date, date):
            expiry = expiry_date
        elif isinstance(expiry_date, str):
            try:
                expiry = datetime.strptime(str(expiry_date)[:10], "%Y-%m-%d").date()
            except ValueError:
                return "unknown", None
        else:
            return "unknown", None

        days_remaining = (expiry - today).days

        if days_remaining < 0:
            return "expired", days_remaining
        elif days_remaining == 0:
            return "today", 0
        else:
            return "upcoming", days_remaining

    @staticmethod
    def _to_date(dt_value) -> Optional[str]:
        """Convert a datetime/date to MySQL date string."""
        if dt_value is None:
            return None
        if isinstance(dt_value, datetime):
            return dt_value.strftime("%Y-%m-%d")
        if isinstance(dt_value, date):
            return dt_value.strftime("%Y-%m-%d")
        return None
