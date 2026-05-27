"""Property-based tests for config_loader module.

Uses hypothesis to validate universal properties of configuration validation.
"""

import pytest
from hypothesis import given, strategies as st, assume, settings

from src.config_loader import validate_url


# --- Strategies for URL generation ---

# Generate a valid hostname label (1-63 chars, alphanumeric)
_host_label = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
    min_size=1,
    max_size=10,
)

# Generate a valid hostname (one or more labels joined by dots)
_valid_host = st.lists(
    _host_label,
    min_size=1,
    max_size=3,
).map(lambda labels: ".".join(labels))

# Valid schemes
_valid_scheme = st.sampled_from(["http", "https"])

# Optional path component
_optional_path = st.one_of(
    st.just(""),
    st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz0123456789/-_.",
        min_size=1,
        max_size=20,
    ).map(lambda p: "/" + p),
)


class TestURLValidationProperty:
    """Property 11: URL Validation

    **Validates: Requirements 12.5, 12.6**

    For any string that does not begin with `http://` or `https://` followed
    by a non-empty host component, the Config_Loader SHALL reject it as an
    invalid login URL. Conversely, for any string beginning with `http://` or
    `https://` followed by a valid host, it SHALL be accepted.
    """

    @given(
        scheme=_valid_scheme,
        host=_valid_host,
        path=_optional_path,
    )
    @settings(max_examples=200)
    def test_valid_urls_are_accepted(self, scheme, host, path):
        """Valid URLs with http/https scheme and non-empty host are accepted.

        **Validates: Requirements 12.5**
        """
        url = f"{scheme}://{host}{path}"
        assert validate_url(url) is True, (
            f"Expected valid URL to be accepted: {url}"
        )

    @given(
        scheme=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz",
            min_size=1,
            max_size=10,
        ).filter(lambda s: s not in ("http", "https")),
        host=_valid_host,
    )
    @settings(max_examples=200)
    def test_invalid_scheme_urls_are_rejected(self, scheme, host):
        """URLs without http or https scheme are rejected.

        **Validates: Requirements 12.5, 12.6**
        """
        url = f"{scheme}://{host}"
        assert validate_url(url) is False, (
            f"Expected URL with invalid scheme to be rejected: {url}"
        )

    @given(
        scheme=_valid_scheme,
    )
    @settings(max_examples=50)
    def test_empty_host_urls_are_rejected(self, scheme):
        """URLs with empty host component are rejected.

        **Validates: Requirements 12.5, 12.6**
        """
        url = f"{scheme}://"
        assert validate_url(url) is False, (
            f"Expected URL with empty host to be rejected: {url}"
        )

    @given(
        text=st.text(min_size=0, max_size=100).filter(
            lambda s: not s.startswith("http://") and not s.startswith("https://")
        ),
    )
    @settings(max_examples=200)
    def test_strings_without_http_scheme_are_rejected(self, text):
        """Arbitrary strings not starting with http:// or https:// are rejected.

        **Validates: Requirements 12.5, 12.6**
        """
        assert validate_url(text) is False, (
            f"Expected string without http/https scheme to be rejected: {repr(text)}"
        )

    @given(
        scheme=_valid_scheme,
        path=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789/-_.",
            min_size=1,
            max_size=20,
        ),
    )
    @settings(max_examples=100)
    def test_scheme_with_only_path_no_host_rejected(self, scheme, path):
        """URLs with scheme but path where host should be (triple slash) are rejected.

        **Validates: Requirements 12.5, 12.6**

        Note: urlparse treats scheme:///path as empty host, which should be rejected.
        """
        url = f"{scheme}:///{path}"
        assert validate_url(url) is False, (
            f"Expected URL with empty host (triple slash) to be rejected: {url}"
        )


# --- Property 12: Invalid Date Format Rejection ---

from src.config_loader import validate_date_format

# Valid characters for date format strings
VALID_DATE_FORMAT_CHARS = set("yMd/-")


class TestInvalidDateFormatRejection:
    """Property 12: Invalid Date Format Rejection

    **Validates: Requirements 8.3**

    For any string containing characters other than the valid date format
    specifiers (y, M, d) and separators (/, -), the Config_Loader SHALL
    raise a validation error (return False from validate_date_format).
    """

    @given(
        invalid_format=st.text(
            alphabet=st.characters(),
            min_size=1,
        ).filter(lambda s: not all(c in VALID_DATE_FORMAT_CHARS for c in s))
    )
    @settings(max_examples=200)
    def test_invalid_date_format_rejected(self, invalid_format: str):
        """Any string with at least one character not in {y, M, d, /, -}
        must be rejected by validate_date_format().

        **Validates: Requirements 8.3**
        """
        assert validate_date_format(invalid_format) is False
