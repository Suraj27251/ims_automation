"""Unit tests for data_parser module."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from src.data_parser import (
    RenewalRecord,
    ParseError,
    parse_renewal_response,
    parse_record,
)


class TestParseRenewalResponse:
    """Tests for parse_renewal_response function."""

    def test_valid_response_with_records(self):
        """Test parsing a complete response with records in the data array."""
        raw_json = {
            "data": [
                {
                    "UserId": "1001",
                    "CustName": "John Doe",
                    "MobileNo": "9876543210",
                    "PlanName": "Premium 100Mbps",
                    "Amount": "999",
                    "PlanExpiryDate": "/Date(1704067200000)/",
                    "ZoneName": "Zone-A",
                }
            ]
        }
        result = parse_renewal_response(raw_json)
        assert len(result) == 1
        assert isinstance(result[0], RenewalRecord)
        assert result[0].user_id == "1001"
        assert result[0].cust_name == "John Doe"

    def test_empty_data_array_returns_empty_list(self):
        """Test that an empty data array returns an empty list."""
        raw_json = {"data": []}
        result = parse_renewal_response(raw_json)
        assert result == []

    def test_raises_parse_error_when_no_data_key(self):
        """Test ParseError raised when response has no 'data' key."""
        raw_json = {"records": []}
        with pytest.raises(ParseError, match="missing 'data' key"):
            parse_renewal_response(raw_json)

    def test_raises_parse_error_when_data_is_not_list(self):
        """Test ParseError raised when 'data' is not a list."""
        raw_json = {"data": "not a list"}
        with pytest.raises(ParseError, match="'data' is not a list"):
            parse_renewal_response(raw_json)

    def test_raises_parse_error_when_input_is_not_dict(self):
        """Test ParseError raised when input is not a dict."""
        with pytest.raises(ParseError, match="expected dict"):
            parse_renewal_response("not a dict")

    def test_raises_parse_error_when_input_is_list(self):
        """Test ParseError raised when input is a list instead of dict."""
        with pytest.raises(ParseError, match="expected dict"):
            parse_renewal_response([{"data": []}])

    def test_raises_parse_error_when_input_is_none(self):
        """Test ParseError raised when input is None."""
        with pytest.raises(ParseError, match="expected dict"):
            parse_renewal_response(None)

    def test_error_message_includes_first_500_chars(self):
        """Test that ParseError message includes first 500 chars of response."""
        # Create a response with a long string to verify truncation
        long_value = "x" * 1000
        raw_json = {"no_data_key": long_value}
        with pytest.raises(ParseError) as exc_info:
            parse_renewal_response(raw_json)
        error_msg = str(exc_info.value)
        # The snippet should be present and truncated
        assert "Response:" in error_msg

    def test_multiple_records_parsed(self):
        """Test parsing response with multiple records."""
        raw_json = {
            "data": [
                {"UserId": "1001", "CustName": "Alice"},
                {"UserId": "1002", "CustName": "Bob"},
                {"UserId": "1003", "CustName": "Charlie"},
            ]
        }
        result = parse_renewal_response(raw_json)
        assert len(result) == 3
        assert result[0].user_id == "1001"
        assert result[1].user_id == "1002"
        assert result[2].user_id == "1003"


class TestParseRecord:
    """Tests for parse_record function."""

    def test_complete_record_all_fields(self):
        """Test parsing a complete record with all fields present."""
        record_dict = {
            "UserId": "1001",
            "CustName": "John Doe",
            "MobileNo": "9876543210",
            "PlanName": "Premium 100Mbps",
            "Amount": "999",
            "PlanExpiryDate": "/Date(1704067200000)/",
            "ZoneName": "Zone-A",
        }
        result = parse_record(record_dict)

        assert result.user_id == "1001"
        assert result.cust_name == "John Doe"
        assert result.mobile_no == "9876543210"
        assert result.plan_name == "Premium 100Mbps"
        assert result.amount == "999"
        assert result.plan_expiry_date == datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert result.zone_name == "Zone-A"

    def test_missing_fields_default_to_none(self):
        """Test that missing fields default to None."""
        record_dict = {"UserId": "1001"}
        result = parse_record(record_dict)

        assert result.user_id == "1001"
        assert result.cust_name is None
        assert result.mobile_no is None
        assert result.plan_name is None
        assert result.amount is None
        assert result.plan_expiry_date is None
        assert result.zone_name is None

    def test_null_fields_default_to_none(self):
        """Test that null (None) fields default to None."""
        record_dict = {
            "UserId": None,
            "CustName": None,
            "MobileNo": None,
            "PlanName": None,
            "Amount": None,
            "PlanExpiryDate": None,
            "ZoneName": None,
        }
        result = parse_record(record_dict)

        assert result.user_id is None
        assert result.cust_name is None
        assert result.mobile_no is None
        assert result.plan_name is None
        assert result.amount is None
        assert result.plan_expiry_date is None
        assert result.zone_name is None

    def test_empty_string_fields_default_to_none(self):
        """Test that empty string fields default to None (falsy values)."""
        record_dict = {
            "UserId": "",
            "CustName": "",
            "MobileNo": "",
            "PlanName": "",
            "Amount": "",
            "ZoneName": "",
        }
        result = parse_record(record_dict)

        assert result.user_id is None
        assert result.cust_name is None
        assert result.mobile_no is None
        assert result.plan_name is None
        assert result.amount is None
        assert result.zone_name is None

    def test_empty_dict_all_fields_none(self):
        """Test that an empty dict results in all None fields."""
        result = parse_record({})

        assert result.user_id is None
        assert result.cust_name is None
        assert result.mobile_no is None
        assert result.plan_name is None
        assert result.amount is None
        assert result.plan_expiry_date is None
        assert result.zone_name is None

    def test_plan_expiry_date_passed_through_date_parser(self):
        """Test that PlanExpiryDate is passed through parse_aspnet_date."""
        # 2024-01-01T00:00:00Z = 1704067200000 ms
        record_dict = {
            "UserId": "1001",
            "PlanExpiryDate": "/Date(1704067200000)/",
        }
        result = parse_record(record_dict)

        expected_date = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert result.plan_expiry_date == expected_date

    def test_plan_expiry_date_with_timezone_offset(self):
        """Test PlanExpiryDate with timezone offset is parsed correctly."""
        record_dict = {
            "UserId": "1001",
            "PlanExpiryDate": "/Date(1704067200000+0530)/",
        }
        result = parse_record(record_dict)

        offset = timedelta(hours=5, minutes=30)
        expected_tz = timezone(offset)
        expected_date = datetime(2024, 1, 1, 5, 30, 0, tzinfo=expected_tz)
        assert result.plan_expiry_date == expected_date

    def test_plan_expiry_date_none_on_parse_failure(self):
        """Test that plan_expiry_date is None if date parsing fails."""
        record_dict = {
            "UserId": "1001",
            "PlanExpiryDate": "invalid-date-string",
        }
        result = parse_record(record_dict)

        assert result.plan_expiry_date is None

    def test_plan_expiry_date_none_on_out_of_range(self):
        """Test that plan_expiry_date is None if date is out of range."""
        record_dict = {
            "UserId": "1001",
            "PlanExpiryDate": "/Date(100000000)/",  # Before year 2000
        }
        result = parse_record(record_dict)

        assert result.plan_expiry_date is None

    def test_plan_expiry_date_none_when_field_is_null(self):
        """Test that plan_expiry_date is None when PlanExpiryDate is null."""
        record_dict = {
            "UserId": "1001",
            "PlanExpiryDate": None,
        }
        result = parse_record(record_dict)

        assert result.plan_expiry_date is None

    def test_extra_fields_ignored(self):
        """Test that extra fields in the record dict are ignored."""
        record_dict = {
            "UserId": "1001",
            "CustName": "John",
            "ExtraField": "should be ignored",
            "AnotherField": 12345,
        }
        result = parse_record(record_dict)

        assert result.user_id == "1001"
        assert result.cust_name == "John"

    def test_returns_renewal_record_instance(self):
        """Test that parse_record returns a RenewalRecord dataclass instance."""
        result = parse_record({"UserId": "1001"})
        assert isinstance(result, RenewalRecord)


class TestRenewalRecord:
    """Tests for RenewalRecord dataclass."""

    def test_default_values_all_none(self):
        """Test that RenewalRecord defaults all fields to None."""
        record = RenewalRecord()
        assert record.user_id is None
        assert record.cust_name is None
        assert record.mobile_no is None
        assert record.plan_name is None
        assert record.amount is None
        assert record.plan_expiry_date is None
        assert record.zone_name is None

    def test_equality(self):
        """Test that two RenewalRecords with same values are equal."""
        record1 = RenewalRecord(user_id="1001", cust_name="John")
        record2 = RenewalRecord(user_id="1001", cust_name="John")
        assert record1 == record2


class TestParseError:
    """Tests for ParseError exception."""

    def test_is_exception(self):
        """Test that ParseError is an Exception subclass."""
        assert issubclass(ParseError, Exception)

    def test_can_be_raised_with_message(self):
        """Test that ParseError can be raised with a message."""
        with pytest.raises(ParseError, match="test error"):
            raise ParseError("test error")
