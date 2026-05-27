"""Diagnostics module for IMS Data Fetcher.

Handles diagnostic mode data persistence, saving raw HTTP request/response
data to disk for reverse engineering and troubleshooting.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Keys that indicate sensitive credential values (case-insensitive matching)
_SENSITIVE_KEY_PATTERN = re.compile(r"(password|cookie|token|auth)", re.IGNORECASE)

# Mask replacement value
_MASK_VALUE = "***MASKED***"


def _mask_credentials(data: Dict[str, Any]) -> Dict[str, Any]:
    """Mask sensitive credential values in a dictionary.

    Replaces values for keys containing 'password', 'cookie', 'token',
    or 'auth' (case-insensitive) with '***MASKED***'.

    Args:
        data: Dictionary potentially containing sensitive values.

    Returns:
        A new dictionary with sensitive values masked.
    """
    masked = {}
    for key, value in data.items():
        if _SENSITIVE_KEY_PATTERN.search(key):
            masked[key] = _MASK_VALUE
        elif isinstance(value, dict):
            masked[key] = _mask_credentials(value)
        else:
            masked[key] = value
    return masked


class DiagnosticsManager:
    """Persists raw HTTP data when diagnostic mode is enabled.

    When enabled, saves request payloads, response bodies, and redirect
    information to timestamped files in the output directory. All credential
    values are masked before writing.

    When disabled, all methods are no-ops.

    Args:
        enabled: Whether diagnostic mode is active.
        output_dir: Directory path for diagnostic output files.
    """

    def __init__(self, enabled: bool, output_dir: Path = Path("diagnostics")):
        self._enabled = enabled
        self._output_dir = output_dir
        self._dir_created = False

    def _ensure_output_dir(self) -> None:
        """Create the output directory if it doesn't exist."""
        if not self._dir_created:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            self._dir_created = True

    def _generate_timestamp(self) -> str:
        """Generate a timestamp string for filenames."""
        return datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    def save_request(
        self, url: str, method: str, payload: dict, headers: dict
    ) -> None:
        """Save request data with timestamped filename and masked credentials.

        Persists the request URL, method, payload, and headers to a JSON file
        in the diagnostics directory. Credential values in payload and headers
        are masked before writing.

        Args:
            url: The request URL.
            method: The HTTP method (GET, POST, etc.).
            payload: The request body/payload dictionary.
            headers: The request headers dictionary.
        """
        if not self._enabled:
            return

        self._ensure_output_dir()

        timestamp = self._generate_timestamp()
        filename = f"request_{timestamp}.json"
        filepath = self._output_dir / filename

        request_data = {
            "timestamp": timestamp,
            "url": url,
            "method": method,
            "payload": _mask_credentials(payload) if payload else {},
            "headers": _mask_credentials(headers) if headers else {},
        }

        try:
            filepath.write_text(
                json.dumps(request_data, indent=2, default=str),
                encoding="utf-8",
            )
            logger.debug("Saved diagnostic request to %s", filepath)
        except OSError as exc:
            logger.error("Failed to save diagnostic request: %s", exc)

    def save_response(
        self, url: str, status_code: int, headers: dict, body: str
    ) -> None:
        """Save response data with timestamped filename.

        Persists the response URL, status code, headers, and body to a JSON
        file in the diagnostics directory.

        Args:
            url: The request URL that generated this response.
            status_code: The HTTP status code.
            headers: The response headers dictionary.
            body: The raw response body string.
        """
        if not self._enabled:
            return

        self._ensure_output_dir()

        timestamp = self._generate_timestamp()
        filename = f"response_{timestamp}.json"
        filepath = self._output_dir / filename

        response_data = {
            "timestamp": timestamp,
            "url": url,
            "status_code": status_code,
            "headers": dict(headers) if headers else {},
            "body": body,
        }

        try:
            filepath.write_text(
                json.dumps(response_data, indent=2, default=str),
                encoding="utf-8",
            )
            logger.debug("Saved diagnostic response to %s", filepath)
        except OSError as exc:
            logger.error("Failed to save diagnostic response: %s", exc)

    def log_redirect(
        self, url: str, status_code: int, location: str, headers: dict
    ) -> None:
        """Log redirect with masked credentials.

        Persists redirect information (3xx responses) including the original
        URL, status code, redirect location, and masked headers.

        Args:
            url: The original request URL.
            status_code: The HTTP 3xx status code.
            location: The redirect target URL.
            headers: The response headers dictionary.
        """
        if not self._enabled:
            return

        self._ensure_output_dir()

        timestamp = self._generate_timestamp()
        filename = f"redirect_{timestamp}.json"
        filepath = self._output_dir / filename

        redirect_data = {
            "timestamp": timestamp,
            "url": url,
            "status_code": status_code,
            "location": location,
            "headers": _mask_credentials(dict(headers)) if headers else {},
        }

        try:
            filepath.write_text(
                json.dumps(redirect_data, indent=2, default=str),
                encoding="utf-8",
            )
            logger.info(
                "Redirect detected: %s -> %s (HTTP %d)",
                url,
                location,
                status_code,
            )
        except OSError as exc:
            logger.error("Failed to save diagnostic redirect: %s", exc)
