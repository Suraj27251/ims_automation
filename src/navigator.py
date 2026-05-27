"""Navigation module for IMS.

Opens required pages after login to establish session context.
The IMS panel requires visiting /MISReport/UpcommingRenewal before
the GetData AJAX endpoint will respond with JSON.
"""

import logging

import requests

logger = logging.getLogger(__name__)


class NavigationError(Exception):
    """Raised when page navigation fails."""
    pass


class IMSNavigator:
    """Navigates to required IMS pages to establish session context.

    The IMS DataTables endpoint (/GetData) only works after the parent
    page (/UpcommingRenewal) has been visited in the same session.
    This class handles that navigation step.
    """

    def __init__(self, session: requests.Session, base_url: str, timeout: int = 30):
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def open_renewal_page(self) -> None:
        """Navigate to /MISReport/UpcommingRenewal to initialize session context.

        This must be called after login and before fetching renewal data.
        The page visit establishes server-side state that the GetData
        endpoint depends on.

        Raises:
            NavigationError: If the page cannot be loaded or redirects to login.
        """
        url = f"{self.base_url}/MISReport/UpcommingRenewal"

        logger.info("Opening renewal page: %s", url)
        logger.debug("Cookies BEFORE opening renewal page: %s", self._cookie_summary())

        try:
            response = self.session.get(
                url,
                timeout=self.timeout,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Referer": f"{self.base_url}/Dashboard/ResellerDashboard",
                },
            )
        except requests.RequestException as e:
            raise NavigationError(f"Failed to open renewal page: {e}") from e

        # Log redirect chain if any
        if response.history:
            logger.debug("Renewal page redirect chain:")
            for r in response.history:
                logger.debug("  %d -> %s", r.status_code, r.headers.get("Location", "?"))
            logger.debug("  Final: %d %s", response.status_code, response.url)

        logger.info("Renewal page: status=%d, final_url=%s", response.status_code, response.url)
        logger.debug("Cookies AFTER opening renewal page: %s", self._cookie_summary())

        # Validate we actually got the renewal page (not redirected to login)
        final_url = (response.url or "").lower()
        if "/admin" in final_url and "renewal" not in final_url:
            raise NavigationError(
                f"Renewal page redirected to login: {response.url}. "
                f"Session is not authenticated."
            )

        # Check response looks like the renewal page (has DataTable references)
        if response.status_code == 200:
            text_lower = response.text[:5000].lower()
            if "upcommingrenewal" in text_lower or "datatable" in text_lower or "getdata" in text_lower:
                logger.info("Renewal page loaded successfully (DataTable context established)")
            else:
                logger.warning(
                    "Renewal page loaded but may not contain expected DataTable content. "
                    "Size: %d bytes", len(response.text)
                )

    def _cookie_summary(self) -> str:
        """Return a summary of current session cookies."""
        cookies = self.session.cookies.get_dict()
        if not cookies:
            return "(none)"
        return ", ".join(f"{k}={v[:20]}..." if len(v) > 20 else f"{k}={v}" for k, v in cookies.items())
