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

    # Common username field name patterns
    _USERNAME_PATTERNS = [
        "txtUserName", "txtUsername", "txtusername",
        "UserName", "Username", "username",
        "txtUser", "txtLogin", "txtEmail",
        "Email", "email", "Login", "login",
        "ctl00$ContentPlaceHolder1$txtUserName",
        "ctl00$MainContent$txtUserName",
    ]

    # Common password field name patterns
    _PASSWORD_PATTERNS = [
        "txtPassword", "txtpassword", "Password",
        "password", "txtPass", "pass",
        "ctl00$ContentPlaceHolder1$txtPassword",
        "ctl00$MainContent$txtPassword",
    ]

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
        3. Validate response indicates successful authentication (redirect to dashboard)
        4. Navigate to renewal page to establish ASP.NET page context

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
            "Extracted %d hidden fields from login page: %s",
            len(hidden_fields),
            list(hidden_fields.keys()),
        )

        # Extract the login button name from the form (ASP.NET requires the
        # submit button's name/value in the POST to trigger the click event)
        submit_button = self._extract_submit_button(get_response.text)

        # Extract the form action URL (may differ from the page URL)
        form_action = self._extract_form_action(get_response.text, login_url)

        # Auto-detect username and password field names from the form
        username_field, password_field = self._detect_credential_fields(
            get_response.text
        )

        # Step 2: POST credentials + tokens to login endpoint
        payload = {
            **hidden_fields,
            username_field: self._config.username,
            password_field: self._config.password,
        }

        # Add submit button to trigger ASP.NET postback event
        if submit_button:
            payload.update(submit_button)
            logger.debug("Added submit button to payload: %s", list(submit_button.keys()))
        else:
            # If no named submit button found, ASP.NET WebForms may need
            # __EVENTTARGET set to the button's UniqueID for the postback
            # to trigger the correct server-side handler
            logger.debug(
                "No named submit button found. "
                "Will rely on hidden fields for postback."
            )

        logger.debug("Submitting login POST request with %d fields to %s", len(payload), form_action)
        logger.debug("Payload keys: %s", list(payload.keys()))

        # Do NOT follow redirects — a successful login typically returns 302
        # to the dashboard. Following it would lose the redirect signal.
        # However, some ASP.NET apps return 200 with the dashboard directly.
        post_response = self._session_manager.session.post(
            form_action,
            data=payload,
            timeout=(
                self._config.connection_timeout,
                self._config.read_timeout,
            ),
            allow_redirects=False,
        )

        logger.debug(
            "Login POST response: status=%d, location=%s, set-cookies=%s",
            post_response.status_code,
            post_response.headers.get("Location", "N/A"),
            list(post_response.cookies.keys()),
        )
        logger.debug(
            "All session cookies: %s",
            list(self._session_manager.session.cookies.get_dict().keys()),
        )

        # Step 3: Validate response
        self._validate_login_response(post_response)

        # If we got a redirect (302/301), follow it to complete the login flow
        # and pick up any additional cookies set during the redirect chain
        if post_response.status_code in (301, 302, 303, 307, 308):
            redirect_url = post_response.headers.get("Location", "")
            if redirect_url:
                from urllib.parse import urljoin
                absolute_redirect = urljoin(login_url, redirect_url)
                logger.debug("Following login redirect to: %s", absolute_redirect)
                self._session_manager.session.get(
                    absolute_redirect,
                    timeout=(
                        self._config.connection_timeout,
                        self._config.read_timeout,
                    ),
                )

        # Log session cookies for diagnostics
        cookies = self._session_manager.session.cookies.get_dict()
        logger.debug(
            "Session cookies after login: %s",
            list(cookies.keys()),
        )

        # Step 4: Navigate to the renewal report page to establish page context.
        # ASP.NET MVC often requires visiting the page before its AJAX endpoints
        # will accept requests (sets server-side session state for the page).
        self._establish_page_context()

        logger.info("Authentication successful for: %s", login_url)

    def _detect_credential_fields(self, html: str) -> tuple:
        """Auto-detect the username and password field names from the login form.

        Searches for text/email inputs (username) and password inputs in the HTML,
        matching against known patterns. Falls back to class defaults if not found.

        Args:
            html: Raw HTML string from the login page.

        Returns:
            Tuple of (username_field_name, password_field_name).
        """
        try:
            soup = BeautifulSoup(html, "html.parser")

            # Detect username field
            username_field = self.USERNAME_FIELD
            for pattern in self._USERNAME_PATTERNS:
                inp = soup.find("input", attrs={"name": pattern})
                if inp:
                    username_field = pattern
                    break
            else:
                # Fallback: find any text/email input that's not hidden
                text_inputs = soup.find_all(
                    "input", attrs={"type": ["text", "email"]}
                )
                for inp in text_inputs:
                    name = inp.get("name", "")
                    if name and not name.startswith("__"):
                        username_field = name
                        break

            # Detect password field
            password_field = self.PASSWORD_FIELD
            for pattern in self._PASSWORD_PATTERNS:
                inp = soup.find("input", attrs={"name": pattern})
                if inp:
                    password_field = pattern
                    break
            else:
                # Fallback: find any password input
                pwd_inputs = soup.find_all(
                    "input", attrs={"type": "password"}
                )
                for inp in pwd_inputs:
                    name = inp.get("name", "")
                    if name:
                        password_field = name
                        break

            logger.debug(
                "Detected credential fields: username='%s', password='%s'",
                username_field,
                password_field,
            )
            return username_field, password_field

        except Exception as exc:
            logger.debug("Failed to detect credential fields: %s", exc)
            return self.USERNAME_FIELD, self.PASSWORD_FIELD

    def _extract_submit_button(self, html: str) -> Dict[str, str]:
        """Extract the login submit button name/value from the form.

        ASP.NET WebForms requires the submit button's name in the POST data
        to trigger the server-side Click event handler. Without it, the form
        submission is treated as a regular postback without any button click,
        and the login logic never executes.

        Args:
            html: Raw HTML string from the login page.

        Returns:
            Dictionary with button name/value, or empty dict if not found.
        """
        try:
            soup = BeautifulSoup(html, "html.parser")

            # Look for submit buttons - try multiple patterns
            # Pattern 1: <input type="submit">
            submit_inputs = soup.find_all("input", attrs={"type": "submit"})
            for btn in submit_inputs:
                name = btn.get("name")
                if name:
                    return {name: btn.get("value", "")}

            # Pattern 2: <button type="submit">
            submit_buttons = soup.find_all("button", attrs={"type": "submit"})
            for btn in submit_buttons:
                name = btn.get("name")
                if name:
                    return {name: btn.get("value", "")}

            # Pattern 3: Look for common ASP.NET login button patterns
            # e.g., btnLogin, btnSubmit, Button1
            for pattern in ["btnLogin", "btnSubmit", "Button1", "btn_login", "LoginButton"]:
                btn = soup.find("input", attrs={"name": pattern})
                if btn:
                    return {pattern: btn.get("value", "")}
                btn = soup.find("button", attrs={"name": pattern})
                if btn:
                    return {pattern: btn.get("value", "")}

            # Pattern 4: Any input/button with "login" or "submit" in the name
            all_inputs = soup.find_all(["input", "button"])
            for inp in all_inputs:
                name = inp.get("name", "")
                if name and ("login" in name.lower() or "submit" in name.lower()):
                    inp_type = inp.get("type", "").lower()
                    if inp_type in ("submit", "button", "image"):
                        return {name: inp.get("value", "")}

            logger.debug("No submit button found in login form")
            return {}

        except Exception as exc:
            logger.debug("Failed to extract submit button: %s", exc)
            return {}

    def _extract_form_action(self, html: str, default_url: str) -> str:
        """Extract the form action URL from the login page.

        The form's action attribute may point to a different URL than the
        page URL itself. If not found, falls back to the default login URL.

        Args:
            html: Raw HTML string from the login page.
            default_url: Fallback URL if form action cannot be determined.

        Returns:
            Absolute URL for the form submission.
        """
        try:
            from urllib.parse import urljoin

            soup = BeautifulSoup(html, "html.parser")

            # Find the form containing the username/password fields
            form = None

            # Try to find form containing our username field
            username_input = soup.find(
                "input", attrs={"name": self.USERNAME_FIELD}
            )
            if username_input:
                form = username_input.find_parent("form")

            # Fallback: find any form with action attribute
            if not form:
                forms = soup.find_all("form")
                for f in forms:
                    if f.get("action"):
                        form = f
                        break

            if form and form.get("action"):
                action = form["action"]
                # Convert relative URL to absolute
                absolute_url = urljoin(default_url, action)
                logger.debug("Form action URL: %s", absolute_url)
                return absolute_url

            logger.debug("No form action found, using default URL: %s", default_url)
            return default_url

        except Exception as exc:
            logger.debug("Failed to extract form action: %s", exc)
            return default_url

    def _establish_page_context(self) -> None:
        """Navigate to the renewal report page after login.

        ASP.NET applications often require the user to visit a page before
        its AJAX/DataTables endpoints will respond with JSON. This GET request
        establishes the server-side page context and ensures any required
        anti-forgery tokens or session state are initialized.
        """
        from urllib.parse import urlparse

        parsed = urlparse(self._config.login_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        renewal_page_url = f"{base_url}/MISReport/UpcommingRenewal"

        logger.debug(
            "Navigating to renewal page to establish context: %s",
            renewal_page_url,
        )

        try:
            response = self._session_manager.session.get(
                renewal_page_url,
                timeout=(
                    self._config.connection_timeout,
                    self._config.read_timeout,
                ),
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            )
            logger.debug(
                "Renewal page response: status=%d, url=%s",
                response.status_code,
                response.url,
            )

            # If we got redirected back to login, the session is not valid
            if response.url and response.url.rstrip("/") == self._config.login_url.rstrip("/"):
                logger.warning(
                    "Renewal page redirected to login page: %s. "
                    "Session is NOT authenticated — login may have failed.",
                    response.url,
                )
            elif response.url and "login" in response.url.lower():
                logger.warning(
                    "Renewal page redirected to login: %s. "
                    "Session may not be fully authenticated.",
                    response.url,
                )

        except Exception as exc:
            # Non-fatal: log and continue, the API request will fail with
            # a clear error if the context wasn't established
            logger.warning(
                "Failed to navigate to renewal page: %s. "
                "API requests may fail if page context is required.",
                exc,
            )

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

        ASP.NET login success indicators:
        - 302 redirect to a non-login page (dashboard/home)
        - New authentication cookies set (.ASPXAUTH, ximscookie, etc.)

        ASP.NET login failure indicators:
        - 200 with login form re-rendered (same page returned)
        - 401/403 status codes

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

        # A 302 redirect after login POST is the strongest success signal
        # (server redirects to dashboard after successful auth)
        if response.status_code in (301, 302, 303, 307, 308):
            redirect_location = response.headers.get("Location", "")
            logger.debug(
                "Login returned redirect (%d) to: %s",
                response.status_code,
                redirect_location,
            )
            # If redirecting back to the login page, authentication failed
            if redirect_location:
                from urllib.parse import urlparse
                redirect_path = urlparse(redirect_location).path.lower()
                login_path = urlparse(login_url).path.lower()
                if redirect_path == login_path:
                    raise LoginError(
                        f"Authentication failed for {login_url}: "
                        f"redirected back to login page"
                    )
            # Redirect to non-login page = success
            return

        # If we got 200, the login form was likely re-rendered (failed login)
        # Check if the response still contains login form elements
        if response.status_code == 200:
            response_text = response.text or ""
            # Check if this looks like the login page (contains password input)
            text_lower = response_text.lower()
            has_password_input = 'type="password"' in text_lower or "type='password'" in text_lower
            has_viewstate = "__viewstate" in text_lower

            if has_password_input and has_viewstate:
                # This is the login page re-rendered — login failed
                # Try to extract error message from the page
                error_msg = self._extract_login_error(response_text)
                if error_msg:
                    raise LoginError(
                        f"Authentication failed for {login_url}: {error_msg}"
                    )
                raise LoginError(
                    f"Authentication failed for {login_url}: "
                    f"login page was re-rendered (HTTP 200). "
                    f"Credentials may be incorrect or form submission incomplete."
                )

        # Fallback: check for session cookies
        has_session_cookie = len(response.cookies) > 0
        if not has_session_cookie:
            has_session_cookie = len(
                self._session_manager.session.cookies
            ) > 0

        if not has_session_cookie:
            raise LoginError(
                f"Authentication failed for {login_url}: "
                f"HTTP {response.status_code} received but no session cookie was set"
            )

    @staticmethod
    def _extract_login_error(html: str) -> str:
        """Try to extract a login error message from the response HTML.

        Args:
            html: Response HTML that may contain an error message.

        Returns:
            Error message string, or empty string if not found.
        """
        try:
            soup = BeautifulSoup(html, "html.parser")

            # Common ASP.NET error display patterns
            # Pattern 1: validation summary
            validation = soup.find(class_="validation-summary-errors")
            if validation:
                return validation.get_text(strip=True)

            # Pattern 2: label with error class
            for cls in ["error", "text-danger", "alert-danger", "login-error", "error-message"]:
                error_el = soup.find(class_=cls)
                if error_el and error_el.get_text(strip=True):
                    return error_el.get_text(strip=True)

            # Pattern 3: span with validator ID
            for span in soup.find_all("span"):
                span_id = span.get("id", "").lower()
                if "validator" in span_id or "error" in span_id:
                    text = span.get_text(strip=True)
                    if text:
                        return text

            return ""
        except Exception:
            return ""
