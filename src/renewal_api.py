"""Renewal API module for IMS Data Fetcher.

Constructs DataTables-compatible payloads and handles paginated data fetching
from the /MISReport/UpcommingRenewal/GetData endpoint.
"""

import logging
from datetime import date
from typing import List, Optional

logger = logging.getLogger(__name__)


class PayloadConstructionError(Exception):
    """Raised when DataTables payload cannot be constructed."""

    pass


class RenewalAPI:
    """Fetches renewal data from /MISReport/UpcommingRenewal/GetData
    using DataTables-compatible server-side processing payloads.

    Args:
        session_manager: SessionManager instance for making HTTP requests.
        base_url: Base URL of the ISP admin panel (e.g. "https://admin.example.com").
        page_size: Number of records per page (default 10).
        date_format: Date format pattern for FromDate/ToDate (default "yyyy/MM/dd").
    """

    ENDPOINT_PATH = "/MISReport/UpcommingRenewal/GetData"

    COLUMNS = [
        "UserId",
        "CustName",
        "MobileNo",
        "PlanName",
        "Amount",
        "PlanExpiryDate",
        "ZoneName",
    ]

    def __init__(
        self,
        session_manager,
        base_url: str,
        page_size: int = 10,
        date_format: str = "yyyy/MM/dd",
    ):
        self._session_manager = session_manager
        self._base_url = base_url.rstrip("/")
        self._page_size = page_size
        self._date_format = date_format
        self._draw_counter = 0

    def fetch_all_renewals(
        self,
        from_date: date,
        to_date: date,
        search_term: Optional[str] = None,
    ) -> List:
        """Fetch all renewal records across all pages.

        Stops when: cumulative records >= recordsTotal OR empty page received.

        Args:
            from_date: Start date for the renewal query.
            to_date: End date for the renewal query.
            search_term: Optional search filter (truncated to 200 chars).

        Returns:
            List of parsed RenewalRecord objects.
        """
        from src.data_parser import parse_renewal_response

        all_records = []
        start = 0
        records_total = None

        while True:
            payload = self._build_datatables_payload(
                start=start,
                length=self._page_size,
                from_date=from_date,
                to_date=to_date,
                search_term=search_term,
            )

            response_json = self._fetch_page(payload)

            # Get total record count from first response
            if records_total is None:
                records_total = response_json.get("recordsTotal", 0)

            # Get page data
            page_data = response_json.get("data", [])

            # Stop on empty page (Requirement 7.3)
            if not page_data:
                logger.info(
                    "Empty page received at offset %d. Stopping pagination.", start
                )
                break

            # Parse the page records
            page_records = parse_renewal_response(response_json)
            all_records.extend(page_records)

            logger.info(
                "Fetched page at offset %d: %d records (cumulative: %d/%d)",
                start,
                len(page_data),
                len(all_records),
                records_total,
            )

            # Stop when cumulative records >= recordsTotal (Requirement 7.2)
            if len(all_records) >= records_total:
                logger.info(
                    "All records fetched: %d/%d. Stopping pagination.",
                    len(all_records),
                    records_total,
                )
                break

            # Increment offset for next page
            start += self._page_size

        return all_records

    def _build_datatables_payload(
        self,
        start: int,
        length: int,
        from_date: date,
        to_date: date,
        search_term: Optional[str] = None,
    ) -> dict:
        """Construct a DataTables-compatible POST payload.

        Includes: draw, columns[x][data/name/searchable/orderable],
                  order[0][column/dir], start, length, search[value],
                  FromDate, ToDate.

        Args:
            start: Pagination offset (non-negative integer).
            length: Page size (positive integer).
            from_date: Start date for filtering.
            to_date: End date for filtering.
            search_term: Optional search filter (truncated to 200 chars max).

        Returns:
            Flat dictionary with DataTables-compatible keys.

        Raises:
            PayloadConstructionError: If parameters are invalid.
        """
        try:
            # Increment draw counter for each request
            self._draw_counter += 1

            payload = {}

            # Draw counter
            payload["draw"] = self._draw_counter

            # Column definitions
            for idx, col_name in enumerate(self.COLUMNS):
                payload[f"columns[{idx}][data]"] = col_name
                payload[f"columns[{idx}][name]"] = col_name
                payload[f"columns[{idx}][searchable]"] = "true"
                payload[f"columns[{idx}][orderable]"] = "true"

            # Order: default ascending by first column
            payload["order[0][column]"] = "0"
            payload["order[0][dir]"] = "asc"

            # Pagination
            payload["start"] = start
            payload["length"] = length

            # Search term (truncated to 200 characters max)
            if search_term is not None:
                payload["search[value]"] = search_term[:200]
            else:
                payload["search[value]"] = ""

            # Date parameters formatted using configured date format
            payload["FromDate"] = self._format_date(from_date)
            payload["ToDate"] = self._format_date(to_date)

            return payload

        except Exception as exc:
            logger.error(
                "Failed to construct DataTables payload: %s. "
                "Parameters: start=%s, length=%s, from_date=%s, to_date=%s, search_term=%s",
                str(exc),
                start,
                length,
                from_date,
                to_date,
                search_term,
            )
            raise PayloadConstructionError(
                f"Failed to construct DataTables payload: {exc}"
            ) from exc

    def _fetch_page(self, payload: dict) -> dict:
        """Send single page request and return parsed JSON response.

        Args:
            payload: DataTables-compatible POST payload dictionary.

        Returns:
            Dict with 'data' (list) and 'recordsTotal' (int) keys.
        """
        url = f"{self._base_url}{self.ENDPOINT_PATH}"

        logger.debug("Fetching page from %s with draw=%s, start=%s", url, payload.get("draw"), payload.get("start"))

        response = self._session_manager.post(url, data=payload)
        return response.json()

    def _format_date(self, d: date) -> str:
        """Format a date object using the configured date format pattern.

        Converts the yyyy/MM/dd pattern to Python strftime format and applies it.

        Args:
            d: Python date object to format.

        Returns:
            Formatted date string.
        """
        # Convert the date format pattern (yyyy/MM/dd style) to strftime format
        strftime_format = self._convert_date_format(self._date_format)
        return d.strftime(strftime_format)

    @staticmethod
    def _convert_date_format(format_pattern: str) -> str:
        """Convert a yyyy/MM/dd style date format pattern to Python strftime format.

        Mapping:
            yyyy -> %Y (4-digit year)
            yy   -> %y (2-digit year)
            MM   -> %m (2-digit month)
            dd   -> %d (2-digit day)

        Args:
            format_pattern: Date format pattern using y, M, d specifiers.

        Returns:
            Python strftime-compatible format string.
        """
        result = format_pattern
        # Replace longer patterns first to avoid partial replacements
        result = result.replace("yyyy", "%Y")
        result = result.replace("yy", "%y")
        result = result.replace("MM", "%m")
        result = result.replace("dd", "%d")
        return result
