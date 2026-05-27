"""Unit tests for date_parser module."""

import pytest
from datetime import datetime, timezone, timedelta

from src.date_parser import (
    DateParseError,
    ASPNET_DATE_PATTERN,
    MIN_TIMESTAMP_MS,
    MAX_TIMESTAMP_MS,
    parse_aspnet_date,
    datetime_to_aspnet_date,
)


class TestDateParseError:
    """Tests for DateParseError exception."""

    def test_is_subclass_of_value_error(self):
        assert issubclass(DateParseError, ValueError)

    def test_can_be_raised_and_caught_as_value_error(self):
        with pytest.raises(ValueError):
            raise DateParseError("test error")


class TestConstants:
    """Tests for module constants."""

    def test_min_timestamp_is_2000(self):
        # 2000-01-01T00:00:00Z
        dt = datetime(2000, 1, 1, tzinfo=timezone.utc)
        assert MIN_TIMESTAMP_MS == int(dt.timestamp() * 1000)

    def test_max_timestamp_is_2100(self):
        # 2100-01-01T00:00:00Z
        dt = datetime(2100, 1, 1, tzinfo=timezone.utc)
        assert MAX_TIMESTAMP_MS == int(dt.timestamp() * 1000)

    def test_pattern_matches_utc_date(self):
        assert ASPNET_DATE_PATTERN.match("/Date(1704067200000)/")

    def test_pattern_matches_positive_offset(self):
        assert ASPNET_DATE_PATTERN.match("/Date(1704067200000+0530)/")

    def test_pattern_matches_negative_offset(self):
        assert ASPNET_DATE_PATTERN.match("/Date(1704067200000-0500)/")

    def test_pattern_rejects_no_slashes(self):
        assert not ASPNET_DATE_PATTERN.match("Date(1704067200000)")

    def test_pattern_rejects_no_parentheses(self):
        assert not ASPNET_DATE_PATTERN.match("/Date1704067200000/")


class TestParseAspnetDate:
    """Tests for parse_aspnet_date function."""

    def test_utc_date_known_value(self):
        # 2024-01-01T00:00:00Z = 1704067200000 ms
        result = parse_aspnet_date("/Date(1704067200000)/")
        expected = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_utc_date_has_utc_timezone(self):
        result = parse_aspnet_date("/Date(1704067200000)/")
        assert result.tzinfo == timezone.utc

    def test_positive_offset(self):
        # +0530 = 5 hours 30 minutes ahead of UTC
        result = parse_aspnet_date("/Date(1704067200000+0530)/")
        offset = timedelta(hours=5, minutes=30)
        expected_tz = timezone(offset)
        # The UTC timestamp is the same, but displayed in +0530
        expected = datetime(2024, 1, 1, 5, 30, 0, tzinfo=expected_tz)
        assert result == expected
        assert result.utcoffset() == offset

    def test_negative_offset(self):
        # -0500 = 5 hours behind UTC
        result = parse_aspnet_date("/Date(1704067200000-0500)/")
        offset = timedelta(hours=-5)
        expected_tz = timezone(offset)
        expected = datetime(2023, 12, 31, 19, 0, 0, tzinfo=expected_tz)
        assert result == expected
        assert result.utcoffset() == offset

    def test_boundary_min_timestamp(self):
        # Exactly at minimum (2000-01-01T00:00:00Z)
        result = parse_aspnet_date(f"/Date({MIN_TIMESTAMP_MS})/")
        expected = datetime(2000, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_boundary_max_timestamp(self):
        # Exactly at maximum (2100-01-01T00:00:00Z)
        result = parse_aspnet_date(f"/Date({MAX_TIMESTAMP_MS})/")
        expected = datetime(2100, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_invalid_format_raises_error(self):
        with pytest.raises(DateParseError, match="Invalid ASP.NET date format"):
            parse_aspnet_date("not a date")

    def test_missing_slashes_raises_error(self):
        with pytest.raises(DateParseError):
            parse_aspnet_date("Date(1704067200000)")

    def test_missing_parentheses_raises_error(self):
        with pytest.raises(DateParseError):
            parse_aspnet_date("/Date1704067200000/")

    def test_letters_in_timestamp_raises_error(self):
        with pytest.raises(DateParseError):
            parse_aspnet_date("/Date(abc123)/")

    def test_below_min_range_raises_error(self):
        below_min = MIN_TIMESTAMP_MS - 1
        with pytest.raises(DateParseError, match="out of supported range"):
            parse_aspnet_date(f"/Date({below_min})/")

    def test_above_max_range_raises_error(self):
        above_max = MAX_TIMESTAMP_MS + 1
        with pytest.raises(DateParseError, match="out of supported range"):
            parse_aspnet_date(f"/Date({above_max})/")

    def test_empty_string_raises_error(self):
        with pytest.raises(DateParseError):
            parse_aspnet_date("")

    def test_error_message_includes_input(self):
        bad_input = "garbage_input"
        with pytest.raises(DateParseError, match=bad_input):
            parse_aspnet_date(bad_input)


class TestDatetimeToAspnetDate:
    """Tests for datetime_to_aspnet_date function."""

    def test_utc_datetime_no_offset_suffix(self):
        dt = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        result = datetime_to_aspnet_date(dt)
        assert result == "/Date(1704067200000)/"

    def test_positive_offset_datetime(self):
        offset = timedelta(hours=5, minutes=30)
        tz = timezone(offset)
        dt = datetime(2024, 1, 1, 5, 30, 0, tzinfo=tz)
        result = datetime_to_aspnet_date(dt)
        assert result == "/Date(1704067200000+0530)/"

    def test_negative_offset_datetime(self):
        offset = timedelta(hours=-5)
        tz = timezone(offset)
        dt = datetime(2023, 12, 31, 19, 0, 0, tzinfo=tz)
        result = datetime_to_aspnet_date(dt)
        assert result == "/Date(1704067200000-0500)/"

    def test_naive_datetime_raises_error(self):
        dt = datetime(2024, 1, 1, 0, 0, 0)
        with pytest.raises(DateParseError, match="naive datetime"):
            datetime_to_aspnet_date(dt)

    def test_round_trip_utc(self):
        original = "/Date(1704067200000)/"
        dt = parse_aspnet_date(original)
        result = datetime_to_aspnet_date(dt)
        assert result == original

    def test_round_trip_positive_offset(self):
        original = "/Date(1704067200000+0530)/"
        dt = parse_aspnet_date(original)
        result = datetime_to_aspnet_date(dt)
        assert result == original

    def test_round_trip_negative_offset(self):
        original = "/Date(1704067200000-0500)/"
        dt = parse_aspnet_date(original)
        result = datetime_to_aspnet_date(dt)
        assert result == original
