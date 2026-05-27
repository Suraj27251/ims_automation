"""Unit tests for login_handler module."""

from unittest.mock import MagicMock, patch, PropertyMock

import pytest
import requests

from src.login_handler import LoginError, LoginHandler, LoginParsingError


# --- Sample HTML fixtures ---

SAMPLE_ASPNET_LOGIN_PAGE = """
<!DOCTYPE html>
<html>
<head><title>Login</title></head>
<body>
<form method="post" action="/Login.aspx">
    <input type="hidden" name="__VIEWSTATE" value="abc123viewstate" />
    <input type="hidden" name="__VIEWSTATEGENERATOR" value="DEADBEEF" />
    <input type="hidden" name="__EVENTVALIDATION" value="eventval456" />
    <input type="hidden" name="__RequestVerificationToken" value="antiforgery789" />
    <input type="text" name="txtUserName" />
    <input type="password" name="txtPassword" />
    <input type="submit" value="Login" />
</form>
</body>
</html>
"""

SAMPLE_MINIMAL_LOGIN_PAGE = """
<html>
<body>
<form>
    <input type="hidden" name="__VIEWSTATE" value="simplestate" />
    <input type="text" name="txtUserName" />
    <input type="password" name="txtPassword" />
</form>
</body>
</html>
"""

SAMPLE_NO_HIDDEN_FIELDS_PAGE = """
<html>
<body>
<form>
    <input type="text" name="txtUserName" />
    <input type="password" name="txtPassword" />
</form>
</body>
</html>
"""


def _make_config(
    login_url="https://admin.example.com/Login.aspx",
    username="testuser",
    password="testpass",
    connection_timeout=30,
    read_timeout=60,
):
    """Create a mock AppConfig with the given values."""
    config = MagicMock()
    config.login_url = login_url
    config.username = username
    config.password = password
    config.connection_timeout = connection_timeout
    config.read_timeout = read_timeout
    return config


def _make_session_manager(session=None):
    """Create a mock SessionManager with an optional mock session."""
    sm = MagicMock()
    if session is None:
        session = MagicMock()
    type(sm).session = PropertyMock(return_value=session)
    return sm


class TestAuthenticate:
    """Tests for LoginHandler.authenticate() full login flow."""

    def test_successful_login_flow(self):
        """Test successful login: GET page, extract tokens, POST credentials, validate."""
        config = _make_config()
        mock_session = MagicMock()
        sm = _make_session_manager(session=mock_session)

        # GET response returns login page HTML with hidden fields
        get_response = MagicMock()
        get_response.text = SAMPLE_ASPNET_LOGIN_PAGE

        # POST response returns 200 with session cookies
        post_response = MagicMock()
        post_response.status_code = 200
        post_response.cookies = {"ASP.NET_SessionId": "abc123"}

        mock_session.get.return_value = get_response
        mock_session.post.return_value = post_response

        handler = LoginHandler(sm, config)
        handler.authenticate()

        # Verify GET was called with login URL and timeout
        mock_session.get.assert_called_once_with(
            config.login_url,
            timeout=(config.connection_timeout, config.read_timeout),
        )

        # Verify POST was called with hidden fields + credentials
        post_call_kwargs = mock_session.post.call_args
        posted_data = post_call_kwargs[1]["data"] if "data" in post_call_kwargs[1] else post_call_kwargs[0][1] if len(post_call_kwargs[0]) > 1 else post_call_kwargs[1].get("data")

        # Check credentials are in the payload
        assert posted_data["txtUserName"] == "testuser"
        assert posted_data["txtPassword"] == "testpass"

        # Check hidden fields are in the payload
        assert posted_data["__VIEWSTATE"] == "abc123viewstate"
        assert posted_data["__VIEWSTATEGENERATOR"] == "DEADBEEF"
        assert posted_data["__EVENTVALIDATION"] == "eventval456"
        assert posted_data["__RequestVerificationToken"] == "antiforgery789"

    def test_authenticate_posts_to_login_url(self):
        """Test that POST is sent to the configured login URL."""
        config = _make_config(login_url="https://isp.example.com/auth")
        mock_session = MagicMock()
        sm = _make_session_manager(session=mock_session)

        get_response = MagicMock()
        get_response.text = SAMPLE_MINIMAL_LOGIN_PAGE

        post_response = MagicMock()
        post_response.status_code = 200
        post_response.cookies = {"session": "valid"}

        mock_session.get.return_value = get_response
        mock_session.post.return_value = post_response

        handler = LoginHandler(sm, config)
        handler.authenticate()

        # Verify POST URL
        post_call_args = mock_session.post.call_args
        assert post_call_args[0][0] == "https://isp.example.com/auth"

    def test_authenticate_uses_configured_timeout(self):
        """Test that both GET and POST use configured timeouts."""
        config = _make_config(connection_timeout=15, read_timeout=45)
        mock_session = MagicMock()
        sm = _make_session_manager(session=mock_session)

        get_response = MagicMock()
        get_response.text = SAMPLE_NO_HIDDEN_FIELDS_PAGE

        post_response = MagicMock()
        post_response.status_code = 200
        post_response.cookies = {"sid": "xyz"}

        mock_session.get.return_value = get_response
        mock_session.post.return_value = post_response

        handler = LoginHandler(sm, config)
        handler.authenticate()

        # Verify timeout on GET
        get_kwargs = mock_session.get.call_args[1]
        assert get_kwargs["timeout"] == (15, 45)

        # Verify timeout on POST
        post_kwargs = mock_session.post.call_args[1]
        assert post_kwargs["timeout"] == (15, 45)

    def test_authenticate_allows_redirects_on_post(self):
        """Test that POST request has allow_redirects=True."""
        config = _make_config()
        mock_session = MagicMock()
        sm = _make_session_manager(session=mock_session)

        get_response = MagicMock()
        get_response.text = SAMPLE_NO_HIDDEN_FIELDS_PAGE

        post_response = MagicMock()
        post_response.status_code = 200
        post_response.cookies = {"sid": "xyz"}

        mock_session.get.return_value = get_response
        mock_session.post.return_value = post_response

        handler = LoginHandler(sm, config)
        handler.authenticate()

        post_kwargs = mock_session.post.call_args[1]
        assert post_kwargs["allow_redirects"] is True


class TestExtractHiddenFields:
    """Tests for LoginHandler._extract_hidden_fields()."""

    def test_extracts_all_aspnet_hidden_fields(self):
        """Test extraction of __VIEWSTATE, __VIEWSTATEGENERATOR, __EVENTVALIDATION, and anti-forgery token."""
        config = _make_config()
        sm = _make_session_manager()
        handler = LoginHandler(sm, config)

        fields = handler._extract_hidden_fields(SAMPLE_ASPNET_LOGIN_PAGE)

        assert fields["__VIEWSTATE"] == "abc123viewstate"
        assert fields["__VIEWSTATEGENERATOR"] == "DEADBEEF"
        assert fields["__EVENTVALIDATION"] == "eventval456"
        assert fields["__RequestVerificationToken"] == "antiforgery789"

    def test_extracts_single_hidden_field(self):
        """Test extraction when only one hidden field exists."""
        config = _make_config()
        sm = _make_session_manager()
        handler = LoginHandler(sm, config)

        fields = handler._extract_hidden_fields(SAMPLE_MINIMAL_LOGIN_PAGE)

        assert fields == {"__VIEWSTATE": "simplestate"}

    def test_returns_empty_dict_when_no_hidden_fields(self):
        """Test returns empty dict when no hidden inputs exist."""
        config = _make_config()
        sm = _make_session_manager()
        handler = LoginHandler(sm, config)

        fields = handler._extract_hidden_fields(SAMPLE_NO_HIDDEN_FIELDS_PAGE)

        assert fields == {}

    def test_extracts_hidden_field_with_empty_value(self):
        """Test hidden field with empty value attribute is extracted."""
        html = '<form><input type="hidden" name="token" value="" /></form>'
        config = _make_config()
        sm = _make_session_manager()
        handler = LoginHandler(sm, config)

        fields = handler._extract_hidden_fields(html)

        assert fields == {"token": ""}

    def test_extracts_hidden_field_with_no_value_attribute(self):
        """Test hidden field with no value attribute defaults to empty string."""
        html = '<form><input type="hidden" name="novalue" /></form>'
        config = _make_config()
        sm = _make_session_manager()
        handler = LoginHandler(sm, config)

        fields = handler._extract_hidden_fields(html)

        assert fields == {"novalue": ""}

    def test_skips_hidden_field_without_name(self):
        """Test hidden input without name attribute is skipped."""
        html = '<form><input type="hidden" value="orphan" /><input type="hidden" name="valid" value="ok" /></form>'
        config = _make_config()
        sm = _make_session_manager()
        handler = LoginHandler(sm, config)

        fields = handler._extract_hidden_fields(html)

        assert fields == {"valid": "ok"}

    def test_extracts_multiple_arbitrary_hidden_fields(self):
        """Test extraction of arbitrary hidden fields beyond ASP.NET standard ones."""
        html = """
        <form>
            <input type="hidden" name="csrf_token" value="csrf123" />
            <input type="hidden" name="custom_field" value="custom_val" />
            <input type="hidden" name="another" value="another_val" />
        </form>
        """
        config = _make_config()
        sm = _make_session_manager()
        handler = LoginHandler(sm, config)

        fields = handler._extract_hidden_fields(html)

        assert len(fields) == 3
        assert fields["csrf_token"] == "csrf123"
        assert fields["custom_field"] == "custom_val"
        assert fields["another"] == "another_val"


class TestValidateLoginResponse:
    """Tests for LoginHandler._validate_login_response()."""

    def test_raises_login_error_on_401(self):
        """Test LoginError raised on HTTP 401 response."""
        config = _make_config()
        sm = _make_session_manager()
        handler = LoginHandler(sm, config)

        response = MagicMock()
        response.status_code = 401

        with pytest.raises(LoginError, match="HTTP 401"):
            handler._validate_login_response(response)

    def test_raises_login_error_on_403(self):
        """Test LoginError raised on HTTP 403 response."""
        config = _make_config()
        sm = _make_session_manager()
        handler = LoginHandler(sm, config)

        response = MagicMock()
        response.status_code = 403

        with pytest.raises(LoginError, match="HTTP 403"):
            handler._validate_login_response(response)

    def test_error_message_includes_login_url_on_401(self):
        """Test error message includes the login URL on auth failure."""
        config = _make_config(login_url="https://isp.example.com/Login")
        sm = _make_session_manager()
        handler = LoginHandler(sm, config)

        response = MagicMock()
        response.status_code = 401

        with pytest.raises(LoginError, match="https://isp.example.com/Login"):
            handler._validate_login_response(response)

    def test_raises_login_error_on_200_with_no_cookies(self):
        """Test LoginError raised on HTTP 200 with no session cookie set."""
        config = _make_config()
        mock_session = MagicMock()
        # No cookies on the response
        mock_session.cookies = {}
        sm = _make_session_manager(session=mock_session)
        handler = LoginHandler(sm, config)

        response = MagicMock()
        response.status_code = 200
        response.cookies = {}  # No cookies in response

        with pytest.raises(LoginError, match="no session cookie"):
            handler._validate_login_response(response)

    def test_success_when_response_has_cookies(self):
        """Test no error raised when response has cookies."""
        config = _make_config()
        sm = _make_session_manager()
        handler = LoginHandler(sm, config)

        response = MagicMock()
        response.status_code = 200
        response.cookies = {"ASP.NET_SessionId": "abc123"}

        # Should not raise
        handler._validate_login_response(response)

    def test_success_when_session_manager_has_cookies(self):
        """Test no error raised when session manager session has cookies (from redirects)."""
        config = _make_config()
        mock_session = MagicMock()
        # Session has cookies (set during redirects)
        mock_session.cookies = {"ASP.NET_SessionId": "redirect_cookie"}
        sm = _make_session_manager(session=mock_session)
        handler = LoginHandler(sm, config)

        response = MagicMock()
        response.status_code = 200
        response.cookies = {}  # No cookies directly on response

        # Should not raise because session manager has cookies
        handler._validate_login_response(response)

    def test_raises_login_error_on_unexpected_status_code(self):
        """Test LoginError raised on unexpected status code (e.g., 500)."""
        config = _make_config()
        sm = _make_session_manager()
        handler = LoginHandler(sm, config)

        response = MagicMock()
        response.status_code = 500

        with pytest.raises(LoginError, match="unexpected"):
            handler._validate_login_response(response)


class TestLoginParsingError:
    """Tests for LoginParsingError on malformed HTML."""

    def test_parsing_error_includes_response_preview(self):
        """Test LoginParsingError includes first 500 chars of response."""
        config = _make_config()
        sm = _make_session_manager()
        handler = LoginHandler(sm, config)

        # Force BeautifulSoup to raise by patching it
        with patch("src.login_handler.BeautifulSoup", side_effect=Exception("parse error")):
            with pytest.raises(LoginParsingError) as exc_info:
                handler._extract_hidden_fields("<html>some content</html>")

        error_msg = str(exc_info.value)
        assert "some content" in error_msg

    def test_parsing_error_truncates_long_response(self):
        """Test LoginParsingError truncates response to 500 chars."""
        config = _make_config()
        sm = _make_session_manager()
        handler = LoginHandler(sm, config)

        long_html = "x" * 1000

        with patch("src.login_handler.BeautifulSoup", side_effect=Exception("parse error")):
            with pytest.raises(LoginParsingError) as exc_info:
                handler._extract_hidden_fields(long_html)

        error_msg = str(exc_info.value)
        # The preview should be at most 500 chars of the original
        assert "x" * 500 in error_msg
        # Should not contain the full 1000 chars
        assert "x" * 501 not in error_msg

    def test_parsing_error_handles_empty_response(self):
        """Test LoginParsingError handles empty HTML gracefully."""
        config = _make_config()
        sm = _make_session_manager()
        handler = LoginHandler(sm, config)

        with patch("src.login_handler.BeautifulSoup", side_effect=Exception("parse error")):
            with pytest.raises(LoginParsingError) as exc_info:
                handler._extract_hidden_fields("")

        error_msg = str(exc_info.value)
        assert "(empty response)" in error_msg

    def test_parsing_error_includes_login_url(self):
        """Test LoginParsingError includes the login URL for diagnostics."""
        config = _make_config(login_url="https://admin.isp.com/Login")
        sm = _make_session_manager()
        handler = LoginHandler(sm, config)

        with patch("src.login_handler.BeautifulSoup", side_effect=Exception("parse error")):
            with pytest.raises(LoginParsingError) as exc_info:
                handler._extract_hidden_fields("<html></html>")

        error_msg = str(exc_info.value)
        assert "https://admin.isp.com/Login" in error_msg

    def test_login_parsing_error_is_subclass_of_login_error(self):
        """Test LoginParsingError inherits from LoginError."""
        assert issubclass(LoginParsingError, LoginError)


class TestRetryBehaviorOnNetworkErrors:
    """Tests for retry behavior when network errors occur during authenticate()."""

    def test_get_request_network_error_propagates(self):
        """Test that network error on GET request propagates to caller."""
        config = _make_config()
        mock_session = MagicMock()
        sm = _make_session_manager(session=mock_session)

        mock_session.get.side_effect = requests.ConnectionError("Connection refused")

        handler = LoginHandler(sm, config)

        with pytest.raises(requests.ConnectionError):
            handler.authenticate()

    def test_post_request_network_error_propagates(self):
        """Test that network error on POST request propagates to caller."""
        config = _make_config()
        mock_session = MagicMock()
        sm = _make_session_manager(session=mock_session)

        get_response = MagicMock()
        get_response.text = SAMPLE_MINIMAL_LOGIN_PAGE
        mock_session.get.return_value = get_response
        mock_session.post.side_effect = requests.Timeout("Read timed out")

        handler = LoginHandler(sm, config)

        with pytest.raises(requests.Timeout):
            handler.authenticate()

    def test_get_request_timeout_propagates(self):
        """Test that timeout on GET request propagates to caller."""
        config = _make_config()
        mock_session = MagicMock()
        sm = _make_session_manager(session=mock_session)

        mock_session.get.side_effect = requests.Timeout("Connection timed out")

        handler = LoginHandler(sm, config)

        with pytest.raises(requests.Timeout):
            handler.authenticate()


class TestFieldConstants:
    """Tests for LoginHandler field name constants."""

    def test_username_field_constant(self):
        """Test USERNAME_FIELD is 'txtUserName'."""
        assert LoginHandler.USERNAME_FIELD == "txtUserName"

    def test_password_field_constant(self):
        """Test PASSWORD_FIELD is 'txtPassword'."""
        assert LoginHandler.PASSWORD_FIELD == "txtPassword"

    def test_credentials_use_field_constants(self):
        """Test authenticate() uses USERNAME_FIELD and PASSWORD_FIELD constants in payload."""
        config = _make_config(username="admin", password="secret")
        mock_session = MagicMock()
        sm = _make_session_manager(session=mock_session)

        get_response = MagicMock()
        get_response.text = SAMPLE_NO_HIDDEN_FIELDS_PAGE

        post_response = MagicMock()
        post_response.status_code = 200
        post_response.cookies = {"sid": "valid"}

        mock_session.get.return_value = get_response
        mock_session.post.return_value = post_response

        handler = LoginHandler(sm, config)
        handler.authenticate()

        post_kwargs = mock_session.post.call_args[1]
        posted_data = post_kwargs["data"]

        assert "txtUserName" in posted_data
        assert "txtPassword" in posted_data
        assert posted_data["txtUserName"] == "admin"
        assert posted_data["txtPassword"] == "secret"
