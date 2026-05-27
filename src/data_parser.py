"""
Data parser module.

Parses JSON API responses into structured RenewalRecord objects.
Handles field mapping, missing/null defaults, and date conversion.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from src.date_parser import parse_aspnet_date

logger = logging.getLogger(__name__)


@dataclass
class RenewalRecord:
    """Normalized renewal data record."""
    user_id: Optional[str] = None
    cust_name: Optional[str] = None
    mobile_no: Optional[str] = None
    plan_name: Optional[str] = None
    amount: Optional[str] = None
    plan_expiry_date: Optional[datetime] = None
    zone_name: Optional[str] = None


class ParseError(Exception):
    """Raised when response cannot be parsed."""
    pass


def parse_renewal_response(raw_json: dict) -> List[RenewalRecord]:
    """
    Parse a single page API response into RenewalRecord objects.

    Expects raw_json to have a 'data' key containing a list of record dicts.

    Args:
        raw_json: Parsed JSON dict with 'data' key containing record list.

    Returns:
        List of RenewalRecord objects. Empty list if no records.

    Raises:
        ParseError: If response structure is invalid (no 'data' key,
                    'data' not a list, etc.). Includes first 500 chars
                    of the raw response in the error message.
    """
    if not isinstance(raw_json, dict):
        snippet = str(raw_json)[:500]
        raise ParseError(
            f"Invalid response structure: expected dict, got "
            f"{type(raw_json).__name__}. Response: {snippet}"
        )

    if "data" not in raw_json:
        snippet = str(raw_json)[:500]
        raise ParseError(
            f"Invalid response structure: missing 'data' key. "
            f"Response: {snippet}"
        )

    data = raw_json["data"]

    if not isinstance(data, list):
        snippet = str(raw_json)[:500]
        raise ParseError(
            f"Invalid response structure: 'data' is not a list, got "
            f"{type(data).__name__}. Response: {snippet}"
        )

    if len(data) == 0:
        return []

    records = []
    for record_dict in data:
        records.append(parse_record(record_dict))

    return records


def parse_record(record_dict: dict) -> RenewalRecord:
    """
    Parse a single JSON object into a RenewalRecord.

    Maps JSON keys to dataclass fields:
        UserId -> user_id
        CustName -> cust_name
        MobileNo -> mobile_no
        PlanName -> plan_name
        Amount -> amount
        PlanExpiryDate -> plan_expiry_date
        ZoneName -> zone_name

    Missing or null fields default to None.
    PlanExpiryDate is passed through date_parser.parse_aspnet_date().
    If date parsing fails, plan_expiry_date is set to None.

    Args:
        record_dict: A single JSON object from the API response data array.

    Returns:
        A RenewalRecord with mapped fields.
    """
    user_id = record_dict.get("UserId") or None
    cust_name = record_dict.get("CustName") or None
    mobile_no = record_dict.get("MobileNo") or None
    plan_name = record_dict.get("PlanName") or None
    amount = record_dict.get("Amount") or None
    zone_name = record_dict.get("ZoneName") or None

    # Parse PlanExpiryDate through date_parser
    plan_expiry_date = None
    raw_date = record_dict.get("PlanExpiryDate")
    if raw_date is not None:
        try:
            plan_expiry_date = parse_aspnet_date(raw_date)
        except (ValueError, TypeError):
            logger.debug(
                "Failed to parse PlanExpiryDate: %s", raw_date
            )
            plan_expiry_date = None

    return RenewalRecord(
        user_id=user_id,
        cust_name=cust_name,
        mobile_no=mobile_no,
        plan_name=plan_name,
        amount=amount,
        plan_expiry_date=plan_expiry_date,
        zone_name=zone_name,
    )
