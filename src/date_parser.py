"""
ASP.NET date format parser.

Converts ASP.NET /Date(...)/ timestamps to Python datetime objects
and back for round-trip validation.
"""

import re
from datetime import datetime, timezone, timedelta


class DateParseError(ValueError):
    """Raised when date string cannot be parsed."""
    pass


# Supported range: year 2000 through year 2100
MIN_TIMESTAMP_MS = 946684800000   # 2000-01-01T00:00:00Z
MAX_TIMESTAMP_MS = 4102444800000  # 2100-01-01T00:00:00Z

# Pattern: /Date(milliseconds)/ or /Date(milliseconds±HHMM)/
ASPNET_DATE_PATTERN = re.compile(
    r'^/Date\((-?\d+)([+-]\d{4})?\)/$'
)


def parse_aspnet_date(date_string: str) -> datetime:
    """
    Convert ASP.NET date string to timezone-aware Python datetime.

    Formats supported:
        /Date(1234567890000)/        -> UTC datetime
        /Date(1234567890000+0530)/   -> datetime with +05:30 offset
        /Date(1234567890000-0500)/   -> datetime with -05:00 offset

    Args:
        date_string: Raw ASP.NET date string.

    Returns:
        Timezone-aware datetime object.

    Raises:
        DateParseError: If format is invalid or date out of range.
    """
    match = ASPNET_DATE_PATTERN.match(date_string)
    if not match:
        raise DateParseError(
            f"Invalid ASP.NET date format: '{date_string}'"
        )

    timestamp_ms = int(match.group(1))
    offset_str = match.group(2)

    # Validate timestamp range
    if timestamp_ms < MIN_TIMESTAMP_MS or timestamp_ms > MAX_TIMESTAMP_MS:
        raise DateParseError(
            f"Date out of supported range (2000-2100): "
            f"timestamp {timestamp_ms} ms"
        )

    # Convert milliseconds to seconds
    timestamp_s = timestamp_ms / 1000.0

    if offset_str:
        # Parse ±HHMM offset
        sign = 1 if offset_str[0] == '+' else -1
        hours = int(offset_str[1:3])
        minutes = int(offset_str[3:5])
        offset = timedelta(hours=sign * hours, minutes=sign * minutes)
        tz = timezone(offset)
    else:
        # No offset means UTC
        tz = timezone.utc

    # Create datetime from UTC timestamp, then convert to target timezone
    dt_utc = datetime.fromtimestamp(timestamp_s, tz=timezone.utc)
    return dt_utc.astimezone(tz)


def datetime_to_aspnet_date(dt: datetime) -> str:
    """
    Convert Python datetime back to ASP.NET date format.
    Used for round-trip validation.

    Args:
        dt: Timezone-aware datetime object.

    Returns:
        ASP.NET date string in /Date(ms)/ or /Date(ms±HHMM)/ format.

    Raises:
        DateParseError: If datetime is not timezone-aware.
    """
    if dt.tzinfo is None:
        raise DateParseError(
            "Cannot convert naive datetime to ASP.NET date format. "
            "Datetime must be timezone-aware."
        )

    # Convert to UTC timestamp in milliseconds using integer arithmetic
    # to avoid floating-point precision loss from dt.timestamp() * 1000
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = dt - epoch
    # Use timedelta's integer components for exact arithmetic
    # delta.days * 86400000 + delta.seconds * 1000 + delta.microseconds // 1000
    timestamp_ms = (
        delta.days * 86_400_000
        + delta.seconds * 1000
        + delta.microseconds // 1000
    )

    # Get the UTC offset
    offset = dt.utcoffset()

    if offset is None or offset == timedelta(0):
        # UTC - no offset suffix
        return f"/Date({timestamp_ms})/"
    else:
        # Format offset as ±HHMM
        total_seconds = int(offset.total_seconds())
        sign = '+' if total_seconds >= 0 else '-'
        abs_seconds = abs(total_seconds)
        hours = abs_seconds // 3600
        minutes = (abs_seconds % 3600) // 60
        return f"/Date({timestamp_ms}{sign}{hours:02d}{minutes:02d})/"
