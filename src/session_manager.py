"""Session manager for IMS Data Fetcher.

Manages the HTTP session lifecycle, cookie persistence, retry logic with
exponential backoff, and transparent re-authentication.
"""

import logging
import time
from typing import Callable, Optional

import requests

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when authentication fails or session cannot be refreshed."""

    pass


class SessionManager:
    """Manages a requests.Session() with automatic cookie persistence,
    retry logic, and transparent re-authentication.

    Args:
        connection_timeout: Timeout in seconds for establishing connections.
        read_timeout: Timeout in seconds for reading responses.
        max_retries: Maximum number of retry attempts for transient failures.
        reauth_callback: Optional callable invoked to re-authenticate the session.
    """

    def __init__(
        self,
        connection_timeout: int = 30,
        read_timeout: int = 60,
        max_retries: int = 2,
        reauth_callback: Optional[Callable] = None,
    ):
        self._session: requests.Session = requests.Session()
        self._connection_timeout = connection_timeout
        self._read_timeout = read_timeout
        self._max_retries = max_retries
        self._reauth_callback = reauth_callback
        self._reauth_timestamps: list = []

    @property
    def session(self) -> requests.Session:
        """Access the underlying requests.Session."""
        return self._session

    def get(self, url: str, **kwargs) -> requests.Response:
        """Perform GET request with retry and re-auth logic.

        Args:
            url: The URL to request.
            **kwargs: Additional keyword arguments passed to requests.

        Returns:
            The HTTP response.

        Raises:
            AuthenticationError: If re-auth fails or rate-limited.
            requests.RequestException: If all retries exhausted.
        """
        return self._execute_with_retry("GET", url, **kwargs)

    def post(self, url: str, data=None, **kwargs) -> requests.Response:
        """Perform POST request with retry and re-auth logic.

        Args:
            url: The URL to request.
            data: The request body data.
            **kwargs: Additional keyword arguments passed to requests.

        Returns:
            The HTTP response.

        Raises:
            AuthenticationError: If re-auth fails or rate-limited.
            requests.RequestException: If all retries exhausted.
        """
        if data is not None:
            kwargs["data"] = data
        return self._execute_with_retry("POST", url, **kwargs)

    def _execute_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        """Execute HTTP request with exponential backoff retry.

        Retries on: connection errors, timeouts, 5xx responses.
        Immediate failure on: 4xx (except 401, 403, 429).
        Re-authenticates on: 401, 403.

        Args:
            method: HTTP method (GET, POST).
            url: The URL to request.
            **kwargs: Additional keyword arguments passed to requests.

        Returns:
            The HTTP response.

        Raises:
            AuthenticationError: If re-auth fails or rate-limited.
            requests.RequestException: If all retries exhausted.
        """
        # Set default timeout if not provided
        if "timeout" not in kwargs:
            kwargs["timeout"] = (self._connection_timeout, self._read_timeout)

        last_exception = None
        attempts = self._max_retries + 1  # initial attempt + retries

        for attempt in range(attempts):
            # Exponential backoff: wait 2^(N-1) seconds before retry N
            if attempt > 0:
                wait_time = 2 ** (attempt - 1)
                logger.warning(
                    "Retry %d/%d for %s %s, waiting %ds",
                    attempt,
                    self._max_retries,
                    method,
                    url,
                    wait_time,
                )
                time.sleep(wait_time)

            try:
                response = self._session.request(method, url, **kwargs)

                # Check for auth failure (401, 403)
                if response.status_code in (401, 403):
                    self._handle_auth_failure(response)
                    # After successful re-auth, retry the original request once
                    response = self._session.request(method, url, **kwargs)
                    # If still failing after re-auth, raise
                    if response.status_code in (401, 403):
                        raise AuthenticationError(
                            f"Authentication failed after re-auth for {method} {url}: "
                            f"HTTP {response.status_code}"
                        )
                    return response

                # Check for non-retryable 4xx (except 429)
                if (
                    400 <= response.status_code < 500
                    and response.status_code not in (401, 403, 429)
                ):
                    logger.error(
                        "Non-retryable HTTP %d for %s %s",
                        response.status_code,
                        method,
                        url,
                    )
                    response.raise_for_status()

                # Check if we should retry (5xx or 429)
                if self._should_retry(response):
                    last_exception = requests.HTTPError(
                        f"HTTP {response.status_code} for {method} {url}",
                        response=response,
                    )
                    if attempt < self._max_retries:
                        continue
                    # All retries exhausted
                    logger.error(
                        "All %d retry attempts exhausted for %s %s. "
                        "Final status: HTTP %d",
                        self._max_retries,
                        method,
                        url,
                        response.status_code,
                    )
                    response.raise_for_status()

                # Successful response
                return response

            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exception = exc
                logger.warning(
                    "Request failed for %s %s (attempt %d/%d): %s",
                    method,
                    url,
                    attempt + 1,
                    attempts,
                    str(exc),
                )
                if attempt >= self._max_retries:
                    logger.error(
                        "All %d retry attempts exhausted for %s %s. "
                        "Error: %s",
                        self._max_retries,
                        method,
                        url,
                        str(exc),
                    )
                    raise

            except requests.HTTPError:
                # Re-raise HTTPError from non-retryable status codes
                raise

            except AuthenticationError:
                # Re-raise authentication errors without retry
                raise

        # Should not reach here, but raise last exception if we do
        if last_exception:
            raise last_exception
        raise requests.RequestException(
            f"Request failed for {method} {url} after {attempts} attempts"
        )

    def _should_retry(self, response: requests.Response) -> bool:
        """Determine if response warrants a retry.

        Returns True for 5xx responses and 429 (rate limited).

        Args:
            response: The HTTP response to evaluate.

        Returns:
            True if the request should be retried.
        """
        return response.status_code >= 500 or response.status_code == 429

    def _handle_auth_failure(self, response: requests.Response) -> None:
        """Trigger re-authentication, enforcing rate limit (3 per 60s).

        Args:
            response: The HTTP response that triggered auth failure.

        Raises:
            AuthenticationError: If rate limit exceeded or re-auth callback
                is not configured or re-auth fails.
        """
        if self._reauth_callback is None:
            raise AuthenticationError(
                f"Authentication failed (HTTP {response.status_code}) "
                f"and no re-auth callback configured."
            )

        # Enforce rate limit: max 3 re-auths per 60 seconds
        now = time.time()
        # Remove timestamps older than 60 seconds
        self._reauth_timestamps = [
            ts for ts in self._reauth_timestamps if now - ts < 60
        ]

        if len(self._reauth_timestamps) >= 3:
            raise AuthenticationError(
                "Re-authentication rate limit exceeded: "
                "3 attempts within 60 seconds. "
                "Please wait before retrying."
            )

        # Record this re-auth attempt
        self._reauth_timestamps.append(now)

        logger.info(
            "Triggering re-authentication (attempt %d/3 in last 60s)",
            len(self._reauth_timestamps),
        )

        try:
            self._reauth_callback()
        except Exception as exc:
            raise AuthenticationError(
                f"Re-authentication failed: {exc}"
            ) from exc
