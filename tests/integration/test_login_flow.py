"""Integration test for full login flow.

Tests the complete login flow with mocked HTTP server using the `responses` library:
1. Mock GET to login URL returning HTML with hidden fields (__VIEWSTATE, etc.)
2. Mock POST to login URL returning 200 with Set-Cookie header
3. Create real SessionManager, real LoginHandler, real AppConfig
4. Call login_handler.authenticate() and verify it succeeds
5. Verify the POST was called with correct payload (hidden fields + credentials)

Validates: Requirements 1.1, 1.2, 2.1, 2.2, 2.3
"""

import os
from unittest.mock import patch

import pytest
import responses

from src.config_loader import AppConfig
from src.login_handler import LoginError, LoginHandler, LoginParsingError
from src.session_manager import SessionManager


# --- Test Constants ---

TEST_LOGIN_URL = "https://admin.example-isp.com/Login.aspx"
TEST_USERNAME = "operator"
TEST_PASSWORD = "s3cur3p@ss"

# Realistic ASP.NET login page HTML with hidden fields
ASPNET_LOGIN_PAGE_HTML = """<!DOCTYPE html>
<html>
<head><title>ISP Admin - Login</title></head>
<body>
<form method="post" action="/Login.aspx" id="form1">
    <input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="/wEPDwUKMTI2NzM0NTY3OA==" />
    <input type="hidden" name="__VIEWSTATEGENERATOR" id="__VIEWSTATEGENERATOR" value="CA0B0334" />
    <input type="hidden" name="__EVENTVALIDATION" id="__EVENTVALIDATION" value="/wEdAAQz8Hy+validation+token==" />
    <input type="hidden" name="__RequestVerificationToken" value="CfDJ8N_antiforgery_token_value" />
    <div class="login-form">
        <input type="text" name="txtUserName" id="txtUserName" />
        <input type="password" name="txtPassword" id="txtPassword" />
        <input type="submit" name="btnLogin" value="Login" />
    </div>
</form>
</body>
</html>"""

# Minimal login page with only __VIEWSTATE
MINIMAL_LOGIN_PAGE_HTML = """<html>
<body>
<form method="post" action="/Login.aspx">
    <input type="hidden" name="__VIEWSTATE" value="minimal_viewstate_value" />
    <input type="text" name="txtUserName" />
    <input type="password" name="txtPassword" />
    <input type="submit" value="Login" />
</form>
</body>
</html>"""


def _make_test_config(
    login_url=TEST_LOGIN_URL,
    username=TEST_USERNAME,
    password=TEST_PASSWORD,
) -> AppConfig:
    """Create a real AppConfig with test values."""
    return AppConfig(
        login_url=login_url,
        username=username,
        password=password,
        connection_timeout=30,
        read_timeout=60,
        retry_count=2,
    )


class TestFullLoginFlow:
    """Integration tests for the complete login flow."""

    @responses.activate
    def test_successful_login_with_all_aspnet_tokens(self):
        """Test complete login flow: GET page → extract tokens → POST credentials → session validated.

        Validates: Requirements 1.1, 1.2, 2.1, 2.2, 2.3
        """
        # Mock GET request to login page returning HTML with hidden fields
        responses.add(
            responses.GET,
            TEST_LOGIN_URL,
            body=ASPNET_LOGIN_PAGE_HTML,
            status=200,
            content_type="text/html",
        )

        # Mock POST request to login URL returning 200 with session cookie
        responses.add(
            responses.POST,
            TEST_LOGIN_URL,
            body="<html><body>Welcome</body></html>",
            status=200,
            content_type="text/html",
            headers={"Set-Cookie": "ASP.NET_SessionId=abc123def456; path=/; HttpOnly"},
        )

        # Create real components
        config = _make_test_config()
        session_manager = SessionManager(
            connection_timeout=config.connection_timeout,
            read_timeout=config.read_timeout,
            max_retries=config.retry_count,
        )
        login_handler = LoginHandler(session_manager, config)

        # Execute the full login flow
        login_handler.authenticate()

        # Verify GET was called first (Requirement 2.1)
        assert len(responses.calls) == 2
        assert responses.calls[0].request.method == "GET"
        assert responses.calls[0].request.url == TEST_LOGIN_URL

        # Verify POST was called second
        assert responses.calls[1].request.method == "POST"
        assert responses.calls[1].request.url == TEST_LOGIN_URL

        # Verify POST payload contains hidden fields (Requirement 2.2, 2.3)
        post_body = responses.calls[1].request.body
        assert "__VIEWSTATE=%2FwEPDwUKMTI2NzM0NTY3OA%3D%3D" in post_body
        assert "__VIEWSTATEGENERATOR=CA0B0334" in post_body
        assert "__EVENTVALIDATION=%2FwEdAAQz8Hy%2Bvalidation%2Btoken%3D%3D" in post_body
        assert "__RequestVerificationToken=CfDJ8N_antiforgery_token_value" in post_body

        # Verify POST payload contains credentials (Requirement 1.1)
        assert "txtUserName=operator" in post_body
        assert "txtPassword=s3cur3p%40ss" in post_body

    @responses.activate
    def test_successful_login_with_minimal_hidden_fields(self):
        """Test login flow with only __VIEWSTATE hidden field.

        Validates: Requirements 1.1, 2.2
        """
        # Mock GET returning minimal login page
        responses.add(
            responses.GET,
            TEST_LOGIN_URL,
            body=MINIMAL_LOGIN_PAGE_HTML,
            status=200,
            content_type="text/html",
        )

        # Mock POST returning success with cookie
        responses.add(
            responses.POST,
            TEST_LOGIN_URL,
            body="<html><body>Dashboard</body></html>",
            status=200,
            content_type="text/html",
            headers={"Set-Cookie": ".ASPXAUTH=authtoken123; path=/; HttpOnly"},
        )

        config = _make_test_config()
        session_manager = SessionManager(
            connection_timeout=config.connection_timeout,
            read_timeout=config.read_timeout,
            max_retries=config.retry_count,
        )
        login_handler = LoginHandler(session_manager, config)

        # Should succeed without error
        login_handler.authenticate()

        # Verify POST contains the viewstate and credentials
        post_body = responses.calls[1].request.body
        assert "__VIEWSTATE=minimal_viewstate_value" in post_body
        assert "txtUserName=operator" in post_body
        assert "txtPassword=s3cur3p%40ss" in post_body

    @responses.activate
    def test_login_fails_when_no_session_cookie_returned(self):
        """Test login raises LoginError when POST returns 200 but no session cookie.

        Validates: Requirement 1.3
        """
        # Mock GET returning login page
        responses.add(
            responses.GET,
            TEST_LOGIN_URL,
            body=ASPNET_LOGIN_PAGE_HTML,
            status=200,
            content_type="text/html",
        )

        # Mock POST returning 200 but NO Set-Cookie header
        responses.add(
            responses.POST,
            TEST_LOGIN_URL,
            body="<html><body>Invalid credentials</body></html>",
            status=200,
            content_type="text/html",
        )

        config = _make_test_config()
        session_manager = SessionManager(
            connection_timeout=config.connection_timeout,
            read_timeout=config.read_timeout,
            max_retries=config.retry_count,
        )
        login_handler = LoginHandler(session_manager, config)

        with pytest.raises(LoginError, match="no session cookie"):
            login_handler.authenticate()

    @responses.activate
    def test_login_fails_on_401_response(self):
        """Test login raises LoginError when POST returns 401.

        Validates: Requirement 1.3
        """
        # Mock GET returning login page
        responses.add(
            responses.GET,
            TEST_LOGIN_URL,
            body=ASPNET_LOGIN_PAGE_HTML,
            status=200,
            content_type="text/html",
        )

        # Mock POST returning 401 Unauthorized
        responses.add(
            responses.POST,
            TEST_LOGIN_URL,
            body="Unauthorized",
            status=401,
            content_type="text/html",
        )

        config = _make_test_config()
        session_manager = SessionManager(
            connection_timeout=config.connection_timeout,
            read_timeout=config.read_timeout,
            max_retries=config.retry_count,
        )
        login_handler = LoginHandler(session_manager, config)

        with pytest.raises(LoginError, match="401"):
            login_handler.authenticate()

    @responses.activate
    def test_login_fails_on_403_response(self):
        """Test login raises LoginError when POST returns 403.

        Validates: Requirement 1.3
        """
        # Mock GET returning login page
        responses.add(
            responses.GET,
            TEST_LOGIN_URL,
            body=ASPNET_LOGIN_PAGE_HTML,
            status=200,
            content_type="text/html",
        )

        # Mock POST returning 403 Forbidden
        responses.add(
            responses.POST,
            TEST_LOGIN_URL,
            body="Forbidden",
            status=403,
            content_type="text/html",
        )

        config = _make_test_config()
        session_manager = SessionManager(
            connection_timeout=config.connection_timeout,
            read_timeout=config.read_timeout,
            max_retries=config.retry_count,
        )
        login_handler = LoginHandler(session_manager, config)

        with pytest.raises(LoginError, match="403"):
            login_handler.authenticate()

    @responses.activate
    def test_get_request_precedes_post_request(self):
        """Test that GET request to login page is performed before POST.

        Validates: Requirement 2.1
        """
        responses.add(
            responses.GET,
            TEST_LOGIN_URL,
            body=ASPNET_LOGIN_PAGE_HTML,
            status=200,
            content_type="text/html",
        )

        responses.add(
            responses.POST,
            TEST_LOGIN_URL,
            body="<html>OK</html>",
            status=200,
            content_type="text/html",
            headers={"Set-Cookie": "session=valid; path=/"},
        )

        config = _make_test_config()
        session_manager = SessionManager(
            connection_timeout=config.connection_timeout,
            read_timeout=config.read_timeout,
            max_retries=config.retry_count,
        )
        login_handler = LoginHandler(session_manager, config)

        login_handler.authenticate()

        # Verify order: GET first, then POST
        assert responses.calls[0].request.method == "GET"
        assert responses.calls[1].request.method == "POST"

    @responses.activate
    def test_session_cookies_persisted_after_login(self):
        """Test that session cookies are stored in the SessionManager after login.

        Validates: Requirement 1.2
        """
        responses.add(
            responses.GET,
            TEST_LOGIN_URL,
            body=ASPNET_LOGIN_PAGE_HTML,
            status=200,
            content_type="text/html",
        )

        responses.add(
            responses.POST,
            TEST_LOGIN_URL,
            body="<html>Welcome</html>",
            status=200,
            content_type="text/html",
            headers={"Set-Cookie": "ASP.NET_SessionId=session_xyz789; path=/; HttpOnly"},
        )

        config = _make_test_config()
        session_manager = SessionManager(
            connection_timeout=config.connection_timeout,
            read_timeout=config.read_timeout,
            max_retries=config.retry_count,
        )
        login_handler = LoginHandler(session_manager, config)

        login_handler.authenticate()

        # Verify cookies are persisted in the session
        cookies = session_manager.session.cookies.get_dict()
        assert "ASP.NET_SessionId" in cookies
        assert cookies["ASP.NET_SessionId"] == "session_xyz789"

    @responses.activate
    def test_hidden_fields_included_alongside_credentials_in_post(self):
        """Test that all hidden fields are sent alongside credentials in POST payload.

        Validates: Requirement 2.3
        """
        responses.add(
            responses.GET,
            TEST_LOGIN_URL,
            body=ASPNET_LOGIN_PAGE_HTML,
            status=200,
            content_type="text/html",
        )

        responses.add(
            responses.POST,
            TEST_LOGIN_URL,
            body="<html>OK</html>",
            status=200,
            content_type="text/html",
            headers={"Set-Cookie": "sid=abc; path=/"},
        )

        config = _make_test_config(username="admin", password="pass123")
        session_manager = SessionManager(
            connection_timeout=config.connection_timeout,
            read_timeout=config.read_timeout,
            max_retries=config.retry_count,
        )
        login_handler = LoginHandler(session_manager, config)

        login_handler.authenticate()

        # Parse the POST body to verify all fields are present
        post_body = responses.calls[1].request.body

        # Hidden fields must be present
        assert "__VIEWSTATE" in post_body
        assert "__VIEWSTATEGENERATOR" in post_body
        assert "__EVENTVALIDATION" in post_body
        assert "__RequestVerificationToken" in post_body

        # Credentials must be present
        assert "txtUserName=admin" in post_body
        assert "txtPassword=pass123" in post_body

    @responses.activate
    def test_login_with_config_from_environment_variables(self):
        """Test full login flow using AppConfig loaded from environment variables.

        Validates: Requirements 1.1, 1.5
        """
        env_vars = {
            "IMS_LOGIN_URL": TEST_LOGIN_URL,
            "IMS_USERNAME": "env_user",
            "IMS_PASSWORD": "env_pass",
        }

        responses.add(
            responses.GET,
            TEST_LOGIN_URL,
            body=MINIMAL_LOGIN_PAGE_HTML,
            status=200,
            content_type="text/html",
        )

        responses.add(
            responses.POST,
            TEST_LOGIN_URL,
            body="<html>OK</html>",
            status=200,
            content_type="text/html",
            headers={"Set-Cookie": "session=env_session; path=/"},
        )

        with patch.dict(os.environ, env_vars, clear=False):
            from src.config_loader import load_config

            config = load_config()

        session_manager = SessionManager(
            connection_timeout=config.connection_timeout,
            read_timeout=config.read_timeout,
            max_retries=config.retry_count,
        )
        login_handler = LoginHandler(session_manager, config)

        login_handler.authenticate()

        # Verify credentials from env vars were used
        post_body = responses.calls[1].request.body
        assert "txtUserName=env_user" in post_body
        assert "txtPassword=env_pass" in post_body
