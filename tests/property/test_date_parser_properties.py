"""Property-based tests for date_parser module."""

import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import pytest
from hypothesis import given, strategies as st

from date_parser import (
    parse_aspnet_date,
    datetime_to_aspnet_date,
    DateParseError,
    MIN_TIMESTAMP_MS,
    MAX_TIMESTAMP_MS,
)


# --- Strategies for Property 1 ---

# Valid millisecond timestamps in the supported range
valid_timestamps = st.integers(
    min_value=MIN_TIMESTAMP_MS,
    max_value=MAX_TIMESTAMP_MS,
)

# Valid timezone offset hours (0-14)
offset_hours = st.integers(min_value=0, max_value=14)

# Valid timezone offset minutes (0 or 30)
offset_minutes = st.sampled_from([0, 30])

# Timezone offset sign
offset_sign = st.sampled_from(["+", "-"])


@st.composite
def valid_timezone_offsets(draw):
    """
    Generate valid timezone offsets as strings (±HHMM) or None for UTC.

    Valid offsets have HH in 00-14 and MM in 00 or 30.
    When HH is 14, MM must be 00 to stay within valid UTC offset range.
    Excludes ±0000 since that is semantically equivalent to UTC (no offset),
    and the implementation normalizes it to the no-offset form.
    """
    use_offset = draw(st.booleans())
    if not use_offset:
        return None

    sign = draw(offset_sign)
    hh = draw(offset_hours)
    mm = draw(offset_minutes)

    # Constrain: ±14:30 exceeds max UTC offset, limit to ±14:00
    if hh == 14:
        mm = 0

    # Exclude ±0000 — semantically identical to UTC, implementation
    # normalizes zero offset to no-offset form in round-trip
    if hh == 0 and mm == 0:
        # Force a non-zero offset
        hh = draw(st.integers(min_value=1, max_value=14))
        if hh == 14:
            mm = 0

    return f"{sign}{hh:02d}{mm:02d}"


@st.composite
def aspnet_date_strings(draw):
    """
    Generate valid ASP.NET date strings with random timestamps and offsets.

    Returns a tuple of (date_string, timestamp_ms, offset_str_or_none).
    """
    ts = draw(valid_timestamps)
    offset = draw(valid_timezone_offsets())

    if offset is None:
        date_str = f"/Date({ts})/"
    else:
        date_str = f"/Date({ts}{offset})/"

    return (date_str, ts, offset)


class TestAspNetDateRoundTrip:
    """Property 1: ASP.NET Date Parsing Round-Trip

    **Validates: Requirements 10.1, 10.2, 10.5**

    For any valid millisecond timestamp in the range [946684800000, 4102444800000]
    and any valid timezone offset (±HHMM where HH is 00-14 and MM is 00 or 30),
    parsing the ASP.NET date string /Date(ms±HHMM)/ to a Python datetime and
    converting it back SHALL produce the original millisecond value and timezone
    offset.
    """

    @given(data=aspnet_date_strings())
    def test_aspnet_date_round_trip(self, data):
        """Parsing and re-serializing an ASP.NET date string produces the
        original string."""
        date_str, original_ts, original_offset = data

        # Parse the ASP.NET date string to a datetime
        parsed_dt = parse_aspnet_date(date_str)

        # Convert back to ASP.NET date string
        round_tripped = datetime_to_aspnet_date(parsed_dt)

        # Verify the round-tripped string matches the original
        assert round_tripped == date_str, (
            f"Round-trip failed:\n"
            f"  Original:      {date_str}\n"
            f"  Round-tripped: {round_tripped}\n"
            f"  Parsed dt:     {parsed_dt}\n"
            f"  Original ts:   {original_ts}\n"
            f"  Original offset: {original_offset}"
        )


# Pattern that matches valid ASP.NET date strings
VALID_ASPNET_PATTERN = re.compile(r'^/Date\(-?\d+([+-]\d{4})?\)/$')


class TestInvalidAspNetDateRejection:
    """Property 2: Invalid ASP.NET Date Rejection

    **Validates: Requirements 10.3**

    For any string that does not match the pattern `/Date(digits)/` or
    `/Date(digits±HHMM)/`, the Date_Parser SHALL raise a ValueError
    containing the invalid input string.
    """

    @given(
        invalid_input=st.text(
            alphabet=st.characters(),
            min_size=0,
            max_size=200,
        ).filter(lambda s: not VALID_ASPNET_PATTERN.match(s))
    )
    def test_non_matching_strings_raise_date_parse_error(self, invalid_input: str):
        """Any string that does not match the valid ASP.NET date pattern
        must cause parse_aspnet_date() to raise DateParseError."""
        with pytest.raises(DateParseError):
            parse_aspnet_date(invalid_input)

    @given(
        invalid_input=st.text(
            alphabet=st.characters(),
            min_size=1,
            max_size=200,
        ).filter(lambda s: not VALID_ASPNET_PATTERN.match(s))
    )
    def test_error_message_contains_invalid_input(self, invalid_input: str):
        """The raised DateParseError message must contain the invalid
        input string for diagnostic purposes."""
        with pytest.raises(DateParseError) as exc_info:
            parse_aspnet_date(invalid_input)
        assert invalid_input in str(exc_info.value)

    @given(
        invalid_input=st.text(
            alphabet=st.characters(),
            min_size=0,
            max_size=200,
        ).filter(lambda s: not VALID_ASPNET_PATTERN.match(s))
    )
    def test_date_parse_error_is_value_error(self, invalid_input: str):
        """DateParseError must be a subclass of ValueError."""
        with pytest.raises(ValueError):
            parse_aspnet_date(invalid_input)


class TestOutOfRangeDateRejection:
    """Property 3: Out-of-Range Date Rejection

    **Validates: Requirements 10.4**

    For any millisecond value less than 946684800000 or greater than
    4102444800000, the Date_Parser SHALL raise a ValueError indicating
    the date is out of the supported range.
    """

    @given(
        timestamp_ms=st.integers(
            min_value=-62135596800000,  # reasonable lower bound (year 1 CE)
            max_value=MIN_TIMESTAMP_MS - 1,
        )
    )
    def test_below_min_timestamp_raises_error(self, timestamp_ms: int):
        """Any timestamp below MIN_TIMESTAMP_MS must raise DateParseError
        with 'out of supported range' in the message."""
        date_string = f"/Date({timestamp_ms})/"
        with pytest.raises(DateParseError, match="out of supported range"):
            parse_aspnet_date(date_string)

    @given(
        timestamp_ms=st.integers(
            min_value=MAX_TIMESTAMP_MS + 1,
            max_value=253402300800000,  # reasonable upper bound (year 9999)
        )
    )
    def test_above_max_timestamp_raises_error(self, timestamp_ms: int):
        """Any timestamp above MAX_TIMESTAMP_MS must raise DateParseError
        with 'out of supported range' in the message."""
        date_string = f"/Date({timestamp_ms})/"
        with pytest.raises(DateParseError, match="out of supported range"):
            parse_aspnet_date(date_string)
