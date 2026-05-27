"""Property-based tests for session_manager module.

Uses hypothesis to validate universal properties of session management,
specifically the exponential backoff timing behavior.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests
from hypothesis import given, strategies as st, settings

from src.session_manager import SessionManager


class TestExponentialBackoffTiming:
    """Property 17: Exponential Backoff Timing

    **Validates: Requirements 13.2**

    For any retry attempt number N (where N >= 1), the wait time before
    that retry SHALL be 2^(N-1) seconds (1s for first retry, 2s for second
    retry, 4s for third retry, etc.).
    """

    @given(max_retries=st.integers(min_value=1, max_value=5))
    @settings(max_examples=50)
    def test_backoff_timing_matches_formula(self, max_retries: int):
        """For any number of retries, each retry N waits exactly 2^(N-1) seconds.

        **Validates: Requirements 13.2**

        We force all attempts to fail with ConnectionError so that every retry
        is exercised, then verify each sleep call matches 2^(N-1).
        """
        sm = SessionManager(max_retries=max_retries)

        with patch("src.session_manager.time.sleep") as mock_sleep:
            with patch.object(
                sm._session,
                "request",
                side_effect=requests.ConnectionError("Connection refused"),
            ):
                with pytest.raises(requests.ConnectionError):
                    sm.get("http://example.com/api")

        # There should be exactly max_retries sleep calls (one per retry)
        assert mock_sleep.call_count == max_retries, (
            f"Expected {max_retries} sleep calls, got {mock_sleep.call_count}"
        )

        # Verify each sleep duration matches 2^(N-1) for retry N
        for retry_number in range(1, max_retries + 1):
            expected_wait = 2 ** (retry_number - 1)
            actual_call = mock_sleep.call_args_list[retry_number - 1]
            actual_wait = actual_call[0][0]
            assert actual_wait == expected_wait, (
                f"Retry {retry_number}: expected wait {expected_wait}s, "
                f"got {actual_wait}s"
            )

    @given(max_retries=st.integers(min_value=1, max_value=5))
    @settings(max_examples=50)
    def test_backoff_timing_on_5xx_responses(self, max_retries: int):
        """Backoff formula holds for 5xx server error retries too.

        **Validates: Requirements 13.2**

        Verifies that the same 2^(N-1) formula applies when retrying
        due to HTTP 5xx responses (not just connection errors).
        """
        sm = SessionManager(max_retries=max_retries)

        mock_5xx = MagicMock()
        mock_5xx.status_code = 500
        mock_5xx.raise_for_status = MagicMock(
            side_effect=requests.HTTPError("500 Server Error")
        )

        with patch("src.session_manager.time.sleep") as mock_sleep:
            with patch.object(
                sm._session,
                "request",
                return_value=mock_5xx,
            ):
                with pytest.raises(requests.HTTPError):
                    sm.get("http://example.com/api")

        # There should be exactly max_retries sleep calls
        assert mock_sleep.call_count == max_retries, (
            f"Expected {max_retries} sleep calls, got {mock_sleep.call_count}"
        )

        # Verify each sleep duration matches 2^(N-1)
        for retry_number in range(1, max_retries + 1):
            expected_wait = 2 ** (retry_number - 1)
            actual_call = mock_sleep.call_args_list[retry_number - 1]
            actual_wait = actual_call[0][0]
            assert actual_wait == expected_wait, (
                f"Retry {retry_number}: expected wait {expected_wait}s, "
                f"got {actual_wait}s"
            )

    @given(
        max_retries=st.integers(min_value=1, max_value=5),
        success_at=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=50)
    def test_backoff_timing_partial_retries(self, max_retries: int, success_at: int):
        """When request succeeds after N failures, only N sleep calls occur
        with correct 2^(N-1) timing for each.

        **Validates: Requirements 13.2**
        """
        # Ensure success_at is within the retry budget
        if success_at > max_retries:
            success_at = max_retries

        sm = SessionManager(max_retries=max_retries)

        mock_200 = MagicMock()
        mock_200.status_code = 200

        # Create side_effect: success_at failures then success
        side_effects = [
            requests.ConnectionError("fail") for _ in range(success_at)
        ] + [mock_200]

        # Patch to avoid AttributeError on mock response methods
        with patch("src.session_manager.time.sleep") as mock_sleep:
            with patch.object(
                sm._session,
                "request",
                side_effect=side_effects,
            ):
                result = sm.get("http://example.com/api")

        assert result is mock_200

        # Should have exactly success_at sleep calls
        assert mock_sleep.call_count == success_at, (
            f"Expected {success_at} sleep calls, got {mock_sleep.call_count}"
        )

        # Verify each sleep duration matches 2^(N-1)
        for retry_number in range(1, success_at + 1):
            expected_wait = 2 ** (retry_number - 1)
            actual_call = mock_sleep.call_args_list[retry_number - 1]
            actual_wait = actual_call[0][0]
            assert actual_wait == expected_wait, (
                f"Retry {retry_number}: expected wait {expected_wait}s, "
                f"got {actual_wait}s"
            )
