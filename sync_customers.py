"""Standalone script to sync ALL customer data from IMS.

Performs a full customer sync:
1. Login to IMS
2. Open customer listing page
3. Fetch all customer records via DataTables AJAX
4. Upsert into local MySQL customers table
5. Calculate category/days_remaining for each record

Usage:
    python sync_customers.py
    python sync_customers.py --page-size 200
    python sync_customers.py --debug
    python sync_customers.py --reclassify-only

Cron:
    /bin/bash /home/countrylinks/public_html/ims_automation/cron_customer_sync.sh
"""

import argparse
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(override=False)

logger = logging.getLogger(__name__)


def setup_logging(debug: bool = False) -> None:
    """Configure logging to console + file."""
    level = logging.DEBUG if debug else logging.INFO
    fmt = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    # Console
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(logging.Formatter(fmt))
    root.addHandler(console)

    # File
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    file_handler = RotatingFileHandler(
        log_dir / "customer_sync.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(fmt))
    root.addHandler(file_handler)

    # Error file
    error_handler = RotatingFileHandler(
        log_dir / "customer_sync_errors.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(logging.Formatter(fmt))
    root.addHandler(error_handler)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="IMS Full Customer Sync Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--page-size", type=int, default=100,
                        help="Records per page (default: 100)")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug logging")
    parser.add_argument("--reclassify-only", action="store_true",
                        help="Only reclassify existing records (skip IMS fetch)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch but don't save to database")
    return parser.parse_args()


def load_env() -> dict:
    """Load environment variables."""
    required = {
        "IMS_BASE_URL": (
            os.environ.get("IMS_BASE_URL")
            or os.environ.get("IMS_LOGIN_URL", "").rsplit("/", 1)[0]
        ),
        "IMS_USERNAME": os.environ.get("IMS_USERNAME"),
        "IMS_PASSWORD": os.environ.get("IMS_PASSWORD"),
    }

    missing = [k for k, v in required.items() if not v]
    if missing:
        logger.error("Missing environment variables: %s", ", ".join(missing))
        sys.exit(1)

    mysql_config = {
        "MYSQL_HOST": (
            os.environ.get("DB_HOST")
            or os.environ.get("MYSQL_HOST")
            or os.environ.get("IMS_MYSQL_HOST")
            or "localhost"
        ),
        "MYSQL_USER": (
            os.environ.get("DB_USER")
            or os.environ.get("MYSQL_USER")
            or os.environ.get("IMS_MYSQL_USER")
            or ""
        ),
        "MYSQL_PASSWORD": (
            os.environ.get("DB_PASSWORD")
            or os.environ.get("MYSQL_PASSWORD")
            or os.environ.get("IMS_MYSQL_PASSWORD")
            or ""
        ),
        "MYSQL_DATABASE": (
            os.environ.get("DB_NAME")
            or os.environ.get("MYSQL_DATABASE")
            or os.environ.get("IMS_MYSQL_DB")
            or "countrylinks_user_database"
        ),
        "MYSQL_PORT": int(
            os.environ.get("DB_PORT")
            or os.environ.get("MYSQL_PORT")
            or os.environ.get("IMS_MYSQL_PORT")
            or "3306"
        ),
    }

    return {**required, **mysql_config}


def main() -> int:
    """Main sync flow."""
    args = parse_args()
    setup_logging(debug=args.debug)

    logger.info("=" * 60)
    logger.info("IMS Full Customer Sync Engine starting")
    logger.info("=" * 60)

    env = load_env()

    # Import repository
    from src.customer_repository import CustomerRepository, CustomerRepositoryError

    # Connect to database
    repo = CustomerRepository(
        host=env["MYSQL_HOST"],
        user=env["MYSQL_USER"],
        password=env["MYSQL_PASSWORD"],
        database=env["MYSQL_DATABASE"],
        port=env["MYSQL_PORT"],
    )

    try:
        repo.connect()
    except CustomerRepositoryError as e:
        logger.error("Database connection failed: %s", e)
        return 1

    try:
        # Reclassify-only mode: just update categories without fetching
        if args.reclassify_only:
            logger.info("Reclassify-only mode: updating categories...")
            stats = repo.reclassify_all()
            logger.info("Reclassification done: %s", stats)
            return 0

        # --- Step 1: Login to IMS ---
        logger.info("Step 1: Logging in to IMS...")
        from src.auth import IMSAuth, AuthError

        auth = IMSAuth(
            base_url=env["IMS_BASE_URL"],
            username=env["IMS_USERNAME"],
            password=env["IMS_PASSWORD"],
        )

        try:
            auth.login()
        except AuthError as e:
            logger.error("Authentication failed: %s", e)
            return 1

        logger.info("Login successful.")

        # --- Step 2: Open customer page ---
        logger.info("Step 2: Opening customer listing page...")
        from src.customer_fetcher import CustomerFetcher, CustomerFetchError

        fetcher = CustomerFetcher(
            session=auth.session,
            base_url=env["IMS_BASE_URL"],
            page_size=args.page_size,
        )

        try:
            fetcher.open_customer_page()
        except CustomerFetchError as e:
            logger.error("Failed to open customer page: %s", e)
            return 1

        # --- Step 3: Fetch all customers ---
        logger.info("Step 3: Fetching all customer records...")
        try:
            records = fetcher.fetch_all()
        except CustomerFetchError as e:
            logger.error("Customer fetch failed: %s", e)
            return 1

        if not records:
            logger.warning("No customer records fetched from IMS.")
            return 0

        logger.info("Fetched %d customer records from IMS.", len(records))

        # --- Step 4: Dry run check ---
        if args.dry_run:
            logger.info("Dry run mode - not saving to database.")
            for r in records[:10]:
                logger.info("  %s | %s | %s | %s | %s",
                            r.user_id, r.customer_name, r.mobile, r.plan_name, r.status)
            if len(records) > 10:
                logger.info("  ... and %d more records", len(records) - 10)
            return 0

        # --- Step 5: Sync to database ---
        logger.info("Step 4: Syncing to MySQL database...")
        sync_stats = repo.sync_records(records)

        logger.info("=" * 60)
        logger.info("SYNC COMPLETE")
        logger.info("  Total fetched:  %d", sync_stats["total"])
        logger.info("  New inserted:   %d", sync_stats["inserted"])
        logger.info("  Updated:        %d", sync_stats["updated"])
        logger.info("  Unchanged:      %d", sync_stats["unchanged"])
        logger.info("=" * 60)

        # --- Step 5: Fetch and mark concurrent users ---
        logger.info("Step 5: Fetching concurrent (inactive but connected) users...")
        from src.customer_fetcher import ConcurrentUserFetcher

        # Re-login for concurrent page (IMS session may expire after bulk fetch)
        try:
            auth2 = IMSAuth(
                base_url=env["IMS_BASE_URL"],
                username=env["IMS_USERNAME"],
                password=env["IMS_PASSWORD"],
            )
            auth2.login()
            logger.info("Re-authenticated for concurrent fetch.")
        except AuthError as e:
            logger.warning("Re-auth failed for concurrent fetch: %s", e)
            return 0  # Main sync already succeeded

        concurrent_fetcher = ConcurrentUserFetcher(
            session=auth2.session,
            base_url=env["IMS_BASE_URL"],
            page_size=100,
        )

        try:
            concurrent_fetcher.open_concurrent_page()
            concurrent_ids = concurrent_fetcher.fetch_concurrent_user_ids()

            if concurrent_ids:
                # Reset previous concurrent tags, then re-apply
                repo.reset_concurrent_status()
                marked = repo.mark_concurrent_users(concurrent_ids)
                logger.info("Concurrent users: %d found, %d marked in DB",
                            len(concurrent_ids), marked)
            else:
                logger.info("No concurrent users found.")

        except CustomerFetchError as e:
            logger.warning("Concurrent user fetch failed (non-fatal): %s", e)
            # Don't fail the whole sync for this

        return 0

    except Exception as e:
        logger.error("Unexpected error: %s", e, exc_info=True)
        return 1

    finally:
        repo.close()


if __name__ == "__main__":
    sys.exit(main())
