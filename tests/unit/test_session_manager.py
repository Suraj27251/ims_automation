"""Unit tests for session_manager module."""

import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.session_manager import AuthenticationError, SessionManager


class TestSessionManagerInit:
    """Tests for SessionManager initialization."""

    def test_default_parameters(self):
        """Test SessionManager initializes with correct defaults."""
        sm = SessionManager()
        assert sm._connection_timeout == 30
        assert sm._read_timeout == 60
        assert sm._max_retries == 2
        assert sm._reauth_callback is None
        assert sm._reauth_timestamps == []

    def test_custom_parameters(self):
        """Test SessionManager accepts custom parameters."""
        callback = MagicMock()
        sm = SessionManager(
            connection_timeout=10,
            read_timeout=20,
            max_retries=3,
            reauth_callback=callback,
        )
        assert sm._connection_timeout == 10
        assert sm._read_timeout == 20
        assert sm._max_retries == 3
        assert sm._reauth_callback is callback

    def test_session_property_returns_requests_session(self):
        """Test session property exposes the underlying requests.Session."""
        sm = SessionManager()
        assert isinstance(sm.session, requests.Session)

    def test_session_property_returns_same_instance(self):
        """Test session property always returns the same Session instance."""
        sm = SessionManager()
        assert sm.session is sm.session


class TestSuccessfulRequests:
    """Tests for successful request handling."""

    def test_get_successful_request(self):
        """Test GET request passes through without retry on success."""
        sm = SessionManager()
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(sm._session, "request", return_value=mock_response):
            result = sm.get("http://example.com/api")

        assert result is mock_response

    def test_post_successful_request(self):
        """Test POST request passes through without retry on success."""
        sm = SessionManager()
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(sm._session, "request", return_value=mock_response):
            result = sm.post("http://example.com/api", data={"key": "value"})

        assert result is mock_response

    def test_post_passes_data_kwarg(self):
        """Test POST request correctly passes data parameter."""
        sm = SessionManager()
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(sm._session, "request", return_value=mock_response) as mock_req:
            sm.post("http://example.com/api", data={"key": "value"})

        mock_req.assert_called_once_with(
            "POST",
            "http://example.com/api",
            data={"key": "value"},
            timeout=(30, 60),
        )

    def test_default_timeout_applied(self):
        """Test default timeout (30s connect, 60s read) is applied."""
        sm = SessionManager()
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(sm._session, "request", return_value=mock_response) as mock_req:
            sm.get("http://example.com/api")

        mock_req.assert_called_once_with(
            "GET",
            "http://example.com/api",
            timeout=(30, 60),
        )

    def test_custom_timeout_not_overridden(self):
        """Test that user-provided timeout is not overridden."""
        sm = SessionManager()
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(sm._session, "request", return_value=mock_response) as mock_req:
            sm.get("http://example.com/api", timeout=5)

        mock_req.assert_called_once_with(
            "GET",
            "http://example.com/api",
            timeout=5,
        )


class TestRetryOnConnectionErrors:
    """Tests for retry behavior on connection errors."""

    @patch("src.session_manager.time.sleep")
    def test_retry_on_connection_error(self, mock_sleep):
        """Test retry on ConnectionError with correct backoff."""
        sm = SessionManager(max_retries=2)
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(
            sm._session,
            "request",
            side_effect=[
                requests.ConnectionError("Connection refused"),
                mock_response,
            ],
        ):
            result = sm.get("http://example.com/api")

        assert result is mock_response
        mock_sleep.assert_called_once_with(1)  # 2^(1-1) = 1s

    @patch("src.session_manager.time.sleep")
    def test_retry_on_timeout_error(self, mock_sleep):
        """Test retry on Timeout error."""
        sm = SessionManager(max_retries=2)
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(
            sm._session,
            "request",
            side_effect=[
                requests.Timeout("Read timed out"),
                mock_response,
            ],
        ):
            result = sm.get("http://example.com/api")

        assert result is mock_response
        mock_sleep.assert_called_once_with(1)

    @patch("src.session_manager.time.sleep")
    def test_exponential_backoff_timing(self, mock_sleep):
        """Test exponential backoff: 1s, 2s for retries."""
        sm = SessionManager(max_retries=2)
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(
            sm._session,
            "request",
            side_effect=[
                requests.ConnectionError("fail 1"),
                requests.ConnectionError("fail 2"),
                mock_response,
            ],
        ):
            result = sm.get("http://example.com/api")

        assert result is mock_response
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(1)  # 2^(1-1) = 1s
        mock_sleep.assert_any_call(2)  # 2^(2-1) = 2s

    @patch("src.session_manager.time.sleep")
    def test_raises_after_all_retries_exhausted(self, mock_sleep):
        """Test raises ConnectionError after all retries exhausted."""
        sm = SessionManager(max_retries=2)

        with patch.object(
            sm._session,
            "request",
            side_effect=requests.ConnectionError("Connection refused"),
        ):
            with pytest.raises(requests.ConnectionError):
                sm.get("http://example.com/api")

        # Should have attempted 3 times total (1 initial + 2 retries)
        assert mock_sleep.call_count == 2


class TestRetryOn5xx:
    """Tests for retry behavior on 5xx responses."""

    @patch("src.session_manager.time.sleep")
    def test_retry_on_500(self, mock_sleep):
        """Test retry on HTTP 500 response."""
        sm = SessionManager(max_retries=2)
        mock_500 = MagicMock()
        mock_500.status_code = 500
        mock_500.raise_for_status = MagicMock(
            side_effect=requests.HTTPError("500 Server Error")
        )

        mock_200 = MagicMock()
        mock_200.status_code = 200

        with patch.object(
            sm._session,
            "request",
            side_effect=[mock_500, mock_200],
        ):
            result = sm.get("http://example.com/api")

        assert result is mock_200
        mock_sleep.assert_called_once_with(1)

    @patch("src.session_manager.time.sleep")
    def test_retry_on_503(self, mock_sleep):
        """Test retry on HTTP 503 response."""
        sm = SessionManager(max_retries=2)
        mock_503 = MagicMock()
        mock_503.status_code = 503
        mock_503.raise_for_status = MagicMock(
            side_effect=requests.HTTPError("503 Service Unavailable")
        )

        mock_200 = MagicMock()
        mock_200.status_code = 200

        with patch.object(
            sm._session,
            "request",
            side_effect=[mock_503, mock_200],
        ):
            result = sm.get("http://example.com/api")

        assert result is mock_200

    @patch("src.session_manager.time.sleep")
    def test_raises_after_5xx_retries_exhausted(self, mock_sleep):
        """Test raises HTTPError after all retries exhausted on 5xx."""
        sm = SessionManager(max_retries=2)
        mock_500 = MagicMock()
        mock_500.status_code = 500
        mock_500.raise_for_status = MagicMock(
            side_effect=requests.HTTPError("500 Server Error")
        )

        with patch.object(
            sm._session,
            "request",
            return_value=mock_500,
        ):
            with pytest.raises(requests.HTTPError):
                sm.get("http://example.com/api")


class TestImmediateFailureOn4xx:
    """Tests for immediate failure on non-retryable 4xx responses."""

    def test_immediate_failure_on_400(self):
        """Test immediate failure on HTTP 400 (no retry)."""
        sm = SessionManager(max_retries=2)
        mock_400 = MagicMock()
        mock_400.status_code = 400
        mock_400.raise_for_status = MagicMock(
            side_effect=requests.HTTPError("400 Bad Request")
        )

        with patch.object(sm._session, "request", return_value=mock_400) as mock_req:
            with pytest.raises(requests.HTTPError):
                sm.get("http://example.com/api")
            # Should only be called once (no retries)
            mock_req.assert_called_once()

    def test_immediate_failure_on_404(self):
        """Test immediate failure on HTTP 404 (no retry)."""
        sm = SessionManager(max_retries=2)
        mock_404 = MagicMock()
        mock_404.status_code = 404
        mock_404.raise_for_status = MagicMock(
            side_effect=requests.HTTPError("404 Not Found")
        )

        with patch.object(sm._session, "request", return_value=mock_404) as mock_req:
            with pytest.raises(requests.HTTPError):
                sm.get("http://example.com/api")
            mock_req.assert_called_once()

    def test_immediate_failure_on_422(self):
        """Test immediate failure on HTTP 422 (no retry)."""
        sm = SessionManager(max_retries=2)
        mock_422 = MagicMock()
        mock_422.status_code = 422
        mock_422.raise_for_status = MagicMock(
            side_effect=requests.HTTPError("422 Unprocessable Entity")
        )

        with patch.object(sm._session, "request", return_value=mock_422) as mock_req:
            with pytest.raises(requests.HTTPError):
                sm.get("http://example.com/api")
            mock_req.assert_called_once()


class TestReauthOn401And403:
    """Tests for re-authentication on 401/403 responses."""

    def test_reauth_triggered_on_401(self):
        """Test re-authentication is triggered on HTTP 401."""
        callback = MagicMock()
        sm = SessionManager(reauth_callback=callback)

        mock_401 = MagicMock()
        mock_401.status_code = 401

        mock_200 = MagicMock()
        mock_200.status_code = 200

        with patch.object(
            sm._session,
            "request",
            side_effect=[mock_401, mock_200],
        ):
            result = sm.get("http://example.com/api")

        assert result is mock_200
        callback.assert_called_once()

    def test_reauth_triggered_on_403(self):
        """Test re-authentication is triggered on HTTP 403."""
        callback = MagicMock()
        sm = SessionManager(reauth_callback=callback)

        mock_403 = MagicMock()
        mock_403.status_code = 403

        mock_200 = MagicMock()
        mock_200.status_code = 200

        with patch.object(
            sm._session,
            "request",
            side_effect=[mock_403, mock_200],
        ):
            result = sm.get("http://example.com/api")

        assert result is mock_200
        callback.assert_called_once()

    def test_raises_auth_error_when_no_callback(self):
        """Test AuthenticationError raised when no reauth_callback configured."""
        sm = SessionManager(reauth_callback=None)

        mock_401 = MagicMock()
        mock_401.status_code = 401

        with patch.object(sm._session, "request", return_value=mock_401):
            with pytest.raises(AuthenticationError, match="no re-auth callback"):
                sm.get("http://example.com/api")

    def test_raises_auth_error_when_reauth_fails(self):
        """Test AuthenticationError raised when reauth callback raises."""
        callback = MagicMock(side_effect=Exception("Login failed"))
        sm = SessionManager(reauth_callback=callback)

        mock_401 = MagicMock()
        mock_401.status_code = 401

        with patch.object(sm._session, "request", return_value=mock_401):
            with pytest.raises(AuthenticationError, match="Re-authentication failed"):
                sm.get("http://example.com/api")

    def test_raises_auth_error_when_still_401_after_reauth(self):
        """Test AuthenticationError raised when still 401 after re-auth."""
        callback = MagicMock()
        sm = SessionManager(reauth_callback=callback)

        mock_401 = MagicMock()
        mock_401.status_code = 401

        with patch.object(sm._session, "request", return_value=mock_401):
            with pytest.raises(AuthenticationError, match="Authentication failed after re-auth"):
                sm.get("http://example.com/api")


class TestReauthRateLimiting:
    """Tests for re-authentication rate limiting (3 per 60s)."""

    def test_rate_limit_exceeded_raises_auth_error(self):
        """Test AuthenticationError when 3 re-auths attempted within 60s."""
        callback = MagicMock()
        sm = SessionManager(reauth_callback=callback)

        # Simulate 3 recent re-auth timestamps
        now = time.time()
        sm._reauth_timestamps = [now - 30, now - 20, now - 10]

        mock_401 = MagicMock()
        mock_401.status_code = 401

        with patch.object(sm._session, "request", return_value=mock_401):
            with pytest.raises(AuthenticationError, match="rate limit exceeded"):
                sm.get("http://example.com/api")

        # Callback should NOT have been called
        callback.assert_not_called()

    def test_old_timestamps_are_pruned(self):
        """Test timestamps older than 60s are removed from tracking."""
        callback = MagicMock()
        sm = SessionManager(reauth_callback=callback)

        # Simulate old timestamps (> 60s ago)
        now = time.time()
        sm._reauth_timestamps = [now - 120, now - 90, now - 61]

        mock_401 = MagicMock()
        mock_401.status_code = 401
        mock_200 = MagicMock()
        mock_200.status_code = 200

        with patch.object(
            sm._session,
            "request",
            side_effect=[mock_401, mock_200],
        ):
            result = sm.get("http://example.com/api")

        assert result is mock_200
        callback.assert_called_once()
        # Old timestamps should be pruned, only new one remains
        assert len(sm._reauth_timestamps) == 1

    def test_allows_reauth_when_under_limit(self):
        """Test re-auth allowed when under 3 attempts in 60s window."""
        callback = MagicMock()
        sm = SessionManager(reauth_callback=callback)

        now = time.time()
        sm._reauth_timestamps = [now - 30, now - 20]  # 2 recent attempts

        mock_401 = MagicMock()
        mock_401.status_code = 401
        mock_200 = MagicMock()
        mock_200.status_code = 200

        with patch.object(
            sm._session,
            "request",
            side_effect=[mock_401, mock_200],
        ):
            result = sm.get("http://example.com/api")

        assert result is mock_200
        callback.assert_called_once()


class TestShouldRetry:
    """Tests for _should_retry method."""

    def test_should_retry_on_500(self):
        """Test _should_retry returns True for 500."""
        sm = SessionManager()
        response = MagicMock()
        response.status_code = 500
        assert sm._should_retry(response) is True

    def test_should_retry_on_502(self):
        """Test _should_retry returns True for 502."""
        sm = SessionManager()
        response = MagicMock()
        response.status_code = 502
        assert sm._should_retry(response) is True

    def test_should_retry_on_503(self):
        """Test _should_retry returns True for 503."""
        sm = SessionManager()
        response = MagicMock()
        response.status_code = 503
        assert sm._should_retry(response) is True

    def test_should_retry_on_429(self):
        """Test _should_retry returns True for 429 (rate limited)."""
        sm = SessionManager()
        response = MagicMock()
        response.status_code = 429
        assert sm._should_retry(response) is True

    def test_should_not_retry_on_200(self):
        """Test _should_retry returns False for 200."""
        sm = SessionManager()
        response = MagicMock()
        response.status_code = 200
        assert sm._should_retry(response) is False

    def test_should_not_retry_on_400(self):
        """Test _should_retry returns False for 400."""
        sm = SessionManager()
        response = MagicMock()
        response.status_code = 400
        assert sm._should_retry(response) is False

    def test_should_not_retry_on_404(self):
        """Test _should_retry returns False for 404."""
        sm = SessionManager()
        response = MagicMock()
        response.status_code = 404
        assert sm._should_retry(response) is False
