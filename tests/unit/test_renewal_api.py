"""Unit tests for renewal_api module."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.renewal_api import PayloadConstructionError, RenewalAPI


class TestBuildDatatablesPayload:
    """Tests for _build_datatables_payload() method."""

    def test_payload_structure_with_known_inputs(self):
        """Test payload contains all required DataTables keys with correct values."""
        session_manager = MagicMock()
        api = RenewalAPI(
            session_manager=session_manager,
            base_url="https://admin.example.com",
            page_size=10,
            date_format="yyyy/MM/dd",
        )

        payload = api._build_datatables_payload(
            start=0,
            length=10,
            from_date=date(2024, 1, 15),
            to_date=date(2024, 3, 31),
            search_term="test",
        )

        # Draw counter should be 1 (first call)
        assert payload["draw"] == 1

        # Verify all 7 columns are present with correct data
        expected_columns = [
            "UserId", "CustName", "MobileNo",
            "PlanName", "Amount", "PlanExpiryDate", "ZoneName",
        ]
        for idx, col_name in enumerate(expected_columns):
            assert payload[f"columns[{idx}][data]"] == col_name
            assert payload[f"columns[{idx}][name]"] == col_name
            assert payload[f"columns[{idx}][searchable]"] == "true"
            assert payload[f"columns[{idx}][orderable]"] == "true"

        # Order parameters
        assert payload["order[0][column]"] == "0"
        assert payload["order[0][dir]"] == "asc"

        # Pagination
        assert payload["start"] == 0
        assert payload["length"] == 10

        # Search
        assert payload["search[value]"] == "test"

        # Dates
        assert payload["FromDate"] == "2024/01/15"
        assert payload["ToDate"] == "2024/03/31"

    def test_payload_with_no_search_term(self):
        """Test payload has empty search value when no search term provided."""
        session_manager = MagicMock()
        api = RenewalAPI(
            session_manager=session_manager,
            base_url="https://admin.example.com",
        )

        payload = api._build_datatables_payload(
            start=0,
            length=10,
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
            search_term=None,
        )

        assert payload["search[value]"] == ""

    def test_search_term_truncation_at_200_chars(self):
        """Test search term is truncated to 200 characters maximum."""
        session_manager = MagicMock()
        api = RenewalAPI(
            session_manager=session_manager,
            base_url="https://admin.example.com",
        )

        long_search = "a" * 300
        payload = api._build_datatables_payload(
            start=0,
            length=10,
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
            search_term=long_search,
        )

        assert len(payload["search[value]"]) == 200
        assert payload["search[value]"] == "a" * 200

    def test_search_term_under_200_chars_not_truncated(self):
        """Test search term under 200 chars is preserved as-is."""
        session_manager = MagicMock()
        api = RenewalAPI(
            session_manager=session_manager,
            base_url="https://admin.example.com",
        )

        search = "hello world"
        payload = api._build_datatables_payload(
            start=0,
            length=10,
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
            search_term=search,
        )

        assert payload["search[value]"] == "hello world"

    def test_search_term_exactly_200_chars_not_truncated(self):
        """Test search term of exactly 200 chars is preserved."""
        session_manager = MagicMock()
        api = RenewalAPI(
            session_manager=session_manager,
            base_url="https://admin.example.com",
        )

        search = "x" * 200
        payload = api._build_datatables_payload(
            start=0,
            length=10,
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
            search_term=search,
        )

        assert payload["search[value]"] == search
        assert len(payload["search[value]"]) == 200

    def test_date_formatting_in_payload(self):
        """Test dates are formatted using configured date format pattern."""
        session_manager = MagicMock()
        api = RenewalAPI(
            session_manager=session_manager,
            base_url="https://admin.example.com",
            date_format="yyyy/MM/dd",
        )

        payload = api._build_datatables_payload(
            start=0,
            length=10,
            from_date=date(2023, 7, 4),
            to_date=date(2023, 12, 25),
        )

        assert payload["FromDate"] == "2023/07/04"
        assert payload["ToDate"] == "2023/12/25"

    def test_date_formatting_with_dash_separator(self):
        """Test dates formatted with dash separator pattern."""
        session_manager = MagicMock()
        api = RenewalAPI(
            session_manager=session_manager,
            base_url="https://admin.example.com",
            date_format="yyyy-MM-dd",
        )

        payload = api._build_datatables_payload(
            start=0,
            length=10,
            from_date=date(2024, 6, 15),
            to_date=date(2024, 9, 30),
        )

        assert payload["FromDate"] == "2024-06-15"
        assert payload["ToDate"] == "2024-09-30"

    def test_draw_counter_increments(self):
        """Test draw counter increments with each call to _build_datatables_payload."""
        session_manager = MagicMock()
        api = RenewalAPI(
            session_manager=session_manager,
            base_url="https://admin.example.com",
        )

        payload1 = api._build_datatables_payload(
            start=0, length=10,
            from_date=date(2024, 1, 1), to_date=date(2024, 12, 31),
        )
        payload2 = api._build_datatables_payload(
            start=10, length=10,
            from_date=date(2024, 1, 1), to_date=date(2024, 12, 31),
        )
        payload3 = api._build_datatables_payload(
            start=20, length=10,
            from_date=date(2024, 1, 1), to_date=date(2024, 12, 31),
        )

        assert payload1["draw"] == 1
        assert payload2["draw"] == 2
        assert payload3["draw"] == 3

    def test_pagination_offset_in_payload(self):
        """Test start offset is correctly set in payload."""
        session_manager = MagicMock()
        api = RenewalAPI(
            session_manager=session_manager,
            base_url="https://admin.example.com",
            page_size=25,
        )

        payload = api._build_datatables_payload(
            start=50,
            length=25,
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
        )

        assert payload["start"] == 50
        assert payload["length"] == 25


class TestFetchAllRenewals:
    """Tests for fetch_all_renewals() pagination logic."""

    def _make_response(self, data, records_total):
        """Helper to create a mock response with .json() method."""
        json_data = {
            "draw": 1,
            "recordsTotal": records_total,
            "recordsFiltered": records_total,
            "data": data,
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.text = '{"draw":1,"recordsTotal":' + str(records_total) + ',"data":[]}'
        mock_response.json.return_value = json_data
        return mock_response

    def _make_record_data(self, user_id):
        """Helper to create a single record dict."""
        return {
            "UserId": str(user_id),
            "CustName": f"Customer {user_id}",
            "MobileNo": f"98765{user_id:05d}",
            "PlanName": "Basic Plan",
            "Amount": "500",
            "PlanExpiryDate": "/Date(1704067200000)/",
            "ZoneName": "Zone-A",
        }

    def test_pagination_with_multi_page_responses(self):
        """Test pagination fetches multiple pages until all records retrieved."""
        session_manager = MagicMock()
        api = RenewalAPI(
            session_manager=session_manager,
            base_url="https://admin.example.com",
            page_size=2,
        )

        # 5 total records, page size 2 -> 3 pages (2, 2, 1)
        page1_data = [self._make_record_data(1), self._make_record_data(2)]
        page2_data = [self._make_record_data(3), self._make_record_data(4)]
        page3_data = [self._make_record_data(5)]

        response1 = self._make_response(page1_data, records_total=5)
        response2 = self._make_response(page2_data, records_total=5)
        response3 = self._make_response(page3_data, records_total=5)

        session_manager.post.side_effect = [response1, response2, response3]

        records = api.fetch_all_renewals(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
        )

        assert len(records) == 5
        assert session_manager.post.call_count == 3

    def test_pagination_stops_on_empty_page(self):
        """Test pagination stops immediately when empty data array received."""
        session_manager = MagicMock()
        api = RenewalAPI(
            session_manager=session_manager,
            base_url="https://admin.example.com",
            page_size=10,
        )

        # First page has data, second page is empty
        page1_data = [self._make_record_data(1), self._make_record_data(2)]
        response1 = self._make_response(page1_data, records_total=100)
        response2 = self._make_response([], records_total=100)

        session_manager.post.side_effect = [response1, response2]

        records = api.fetch_all_renewals(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
        )

        assert len(records) == 2
        assert session_manager.post.call_count == 2

    def test_pagination_stops_when_cumulative_gte_records_total(self):
        """Test pagination stops when cumulative records >= recordsTotal."""
        session_manager = MagicMock()
        api = RenewalAPI(
            session_manager=session_manager,
            base_url="https://admin.example.com",
            page_size=3,
        )

        # 3 total records, page size 3 -> 1 page
        page1_data = [
            self._make_record_data(1),
            self._make_record_data(2),
            self._make_record_data(3),
        ]
        response1 = self._make_response(page1_data, records_total=3)

        session_manager.post.side_effect = [response1]

        records = api.fetch_all_renewals(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
        )

        assert len(records) == 3
        # Only one page request made since cumulative (3) >= recordsTotal (3)
        assert session_manager.post.call_count == 1

    def test_pagination_stops_when_cumulative_exceeds_records_total(self):
        """Test pagination stops when cumulative records exceed recordsTotal."""
        session_manager = MagicMock()
        api = RenewalAPI(
            session_manager=session_manager,
            base_url="https://admin.example.com",
            page_size=5,
        )

        # recordsTotal says 4, but page returns 5 records
        page1_data = [self._make_record_data(i) for i in range(1, 6)]
        response1 = self._make_response(page1_data, records_total=4)

        session_manager.post.side_effect = [response1]

        records = api.fetch_all_renewals(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
        )

        assert len(records) == 5
        assert session_manager.post.call_count == 1

    def test_single_page_response(self):
        """Test single page response when all records fit in one page."""
        session_manager = MagicMock()
        api = RenewalAPI(
            session_manager=session_manager,
            base_url="https://admin.example.com",
            page_size=10,
        )

        page_data = [self._make_record_data(i) for i in range(1, 4)]
        response = self._make_response(page_data, records_total=3)

        session_manager.post.side_effect = [response]

        records = api.fetch_all_renewals(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
        )

        assert len(records) == 3
        assert session_manager.post.call_count == 1

    def test_empty_first_page_returns_empty_list(self):
        """Test empty first page returns empty list immediately."""
        session_manager = MagicMock()
        api = RenewalAPI(
            session_manager=session_manager,
            base_url="https://admin.example.com",
            page_size=10,
        )

        response = self._make_response([], records_total=0)
        session_manager.post.side_effect = [response]

        records = api.fetch_all_renewals(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
        )

        assert records == []
        assert session_manager.post.call_count == 1

    def test_fetch_sends_post_to_correct_endpoint(self):
        """Test fetch sends POST to the correct endpoint URL."""
        session_manager = MagicMock()
        api = RenewalAPI(
            session_manager=session_manager,
            base_url="https://admin.example.com",
            page_size=10,
        )

        response = self._make_response([], records_total=0)
        session_manager.post.return_value = response

        api.fetch_all_renewals(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
        )

        call_args = session_manager.post.call_args
        assert call_args[0][0] == "https://admin.example.com/MISReport/UpcommingRenewal/GetData"

    def test_fetch_passes_search_term(self):
        """Test fetch passes search term through to payload."""
        session_manager = MagicMock()
        api = RenewalAPI(
            session_manager=session_manager,
            base_url="https://admin.example.com",
            page_size=10,
        )

        response = self._make_response([], records_total=0)
        session_manager.post.return_value = response

        api.fetch_all_renewals(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
            search_term="John",
        )

        call_args = session_manager.post.call_args
        payload = call_args[1]["data"]
        assert payload["search[value]"] == "John"

    def test_pagination_increments_start_offset(self):
        """Test pagination increments start offset by page_size each page."""
        session_manager = MagicMock()
        api = RenewalAPI(
            session_manager=session_manager,
            base_url="https://admin.example.com",
            page_size=5,
        )

        page1_data = [self._make_record_data(i) for i in range(1, 6)]
        page2_data = [self._make_record_data(i) for i in range(6, 11)]

        response1 = self._make_response(page1_data, records_total=10)
        response2 = self._make_response(page2_data, records_total=10)

        session_manager.post.side_effect = [response1, response2]

        api.fetch_all_renewals(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
        )

        # Check start offsets in the payloads
        first_call_payload = session_manager.post.call_args_list[0][1]["data"]
        second_call_payload = session_manager.post.call_args_list[1][1]["data"]

        assert first_call_payload["start"] == 0
        assert second_call_payload["start"] == 5


class TestFetchPage:
    """Tests for _fetch_page() method."""

    def test_fetch_page_sends_post_with_payload(self):
        """Test _fetch_page sends POST request with given payload."""
        session_manager = MagicMock()
        api = RenewalAPI(
            session_manager=session_manager,
            base_url="https://admin.example.com",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.text = '{"data": [], "recordsTotal": 0}'
        mock_response.json.return_value = {"data": [], "recordsTotal": 0}
        session_manager.post.return_value = mock_response

        payload = {"draw": 1, "start": 0, "length": 10}
        result = api._fetch_page(payload)

        session_manager.post.assert_called_once_with(
            "https://admin.example.com/MISReport/UpcommingRenewal/GetData",
            data=payload,
        )
        assert result == {"data": [], "recordsTotal": 0}

    def test_fetch_page_strips_trailing_slash_from_base_url(self):
        """Test base_url trailing slash is stripped for endpoint construction."""
        session_manager = MagicMock()
        api = RenewalAPI(
            session_manager=session_manager,
            base_url="https://admin.example.com/",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.text = '{"data": [], "recordsTotal": 0}'
        mock_response.json.return_value = {"data": [], "recordsTotal": 0}
        session_manager.post.return_value = mock_response

        api._fetch_page({"draw": 1})

        call_url = session_manager.post.call_args[0][0]
        assert call_url == "https://admin.example.com/MISReport/UpcommingRenewal/GetData"


class TestDateFormatConversion:
    """Tests for _convert_date_format() and _format_date() methods."""

    def test_convert_yyyy_mm_dd_slash(self):
        """Test yyyy/MM/dd converts to %Y/%m/%d."""
        result = RenewalAPI._convert_date_format("yyyy/MM/dd")
        assert result == "%Y/%m/%d"

    def test_convert_yyyy_mm_dd_dash(self):
        """Test yyyy-MM-dd converts to %Y-%m-%d."""
        result = RenewalAPI._convert_date_format("yyyy-MM-dd")
        assert result == "%Y-%m-%d"

    def test_convert_dd_mm_yyyy(self):
        """Test dd/MM/yyyy converts to %d/%m/%Y."""
        result = RenewalAPI._convert_date_format("dd/MM/yyyy")
        assert result == "%d/%m/%Y"

    def test_format_date_produces_correct_string(self):
        """Test _format_date produces correctly formatted date string."""
        session_manager = MagicMock()
        api = RenewalAPI(
            session_manager=session_manager,
            base_url="https://admin.example.com",
            date_format="yyyy/MM/dd",
        )

        result = api._format_date(date(2024, 3, 15))
        assert result == "2024/03/15"

    def test_format_date_with_single_digit_month_and_day(self):
        """Test date formatting pads single-digit month and day."""
        session_manager = MagicMock()
        api = RenewalAPI(
            session_manager=session_manager,
            base_url="https://admin.example.com",
            date_format="yyyy/MM/dd",
        )

        result = api._format_date(date(2024, 1, 5))
        assert result == "2024/01/05"
