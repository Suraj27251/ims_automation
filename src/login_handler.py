"""Login handler for IMS Data Fetcher.

Automates ASP.NET form-based login with hidden token extraction,
including __VIEWSTATE, __VIEWSTATEGENERATOR, __EVENTVALIDATION,
and anti-forgery tokens.
"""

import logging
from typing import TYPE_CHECKING, Dict

from bs4 import BeautifulSoup

if TYPE_CHECKING:
    from src.config_loader import AppConfig
    from src.session_manager import SessionManager

logger = logging.getLogger(__name__)


class LoginError(Exception):
    """Raised when login fails."""

    pass


class LoginParsingError(LoginError):
    """Raised when login page HTML cannot be parsed for tokens."""

    pass


class LoginHandler:
    """Automates ASP.NET form-based login with hidden token extraction.

    Performs the full login flow:
    1. GET login page to extract hidden form tokens
    2. POST credentials + tokens to login endpoint
    3. Validate response contains session cookies
    """

    # Default form field names for ASP.NET login forms
    USERNAME_FIELD = "txtUserName"
    PASSWORD_FIELD = "txtPassword"

    def __init__(self, session_manager: "SessionManager", config: "AppConfig"):
        """Initialize LoginHandler.

        Args:
            session_manager: SessionManager instance for HTTP requests.
            config: AppConfig instance with login credentials and settings.
        """
        self._session_manager = session_manager
        self._config = config

    def authenticate(self) -> None:
        """Perform full login flow.

        1. GET login page to extract hidden tokens
        2. POST credentials + tokens to login endpoint
        3. Validate response contains session cookies

        Raises:
            LoginError: If authentication fails (401/403 or no session cookie).
            LoginParsingError: If token extraction fails.
        """
        login_url = self._config.login_url
        logger.info("Starting authentication flow for: %s", login_url)

        # Step 1: GET login page to extract hidden tokens
        logger.debug("Fetching login page to extract hidden fields")
        get_response = self._session_manager.session.get(
            login_url,
            timeout=(
                self._config.connection_timeout,
                self._config.read_timeout,
            ),
        )

        # Extract hidden fields from the login page HTML
        hidden_fields = self._extract_hidden_fields(get_response.text)
        logger.debug(
            "Extracted %d hidden fields from login page", len(hidden_fields)
        )

        # Step 2: POST credentials + tokens to login endpoint
        payload = {
            **hidden_fields,
            self.USERNAME_FIELD: self._config.username,
            self.PASSWORD_FIELD: self._config.password,
        }

        logger.debug("Submitting login POST request")
        post_response = self._session_manager.session.post(
            login_url,
            data=payload,
            timeout=(
                self._config.connection_timeout,
                self._config.read_timeout,
            ),
            allow_redirects=True,
        )

        # Step 3: Validate response
        self._validate_login_response(post_response)
        logger.info("Authentication successful for: %s", login_url)

    def _extract_hidden_fields(self, html: str) -> Dict[str, str]:
        """Parse HTML and extract all hidden input field name/value pairs.

        Targets: __VIEWSTATE, __VIEWSTATEGENERATOR, __EVENTVALIDATION,
                 __RequestVerificationToken, and any other hidden inputs.

        Args:
            html: Raw HTML string from the login page.

        Returns:
            Dictionary mapping hidden field names to their values.

        Raises:
            LoginParsingError: If HTML parsing fails.
        """
        try:
            soup = BeautifulSoup(html, "html.parser")
            hidden_inputs = soup.find_all("input", attrs={"type": "hidden"})

            fields: Dict[str, str] = {}
            for input_tag in hidden_inputs:
                name = input_tag.get("name")
                value = input_tag.get("value", "")
                if name:
                    fields[name] = value

            return fields

        except Exception as e:
            # Include first 500 chars of response for diagnostics
            response_preview = html[:500] if html else "(empty response)"
            raise LoginParsingError(
                f"Failed to parse login page HTML from "
                f"{self._config.login_url}: {e}. "
                f"Response preview: {response_preview}"
            ) from e

    def _validate_login_response(self, response) -> None:
        """Validate that login response indicates success.

        Checks:
        - Status code is 200
        - Response contains a session cookie (Set-Cookie header)

        Args:
            response: The HTTP response from the login POST request.

        Raises:
            LoginError: If validation fails (auth failure or no session cookie).
        """
        login_url = self._config.login_url

        # Check for explicit authentication failure status codes
        if response.status_code in (401, 403):
            raise LoginError(
                f"Authentication failed for {login_url}: "
                f"received HTTP {response.status_code}"
            )

        # Check for successful status code
        if response.status_code != 200:
            raise LoginError(
                f"Login request to {login_url} returned unexpected "
                f"status code: {response.status_code}"
            )

        # Check for session cookie in the response cookies
        # ASP.NET typically sets ASP.NET_SessionId or .ASPXAUTH cookies
        has_session_cookie = len(response.cookies) > 0

        # Also check if the session manager's session has cookies set
        # (cookies may have been set during redirects)
        if not has_session_cookie:
            has_session_cookie = len(
                self._session_manager.session.cookies
            ) > 0

        if not has_session_cookie:
            raise LoginError(
                f"Authentication failed for {login_url}: "
                f"HTTP 200 received but no session cookie was set"
            )
