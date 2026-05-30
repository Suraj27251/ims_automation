"""Database connection and table management for the renewal campaign system.

Uses mysql-connector-python with connection pooling for performance.
"""

import logging
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)

_pool = None


def get_connection_pool(config):
    """Get or create a MySQL connection pool.

    Args:
        config: Config object with MySQL credentials.

    Returns:
        mysql.connector pooled connection.
    """
    global _pool
    if _pool is not None:
        return _pool

    try:
        import mysql.connector
        from mysql.connector import pooling

        _pool = pooling.MySQLConnectionPool(
            pool_name="renewal_pool",
            pool_size=5,
            pool_reset_session=True,
            host=config.MYSQL_HOST,
            port=config.MYSQL_PORT,
            user=config.MYSQL_USER,
            password=config.MYSQL_PASSWORD,
            database=config.MYSQL_DATABASE,
            charset="utf8mb4",
            autocommit=False,
        )
        logger.info("MySQL connection pool created: %s@%s/%s",
                    config.MYSQL_USER, config.MYSQL_HOST, config.MYSQL_DATABASE)
    except Exception as e:
        logger.error("Failed to create connection pool: %s", e)
        raise

    return _pool


@contextmanager
def get_db_connection(config):
    """Context manager for database connections from the pool.

    Usage:
        with get_db_connection(config) as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT ...")
    """
    pool = get_connection_pool(config)
    conn = pool.get_connection()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_db_cursor(config, dictionary=True):
    """Context manager for database cursor with auto-commit.

    Usage:
        with get_db_cursor(config) as cursor:
            cursor.execute("SELECT ...")
            rows = cursor.fetchall()
    """
    with get_db_connection(config) as conn:
        cursor = conn.cursor(dictionary=dictionary)
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()


# ============================================================
# Table creation SQL
# ============================================================

RENEWAL_RECORDS_TABLE = """
CREATE TABLE IF NOT EXISTS renewal_records (
    id INT AUTO_INCREMENT PRIMARY KEY,
    customer_name VARCHAR(255),
    mobile VARCHAR(20),
    account_id VARCHAR(100),
    plan_name VARCHAR(255),
    expiry_date DATE,
    days_remaining INT,
    category VARCHAR(50),
    zone_name VARCHAR(100),
    amount VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_category (category),
    INDEX idx_expiry_date (expiry_date),
    INDEX idx_mobile (mobile),
    UNIQUE KEY unique_account (account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

WHATSAPP_CAMPAIGN_LOGS_TABLE = """
CREATE TABLE IF NOT EXISTS whatsapp_campaign_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    renewal_id INT,
    mobile VARCHAR(20),
    template_name VARCHAR(100),
    template_params JSON,
    status VARCHAR(50) DEFAULT 'pending',
    delivery_status VARCHAR(50) DEFAULT NULL,
    whatsapp_message_id VARCHAR(255),
    operator_name VARCHAR(255),
    error_message TEXT,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    delivered_at TIMESTAMP NULL,
    read_at TIMESTAMP NULL,
    INDEX idx_renewal_id (renewal_id),
    INDEX idx_mobile (mobile),
    INDEX idx_status (status),
    INDEX idx_delivery_status (delivery_status),
    INDEX idx_sent_at (sent_at),
    INDEX idx_template_name (template_name),
    INDEX idx_whatsapp_message_id (whatsapp_message_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

OPERATOR_ACTIONS_TABLE = """
CREATE TABLE IF NOT EXISTS operator_actions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    operator_name VARCHAR(255),
    action_type VARCHAR(100),
    target_id INT,
    details JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_operator (operator_name),
    INDEX idx_action_type (action_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def init_tables(config):
    """Create all required tables if they don't exist."""
    with get_db_cursor(config, dictionary=False) as cursor:
        cursor.execute(RENEWAL_RECORDS_TABLE)
        cursor.execute(WHATSAPP_CAMPAIGN_LOGS_TABLE)
        cursor.execute(OPERATOR_ACTIONS_TABLE)

        # Normalize collation across all tables to avoid mismatch errors
        tables = ["renewal_records", "whatsapp_campaign_logs", "operator_actions"]
        for table in tables:
            try:
                cursor.execute(f"""
                    ALTER TABLE {table}
                    CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci
                """)
            except Exception:
                pass  # Table might not exist yet or already correct

        # Add delivery_status column if table already exists without it
        try:
            cursor.execute("""
                ALTER TABLE whatsapp_campaign_logs
                ADD COLUMN IF NOT EXISTS delivery_status VARCHAR(50) DEFAULT NULL,
                ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMP NULL,
                ADD COLUMN IF NOT EXISTS read_at TIMESTAMP NULL
            """)
        except Exception:
            pass  # Column already exists or MySQL version doesn't support IF NOT EXISTS

        # Add index on whatsapp_message_id if not exists
        try:
            cursor.execute("""
                ALTER TABLE whatsapp_campaign_logs
                ADD INDEX idx_whatsapp_message_id (whatsapp_message_id)
            """)
        except Exception:
            pass  # Index already exists

        logger.info("All renewal campaign tables initialized.")
