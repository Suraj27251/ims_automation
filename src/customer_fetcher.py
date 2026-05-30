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
                 page_size: int = 100, timeout: int = 60, max_retries: int = 2):
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.page_size = min(page_size, 100)  # IMS caps at 100 per page
        self.timeout = timeout
        self.max_retries = max_retries
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
        IMS caps page size at 100, so we paginate in chunks of 100.

        Returns:
            List of CustomerRecord objects.

        Raises:
            CustomerFetchError: If the API returns an error or non-JSON response.
        """
        all_records: List[CustomerRecord] = []
        start = 0
        total = None
        consecutive_empty = 0

        logger.info("Fetching all customers (page_size=%d)", self.page_size)

        while True:
            self._draw += 1
            payload = self._build_payload(start)

            # Retry logic for transient failures
            response_data = None
            for attempt in range(self.max_retries + 1):
                try:
                    response_data = self._post_request(payload)
                    break
                except CustomerFetchError as e:
                    if attempt < self.max_retries:
                        logger.warning("Fetch attempt %d failed: %s. Retrying...",
                                       attempt + 1, e)
                        import time
                        time.sleep(2)
                    else:
                        raise

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
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    logger.info("Two consecutive empty pages at offset %d, stopping.", start)
                    break
                # Try next offset in case of a gap
                start += self.page_size
                continue

            consecutive_empty = 0

            # Log raw field names from first record for debugging
            if len(all_records) == 0 and page_data:
                first_record = page_data[0]
                logger.info("RAW FIELDS from IMS (first record keys): %s",
                            list(first_record.keys()))
                logger.info("RAW FIRST RECORD: %s",
                            {k: str(v)[:80] for k, v in first_record.items()})

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
        """Parse a list of raw record dicts into CustomerRecord objects.

        Handles multiple possible field name variations from IMS.
        """
        records = []
        for item in data_list:
            record = CustomerRecord(
                user_id=self._get_field(item, "UserId", "UserID", "userId", "user_id", "UserName"),
                customer_name=self._get_field(item, "CustName", "Name", "CustomerName", "custName", "customer_name"),
                mobile=self._get_field(item, "MobileNo", "Mobile", "mobile", "MobileNumber", "Phone"),
                plan_name=self._get_field(item, "PlanName", "Plan", "planName", "plan_name"),
                plan_category=self._get_field(item, "PlanCategory", "Category", "planCategory"),
                validity=self._get_field(item, "Validity", "validity", "PlanValidity"),
                status=self._get_field(item, "Status", "status", "UserStatus", "AccountStatus", "IsActive"),
                zone_name=self._get_field(item, "ZoneName", "Zone", "zoneName", "zone_name"),
                area=self._get_field(item, "Area", "area", "AreaName"),
                building=self._get_field(item, "Building", "building", "BuildingName"),
                flat_no=self._get_field(item, "FlatNo", "flatNo", "Flat", "FlatNumber"),
                address=self._get_field(item, "Address", "address", "FullAddress"),
                network_type=self._get_field(item, "NetworkType", "networkType", "Network"),
                connectivity_mode=self._get_field(item, "ConnectivityMode", "connectivityMode", "Connectivity"),
                mac=self._get_field(item, "MAC", "Mac", "mac", "MacAddress"),
                mac_free=self._get_field(item, "MACFree", "MacFree", "macFree"),
                onu_no=self._get_field(item, "ONUNo", "OnuNo", "ONU", "onuNo"),
                static_ip=self._get_field(item, "StaticIP", "StaticIp", "staticIp", "IPAddress"),
                radius_password=self._get_field(item, "RadiusPassword", "radiusPassword", "Password"),
                email=self._get_field(item, "Email", "email", "EmailId", "EmailAddress"),
                company_name=self._get_field(item, "CompanyName", "companyName", "Company"),
                owner_tenant=self._get_field(item, "OwnerTenant", "ownerTenant", "OwnerOrTenant"),
                payment_id=self._get_field(item, "PaymentId", "paymentId", "PaymentID"),
                created_by=self._get_field(item, "CreatedBy", "createdBy"),
                adv_renew=self._get_field(item, "AdvRenew", "advRenew", "AdvanceRenew"),
                kyc_approved=self._get_field(item, "KYCApproved", "kycApproved", "KYC", "KycStatus"),
                roaming=self._get_field(item, "Roaming", "roaming"),
                password_plain=self._get_field(item, "PasswordPlain", "passwordPlain", "PlainPassword"),
                id_no=self._get_field(item, "IdNo", "idNo", "IDNo", "IdNumber"),
            )

            # Parse date fields - try multiple possible names
            record.activation_date = self._parse_date(
                self._get_field_raw(item, "ActivationDate", "activationDate", "ActivateDate", "StartDate")
            )
            record.expiry_date = self._parse_date(
                self._get_field_raw(item, "PlanExpiryDate", "ExpiryDate", "ExpDate", "expiryDate", "Expiry")
            )
            record.data_reset_date = self._parse_date(
                self._get_field_raw(item, "DataResetDate", "dataResetDate", "ResetDate")
            )
            record.reg_date = self._parse_date(
                self._get_field_raw(item, "RegDate", "regDate", "RegistrationDate", "RegisterDate", "CreatedDate")
            )

            records.append(record)

        return records

    def _get_field(self, item: dict, *keys) -> Optional[str]:
        """Try multiple field names and return the first non-empty value as cleaned string."""
        for key in keys:
            val = item.get(key)
            if val is not None:
                cleaned = self._clean_str(val)
                if cleaned:
                    return cleaned
        return None

    def _get_field_raw(self, item: dict, *keys):
        """Try multiple field names and return the first non-None raw value."""
        for key in keys:
            val = item.get(key)
            if val is not None and str(val).strip() and str(val).strip().lower() not in ("null", "none"):
                return val
        return None

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
