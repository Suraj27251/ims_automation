"""Property-based tests for data_exporter module."""

import csv
import io
import json
import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import pytest
from hypothesis import given, strategies as st, settings

from data_parser import RenewalRecord
from data_exporter import DataExporter


# --- Strategies for Property 14 ---

# Strategy for optional string fields (non-empty or None)
optional_strings = st.one_of(
    st.text(
        alphabet=st.characters(blacklist_categories=("Cs",)),
        min_size=1,
        max_size=50,
    ),
    st.none(),
)


@st.composite
def renewal_records(draw):
    """Generate a random RenewalRecord with optional string fields and no date."""
    return RenewalRecord(
        user_id=draw(optional_strings),
        cust_name=draw(optional_strings),
        mobile_no=draw(optional_strings),
        plan_name=draw(optional_strings),
        amount=draw(optional_strings),
        plan_expiry_date=None,
        zone_name=draw(optional_strings),
    )


def renewal_record_lists():
    """Strategy for lists of RenewalRecord objects."""
    return st.lists(renewal_records(), min_size=0, max_size=20)


class TestCSVExportStructureIntegrity:
    """Property 14: CSV Export Structure Integrity

    **Validates: Requirements 11.2**

    For any list of RenewalRecord objects, the CSV export SHALL produce a file
    where the first row contains headers in the order [UserId, CustName,
    MobileNo, PlanName, Amount, PlanExpiryDate, ZoneName] and subsequent rows
    contain the corresponding field values with row count equal to the input
    record count.
    """

    EXPECTED_HEADERS = [
        "UserId",
        "CustName",
        "MobileNo",
        "PlanName",
        "Amount",
        "PlanExpiryDate",
        "ZoneName",
    ]

    def _create_exporter(self):
        """Create a DataExporter with a mocked AppConfig."""
        mock_config = MagicMock()
        return DataExporter(mock_config)

    @given(records=renewal_record_lists())
    @settings(max_examples=100)
    def test_first_row_is_correct_header(self, records):
        """First row of CSV contains headers in the correct order.

        **Validates: Requirements 11.2**
        """
        exporter = self._create_exporter()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as tmp:
            tmp_path = Path(tmp.name)

        try:
            exporter.export_csv(records, tmp_path)

            with open(tmp_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header_row = next(reader)

            assert header_row == self.EXPECTED_HEADERS, (
                f"Header mismatch:\n"
                f"  Expected: {self.EXPECTED_HEADERS}\n"
                f"  Actual:   {header_row}"
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    @given(records=renewal_record_lists())
    @settings(max_examples=100)
    def test_data_row_count_equals_input_record_count(self, records):
        """Number of data rows equals the input record count.

        **Validates: Requirements 11.2**
        """
        exporter = self._create_exporter()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as tmp:
            tmp_path = Path(tmp.name)

        try:
            exporter.export_csv(records, tmp_path)

            with open(tmp_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                all_rows = list(reader)

            # First row is header, rest are data rows
            data_rows = all_rows[1:]
            assert len(data_rows) == len(records), (
                f"Data row count mismatch:\n"
                f"  Expected: {len(records)} rows\n"
                f"  Actual:   {len(data_rows)} rows"
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    @given(records=renewal_record_lists())
    @settings(max_examples=100)
    def test_each_row_has_exactly_seven_fields(self, records):
        """Each row (header and data) has exactly 7 fields.

        **Validates: Requirements 11.2**
        """
        exporter = self._create_exporter()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as tmp:
            tmp_path = Path(tmp.name)

        try:
            exporter.export_csv(records, tmp_path)

            with open(tmp_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                all_rows = list(reader)

            for i, row in enumerate(all_rows):
                assert len(row) == 7, (
                    f"Row {i} has {len(row)} fields, expected 7.\n"
                    f"  Row content: {row}"
                )
        finally:
            tmp_path.unlink(missing_ok=True)



# --- Property 13: Console Export Produces Valid JSON ---


def _create_exporter() -> DataExporter:
    """Create a DataExporter with a mocked AppConfig."""
    mock_config = MagicMock()
    return DataExporter(mock_config)


class TestConsoleExportProducesValidJSON:
    """Property 13: Console Export Produces Valid JSON

    **Validates: Requirements 11.1**

    For any list of RenewalRecord objects (including empty list), the console
    export SHALL produce output that is valid JSON parseable back into a list,
    with 2-space indentation.
    """

    @given(records=renewal_record_lists())
    @settings(max_examples=200)
    def test_output_is_valid_json(self, records):
        """Console export output is valid JSON (json.loads succeeds).

        **Validates: Requirements 11.1**
        """
        exporter = _create_exporter()

        # Capture stdout
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            exporter.export_console(records)
        finally:
            sys.stdout = old_stdout

        output = captured.getvalue()

        # json.loads should not raise
        parsed = json.loads(output)
        assert parsed is not None or output.strip() == "null"

    @given(records=renewal_record_lists())
    @settings(max_examples=200)
    def test_parsed_result_is_a_list(self, records):
        """Parsed JSON result is a list.

        **Validates: Requirements 11.1**
        """
        exporter = _create_exporter()

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            exporter.export_console(records)
        finally:
            sys.stdout = old_stdout

        output = captured.getvalue()
        parsed = json.loads(output)

        assert isinstance(parsed, list), (
            f"Expected list, got {type(parsed).__name__}: {parsed!r}"
        )

    @given(records=renewal_record_lists())
    @settings(max_examples=200)
    def test_list_length_equals_input_record_count(self, records):
        """Parsed list length equals input record count.

        **Validates: Requirements 11.1**
        """
        exporter = _create_exporter()

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            exporter.export_console(records)
        finally:
            sys.stdout = old_stdout

        output = captured.getvalue()
        parsed = json.loads(output)

        assert len(parsed) == len(records), (
            f"Expected {len(records)} records, got {len(parsed)}"
        )

    @given(records=renewal_record_lists())
    @settings(max_examples=200)
    def test_output_uses_2_space_indentation(self, records):
        """Output uses 2-space indentation.

        **Validates: Requirements 11.1**
        """
        exporter = _create_exporter()

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            exporter.export_console(records)
        finally:
            sys.stdout = old_stdout

        output = captured.getvalue()

        # Verify 2-space indentation by re-serializing with indent=2
        # and comparing to the actual output (minus trailing newline from print)
        parsed = json.loads(output)
        expected_output = json.dumps(parsed, indent=2, ensure_ascii=False)

        # print() adds a trailing newline, so strip both for comparison
        assert output.strip() == expected_output.strip(), (
            f"Output indentation mismatch.\n"
            f"Expected:\n{expected_output[:200]}\n"
            f"Got:\n{output[:200]}"
        )
