"""
Property-based tests for the Renewal API module.

Tests DataTables payload structure completeness and pagination correctness
using Hypothesis.
"""

import math
import sys
import os
from datetime import date
from unittest.mock import MagicMock, patch

from hypothesis import given, settings, strategies as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from renewal_api import RenewalAPI


# --- Strategies for Property 4 ---

# Non-negative page offsets
page_offsets = st.integers(min_value=0, max_value=100000)

# Positive page sizes
page_sizes = st.integers(min_value=1, max_value=1000)

# Valid dates in a reasonable range
valid_dates = st.dates(
    min_value=date(2000, 1, 1),
    max_value=date(2099, 12, 31),
)

# Optional search terms (None or string up to 200 characters)
search_terms = st.one_of(
    st.none(),
    st.text(
        alphabet=st.characters(blacklist_categories=("Cs",)),
        min_size=0,
        max_size=200,
    ),
)


@st.composite
def valid_date_ranges(draw):
    """Generate valid date ranges where from_date <= to_date."""
    d1 = draw(valid_dates)
    d2 = draw(valid_dates)
    if d1 <= d2:
        return (d1, d2)
    else:
        return (d2, d1)


class TestDataTablesPayloadStructureCompleteness:
    """Property 4: DataTables Payload Structure Completeness

    **Validates: Requirements 5.1, 5.2, 5.3, 6.2**

    For any valid combination of page offset (non-negative integer), page size
    (positive integer), date range (two valid dates where from <= to), and
    optional search term (string up to 200 characters), the constructed
    DataTables payload SHALL contain all required keys: draw,
    columns[0..6][data], columns[0..6][name], columns[0..6][searchable],
    columns[0..6][orderable], order[0][column], order[0][dir], start, length,
    search[value], FromDate, and ToDate — with FromDate and ToDate formatted
    according to the configured date format.
    """

    @given(
        start=page_offsets,
        length=page_sizes,
        date_range=valid_date_ranges(),
        search_term=search_terms,
    )
    @settings(max_examples=200, deadline=None)
    def test_payload_contains_all_required_keys(
        self, start: int, length: int, date_range, search_term
    ):
        """The DataTables payload must contain all required keys for any
        valid combination of inputs."""
        from_date, to_date = date_range

        # Create a RenewalAPI instance (session_manager not needed for payload building)
        api = RenewalAPI(
            session_manager=None,
            base_url="https://example.com",
            page_size=length,
            date_format="yyyy/MM/dd",
        )

        payload = api._build_datatables_payload(
            start=start,
            length=length,
            from_date=from_date,
            to_date=to_date,
            search_term=search_term,
        )

        # Build the set of all required keys
        required_keys = set()

        # draw counter
        required_keys.add("draw")

        # Column definitions for columns 0..6
        for idx in range(7):
            required_keys.add(f"columns[{idx}][data]")
            required_keys.add(f"columns[{idx}][name]")
            required_keys.add(f"columns[{idx}][searchable]")
            required_keys.add(f"columns[{idx}][orderable]")

        # Order parameters
        required_keys.add("order[0][column]")
        required_keys.add("order[0][dir]")

        # Pagination parameters
        required_keys.add("start")
        required_keys.add("length")

        # Search parameter
        required_keys.add("search[value]")

        # Date parameters
        required_keys.add("FromDate")
        required_keys.add("ToDate")

        # Verify all required keys are present
        payload_keys = set(payload.keys())
        missing_keys = required_keys - payload_keys
        assert not missing_keys, (
            f"Payload is missing required keys: {missing_keys}\n"
            f"Payload keys: {sorted(payload_keys)}\n"
            f"Inputs: start={start}, length={length}, "
            f"from_date={from_date}, to_date={to_date}, "
            f"search_term={repr(search_term)}"
        )

    @given(
        start=page_offsets,
        length=page_sizes,
        date_range=valid_date_ranges(),
        search_term=search_terms,
    )
    @settings(max_examples=200, deadline=None)
    def test_from_date_and_to_date_formatted_correctly(
        self, start: int, length: int, date_range, search_term
    ):
        """FromDate and ToDate must be formatted according to the configured
        date format (yyyy/MM/dd)."""
        from_date, to_date = date_range

        api = RenewalAPI(
            session_manager=None,
            base_url="https://example.com",
            page_size=length,
            date_format="yyyy/MM/dd",
        )

        payload = api._build_datatables_payload(
            start=start,
            length=length,
            from_date=from_date,
            to_date=to_date,
            search_term=search_term,
        )

        # Verify dates are formatted as yyyy/MM/dd
        expected_from = from_date.strftime("%Y/%m/%d")
        expected_to = to_date.strftime("%Y/%m/%d")

        assert payload["FromDate"] == expected_from, (
            f"FromDate format mismatch: got {payload['FromDate']!r}, "
            f"expected {expected_from!r}"
        )
        assert payload["ToDate"] == expected_to, (
            f"ToDate format mismatch: got {payload['ToDate']!r}, "
            f"expected {expected_to!r}"
        )


class TestPaginationCompleteness:
    """
    Property 6: Pagination Completeness
    **Validates: Requirements 6.4, 7.1, 7.2**

    For any total record count (recordsTotal > 0) and page size (positive integer),
    the pagination logic SHALL request exactly ceil(recordsTotal / page_size) pages,
    with each page's start offset incrementing by page_size, and the cumulative
    fetched records SHALL equal recordsTotal.
    """

    @given(
        records_total=st.integers(min_value=1, max_value=500),
        page_size=st.integers(min_value=1, max_value=50),
    )
    @settings(max_examples=200, deadline=None)
    def test_pagination_completeness(self, records_total, page_size):
        """
        **Validates: Requirements 6.4, 7.1, 7.2**

        Verify that for any recordsTotal and page_size:
        1. The number of POST calls equals ceil(recordsTotal / page_size)
        2. Each call's start offset increments by page_size
        3. Total records returned equals recordsTotal
        """
        expected_pages = math.ceil(records_total / page_size)

        # Build mock responses for each page
        def make_mock_response(start):
            """Create a mock response for a given start offset."""
            remaining = records_total - start
            page_record_count = min(page_size, remaining)

            page_data = [
                {
                    "UserId": f"user_{start + i}",
                    "CustName": f"Customer {start + i}",
                    "MobileNo": f"900000{start + i:04d}",
                    "PlanName": "TestPlan",
                    "Amount": "100",
                    "PlanExpiryDate": None,
                    "ZoneName": "Zone-A",
                }
                for i in range(page_record_count)
            ]

            response_json = {
                "recordsTotal": records_total,
                "recordsFiltered": records_total,
                "data": page_data,
                "draw": 1,
            }

            mock_resp = MagicMock()
            mock_resp.json.return_value = response_json
            return mock_resp

        # Track calls to session_manager.post
        call_payloads = []

        def mock_post(url, data=None, **kwargs):
            call_payloads.append(data)
            start_offset = data.get("start", 0)
            return make_mock_response(start_offset)

        # Set up the RenewalAPI with mocked session manager
        mock_session_manager = MagicMock()
        mock_session_manager.post.side_effect = mock_post

        api = RenewalAPI(
            session_manager=mock_session_manager,
            base_url="https://admin.example.com",
            page_size=page_size,
        )

        # Execute the pagination - parse_renewal_response is imported locally
        # inside fetch_all_renewals, so we let it run with real parsing.
        # Since PlanExpiryDate is None, no date parsing issues will occur.
        records = api.fetch_all_renewals(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
        )

        # Assertion 1: Number of POST calls equals ceil(recordsTotal / page_size)
        assert len(call_payloads) == expected_pages, (
            f"Expected {expected_pages} page requests for "
            f"recordsTotal={records_total}, page_size={page_size}, "
            f"but got {len(call_payloads)}"
        )

        # Assertion 2: Each call's start offset increments by page_size
        for i, payload in enumerate(call_payloads):
            expected_start = i * page_size
            actual_start = payload["start"]
            assert actual_start == expected_start, (
                f"Page {i}: expected start offset {expected_start}, "
                f"got {actual_start}"
            )

        # Assertion 3: Total records returned equals recordsTotal
        assert len(records) == records_total, (
            f"Expected {records_total} total records, "
            f"but got {len(records)}"
        )


# --- Strategies for Property 5 ---

# Arbitrary strings of varying lengths (0 to 600) for search term truncation testing
search_terms_arbitrary_length = st.text(
    alphabet=st.characters(codec="utf-8", categories=("L", "N", "P", "S", "Z")),
    min_size=0,
    max_size=600,
)


class TestSearchTermTruncation:
    """Property 5: Search Term Truncation

    **Validates: Requirements 6.3**

    For any string of arbitrary length provided as a search term, the DataTables
    payload SHALL contain a search[value] field whose length is at most 200
    characters, and for strings of 200 characters or fewer, the value SHALL equal
    the original input.
    """

    def _build_api(self):
        """Create a RenewalAPI instance with a mock session manager."""
        mock_session = MagicMock()
        return RenewalAPI(
            session_manager=mock_session,
            base_url="https://admin.example.com",
            page_size=10,
            date_format="yyyy/MM/dd",
        )

    @given(search_term=search_terms_arbitrary_length)
    @settings(max_examples=200, deadline=None)
    def test_search_value_length_never_exceeds_200(self, search_term: str):
        """The payload search[value] field length is always <= 200 characters."""
        api = self._build_api()
        payload = api._build_datatables_payload(
            start=0,
            length=10,
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
            search_term=search_term,
        )

        assert len(payload["search[value]"]) <= 200, (
            f"search[value] length {len(payload['search[value]'])} exceeds 200 "
            f"for input of length {len(search_term)}"
        )

    @given(
        search_term=st.text(
            alphabet=st.characters(codec="utf-8", categories=("L", "N", "P", "S", "Z")),
            min_size=0,
            max_size=200,
        )
    )
    @settings(max_examples=200, deadline=None)
    def test_short_search_term_preserved_exactly(self, search_term: str):
        """For strings of 200 characters or fewer, the value equals the original input."""
        api = self._build_api()
        payload = api._build_datatables_payload(
            start=0,
            length=10,
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
            search_term=search_term,
        )

        assert payload["search[value]"] == search_term, (
            f"search[value] does not match original for string of length "
            f"{len(search_term)}:\n"
            f"  Expected: {search_term!r}\n"
            f"  Got:      {payload['search[value]']!r}"
        )

    @given(
        search_term=st.text(
            alphabet=st.characters(codec="utf-8", categories=("L", "N", "P", "S", "Z")),
            min_size=201,
            max_size=600,
        )
    )
    @settings(max_examples=200, deadline=None)
    def test_long_search_term_truncated_to_first_200_chars(self, search_term: str):
        """For strings > 200 chars, the value equals the first 200 characters."""
        api = self._build_api()
        payload = api._build_datatables_payload(
            start=0,
            length=10,
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
            search_term=search_term,
        )

        expected = search_term[:200]
        assert payload["search[value]"] == expected, (
            f"search[value] not truncated correctly for string of length "
            f"{len(search_term)}:\n"
            f"  Expected first 200: {expected!r}\n"
            f"  Got:                {payload['search[value]']!r}"
        )
