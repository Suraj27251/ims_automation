"""Customer data fetcher for IMS.

Sends AJAX POST requests to /Customer/Customer/GetData
using the authenticated session. Handles DataTables server-side
processing with pagination to fetch ALL customer records.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

import requests

from src.date_parser import parse_aspnet_date

logger = logging.getLogger(__name__)


class CustomerFetchError(Exception):
    """Raised when customer data fetching fails."""
    pass


@dataclass
class CustomerRecord:
    """A single customer record from the IMS system."""
    user_id: Optional[str] = None
    customer_name: Optional[str] = None
    mobile: Optional[str] = None
    plan_name: Optional[str] = None
    plan_category: Optional[str] = None
    validity: Optional[str] = None
    status: Optional[str] = None
    activation_date: Optional[datetime] = None
    expiry_date: Optional[datetime] = None
    data_reset_date: Optional[datetime] = None
    reg_date: Optional[datetime] = None
    zone_name: Optional[str] = None
    area: Optional[str] = None
    building: Optional[str] = None
    flat_no: Optional[str] = None
    address: Optional[str] = None
    network_type: Optional[str] = None
    connectivity_mode: Optional[str] = None
    mac: Optional[str] = None
    mac_free: Optional[str] = None
    onu_no: Optional[str] = None
    static_ip: Optional[str] = None
    radius_password: Optional[str] = None
    email: Optional[str] = None
    company_name: Optional[str] = None
    owner_tenant: Optional[str] = None
    payment_id: Optional[str] = None
    created_by: Optional[str] = None
    adv_renew: Optional[str] = None
    kyc_approved: Optional[str] = None
    roaming: Optional[str] = None
    password_plain: Optional[str] = None
    id_no: Optional[str] = None


class CustomerFetcher:
    """Fetches all customer data from the IMS Customer listing endpoint.

    Uses DataTables-compatible server-side processing payloads
    with pagination support to retrieve the complete customer database.
    """

    ENDPOINT = "/Customer/Customer/GetData"
    PAGE_URL = "/Customer/Customer/Index"

    # Expected columns from the IMS DataTables response
    COLUMNS = [
        "UserId", "CustName", "MobileNo", "PlanName", "PlanCategory",
        "Validity", "Status", "ActivationDate", "PlanExpiryDate",
        "DataResetDate", "RegDate", "ZoneName", "Area", "Building",
        "FlatNo", "Address", "NetworkType", "ConnectivityMode",
        "MAC", "MACFree", "ONUNo", "StaticIP", "RadiusPassword",
        "Email", "CompanyName", "OwnerTenant", "PaymentId",
        "CreatedBy", "AdvRenew", "KYCApproved", "Roaming",
        "PasswordPlain", "IdNo",
    ]

    def __init__(self, session: requests.Session, base_url: str,
                 page_size: int = 100, timeout: int = 60):
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.page_size = page_size
        self.timeout = timeout
        self._draw = 0

    def open_customer_page(self) -> None:
        """Navigate to the customer listing page to establish session context.

        The IMS DataTables endpoint requires the parent page to be visited first.

        Raises:
            CustomerFetchError: If the page cannot be loaded.
        """
        url = f"{self.base_url}{self.PAGE_URL}"
        logger.info("Opening customer page: %s", url)

        try:
            response = self.session.get(
                url,
                timeout=self.timeout,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Referer": f"{self.base_url}/Dashboard/Index",
                },
            )
        except requests.RequestException as e:
            raise CustomerFetchError(f"Failed to open customer page: {e}") from e

        # Check for redirect to login
        final_url = (response.url or "").lower()
        if "/admin" in final_url and "customer" not in final_url:
            raise CustomerFetchError(
                f"Customer page redirected to login: {response.url}. "
                f"Session is not authenticated."
            )

        if response.status_code != 200:
            raise CustomerFetchError(
                f"Customer page returned HTTP {response.status_code}"
            )

        logger.info("Customer page loaded: status=%d, url=%s", response.status_code, response.url)

    def fetch_all(self) -> List[CustomerRecord]:
        """Fetch all customer records from IMS.

        Paginates through all pages until all records are retrieved.

        Returns:
            List of CustomerRecord objects.

        Raises:
            CustomerFetchError: If the API returns an error or non-JSON response.
        """
        all_records: List[CustomerRecord] = []
        start = 0
        total = None

        logger.info("Fetching all customers (page_size=%d)", self.page_size)

        while True:
            self._draw += 1
            payload = self._build_payload(start)
            response_data = self._post_request(payload)

            # Get total on first page
            if total is None:
                total = response_data.get("recordsTotal", 0)
                logger.info("Total customer records available: %d", total)

                if total == 0:
                    logger.warning("IMS reports 0 total customers. Check session/permissions.")
                    break

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

        logger.info("Customer fetch complete: %d total records", len(all_records))
        return all_records

    def _build_payload(self, start: int) -> dict:
        """Build DataTables-compatible POST payload for customer listing."""
        payload = {
            "draw": self._draw,
            "start": start,
            "length": self.page_size,
            "search[value]": "",
            "search[regex]": "false",
            "order[0][column]": "0",
            "order[0][dir]": "asc",
        }

        # Column definitions
        for idx, col in enumerate(self.COLUMNS):
            payload[f"columns[{idx}][data]"] = col
            payload[f"columns[{idx}][name]"] = col
            payload[f"columns[{idx}][searchable]"] = "true"
            payload[f"columns[{idx}][orderable]"] = "true"
            payload[f"columns[{idx}][search][value]"] = ""
            payload[f"columns[{idx}][search][regex]"] = "false"

        return payload

    def _post_request(self, payload: dict) -> dict:
        """Send POST request to GetData endpoint and return parsed JSON.

        Raises:
            CustomerFetchError: On non-200 status, non-JSON response, or network error.
        """
        url = f"{self.base_url}{self.ENDPOINT}"

        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": f"{self.base_url}{self.PAGE_URL}",
        }

        logger.debug("POST %s (draw=%d, start=%d)", url, payload.get("draw"), payload.get("start"))

        try:
            response = self.session.post(url, data=payload, headers=headers, timeout=self.timeout)
        except requests.RequestException as e:
            raise CustomerFetchError(f"Network error fetching customer data: {e}") from e

        logger.debug(
            "Response: status=%d, content-type=%s, size=%d",
            response.status_code,
            response.headers.get("Content-Type", "N/A"),
            len(response.text),
        )

        # Detect redirects (session expired)
        if response.url and response.url != url:
            logger.error("Request redirected: %s -> %s", url, response.url)
            raise CustomerFetchError(
                f"Session expired: redirected from {url} to {response.url}. "
                f"Re-authentication required."
            )

        # Check status
        if response.status_code != 200:
            raise CustomerFetchError(
                f"API returned HTTP {response.status_code}. "
                f"Body: {response.text[:300]}"
            )

        # Validate content type
        content_type = response.headers.get("Content-Type", "")
        if "json" not in content_type.lower():
            # Detect HTML login page
            if "text/html" in content_type.lower():
                body_lower = response.text[:500].lower()
                if "password" in body_lower or "login" in body_lower:
                    raise CustomerFetchError(
                        "Session expired: received login page instead of JSON data."
                    )
            raise CustomerFetchError(
                f"API returned non-JSON (Content-Type: {content_type}). "
                f"Body: {response.text[:300]}"
            )

        # Parse JSON
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as e:
            raise CustomerFetchError(
                f"Invalid JSON response: {e}. Body: {response.text[:300]}"
            ) from e

        if not isinstance(data, dict):
            raise CustomerFetchError(f"Expected JSON object, got {type(data).__name__}")

        return data

    def _parse_records(self, data_list: list) -> List[CustomerRecord]:
        """Parse a list of raw record dicts into CustomerRecord objects."""
        records = []
        for item in data_list:
            record = CustomerRecord(
                user_id=self._clean_str(item.get("UserId")),
                customer_name=self._clean_str(item.get("CustName")),
                mobile=self._clean_str(item.get("MobileNo")),
                plan_name=self._clean_str(item.get("PlanName")),
                plan_category=self._clean_str(item.get("PlanCategory")),
                validity=self._clean_str(item.get("Validity")),
                status=self._clean_str(item.get("Status")),
                zone_name=self._clean_str(item.get("ZoneName")),
                area=self._clean_str(item.get("Area")),
                building=self._clean_str(item.get("Building")),
                flat_no=self._clean_str(item.get("FlatNo")),
                address=self._clean_str(item.get("Address")),
                network_type=self._clean_str(item.get("NetworkType")),
                connectivity_mode=self._clean_str(item.get("ConnectivityMode")),
                mac=self._clean_str(item.get("MAC")),
                mac_free=self._clean_str(item.get("MACFree")),
                onu_no=self._clean_str(item.get("ONUNo")),
                static_ip=self._clean_str(item.get("StaticIP")),
                radius_password=self._clean_str(item.get("RadiusPassword")),
                email=self._clean_str(item.get("Email")),
                company_name=self._clean_str(item.get("CompanyName")),
                owner_tenant=self._clean_str(item.get("OwnerTenant")),
                payment_id=self._clean_str(item.get("PaymentId")),
                created_by=self._clean_str(item.get("CreatedBy")),
                adv_renew=self._clean_str(item.get("AdvRenew")),
                kyc_approved=self._clean_str(item.get("KYCApproved")),
                roaming=self._clean_str(item.get("Roaming")),
                password_plain=self._clean_str(item.get("PasswordPlain")),
                id_no=self._clean_str(item.get("IdNo")),
            )

            # Parse date fields
            record.activation_date = self._parse_date(item.get("ActivationDate"))
            record.expiry_date = self._parse_date(item.get("PlanExpiryDate"))
            record.data_reset_date = self._parse_date(item.get("DataResetDate"))
            record.reg_date = self._parse_date(item.get("RegDate"))

            records.append(record)

        return records

    def _parse_date(self, raw_value) -> Optional[datetime]:
        """Parse a date field - handles ASP.NET /Date()/ format and ISO strings."""
        if not raw_value:
            return None

        raw_str = str(raw_value).strip()
        if not raw_str or raw_str.lower() in ("null", "none", ""):
            return None

        # ASP.NET /Date(...)/ format
        if raw_str.startswith("/Date("):
            try:
                return parse_aspnet_date(raw_str)
            except (ValueError, TypeError):
                logger.debug("Failed to parse ASP.NET date: %s", raw_str)
                return None

        # ISO format fallback
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(raw_str, fmt)
            except ValueError:
                continue

        logger.debug("Unrecognized date format: %s", raw_str)
        return None

    @staticmethod
    def _clean_str(value) -> Optional[str]:
        """Clean a string value - return None for empty/null values."""
        if value is None:
            return None
        s = str(value).strip()
        if not s or s.lower() in ("null", "none"):
            return None
        return s
