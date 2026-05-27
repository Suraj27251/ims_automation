"""Property-based tests for login_handler module.

Uses hypothesis to validate universal properties of login form token extraction.
"""

from unittest.mock import MagicMock

import pytest
from hypothesis import given, strategies as st, settings, assume

from src.login_handler import LoginHandler


# --- Strategies for HTML hidden field generation ---

# Generate valid HTML attribute name characters (letters, digits, hyphens, underscores)
# HTML attribute names must start with a letter or underscore
_attr_name_start = st.sampled_from(
    list("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")
)
_attr_name_rest = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-",
    min_size=0,
    max_size=30,
)

# Build a valid field name (non-empty, starts with letter or underscore)
_field_name = st.builds(
    lambda start, rest: start + rest,
    _attr_name_start,
    _attr_name_rest,
)

# Generate field values - any text that doesn't contain quotes that would break HTML
# Use printable ASCII excluding quotes and angle brackets to avoid HTML parsing issues
_field_value = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        blacklist_characters='"<>&\'',
    ),
    min_size=0,
    max_size=100,
)

# Generate a dictionary of name/value pairs for hidden fields
_hidden_fields_dict = st.dictionaries(
    keys=_field_name,
    values=_field_value,
    min_size=0,
    max_size=15,
)


def _build_html_with_hidden_fields(fields: dict) -> str:
    """Construct an HTML document with hidden input elements for the given fields."""
    hidden_inputs = []
    for name, value in fields.items():
        # Escape value for HTML attribute (handle ampersands)
        escaped_value = value.replace("&", "&amp;").replace('"', "&quot;")
        hidden_inputs.append(
            f'<input type="hidden" name="{name}" value="{escaped_value}" />'
        )

    inputs_html = "\n".join(hidden_inputs)
    return f"""<!DOCTYPE html>
<html>
<head><title>Login</title></head>
<body>
<form method="post" action="/login">
{inputs_html}
<input type="text" name="txtUserName" value="" />
<input type="password" name="txtPassword" value="" />
<input type="submit" value="Login" />
</form>
</body>
</html>"""


def _create_login_handler() -> LoginHandler:
    """Create a LoginHandler instance with mocked dependencies.

    _extract_hidden_fields only uses self._config.login_url for error messages,
    so we mock the config and session_manager.
    """
    mock_session_manager = MagicMock()
    mock_config = MagicMock()
    mock_config.login_url = "https://example.com/login"
    return LoginHandler(session_manager=mock_session_manager, config=mock_config)


class TestHiddenFormFieldExtraction:
    """Property 9: Hidden Form Field Extraction

    **Validates: Requirements 2.2**

    For any HTML document containing hidden input elements with arbitrary
    name/value pairs, the Login_Handler's extraction function SHALL return
    a dictionary containing all hidden input names mapped to their
    corresponding values.
    """

    @given(fields=_hidden_fields_dict)
    @settings(max_examples=200)
    def test_extracts_all_hidden_fields(self, fields: dict):
        """All hidden input name/value pairs in the HTML are extracted correctly.

        **Validates: Requirements 2.2**
        """
        html = _build_html_with_hidden_fields(fields)
        handler = _create_login_handler()

        result = handler._extract_hidden_fields(html)

        # The result must contain all the hidden fields we put in
        for name, value in fields.items():
            assert name in result, (
                f"Expected hidden field '{name}' to be in result, "
                f"but got keys: {list(result.keys())}"
            )
            assert result[name] == value, (
                f"Expected field '{name}' to have value '{value}', "
                f"but got '{result[name]}'"
            )

    @given(fields=_hidden_fields_dict)
    @settings(max_examples=200)
    def test_no_extra_fields_beyond_hidden_inputs(self, fields: dict):
        """The result contains only the hidden fields, no extra entries.

        **Validates: Requirements 2.2**
        """
        html = _build_html_with_hidden_fields(fields)
        handler = _create_login_handler()

        result = handler._extract_hidden_fields(html)

        # Result should have exactly the same keys as our input fields
        assert set(result.keys()) == set(fields.keys()), (
            f"Expected keys {set(fields.keys())}, got {set(result.keys())}"
        )

    @given(fields=st.dictionaries(
        keys=_field_name,
        values=_field_value,
        min_size=1,
        max_size=10,
    ))
    @settings(max_examples=100)
    def test_result_dict_size_matches_input(self, fields: dict):
        """The number of extracted fields matches the number of hidden inputs.

        **Validates: Requirements 2.2**
        """
        html = _build_html_with_hidden_fields(fields)
        handler = _create_login_handler()

        result = handler._extract_hidden_fields(html)

        assert len(result) == len(fields), (
            f"Expected {len(fields)} fields, got {len(result)}"
        )
