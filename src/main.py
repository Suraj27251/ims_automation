"""IMS Renewal Data Fetcher - Main entry point.

Simple flow:
    1. Login to IMS
    2. Open renewal page (establish session context)
    3. Fetch renewal data via AJAX endpoint
    4. Save to MySQL database

Usage:
    python -m src.main --from-date 2026/05/26 --to-date 2026/05/27
    python -m src.main --from-date 2026/05/26 --to-date 2026/05/27 --debug
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def setup_logging(debug: bool = False) -> None:
    """Configure logging to console + file.

    Args:
        debug: If True, set level to DEBUG. Otherwise INFO.
    """
    level = logging.DEBUG if debug else logging.INFO
    fmt = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(logging.Formatter(fmt))
    root.addHandler(console)

    # File handler - logs/app.log
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    file_handler = RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(fmt))
    root.addHandler(file_handler)

    # Error file handler - logs/errors.log
    error_handler = RotatingFileHandler(
        log_dir / "errors.log",
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
        description="IMS Renewal Data Fetcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m src.main --from-date 2026/05/26 --to-date 2026/05/27\n"
            "  python -m src.main --from-date 2026/05/26 --to-date 2026/05/27 --debug\n"
            "  python -m src.main --from-date 2026/05/26 --to-date 2026/05/27 --page-size 100\n"
        ),
    )
    parser.add_argument("--from-date", required=True, help="Start date (YYYY/MM/DD)")
    parser.add_argument("--to-date", required=True, help="End date (YYYY/MM/DD)")
    parser.add_argument("--page-size", type=int, default=50, help="Records per page (default: 50)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--skip-db", action="store_true", help="Skip database save (dry run)")
    return parser.parse_args()


def load_env() -> dict:
    """Load environment variables from .env file.

    Returns:
        Dict with required config values.

    Raises:
        SystemExit: If required variables are missing.
    """
    load_dotenv(override=False)

    required = {
        "IMS_BASE_URL": os.environ.get("IMS_BASE_URL") or os.environ.get("IMS_LOGIN_URL", "").rsplit("/", 1)[0],
        "IMS_USERNAME": os.environ.get("IMS_USERNAME"),
        "IMS_PASSWORD": os.environ.get("IMS_PASSWORD"),
    }

    # Check required vars
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"Error: Missing environment variables: {', '.join(missing)}", file=sys.stderr)
        print("Set them in .env file or as environment variables.", file=sys.stderr)
        sys.exit(1)

    # MySQL config (optional) - check multiple env var naming conventions
    mysql_config = {
        "MYSQL_HOST": (
            os.environ.get("MYSQL_HOST")
            or os.environ.get("DB_HOST")
            or os.environ.get("IMS_MYSQL_HOST")
        ),
        "MYSQL_USER": (
            os.environ.get("MYSQL_USER")
            or os.environ.get("DB_USER")
            or os.environ.get("IMS_MYSQL_USER")
        ),
        "MYSQL_PASSWORD": (
            os.environ.get("MYSQL_PASSWORD")
            or os.environ.get("DB_PASSWORD")
            or os.environ.get("IMS_MYSQL_PASSWORD")
        ),
        "MYSQL_DATABASE": (
            os.environ.get("MYSQL_DATABASE")
            or os.environ.get("DB_NAME")
            or os.environ.get("IMS_MYSQL_DB")
        ),
        "MYSQL_PORT": int(
            os.environ.get("MYSQL_PORT")
            or os.environ.get("DB_PORT")
            or os.environ.get("IMS_MYSQL_PORT")
            or "3306"
        ),
    }

    return {**required, **mysql_config}


def main() -> int:
    """Main application flow.

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    args = parse_args()
    setup_logging(debug=args.debug)

    logger.info("=" * 60)
    logger.info("IMS Renewal Data Fetcher starting")
    logger.info("=" * 60)

    # Load config
    env = load_env()
    base_url = env["IMS_BASE_URL"]

    logger.info("Base URL: %s", base_url)
    logger.info("Date range: %s to %s", args.from_date, args.to_date)

    # Parse dates
    try:
        from_date = datetime.strptime(args.from_date, "%Y/%m/%d").date()
        to_date = datetime.strptime(args.to_date, "%Y/%m/%d").date()
    except ValueError as e:
        logger.error("Invalid date format: %s. Use YYYY/MM/DD.", e)
        return 1

    # --- Step 1: Login ---
    from src.auth import IMSAuth, AuthError

    auth = IMSAuth(
        base_url=base_url,
        username=env["IMS_USERNAME"],
        password=env["IMS_PASSWORD"],
    )

    try:
        auth.login()
    except AuthError as e:
        logger.error("Authentication failed: %s", e)
        return 1

    # --- Step 2: Open renewal page ---
    from src.navigator import IMSNavigator, NavigationError

    navigator = IMSNavigator(
        session=auth.session,
        base_url=base_url,
    )

    try:
        navigator.open_renewal_page()
    except NavigationError as e:
        logger.error("Navigation failed: %s", e)
        return 1

    # --- Step 3: Fetch renewal data ---
    from src.renewal_fetcher import RenewalFetcher, FetchError

    fetcher = RenewalFetcher(
        session=auth.session,
        base_url=base_url,
        page_size=args.page_size,
    )

    try:
        records = fetcher.fetch(from_date=from_date, to_date=to_date)
    except FetchError as e:
        logger.error("Data fetch failed: %s", e)
        return 1

    if not records:
        logger.info("No renewal records found for the given date range.")
        return 0

    logger.info("Fetched %d renewal records", len(records))

    # --- Step 4: Save to database ---
    if args.skip_db:
        logger.info("--skip-db flag set, skipping database save.")
        # Print summary to console
        for r in records[:5]:
            logger.info("  %s | %s | %s | %s", r.user_id, r.cust_name, r.plan_name, r.plan_expiry_date)
        if len(records) > 5:
            logger.info("  ... and %d more records", len(records) - 5)
        return 0

    # Check MySQL config
    if not env.get("MYSQL_HOST") or not env.get("MYSQL_DATABASE"):
        logger.warning(
            "MySQL not configured (MYSQL_HOST=%s, MYSQL_DATABASE=%s). "
            "Printing records to console instead.",
            env.get("MYSQL_HOST"), env.get("MYSQL_DATABASE"),
        )
        for r in records:
            print(f"{r.user_id} | {r.cust_name} | {r.mobile_no} | {r.plan_name} | {r.amount} | {r.plan_expiry_date} | {r.zone_name}")
        return 0

    from src.database import Database, DatabaseError

    logger.info(
        "Connecting to MySQL: %s@%s/%s",
        env["MYSQL_USER"], env["MYSQL_HOST"], env["MYSQL_DATABASE"],
    )

    db = Database(
        host=env["MYSQL_HOST"],
        user=env["MYSQL_USER"],
        password=env["MYSQL_PASSWORD"],
        database=env["MYSQL_DATABASE"],
        port=env.get("MYSQL_PORT", 3306),
    )

    try:
        db.connect()
        inserted = db.save_records(records)
        logger.info("Saved to database: %d new records", inserted)
    except DatabaseError as e:
        logger.error("Database error: %s", e)
        return 1
    finally:
        db.close()

    logger.info("IMS Renewal Data Fetcher completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
