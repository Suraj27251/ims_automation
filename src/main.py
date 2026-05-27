"""CLI entry point and orchestration for IMS Data Fetcher.

Provides command-line argument parsing, logging configuration, and
orchestrates the full pipeline: config → session → login → API → export.
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.config_loader import ConfigError, load_config, validate_date_format
from src.data_exporter import DataExporter, ExportError
from src.data_parser import ParseError
from src.diagnostics import DiagnosticsManager
from src.login_handler import LoginError, LoginHandler
from src.renewal_api import RenewalAPI
from src.session_manager import AuthenticationError, SessionManager

logger = logging.getLogger(__name__)

LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "ims_data_fetcher.log"
LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
LOG_BACKUP_COUNT = 5


def build_argument_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser.

    Arguments:
        --from-date: Start date for renewal query (required for execution).
        --to-date: End date for renewal query (required for execution).
        --page-size: Number of records per page (default 10).
        --debug: Enable debug logging and diagnostic mode.
        --export: Export format(s), comma-separated (default "console").

    Returns:
        Configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        description="IMS Data Fetcher - Extract renewal data from ISP admin panel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m src.main --from-date 2024/01/01 --to-date 2024/12/31\n"
            "  python -m src.main --from-date 2024/01/01 --to-date 2024/12/31 --page-size 50\n"
            "  python -m src.main --from-date 2024/01/01 --to-date 2024/12/31 --debug\n"
            "  python -m src.main --from-date 2024/01/01 --to-date 2024/12/31 --export csv,console\n"
        ),
    )

    parser.add_argument(
        "--from-date",
        type=str,
        required=False,
        help="Start date for renewal query (format: configured date format, default yyyy/MM/dd)",
    )

    parser.add_argument(
        "--to-date",
        type=str,
        required=False,
        help="End date for renewal query (format: configured date format, default yyyy/MM/dd)",
    )

    parser.add_argument(
        "--page-size",
        type=int,
        default=10,
        help="Number of records per page (default: 10)",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging and diagnostic mode",
    )

    parser.add_argument(
        "--export",
        type=str,
        default="console",
        help="Export format(s), comma-separated: console, csv, mysql (default: console)",
    )

    return parser


def _configure_logging(debug_mode: bool, file_logging: bool) -> None:
    """Configure application logging.

    Console logging is always enabled. File logging uses a RotatingFileHandler
    when enabled, rotating at 5MB with 5 backup files.

    Args:
        debug_mode: If True, set log level to DEBUG; otherwise INFO.
        file_logging: If True, enable file logging to logs/ directory.
    """
    log_level = logging.DEBUG if debug_mode else logging.INFO

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove any existing handlers to avoid duplicates
    root_logger.handlers.clear()

    # Console handler (always enabled)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root_logger.addHandler(console_handler)

    # File handler (when enabled)
    if file_logging:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root_logger.addHandler(file_handler)


def _parse_date(date_str: str, date_format: str) -> datetime:
    """Parse a date string using the configured date format.

    Converts the yyyy/MM/dd style format to Python strftime format
    and validates the date string against it.

    Args:
        date_str: The date string to parse.
        date_format: The configured date format pattern (e.g. "yyyy/MM/dd").

    Returns:
        Parsed datetime object.

    Raises:
        ValueError: If the date string doesn't match the configured format.
    """
    # Convert format pattern to strftime
    strftime_format = date_format
    strftime_format = strftime_format.replace("yyyy", "%Y")
    strftime_format = strftime_format.replace("yy", "%y")
    strftime_format = strftime_format.replace("MM", "%m")
    strftime_format = strftime_format.replace("dd", "%d")

    return datetime.strptime(date_str, strftime_format)


def main() -> int:
    """Main orchestration function.

    Pipeline:
    1. Parse CLI arguments
    2. Load configuration with CLI overrides
    3. Configure logging
    4. Enable diagnostic mode if --debug
    5. Validate date arguments
    6. Initialize session manager
    7. Authenticate via login handler
    8. Fetch renewal data
    9. Export results

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    parser = build_argument_parser()
    args = parser.parse_args()

    try:
        # Build CLI overrides for config
        cli_overrides = {
            "page_size": args.page_size,
        }

        if args.debug:
            cli_overrides["debug_mode"] = True
            cli_overrides["diagnostic_mode"] = True

        if args.export:
            export_formats = [f.strip().lower() for f in args.export.split(",") if f.strip()]
            if export_formats:
                cli_overrides["export_formats"] = ",".join(export_formats)

        # Load configuration
        config = load_config(cli_overrides)

        # Configure logging
        _configure_logging(config.debug_mode, config.file_logging)

        logger.info("IMS Data Fetcher starting")
        logger.debug("Configuration loaded successfully")

        # Validate required date arguments
        if not args.from_date or not args.to_date:
            print(
                "Error: --from-date and --to-date are required parameters.\n"
            )
            parser.print_usage()
            print(
                "\nUsage: python -m src.main --from-date <date> --to-date <date> "
                "[--page-size N] [--debug] [--export format]"
            )
            return 1

        # Validate date format
        try:
            from_date = _parse_date(args.from_date, config.date_format)
        except ValueError:
            print(
                f"Error: --from-date '{args.from_date}' does not match "
                f"the configured date format '{config.date_format}'.\n"
            )
            parser.print_usage()
            return 1

        try:
            to_date = _parse_date(args.to_date, config.date_format)
        except ValueError:
            print(
                f"Error: --to-date '{args.to_date}' does not match "
                f"the configured date format '{config.date_format}'.\n"
            )
            parser.print_usage()
            return 1

        # Initialize diagnostics manager
        diagnostics = DiagnosticsManager(enabled=config.diagnostic_mode)

        # Initialize session manager
        session_manager = SessionManager(
            connection_timeout=config.connection_timeout,
            read_timeout=config.read_timeout,
            max_retries=config.retry_count,
        )

        # Initialize login handler and authenticate
        login_handler = LoginHandler(
            session_manager=session_manager,
            config=config,
        )

        # Set re-auth callback on session manager
        session_manager._reauth_callback = login_handler.authenticate

        logger.info("Authenticating with ISP admin panel")
        login_handler.authenticate()
        logger.info("Authentication successful")

        # Initialize Renewal API
        # Extract base URL from login URL (scheme + host)
        from urllib.parse import urlparse

        parsed_url = urlparse(config.login_url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

        renewal_api = RenewalAPI(
            session_manager=session_manager,
            base_url=base_url,
            page_size=config.page_size,
            date_format=config.date_format,
        )

        # Fetch all renewal data
        logger.info(
            "Fetching renewal data from %s to %s",
            args.from_date,
            args.to_date,
        )
        records = renewal_api.fetch_all_renewals(
            from_date=from_date.date(),
            to_date=to_date.date(),
        )
        logger.info("Fetched %d total records", len(records))

        # Export results
        exporter = DataExporter(config=config)

        for export_format in config.export_formats:
            if export_format == "console":
                logger.info("Exporting to console (JSON)")
                exporter.export_console(records)

            elif export_format == "csv":
                output_dir = Path("output")
                output_dir.mkdir(parents=True, exist_ok=True)
                csv_path = output_dir / f"renewals_{args.from_date.replace('/', '-')}_{args.to_date.replace('/', '-')}.csv"
                logger.info("Exporting to CSV: %s", csv_path)
                exporter.export_csv(records, csv_path)

            elif export_format == "mysql":
                if config.mysql_enabled:
                    logger.info("Exporting to MySQL")
                    exporter.export_mysql(records)
                else:
                    logger.warning(
                        "MySQL export requested but MySQL is not enabled in configuration"
                    )

        logger.info("IMS Data Fetcher completed successfully")
        return 0

    except ConfigError as exc:
        # Configuration errors - log if logging is configured, always print
        print(f"Configuration error: {exc}", file=sys.stderr)
        logger.error("Configuration error: %s", exc)
        return 1

    except (LoginError, AuthenticationError) as exc:
        logger.error("Authentication error: %s", exc)
        return 1

    except ParseError as exc:
        logger.error("Data parsing error: %s", exc)
        return 1

    except ExportError as exc:
        logger.error("Export error: %s", exc)
        return 1

    except KeyboardInterrupt:
        logger.info("Operation cancelled by user")
        return 1

    except Exception as exc:
        logger.error(
            "Unexpected error: %s: %s",
            type(exc).__name__,
            exc,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
