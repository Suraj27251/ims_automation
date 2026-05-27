"""Authentication module for IMS.

Handles login to the IMS admin panel using requests.Session().
Maintains session cookies across the entire application lifecycle.
"""

import logging

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """Raised when authentication fails."""
    pass


class IMSAuth:
    """Manages IMS authentication and session persistence.

    Usage:
        auth = IMSAuth(base_url, username, password)
        auth.login()
        # auth.session is now authenticated for subsequent requests
    """

    def __init__(self, base_url: str, username: str, password: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self.session = requests.Session()

        # Browser-like headers to avoid being blocked
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        })

    def login(self) -> None:
        """Perform full login flow.

        1. GET /Admin to fetch login page and extract hidden fields
        2. POST credentials + hidden fields to /Admin
        3. Follow redirects to establish authenticated session
        4. Validate that login succeeded

        Raises:
            AuthError: If login fails for any reason.
        """
        login_url = f"{self.base_url}/Admin"

        # --- Debug: cookies before login ---
        logger.info("Cookies BEFORE login: %s", self._cookie_summary())

        # Step 1: GET login page
        logger.info("Fetching login page: %s", login_url)
        try:
            get_resp = self.session.get(login_url, timeout=self.timeout)
        except requests.RequestException as e:
            raise AuthError(f"Failed to fetch login page: {e}") from e

        logger.debug("Login page: status=%d, size=%d bytes", get_resp.status_code, len(get_resp.text))

        # Extract hidden fields and form details
        hidden_fields = self._extract_hidden_fields(get_resp.text)
        submit_btn = self._extract_submit_button(get_resp.text)
        form_action = self._extract_form_action(get_resp.text, login_url)
        username_field, password_field = self._detect_field_names(get_resp.text)

        logger.debug("Hidden fields: %s", list(hidden_fields.keys()))
        logger.debug("Submit button: %s", submit_btn)
        logger.debug("Form action: %s", form_action)
        logger.debug("Credential fields: username='%s', password='%s'", username_field, password_field)

        # Step 2: Build payload and POST
        payload = {
            **hidden_fields,
            username_field: self.username,
            password_field: self.password,
        }
        if submit_btn:
            payload.update(submit_btn)

        logger.info("Submitting login POST to: %s", form_action)
        logger.debug("Payload keys: %s", list(payload.keys()))

        try:
            post_resp = self.session.post(
                form_action,
                data=payload,
                timeout=self.timeout,
                allow_redirects=True,
            )
        except requests.RequestException as e:
            raise AuthError(f"Login POST failed: {e}") from e

        # Log redirect chain
        if post_resp.history:
            logger.info("Login redirect chain:")
            for r in post_resp.history:
                logger.info("  %d -> %s", r.status_code, r.headers.get("Location", "?"))
            logger.info("  Final: %d %s", post_resp.status_code, post_resp.url)
        else:
            logger.info("Login response: status=%d, url=%s", post_resp.status_code, post_resp.url)

        # --- Debug: cookies after login ---
        logger.info("Cookies AFTER login: %s", self._cookie_summary())

        # Step 3: Validate login success
        self._validate_login(post_resp, login_url)
        logger.info("Authentication successful")

    def _validate_login(self, response: requests.Response, login_url: str) -> None:
        """Check if login succeeded.

        Success indicators:
        - Final URL is NOT the login page (redirected to dashboard)
        - Response does not contain login form fields

        Raises:
            AuthError: If login appears to have failed.
        """
        final_url = response.url or ""

        # If we ended up back at the login page, login failed
        if final_url.rstrip("/").lower() == login_url.rstrip("/").lower():
            # Check for error message in the page
            error_msg = self._extract_error_message(response.text)
            if error_msg:
                raise AuthError(f"Login failed: {error_msg}")
            raise AuthError(
                "Login failed: ended up back at login page. "
                "Check credentials or form field names."
            )

        # If response still has password field, login page was re-rendered
        text_lower = (response.text or "").lower()
        if 'type="password"' in text_lower and "__viewstate" in text_lower:
            error_msg = self._extract_error_message(response.text)
            if error_msg:
                raise AuthError(f"Login failed: {error_msg}")
            raise AuthError("Login failed: login form re-rendered (HTTP 200).")

    def _extract_hidden_fields(self, html: str) -> dict:
        """Extract all hidden input fields from HTML."""
        soup = BeautifulSoup(html, "html.parser")
        fields = {}
        for inp in soup.find_all("input", attrs={"type": "hidden"}):
            name = inp.get("name")
            if name:
                fields[name] = inp.get("value", "")
        return fields

    def _extract_submit_button(self, html: str) -> dict:
        """Find the submit button name/value pair."""
        soup = BeautifulSoup(html, "html.parser")

        # input type="submit"
        for btn in soup.find_all("input", attrs={"type": "submit"}):
            name = btn.get("name")
            if name:
                return {name: btn.get("value", "")}

        # button type="submit"
        for btn in soup.find_all("button", attrs={"type": "submit"}):
            name = btn.get("name")
            if name:
                return {name: btn.get("value", "")}

        return {}

    def _extract_form_action(self, html: str, default_url: str) -> str:
        """Extract form action URL, defaulting to the login URL."""
        from urllib.parse import urljoin

        soup = BeautifulSoup(html, "html.parser")

        # Find form containing a password field
        pwd_input = soup.find("input", attrs={"type": "password"})
        if pwd_input:
            form = pwd_input.find_parent("form")
            if form and form.get("action"):
                return urljoin(default_url, form["action"])

        return default_url

    def _detect_field_names(self, html: str) -> tuple:
        """Auto-detect username and password field names from the form."""
        soup = BeautifulSoup(html, "html.parser")

        # Find password field
        password_field = "txtPassword"
        pwd_inputs = soup.find_all("input", attrs={"type": "password"})
        for inp in pwd_inputs:
            name = inp.get("name")
            if name:
                password_field = name
                break

        # Find text/email field (username) - skip hidden fields
        username_field = "txtUserName"
        text_inputs = soup.find_all("input", attrs={"type": ["text", "email"]})
        for inp in text_inputs:
            name = inp.get("name", "")
            if name and not name.startswith("__"):
                username_field = name
                break

        return username_field, password_field

    def _extract_error_message(self, html: str) -> str:
        """Try to extract login error message from response."""
        if not html:
            return ""
        try:
            soup = BeautifulSoup(html, "html.parser")
            for cls in ["error", "text-danger", "alert-danger", "validation-summary-errors"]:
                el = soup.find(class_=cls)
                if el and el.get_text(strip=True):
                    return el.get_text(strip=True)
            return ""
        except Exception:
            return ""

    def _cookie_summary(self) -> str:
        """Return a summary of current session cookies."""
        cookies = self.session.cookies.get_dict()
        if not cookies:
            return "(none)"
        return ", ".join(f"{k}={v[:20]}..." if len(v) > 20 else f"{k}={v}" for k, v in cookies.items())
