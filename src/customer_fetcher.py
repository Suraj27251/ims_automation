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
                records_total = response_data.get("recordsTotal", 0)
                records_filtered = response_data.get("recordsFiltered", 0)
                # Use the larger value - IMS sometimes reports inconsistent totals
                total = max(records_total, records_filtered)
                logger.info("Total customer records: recordsTotal=%d, recordsFiltered=%d, using=%d",
                            records_total, records_filtered, total)

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

            # Stop conditions:
            # 1. We got fewer records than page_size (last page)
            # 2. We have all records based on reported total
            if len(page_data) < self.page_size:
                logger.info("Got %d records (less than page_size %d), this is the last page.",
                            len(page_data), self.page_size)
                break

            if len(all_records) >= total:
                break

            start += self.page_size

        logger.info("Customer fetch complete: %d total records", len(all_records))
        return all_records

    def _build_payload(self, start: int) -> dict:
        """Build DataTables-compatible POST payload for customer listing.

        Note: IMS may cap page size at 100. We handle this via pagination.
        """
        payload = {
            "draw": self._draw,
            "start": start,
            "length": self.page_size,
            "search[value]": "",
            "search[regex]": "false",
            "order[0][column]": "0",
            "order[0][dir]": "asc",
            # Include filter params to ensure no server-side filtering
            "Zone": "",
            "Status": "",
            "UserId": "",
            "Name": "",
            "Mobile": "",
            "Address": "",
            "MAC": "",
            "FlatNo": "",
            "Building": "",
            "ConnectivityMode": "",
            "NetworkType": "",
            "Area": "",
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

        Field mapping based on actual IMS response:
        - UserId: user ID
        - FirstName: customer name (IMS uses FirstName, not CustName)
        - StatusName: Active/Inactive (human-readable)
        - StatusId: 1=Active, 2=Inactive
        - IsActive: 0/1
        - CurrentStatus: 0/1
        - PlanName: plan name
        - PlanCategory: Unlimited/FUP etc
        - BillingcycName: Monthly/Quarterly/Semi-Annually (validity)
        - ZoneName: zone
        - AreaName: area
        - BuildingName: building
        - FlatNo: flat number
        - Address: address
        - MobileNo: mobile
        - Email: email
        - MACID: MAC address
        - MACFree: MAC free flag
        - ONUNo: ONU number
        - StaticIP: static IP
        - RadiusPassword: radius password
        - NetworkType: PPPOE etc
        - FiberName: FTTH etc (connectivity mode)
        - OwnerORTenant: owner/tenant
        - CompanyName: company
        - KYCApproved: 0/1
        - Roaming: 0/1
        - Password: plain password
        - IdNo: ID number
        - PayUserId: payment ID
        - CreatedByName: created by
        - IsAdv: advance renew flag
        """
        records = []
        for item in data_list:
            # Determine status: use StatusName if available, else derive from IsActive
            status_name = item.get("StatusName")
            if status_name:
                status = str(status_name).strip()
            else:
                is_active = item.get("IsActive", item.get("CurrentStatus", ""))
                status = "Active" if str(is_active) == "1" else "Inactive"

            record = CustomerRecord(
                user_id=self._clean_str(item.get("UserId")),
                customer_name=self._clean_str(
                    item.get("FirstName") or item.get("CustName") or item.get("Name")
                ),
                mobile=self._clean_str(item.get("MobileNo") or item.get("Mobile")),
                plan_name=self._clean_str(item.get("PlanName")),
                plan_category=self._clean_str(item.get("PlanCategory")),
                validity=self._clean_str(item.get("BillingcycName") or item.get("Validity")),
                status=status,
                zone_name=self._clean_str(item.get("ZoneName")),
                area=self._clean_str(item.get("AreaName") or item.get("Area")),
                building=self._clean_str(item.get("BuildingName") or item.get("Building")),
                flat_no=self._clean_str(item.get("FlatNo")),
                address=self._clean_str(item.get("Address")),
                network_type=self._clean_str(item.get("NetworkType")),
                connectivity_mode=self._clean_str(item.get("FiberName") or item.get("ConnectivityMode")),
                mac=self._clean_str(item.get("MACID") or item.get("MAC")),
                mac_free=self._clean_str(item.get("MACFree")),
                onu_no=self._clean_str(item.get("ONUNo")),
                static_ip=self._clean_str(item.get("StaticIP")),
                radius_password=self._clean_str(item.get("RadiusPassword")),
                email=self._clean_str(item.get("Email")),
                company_name=self._clean_str(item.get("CompanyName")),
                owner_tenant=self._clean_str(item.get("OwnerORTenant") or item.get("OwnerTenant")),
                payment_id=self._clean_str(item.get("PayUserId") or item.get("PaymentId")),
                created_by=self._clean_str(item.get("CreatedByName") or item.get("CreatedBy")),
                adv_renew=self._clean_str(item.get("IsAdv") or item.get("AdvRenew")),
                kyc_approved=self._clean_str(item.get("KYCApproved")),
                roaming=self._clean_str(item.get("Roaming")),
                password_plain=self._clean_str(item.get("Password") or item.get("PasswordPlain")),
                id_no=self._clean_str(item.get("IdNo")),
            )

            # Parse date fields using actual IMS field names
            record.activation_date = self._parse_date(
                item.get("ActivationDateS") or item.get("PlanActivationDateS")
            )
            record.expiry_date = self._parse_date(
                item.get("PlanExpiryDate") or item.get("PlanExpiryDateS") or item.get("PlanExpiryDateNew")
            )
            record.data_reset_date = self._parse_date(item.get("DataResetDate"))
            record.reg_date = self._parse_date(
                item.get("CreatedDate") or item.get("CreatedDateS")
            )

            records.append(record)

        return records

    def _parse_date(self, raw_value) -> Optional[datetime]:
        """Parse a date field - handles ASP.NET /Date()/ format and ISO strings.

        Handles negative timestamps and out-of-range dates gracefully.
        """
        if not raw_value:
            return None

        raw_str = str(raw_value).strip()
        if not raw_str or raw_str.lower() in ("null", "none", "", "no data"):
            return None

        # ASP.NET /Date(...)/ format
        if raw_str.startswith("/Date("):
            try:
                return parse_aspnet_date(raw_str)
            except (ValueError, TypeError):
                # Try manual parsing for out-of-range dates
                import re
                match = re.match(r'^/Date\((-?\d+)([+-]\d{4})?\)/$', raw_str)
                if match:
                    timestamp_ms = int(match.group(1))
                    # Skip negative timestamps (invalid/placeholder dates)
                    if timestamp_ms < 0:
                        return None
                    # Try converting even if outside the strict 2000-2100 range
                    try:
                        from datetime import timezone
                        dt = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
                        # Only accept reasonable dates (2000-2100)
                        if dt.year < 2000 or dt.year > 2100:
                            return None
                        return dt
                    except (OSError, OverflowError, ValueError):
                        return None
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
        """Clean a string value - return None for empty/null/placeholder values."""
        if value is None:
            return None
        s = str(value).strip()
        if not s or s.lower() in ("null", "none", "no data"):
            return None
        return s


class ConcurrentUserFetcher:
    """Fetches concurrent (inactive but connected) users from IMS.

    These are users who appear on the Dashboard/UserDataConcurrent page.
    They are technically inactive (not renewed) but still using the network.

    URL: /Dashboard/UserDataConcurrent?StatusName=Inactive
    """

    PAGE_URL = "/Dashboard/UserDataConcurrent"
    ENDPOINT = "/Dashboard/UserDataConcurrent/GetData"

    def __init__(self, session: requests.Session, base_url: str,
                 page_size: int = 100, timeout: int = 60):
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.page_size = min(page_size, 100)
        self.timeout = timeout
        self._draw = 0

    def open_concurrent_page(self) -> None:
        """Navigate to the concurrent users page to establish session context."""
        url = f"{self.base_url}{self.PAGE_URL}?StatusName=Inactive"
        logger.info("Opening concurrent users page: %s", url)

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
            raise CustomerFetchError(f"Failed to open concurrent page: {e}") from e

        final_url = (response.url or "").lower()
        if "/admin" in final_url and "dashboard" not in final_url:
            raise CustomerFetchError(
                f"Concurrent page redirected to login: {response.url}. "
                f"Session is not authenticated."
            )

        if response.status_code != 200:
            raise CustomerFetchError(
                f"Concurrent page returned HTTP {response.status_code}"
            )

        logger.info("Concurrent users page loaded: status=%d", response.status_code)

    def fetch_concurrent_user_ids(self) -> List[str]:
        """Fetch all concurrent user IDs from IMS.

        Returns:
            List of user_id strings that are in concurrent state.
        """
        all_user_ids: List[str] = []
        start = 0
        total = None

        logger.info("Fetching concurrent users (page_size=%d)", self.page_size)

        while True:
            self._draw += 1
            payload = self._build_payload(start)

            try:
                response_data = self._post_request(payload)
            except CustomerFetchError as e:
                logger.error("Failed to fetch concurrent users: %s", e)
                break

            # Get total on first page
            if total is None:
                records_total = response_data.get("recordsTotal", 0)
                records_filtered = response_data.get("recordsFiltered", 0)
                total = max(records_total, records_filtered)
                logger.info("Total concurrent users: recordsTotal=%d, recordsFiltered=%d, using=%d",
                            records_total, records_filtered, total)

                if total == 0:
                    break

            # Parse page data
            page_data = response_data.get("data", [])
            if not page_data:
                break

            # Log first record for debugging
            if len(all_user_ids) == 0 and page_data:
                logger.info("Concurrent RAW FIELDS: %s", list(page_data[0].keys()))
                logger.info("Concurrent RAW FIRST RECORD: %s",
                            {k: str(v)[:60] for k, v in page_data[0].items()})

            # Extract user IDs
            for item in page_data:
                user_id = (
                    item.get("UserId") or item.get("UserID") or
                    item.get("userId") or item.get("UserName") or
                    item.get("user_id")
                )
                if user_id:
                    uid = str(user_id).strip()
                    if uid and uid.lower() not in ("null", "none"):
                        all_user_ids.append(uid)

            logger.info("Concurrent page offset=%d: %d users (cumulative: %d/%d)",
                        start, len(page_data), len(all_user_ids), total)

            # Stop if last page
            if len(page_data) < self.page_size:
                break
            if len(all_user_ids) >= total:
                break

            start += self.page_size

        logger.info("Concurrent fetch complete: %d user IDs", len(all_user_ids))
        return all_user_ids

    def _build_payload(self, start: int) -> dict:
        """Build DataTables POST payload for concurrent users."""
        payload = {
            "draw": self._draw,
            "start": start,
            "length": self.page_size,
            "search[value]": "",
            "search[regex]": "false",
            "order[0][column]": "0",
            "order[0][dir]": "asc",
            "StatusName": "Inactive",
        }

        # Columns visible on the concurrent page
        columns = ["UserId", "PlanName", "IPAddress", "NAS", "ZoneName", "CallerId", "UpTime"]
        for idx, col in enumerate(columns):
            payload[f"columns[{idx}][data]"] = col
            payload[f"columns[{idx}][name]"] = col
            payload[f"columns[{idx}][searchable]"] = "true"
            payload[f"columns[{idx}][orderable]"] = "true"
            payload[f"columns[{idx}][search][value]"] = ""
            payload[f"columns[{idx}][search][regex]"] = "false"

        return payload

    def _post_request(self, payload: dict) -> dict:
        """Send POST request to concurrent GetData endpoint."""
        # The concurrent page uses the same URL pattern as other IMS DataTables:
        # POST to the page URL itself with DataTables params returns JSON
        # But we need to pass StatusName as a query param or form field
        url = f"{self.base_url}{self.PAGE_URL}"

        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": f"{self.base_url}{self.PAGE_URL}?StatusName=Inactive",
        }

        # Try posting to the page URL with query param
        url_with_param = f"{url}?StatusName=Inactive"

        logger.debug("POST %s (draw=%d, start=%d)", url_with_param, payload.get("draw"), payload.get("start"))

        try:
            response = self.session.post(url_with_param, data=payload, headers=headers, timeout=self.timeout)
        except requests.RequestException as e:
            raise CustomerFetchError(f"Network error fetching concurrent data: {e}") from e

        content_type = response.headers.get("Content-Type", "")

        # If first attempt returned HTML, try GetData sub-path with query param
        if "json" not in content_type.lower() and response.status_code == 200:
            alt_urls = [
                f"{self.base_url}/Dashboard/UserDataConcurrent/GetData?StatusName=Inactive",
                f"{self.base_url}/Dashboard/UserDataConcurrentGetData?StatusName=Inactive",
                f"{self.base_url}/Dashboard/GetConcurrentUsers?StatusName=Inactive",
            ]
            for alt_url in alt_urls:
                try:
                    logger.debug("Trying alternate concurrent URL: %s", alt_url)
                    response = self.session.post(alt_url, data=payload, headers=headers, timeout=self.timeout)
                    content_type = response.headers.get("Content-Type", "")
                    if "json" in content_type.lower():
                        logger.info("Concurrent endpoint found: %s", alt_url)
                        break
                except requests.RequestException:
                    continue

        if response.status_code != 200:
            raise CustomerFetchError(
                f"Concurrent API returned HTTP {response.status_code}. "
                f"Body: {response.text[:300]}"
            )

        content_type = response.headers.get("Content-Type", "")
        if "json" not in content_type.lower():
            raise CustomerFetchError(
                f"Concurrent API returned non-JSON (Content-Type: {content_type}). "
                f"Body: {response.text[:300]}"
            )

        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as e:
            raise CustomerFetchError(
                f"Invalid JSON from concurrent endpoint: {e}"
            ) from e

        return data
