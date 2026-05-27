"""Property-based tests for diagnostics module.

Uses hypothesis to validate universal properties of credential masking.
"""

import pytest
from hypothesis import given, strategies as st, settings, assume

from src.diagnostics import _mask_credentials, _MASK_VALUE


# --- Strategies for credential generation ---

# Sensitive key name fragments (case variations tested via mixing)
_sensitive_fragments = st.sampled_from(["password", "cookie", "token", "auth"])

# Generate key names that contain a sensitive fragment
_sensitive_key = st.builds(
    lambda prefix, fragment, suffix: f"{prefix}{fragment}{suffix}",
    prefix=st.sampled_from(["", "user_", "session_", "my_", "x_"]),
    fragment=_sensitive_fragments,
    suffix=st.sampled_from(["", "_value", "_hash", "_key", "123"]),
)

# Generate key names with mixed case sensitive fragments
_sensitive_key_mixed_case = st.builds(
    lambda prefix, fragment, suffix: f"{prefix}{fragment}{suffix}",
    prefix=st.sampled_from(["", "User", "Session", "My", "X"]),
    fragment=st.sampled_from([
        "Password", "PASSWORD", "passWORD",
        "Cookie", "COOKIE", "cookIE",
        "Token", "TOKEN", "toKEN",
        "Auth", "AUTH", "auTH",
    ]),
    suffix=st.sampled_from(["", "_Value", "_Hash", "Key", "123"]),
)

# Generate non-sensitive key names (no password/cookie/token/auth substring)
_non_sensitive_key = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz_",
    min_size=1,
    max_size=20,
).filter(
    lambda k: all(
        frag not in k.lower()
        for frag in ("password", "cookie", "token", "auth")
    )
)

# Generate credential values (non-empty strings that won't collide with the mask)
_credential_value = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),
        blacklist_characters="\x00",
    ),
    min_size=1,
    max_size=100,
).filter(lambda v: v != _MASK_VALUE)


class TestCredentialMaskingProperty:
    """Property 15: Credential Masking in Output

    **Validates: Requirements 14.5, 15.4**

    For any password, session cookie value, or authentication token present
    in the application state, all log output and diagnostic file output
    SHALL NOT contain the literal credential value.
    """

    @given(
        key=_sensitive_key,
        value=_credential_value,
    )
    @settings(max_examples=200)
    def test_sensitive_values_masked_with_standard_keys(self, key, value):
        """Credential values under keys containing 'password', 'cookie',
        'token', or 'auth' are never present in masked output.

        **Validates: Requirements 14.5, 15.4**
        """
        data = {key: value}
        masked = _mask_credentials(data)

        # The original credential value must not appear in the output
        assert masked[key] != value, (
            f"Credential value for key '{key}' was not masked: {value}"
        )
        assert masked[key] == _MASK_VALUE, (
            f"Expected masked value to be '{_MASK_VALUE}', got '{masked[key]}'"
        )

    @given(
        key=_sensitive_key_mixed_case,
        value=_credential_value,
    )
    @settings(max_examples=200)
    def test_sensitive_values_masked_case_insensitive(self, key, value):
        """Credential masking is case-insensitive for key matching.

        **Validates: Requirements 14.5, 15.4**
        """
        data = {key: value}
        masked = _mask_credentials(data)

        assert masked[key] != value, (
            f"Credential value for key '{key}' was not masked: {value}"
        )
        assert masked[key] == _MASK_VALUE, (
            f"Expected masked value to be '{_MASK_VALUE}', got '{masked[key]}'"
        )

    @given(
        non_sensitive_key=_non_sensitive_key,
        non_sensitive_value=_credential_value,
        sensitive_key=_sensitive_key,
        sensitive_value=_credential_value,
    )
    @settings(max_examples=200)
    def test_only_sensitive_keys_are_masked(self, non_sensitive_key,
                                            non_sensitive_value,
                                            sensitive_key,
                                            sensitive_value):
        """Non-sensitive keys preserve their values while sensitive keys are masked.

        **Validates: Requirements 14.5, 15.4**
        """
        data = {
            non_sensitive_key: non_sensitive_value,
            sensitive_key: sensitive_value,
        }
        masked = _mask_credentials(data)

        # Non-sensitive value is preserved
        assert masked[non_sensitive_key] == non_sensitive_value, (
            f"Non-sensitive key '{non_sensitive_key}' value was incorrectly modified"
        )
        # Sensitive value is masked
        assert masked[sensitive_key] == _MASK_VALUE, (
            f"Sensitive key '{sensitive_key}' value was not masked"
        )

    @given(
        outer_key=_non_sensitive_key,
        inner_key=_sensitive_key,
        inner_value=_credential_value,
    )
    @settings(max_examples=200)
    def test_nested_sensitive_values_masked(self, outer_key, inner_key, inner_value):
        """Credential values in nested dictionaries are also masked.

        **Validates: Requirements 14.5, 15.4**
        """
        data = {outer_key: {inner_key: inner_value}}
        masked = _mask_credentials(data)

        # The nested credential value must not appear in the output
        assert masked[outer_key][inner_key] == _MASK_VALUE, (
            f"Nested credential value for '{outer_key}.{inner_key}' was not masked"
        )

    @given(
        data=st.dictionaries(
            keys=_sensitive_key,
            values=st.text(
                alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&",
                min_size=8,
                max_size=50,
            ).filter(lambda v: v != _MASK_VALUE),
            min_size=1,
            max_size=5,
        ),
    )
    @settings(max_examples=200)
    def test_no_credential_value_leaks_in_masked_output(self, data):
        """No original credential value appears anywhere in the masked
        dictionary values.

        **Validates: Requirements 14.5, 15.4**
        """
        masked = _mask_credentials(data)

        for key, original_value in data.items():
            # The masked value must be the mask constant, not the original
            assert masked[key] == _MASK_VALUE, (
                f"Credential value for key '{key}' was not properly masked"
            )
            # Verify original value does not appear in any masked dict value
            for masked_value in masked.values():
                assert original_value not in str(masked_value), (
                    f"Credential value '{original_value}' for key '{key}' "
                    f"leaked into masked output value: {masked_value}"
                )
