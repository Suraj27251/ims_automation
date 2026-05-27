"""Integration test for the full fetch flow.

Tests the complete fetch pipeline with mocked API responses using the
`responses` library. Validates pagination across multiple pages, data
parsing, and record creation end-to-end.

Validates: Requirements 6.1, 6.4, 7.1, 7.2, 9.1
"""

import pytest
import responses
from datetime import date, datetime, timezone

from src.session_manager import SessionManager
from src.renewal_api import RenewalAPI
from src.data_parser import RenewalRecord


BASE_URL = "https://admin.example.com"
ENDPOINT_URL = f"{BASE_URL}/MISReport/UpcommingRenewal/GetData"


def make_record(user_id: int, expiry_ms: int = 1704067200000) -> dict:
    """Create a single API record dict with a valid ASP.NET date.

    Args:
        user_id: Numeric user ID for generating unique record data.
        expiry_ms: Milliseconds since epoch for PlanExpiryDate.
                   Default is 2024-01-01T00:00:00Z (1704067200000).
    """
    return {
        "UserId": str(user_id),
        "CustName": f"Customer {user_id}",
        "MobileNo": f"98765{user_id:05d}",
        "PlanName": f"Plan-{user_id}",
        "Amount": str(500 + user_id * 100),
        "PlanExpiryDate": f"/Date({expiry_ms})/",
        "ZoneName": f"Zone-{chr(64 + (user_id % 26) + 1)}",
    }


def make_page_response(data: list, records_total: int, draw: int = 1) -> dict:
    """Create a DataTables-compatible JSON response body."""
    return {
        "draw": draw,
        "recordsTotal": records_total,
        "recordsFiltered": records_total,
        "data": data,
    }


class TestFullFetchFlow:
    """Integration tests for the complete fetch pipeline."""

    @responses.activate
    def test_complete_fetch_pipeline_single_page(self):
        """Test complete fetch with a single page of results.

        Validates: Req 6.1 (POST to endpoint), Req 9.1 (record parsing)
        """
        records_data = [make_record(i) for i in range(1, 4)]
        responses.add(
            responses.POST,
            ENDPOINT_URL,
            json=make_page_response(records_data, records_total=3),
            status=200,
        )

        session_manager = SessionManager(
            connection_timeout=10,
            read_timeout=10,
            max_retries=0,
        )
        api = RenewalAPI(
            session_manager=session_manager,
            base_url=BASE_URL,
            page_size=10,
        )

        results = api.fetch_all_renewals(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
        )

        # Verify correct number of records returned
        assert len(results) == 3

        # Verify all results are RenewalRecord instances
        for record in results:
            assert isinstance(record, RenewalRecord)

        # Verify first record parsed correctly
        assert results[0].user_id == "1"
        assert results[0].cust_name == "Customer 1"
        assert results[0].mobile_no == "9876500001"
        assert results[0].plan_name == "Plan-1"
        assert results[0].amount == "600"
        assert results[0].zone_name == "Zone-B"

        # Verify exactly 1 request was made
        assert len(responses.calls) == 1

    @responses.activate
    def test_pagination_across_multiple_pages(self):
        """Test pagination with 5 records and page_size=2 results in 3 pages.

        Validates: Req 6.4 (iterate pages), Req 7.1 (continue until all fetched),
                   Req 7.2 (stop when cumulative >= recordsTotal)
        """
        # 5 total records, page_size=2 -> pages: [2, 2, 1]
        page1_data = [make_record(1), make_record(2)]
        page2_data = [make_record(3), make_record(4)]
        page3_data = [make_record(5)]

        responses.add(
            responses.POST,
            ENDPOINT_URL,
            json=make_page_response(page1_data, records_total=5, draw=1),
            status=200,
        )
        responses.add(
            responses.POST,
            ENDPOINT_URL,
            json=make_page_response(page2_data, records_total=5, draw=2),
            status=200,
        )
        responses.add(
            responses.POST,
            ENDPOINT_URL,
            json=make_page_response(page3_data, records_total=5, draw=3),
            status=200,
        )

        session_manager = SessionManager(
            connection_timeout=10,
            read_timeout=10,
            max_retries=0,
        )
        api = RenewalAPI(
            session_manager=session_manager,
            base_url=BASE_URL,
            page_size=2,
        )

        results = api.fetch_all_renewals(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
        )

        # Verify all 5 records fetched
        assert len(results) == 5

        # Verify correct number of pages requested (3 pages)
        assert len(responses.calls) == 3

        # Verify records are in order
        for i, record in enumerate(results, start=1):
            assert record.user_id == str(i)
            assert record.cust_name == f"Customer {i}"

    @responses.activate
    def test_pagination_stops_on_empty_page(self):
        """Test pagination stops immediately when an empty page is received.

        Validates: Req 7.2 (stop on empty page - design says stop on empty)
        """
        page1_data = [make_record(1), make_record(2)]

        responses.add(
            responses.POST,
            ENDPOINT_URL,
            json=make_page_response(page1_data, records_total=10, draw=1),
            status=200,
        )
        responses.add(
            responses.POST,
            ENDPOINT_URL,
            json=make_page_response([], records_total=10, draw=2),
            status=200,
        )

        session_manager = SessionManager(
            connection_timeout=10,
            read_timeout=10,
            max_retries=0,
        )
        api = RenewalAPI(
            session_manager=session_manager,
            base_url=BASE_URL,
            page_size=2,
        )

        results = api.fetch_all_renewals(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
        )

        # Only 2 records from first page
        assert len(results) == 2
        # Stopped after 2 requests (didn't keep going)
        assert len(responses.calls) == 2

    @responses.activate
    def test_pagination_stops_when_cumulative_equals_total(self):
        """Test pagination stops exactly when cumulative records == recordsTotal.

        Validates: Req 7.2 (stop when cumulative == recordsTotal)
        """
        # 4 records, page_size=2 -> exactly 2 pages
        page1_data = [make_record(1), make_record(2)]
        page2_data = [make_record(3), make_record(4)]

        responses.add(
            responses.POST,
            ENDPOINT_URL,
            json=make_page_response(page1_data, records_total=4, draw=1),
            status=200,
        )
        responses.add(
            responses.POST,
            ENDPOINT_URL,
            json=make_page_response(page2_data, records_total=4, draw=2),
            status=200,
        )

        session_manager = SessionManager(
            connection_timeout=10,
            read_timeout=10,
            max_retries=0,
        )
        api = RenewalAPI(
            session_manager=session_manager,
            base_url=BASE_URL,
            page_size=2,
        )

        results = api.fetch_all_renewals(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
        )

        assert len(results) == 4
        # Exactly 2 pages requested, no extra request
        assert len(responses.calls) == 2

    @responses.activate
    def test_data_parsing_with_aspnet_dates(self):
        """Test date parsing integration with valid ASP.NET dates.

        Validates: Req 9.1 (field extraction including PlanExpiryDate)
        """
        # Use different timestamps for each record
        # 2024-01-01 00:00:00 UTC = 1704067200000
        # 2024-06-15 12:00:00 UTC = 1718452800000
        # 2024-12-31 23:59:59 UTC = 1735689599000
        records_data = [
            make_record(1, expiry_ms=1704067200000),
            make_record(2, expiry_ms=1718452800000),
            make_record(3, expiry_ms=1735689599000),
        ]

        responses.add(
            responses.POST,
            ENDPOINT_URL,
            json=make_page_response(records_data, records_total=3),
            status=200,
        )

        session_manager = SessionManager(
            connection_timeout=10,
            read_timeout=10,
            max_retries=0,
        )
        api = RenewalAPI(
            session_manager=session_manager,
            base_url=BASE_URL,
            page_size=10,
        )

        results = api.fetch_all_renewals(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
        )

        assert len(results) == 3

        # Verify dates were parsed to datetime objects
        assert results[0].plan_expiry_date == datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert results[1].plan_expiry_date == datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        assert results[2].plan_expiry_date == datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

        # Verify all dates are timezone-aware
        for record in results:
            assert record.plan_expiry_date is not None
            assert record.plan_expiry_date.tzinfo is not None

    @responses.activate
    def test_data_parsing_all_fields_mapped_correctly(self):
        """Test all RenewalRecord fields are correctly mapped from JSON.

        Validates: Req 9.1 (extract UserId, CustName, MobileNo, PlanName,
                   Amount, PlanExpiryDate, ZoneName)
        """
        record_json = {
            "UserId": "42",
            "CustName": "Alice Smith",
            "MobileNo": "9123456789",
            "PlanName": "Premium 200Mbps",
            "Amount": "1499",
            "PlanExpiryDate": "/Date(1709251200000)/",  # 2024-03-01 00:00:00 UTC
            "ZoneName": "Downtown",
        }

        responses.add(
            responses.POST,
            ENDPOINT_URL,
            json=make_page_response([record_json], records_total=1),
            status=200,
        )

        session_manager = SessionManager(
            connection_timeout=10,
            read_timeout=10,
            max_retries=0,
        )
        api = RenewalAPI(
            session_manager=session_manager,
            base_url=BASE_URL,
            page_size=10,
        )

        results = api.fetch_all_renewals(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
        )

        assert len(results) == 1
        record = results[0]
        assert record.user_id == "42"
        assert record.cust_name == "Alice Smith"
        assert record.mobile_no == "9123456789"
        assert record.plan_name == "Premium 200Mbps"
        assert record.amount == "1499"
        assert record.plan_expiry_date == datetime(2024, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert record.zone_name == "Downtown"

    @responses.activate
    def test_empty_response_returns_empty_list(self):
        """Test that an empty first page returns an empty list.

        Validates: Req 7.1 (pagination terminates correctly)
        """
        responses.add(
            responses.POST,
            ENDPOINT_URL,
            json=make_page_response([], records_total=0),
            status=200,
        )

        session_manager = SessionManager(
            connection_timeout=10,
            read_timeout=10,
            max_retries=0,
        )
        api = RenewalAPI(
            session_manager=session_manager,
            base_url=BASE_URL,
            page_size=10,
        )

        results = api.fetch_all_renewals(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
        )

        assert results == []
        assert len(responses.calls) == 1

    @responses.activate
    def test_pagination_payload_offsets_increment_correctly(self):
        """Test that pagination sends correct start offsets in each request.

        Validates: Req 6.4 (incrementing page offset by page size)
        """
        page_size = 3
        # 7 records -> pages at offsets 0, 3, 6
        page1_data = [make_record(i) for i in range(1, 4)]
        page2_data = [make_record(i) for i in range(4, 7)]
        page3_data = [make_record(7)]

        responses.add(
            responses.POST,
            ENDPOINT_URL,
            json=make_page_response(page1_data, records_total=7, draw=1),
            status=200,
        )
        responses.add(
            responses.POST,
            ENDPOINT_URL,
            json=make_page_response(page2_data, records_total=7, draw=2),
            status=200,
        )
        responses.add(
            responses.POST,
            ENDPOINT_URL,
            json=make_page_response(page3_data, records_total=7, draw=3),
            status=200,
        )

        session_manager = SessionManager(
            connection_timeout=10,
            read_timeout=10,
            max_retries=0,
        )
        api = RenewalAPI(
            session_manager=session_manager,
            base_url=BASE_URL,
            page_size=page_size,
        )

        results = api.fetch_all_renewals(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
        )

        assert len(results) == 7
        assert len(responses.calls) == 3

        # Verify the start offsets in each request body
        # The responses library captures the request body
        call_bodies = []
        for call in responses.calls:
            body = call.request.body
            # Parse the URL-encoded form data
            from urllib.parse import parse_qs
            parsed = parse_qs(body)
            call_bodies.append(parsed)

        assert call_bodies[0]["start"] == ["0"]
        assert call_bodies[1]["start"] == ["3"]
        assert call_bodies[2]["start"] == ["6"]

    @responses.activate
    def test_large_dataset_pagination(self):
        """Test pagination with a larger dataset (20 records, page_size=5).

        Validates: Req 6.4, 7.1, 7.2 (pagination across many pages)
        """
        total_records = 20
        page_size = 5
        expected_pages = 4  # 20 / 5 = 4 pages

        for page_num in range(expected_pages):
            start_id = page_num * page_size + 1
            end_id = start_id + page_size
            page_data = [make_record(i) for i in range(start_id, end_id)]
            responses.add(
                responses.POST,
                ENDPOINT_URL,
                json=make_page_response(page_data, records_total=total_records, draw=page_num + 1),
                status=200,
            )

        session_manager = SessionManager(
            connection_timeout=10,
            read_timeout=10,
            max_retries=0,
        )
        api = RenewalAPI(
            session_manager=session_manager,
            base_url=BASE_URL,
            page_size=page_size,
        )

        results = api.fetch_all_renewals(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
        )

        # All 20 records fetched
        assert len(results) == total_records
        # Exactly 4 pages requested
        assert len(responses.calls) == expected_pages
        # Records are in order
        for i, record in enumerate(results, start=1):
            assert record.user_id == str(i)

    @responses.activate
    def test_records_with_timezone_offset_dates(self):
        """Test parsing records with ASP.NET dates that include timezone offsets.

        Validates: Req 9.1 (field extraction with timezone-aware dates)
        """
        # Record with +0530 offset (India Standard Time)
        record_json = {
            "UserId": "100",
            "CustName": "Raj Kumar",
            "MobileNo": "9876543210",
            "PlanName": "Fiber 50Mbps",
            "Amount": "799",
            "PlanExpiryDate": "/Date(1704067200000+0530)/",
            "ZoneName": "Mumbai",
        }

        responses.add(
            responses.POST,
            ENDPOINT_URL,
            json=make_page_response([record_json], records_total=1),
            status=200,
        )

        session_manager = SessionManager(
            connection_timeout=10,
            read_timeout=10,
            max_retries=0,
        )
        api = RenewalAPI(
            session_manager=session_manager,
            base_url=BASE_URL,
            page_size=10,
        )

        results = api.fetch_all_renewals(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 12, 31),
        )

        assert len(results) == 1
        record = results[0]
        assert record.user_id == "100"
        assert record.plan_expiry_date is not None
        assert record.plan_expiry_date.tzinfo is not None
        # The datetime should represent the same instant as 2024-01-01 00:00:00 UTC
        # but displayed in +05:30
        from datetime import timedelta
        expected_offset = timezone(timedelta(hours=5, minutes=30))
        assert record.plan_expiry_date.tzinfo == expected_offset
