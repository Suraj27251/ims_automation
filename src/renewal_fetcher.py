"""Renewal data fetcher for IMS.

Sends AJAX POST requests to /MISReport/UpcommingRenewal/GetData
using the authenticated session. Handles DataTables server-side
processing with pagination.
"""

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional

import requests

from src.date_parser import parse_aspnet_date

logger = logging.getLogger(__name__)


class FetchError(Exception):
    """Raised when data fetching fails."""
    pass


@dataclass
class RenewalRecord:
    """A single renewal record from the IMS system."""
    user_id: Optional[str] = None
    cust_name: Optional[str] = None
    mobile_no: Optional[str] = None
    plan_name: Optional[str] = None
    amount: Optional[str] = None
    plan_expiry_date: Optional[datetime] = None
    zone_name: Optional[str] = None


class RenewalFetcher:
    """Fetches renewal data from the IMS GetData endpoint.

    Uses DataTables-compatible server-side processing payloads
    with pagination support.
    """

    ENDPOINT = "/MISReport/UpcommingRenewal/GetData"
    REFERER = "/MISReport/UpcommingRenewal"

    COLUMNS = [
        "UserId", "CustName", "MobileNo",
        "PlanName", "Amount", "PlanExpiryDate", "ZoneName",
    ]

    def __init__(self, session: requests.Session, base_url: str,
                 page_size: int = 50, timeout: int = 30):
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.page_size = page_size
        self.timeout = timeout
        self._draw = 0

    def fetch(self, from_date: date, to_date: date) -> List[RenewalRecord]:
        """Fetch all renewal records for the given date range.

        Paginates through all pages until all records are retrieved.

        Args:
            from_date: Start date (inclusive).
            to_date: End date (inclusive).

        Returns:
            List of RenewalRecord objects.

        Raises:
            FetchError: If the API returns an error or non-JSON response.
        """
        all_records: List[RenewalRecord] = []
        start = 0
        total = None

        logger.info("Fetching renewals from %s to %s (page_size=%d)",
                    from_date, to_date, self.page_size)

        while True:
            self._draw += 1
            payload = self._build_payload(start, from_date, to_date)
            response_data = self._post_request(payload)

            # Get total on first page
            if total is None:
                total = response_data.get("recordsTotal", 0)
                logger.info("Total records available: %d", total)

            # Parse page data
            page_data = response_data.get("data", [])
            if not page_data:
                logger.info("Empty page at offset %d, stopping.", start)
                break

            records = self._parse_records(page_data)
            all_records.extend(records)

            logger.info("Page offset=%d: %d records (cumulative: %d/%d)",
                        start, len(records), len(all_records), total)

            # Stop when we have all records
            if len(all_records) >= total:
                break

            start += self.page_size

        logger.info("Fetch complete: %d total records", len(all_records))
        return all_records

    def _build_payload(self, start: int, from_date: date, to_date: date) -> dict:
        """Build DataTables-compatible POST payload."""
        payload = {
            "draw": self._draw,
            "start": start,
            "length": self.page_size,
            "search[value]": "",
            "order[0][column]": "0",
            "order[0][dir]": "asc",
            "FromDate": from_date.strftime("%Y/%m/%d"),
            "ToDate": to_date.strftime("%Y/%m/%d"),
        }

        # Column definitions
        for idx, col in enumerate(self.COLUMNS):
            payload[f"columns[{idx}][data]"] = col
            payload[f"columns[{idx}][name]"] = col
            payload[f"columns[{idx}][searchable]"] = "true"
            payload[f"columns[{idx}][orderable]"] = "true"

        return payload

    def _post_request(self, payload: dict) -> dict:
        """Send POST request to GetData endpoint and return parsed JSON.

        Raises:
            FetchError: On non-200 status, non-JSON response, or network error.
        """
        url = f"{self.base_url}{self.ENDPOINT}"

        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": f"{self.base_url}{self.REFERER}",
        }

        logger.debug("POST %s (draw=%d, start=%d)", url, payload.get("draw"), payload.get("start"))

        try:
            response = self.session.post(url, data=payload, headers=headers, timeout=self.timeout)
        except requests.RequestException as e:
            raise FetchError(f"Network error fetching data: {e}") from e

        # Log response details
        logger.debug(
            "Response: status=%d, content-type=%s, size=%d, url=%s",
            response.status_code,
            response.headers.get("Content-Type", "N/A"),
            len(response.text),
            response.url,
        )

        # Detect redirects (session expired)
        if response.url and response.url != url:
            logger.error("Request redirected: %s -> %s", url, response.url)
            raise FetchError(
                f"Session expired: redirected from {url} to {response.url}. "
                f"Re-authentication required."
            )

        # Check status
        if response.status_code != 200:
            raise FetchError(
                f"API returned HTTP {response.status_code}. "
                f"Body: {response.text[:300]}"
            )

        # Validate content type
        content_type = response.headers.get("Content-Type", "")
        if "json" not in content_type.lower():
            raise FetchError(
                f"API returned non-JSON (Content-Type: {content_type}). "
                f"Body: {response.text[:300]}"
            )

        # Parse JSON
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as e:
            raise FetchError(
                f"Invalid JSON response: {e}. Body: {response.text[:300]}"
            ) from e

        if not isinstance(data, dict):
            raise FetchError(f"Expected JSON object, got {type(data).__name__}")

        return data

    def _parse_records(self, data_list: list) -> List[RenewalRecord]:
        """Parse a list of raw record dicts into RenewalRecord objects."""
        records = []
        for item in data_list:
            record = RenewalRecord(
                user_id=item.get("UserId") or None,
                cust_name=item.get("CustName") or None,
                mobile_no=item.get("MobileNo") or None,
                plan_name=item.get("PlanName") or None,
                amount=item.get("Amount") or None,
                zone_name=item.get("ZoneName") or None,
            )

            # Parse ASP.NET date
            raw_date = item.get("PlanExpiryDate")
            if raw_date:
                try:
                    record.plan_expiry_date = parse_aspnet_date(raw_date)
                except (ValueError, TypeError):
                    logger.debug("Failed to parse date: %s", raw_date)

            records.append(record)

        return records
