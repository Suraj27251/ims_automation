"""Property-based tests for data_parser module."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import pytest
from hypothesis import given, strategies as st, assume

from data_parser import parse_record, RenewalRecord


# --- Strategies for Property 7 ---

# The fields that parse_record extracts (excluding PlanExpiryDate which goes
# through date parsing and is tested separately)
STRING_FIELDS = {
    "UserId": "user_id",
    "CustName": "cust_name",
    "MobileNo": "mobile_no",
    "PlanName": "plan_name",
    "Amount": "amount",
    "ZoneName": "zone_name",
}

# Non-empty strings for field values (empty strings are treated as falsy
# by the `or None` pattern in parse_record, so we use min_size=1)
non_empty_strings = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=1,
    max_size=100,
)

# Field values: either a non-empty string or None
field_values = st.one_of(non_empty_strings, st.none())


@st.composite
def renewal_json_subsets(draw):
    """
    Generate a JSON object containing a random subset of the renewal fields
    with random string values or None.

    PlanExpiryDate is always set to None (excluded from string equality check
    since it goes through date parsing).

    Returns a tuple of (json_dict, expected_field_map) where expected_field_map
    maps dataclass field names to expected values.
    """
    # Decide which fields to include
    included_fields = draw(
        st.lists(
            st.sampled_from(list(STRING_FIELDS.keys())),
            unique=True,
            min_size=0,
            max_size=len(STRING_FIELDS),
        )
    )

    json_dict = {}
    expected = {}

    for json_key, attr_name in STRING_FIELDS.items():
        if json_key in included_fields:
            value = draw(field_values)
            json_dict[json_key] = value
            # parse_record uses `get(key) or None`, so empty string would
            # become None, but our strategy only generates non-empty strings
            # or None. A non-empty string stays as-is; None stays as None.
            if value:
                expected[attr_name] = value
            else:
                expected[attr_name] = None
        else:
            # Field is missing from the JSON object
            expected[attr_name] = None

    # PlanExpiryDate is excluded from string equality check - set to None
    # so it doesn't trigger date parsing
    expected["plan_expiry_date"] = None

    return (json_dict, expected)


class TestRenewalRecordFieldExtractionWithDefaults:
    """Property 7: Renewal Record Field Extraction with Defaults

    **Validates: Requirements 9.1, 9.2**

    For any JSON object containing any subset of the fields {UserId, CustName,
    MobileNo, PlanName, Amount, PlanExpiryDate, ZoneName} with string values
    (or null), the Data_Parser SHALL produce a RenewalRecord where present
    fields have values equal to the JSON values and missing/null fields have
    value None.
    """

    @given(data=renewal_json_subsets())
    def test_present_non_null_fields_equal_json_values(self, data):
        """Present non-null string fields have values equal to the JSON values."""
        json_dict, expected = data

        record = parse_record(json_dict)

        for attr_name, expected_value in expected.items():
            if expected_value is not None:
                actual = getattr(record, attr_name)
                assert actual == expected_value, (
                    f"Field '{attr_name}' mismatch:\n"
                    f"  Expected: {expected_value!r}\n"
                    f"  Actual:   {actual!r}\n"
                    f"  JSON input: {json_dict}"
                )

    @given(data=renewal_json_subsets())
    def test_missing_fields_default_to_none(self, data):
        """Missing fields have value None."""
        json_dict, expected = data

        record = parse_record(json_dict)

        for json_key, attr_name in STRING_FIELDS.items():
            if json_key not in json_dict:
                actual = getattr(record, attr_name)
                assert actual is None, (
                    f"Missing field '{attr_name}' should be None, got {actual!r}\n"
                    f"  JSON input: {json_dict}"
                )

    @given(data=renewal_json_subsets())
    def test_null_fields_default_to_none(self, data):
        """Null fields have value None."""
        json_dict, expected = data

        record = parse_record(json_dict)

        for json_key, attr_name in STRING_FIELDS.items():
            if json_key in json_dict and json_dict[json_key] is None:
                actual = getattr(record, attr_name)
                assert actual is None, (
                    f"Null field '{attr_name}' should be None, got {actual!r}\n"
                    f"  JSON input: {json_dict}"
                )

    @given(data=renewal_json_subsets())
    def test_plan_expiry_date_none_when_absent(self, data):
        """PlanExpiryDate defaults to None when not present in JSON."""
        json_dict, expected = data

        record = parse_record(json_dict)

        # Since we don't include PlanExpiryDate in our generated JSON,
        # it should always be None
        assert record.plan_expiry_date is None, (
            f"plan_expiry_date should be None when PlanExpiryDate is absent, "
            f"got {record.plan_expiry_date!r}"
        )


# --- Property 8: Renewal Record Round-Trip Fidelity ---

# Strategy for non-empty, non-whitespace-only strings that won't be
# collapsed to None by the `or None` pattern in parse_record
roundtrip_strings = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=1,
    max_size=200,
).filter(lambda s: bool(s))  # filter out falsy strings (empty after strip, etc.)


class TestRenewalRecordRoundTripFidelity:
    """Property 8: Renewal Record Round-Trip Fidelity

    **Validates: Requirements 9.5**

    For any valid RenewalRecord with non-None string fields, serializing the
    record to the JSON format used by the API response and parsing it back
    SHALL produce a RenewalRecord with field values string-equal to the
    original for string fields.
    """

    @given(
        user_id=roundtrip_strings,
        cust_name=roundtrip_strings,
        mobile_no=roundtrip_strings,
        plan_name=roundtrip_strings,
        amount=roundtrip_strings,
        zone_name=roundtrip_strings,
    )
    def test_string_fields_round_trip(
        self, user_id, cust_name, mobile_no, plan_name, amount, zone_name
    ):
        """
        Serializing a RenewalRecord's string fields to API JSON format and
        parsing back with parse_record() produces string-equal field values.

        **Validates: Requirements 9.5**
        """
        # Arrange: build a JSON dict in the API response format
        api_json = {
            "UserId": user_id,
            "CustName": cust_name,
            "MobileNo": mobile_no,
            "PlanName": plan_name,
            "Amount": amount,
            "ZoneName": zone_name,
            # PlanExpiryDate is skipped - it's a datetime field, not a string
            # round-trip, and goes through date parsing
        }

        # Act: parse the JSON dict back into a RenewalRecord
        result = parse_record(api_json)

        # Assert: all string fields are equal to the originals
        assert result.user_id == user_id, (
            f"user_id mismatch: expected {user_id!r}, got {result.user_id!r}"
        )
        assert result.cust_name == cust_name, (
            f"cust_name mismatch: expected {cust_name!r}, got {result.cust_name!r}"
        )
        assert result.mobile_no == mobile_no, (
            f"mobile_no mismatch: expected {mobile_no!r}, got {result.mobile_no!r}"
        )
        assert result.plan_name == plan_name, (
            f"plan_name mismatch: expected {plan_name!r}, got {result.plan_name!r}"
        )
        assert result.amount == amount, (
            f"amount mismatch: expected {amount!r}, got {result.amount!r}"
        )
        assert result.zone_name == zone_name, (
            f"zone_name mismatch: expected {zone_name!r}, got {result.zone_name!r}"
        )
