# Implementation Plan: IMS Data Fetcher

## Overview

Implement a modular Python CLI application that automates authenticated data extraction from an ISP admin panel. The implementation follows the pipeline architecture: Configuration → Authentication → Data Fetching → Parsing → Export. Each module is built incrementally with property-based and unit tests validating correctness at each stage.

## Tasks

- [x] 1. Set up project structure and dependencies
  - [x] 1.1 Create project directory structure and install dependencies
    - Create `src/` directory with empty `__init__.py`
    - Create `tests/unit/`, `tests/property/`, `tests/integration/` directories
    - Create `requirements.txt` with: requests>=2.31.0, python-dotenv>=1.0.0, beautifulsoup4>=4.12.0, PyMySQL>=1.1.0
    - Create `requirements-dev.txt` with: pytest>=7.4.0, pytest-mock>=3.12.0, pytest-cov>=4.1.0, hypothesis>=6.92.0, responses>=0.24.0
    - Create `pytest.ini` or `pyproject.toml` with pytest configuration
    - _Requirements: 12.1, 12.4_

- [x] 2. Implement configuration loader
  - [x] 2.1 Implement `config_loader.py` with AppConfig dataclass and load_config function
    - Define `AppConfig` frozen dataclass with all fields (login_url, username, password, mysql_*, retry_count, connection_timeout, read_timeout, page_size, date_format, export_formats, debug_mode, diagnostic_mode, file_logging)
    - Define `ConfigError` exception class
    - Implement `load_config()` that reads from `.env` file and environment variables (system env takes precedence)
    - Implement `validate_url()` to check HTTP/HTTPS scheme and non-empty host
    - Implement `validate_date_format()` to check only valid specifiers (y, M, d, /, -)
    - Accept CLI overrides dict that takes highest precedence
    - Raise `ConfigError` listing all missing required variables when any are absent
    - Reject whitespace-only credential values with `ConfigError`
    - _Requirements: 1.5, 1.6, 8.1, 8.3, 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7, 12.8_

  - [x] 2.2 Write property test for whitespace credential rejection
    - **Property 10: Whitespace Credential Rejection**
    - **Validates: Requirements 1.6**

  - [x] 2.3 Write property test for URL validation
    - **Property 11: URL Validation**
    - **Validates: Requirements 12.5, 12.6**

  - [x] 2.4 Write property test for invalid date format rejection
    - **Property 12: Invalid Date Format Rejection**
    - **Validates: Requirements 8.3**

  - [x] 2.5 Write property test for missing config variables listed in error
    - **Property 16: Missing Config Variables Listed in Error**
    - **Validates: Requirements 12.3**

  - [x] 2.6 Write unit tests for config_loader
    - Test loading from environment variables
    - Test `.env` file loading with system env precedence
    - Test default values for optional parameters
    - Test MySQL config required when mysql_enabled is true
    - Test CLI overrides take highest precedence
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.7_

- [x] 3. Implement date parser
  - [x] 3.1 Implement `date_parser.py` with ASP.NET date conversion functions
    - Define `DateParseError` as subclass of `ValueError`
    - Define `ASPNET_DATE_PATTERN` regex for `/Date(ms)/` and `/Date(ms±HHMM)/`
    - Define `MIN_TIMESTAMP_MS` (946684800000) and `MAX_TIMESTAMP_MS` (4102444800000)
    - Implement `parse_aspnet_date()` that converts ASP.NET date string to timezone-aware datetime
    - Implement `datetime_to_aspnet_date()` for round-trip conversion back to ASP.NET format
    - Handle UTC (no offset) and offset variants (±HHMM)
    - Raise `DateParseError` for invalid format or out-of-range timestamps
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 3.2 Write property test for ASP.NET date parsing round-trip
    - **Property 1: ASP.NET Date Parsing Round-Trip**
    - **Validates: Requirements 10.1, 10.2, 10.5**

  - [x] 3.3 Write property test for invalid ASP.NET date rejection
    - **Property 2: Invalid ASP.NET Date Rejection**
    - **Validates: Requirements 10.3**

  - [x] 3.4 Write property test for out-of-range date rejection
    - **Property 3: Out-of-Range Date Rejection**
    - **Validates: Requirements 10.4**

  - [x] 3.5 Write unit tests for date_parser
    - Test known good dates with expected datetime output
    - Test UTC dates without offset
    - Test dates with positive and negative timezone offsets
    - Test boundary values (exactly at min/max range)
    - Test malformed strings (missing slashes, no parentheses, letters in ms)
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement session manager
  - [x] 5.1 Implement `session_manager.py` with retry and re-auth logic
    - Define `AuthenticationError` exception class
    - Implement `SessionManager` class with `requests.Session()` lifecycle
    - Implement `get()` and `post()` methods with retry and re-auth
    - Implement `_execute_with_retry()` with exponential backoff (2^(N-1) seconds)
    - Implement `_should_retry()` for connection errors, timeouts, 5xx responses
    - Implement `_handle_auth_failure()` with re-auth rate limiting (3 per 60s)
    - Immediate failure on 4xx (except 401, 403, 429)
    - Configure connection timeout (30s) and read timeout (60s)
    - Accept `reauth_callback` for transparent re-authentication
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.1, 4.2, 4.3, 13.1, 13.2, 13.3, 13.4, 13.5_

  - [x] 5.2 Write property test for exponential backoff timing
    - **Property 17: Exponential Backoff Timing**
    - **Validates: Requirements 13.2**

  - [x] 5.3 Write unit tests for session_manager
    - Test retry on connection errors with correct backoff timing
    - Test retry on 5xx responses
    - Test immediate failure on 4xx (not 401/403/429)
    - Test re-authentication triggered on 401/403
    - Test re-auth rate limiting (3 per 60s)
    - Test successful request passes through without retry
    - _Requirements: 3.1, 3.2, 3.4, 3.6, 13.1, 13.2, 13.3, 13.4, 13.5_

- [x] 6. Implement login handler
  - [x] 6.1 Implement `login_handler.py` with token extraction and login flow
    - Define `LoginError` and `LoginParsingError` exception classes
    - Implement `LoginHandler` class with `authenticate()` method
    - Implement `_extract_hidden_fields()` using BeautifulSoup to parse hidden inputs
    - Extract `__VIEWSTATE`, `__VIEWSTATEGENERATOR`, `__EVENTVALIDATION`, anti-forgery tokens
    - Implement `_validate_login_response()` to check status 200 + session cookie
    - Full flow: GET login page → extract tokens → POST credentials + tokens → validate response
    - Raise `LoginParsingError` with first 500 chars of response on parse failure
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4_

  - [x] 6.2 Write property test for hidden form field extraction
    - **Property 9: Hidden Form Field Extraction**
    - **Validates: Requirements 2.2**

  - [x] 6.3 Write unit tests for login_handler
    - Test successful login flow with mocked HTTP responses
    - Test hidden field extraction from sample ASP.NET HTML
    - Test login failure on 401/403 response
    - Test login failure on 200 with no session cookie
    - Test LoginParsingError on malformed HTML
    - Test retry behavior on network errors
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4_

- [x] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Implement renewal API
  - [x] 8.1 Implement `renewal_api.py` with DataTables payload and pagination
    - Define `PayloadConstructionError` exception class
    - Implement `RenewalAPI` class with `ENDPOINT_PATH` and `COLUMNS` constants
    - Implement `_build_datatables_payload()` with all DataTables parameters (draw, columns[0..6], order, start, length, search, FromDate, ToDate)
    - Implement `fetch_all_renewals()` with pagination loop (stop on cumulative >= recordsTotal or empty page)
    - Implement `_fetch_page()` for single page request and JSON parsing
    - Truncate search terms to 200 characters maximum
    - Format dates using configured date format
    - Increment draw counter per request
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 7.1, 7.2, 7.3, 7.4, 8.2_

  - [x] 8.2 Write property test for DataTables payload structure completeness
    - **Property 4: DataTables Payload Structure Completeness**
    - **Validates: Requirements 5.1, 5.2, 5.3, 6.2**

  - [x] 8.3 Write property test for search term truncation
    - **Property 5: Search Term Truncation**
    - **Validates: Requirements 6.3**

  - [x] 8.4 Write property test for pagination completeness
    - **Property 6: Pagination Completeness**
    - **Validates: Requirements 6.4, 7.1, 7.2**

  - [x] 8.5 Write unit tests for renewal_api
    - Test payload structure with known inputs
    - Test pagination with multi-page responses
    - Test pagination stops on empty page
    - Test pagination stops when cumulative >= recordsTotal
    - Test search term truncation at 200 chars
    - Test date formatting in payload
    - Test draw counter increments
    - _Requirements: 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.3_

- [x] 9. Implement data parser
  - [x] 9.1 Implement `data_parser.py` with RenewalRecord and parsing functions
    - Define `RenewalRecord` dataclass with all fields (user_id, cust_name, mobile_no, plan_name, amount, plan_expiry_date, zone_name)
    - Define `ParseError` exception class
    - Implement `parse_renewal_response()` to extract records from API response dict
    - Implement `parse_record()` to convert single JSON object to RenewalRecord
    - Default missing/null fields to None
    - Pass PlanExpiryDate through `date_parser.parse_aspnet_date()`
    - Raise `ParseError` with first 500 chars on invalid response structure
    - Return empty list for zero records
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [x] 9.2 Write property test for renewal record field extraction with defaults
    - **Property 7: Renewal Record Field Extraction with Defaults**
    - **Validates: Requirements 9.1, 9.2**

  - [x] 9.3 Write property test for renewal record round-trip fidelity
    - **Property 8: Renewal Record Round-Trip Fidelity**
    - **Validates: Requirements 9.5**

  - [x] 9.4 Write unit tests for data_parser
    - Test parsing complete record with all fields
    - Test parsing record with missing fields (defaults to None)
    - Test parsing record with null fields
    - Test parsing empty data array returns empty list
    - Test ParseError on invalid response structure
    - Test PlanExpiryDate passed through date_parser
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

- [x] 10. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Implement data exporter
  - [x] 11.1 Implement `data_exporter.py` with console, CSV, and MySQL export
    - Define `ExportError` exception class
    - Implement `DataExporter` class with `FIELD_ORDER` constant
    - Implement `export_console()` to print JSON with 2-space indentation
    - Implement `export_csv()` to write CSV with header row in specified field order
    - Implement `export_mysql()` with INSERT IGNORE (skip existing UserIds)
    - Handle empty records list gracefully for all export types
    - Read MySQL connection params from config
    - Raise `ExportError` on file write or database failures
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8_

  - [x] 11.2 Write property test for console export produces valid JSON
    - **Property 13: Console Export Produces Valid JSON**
    - **Validates: Requirements 11.1**

  - [x] 11.3 Write property test for CSV export structure integrity
    - **Property 14: CSV Export Structure Integrity**
    - **Validates: Requirements 11.2**

  - [x] 11.4 Write unit tests for data_exporter
    - Test console export outputs valid JSON with 2-space indent
    - Test CSV export with header row and correct field order
    - Test CSV export with empty records produces header-only file
    - Test MySQL export skips existing UserIds
    - Test ExportError on file write failure
    - Test ExportError on MySQL connection failure
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.7_

- [x] 12. Implement diagnostics module
  - [x] 12.1 Implement `diagnostics.py` with request/response persistence
    - Implement `DiagnosticsManager` class with enabled flag and output directory
    - Implement `save_request()` with timestamped filename and credential masking
    - Implement `save_response()` with timestamped filename
    - Implement `log_redirect()` for 3xx responses with masked credentials
    - Create `diagnostics/` directory on first write if it doesn't exist
    - No-op all methods when disabled
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5_

  - [x] 12.2 Write property test for credential masking in output
    - **Property 15: Credential Masking in Output**
    - **Validates: Requirements 14.5, 15.4**

  - [x] 12.3 Write unit tests for diagnostics
    - Test request saving with credential masking
    - Test response saving with timestamped filenames
    - Test redirect logging
    - Test no-op when disabled
    - Test directory creation on first write
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5_

- [x] 13. Implement CLI entry point and orchestration
  - [x] 13.1 Implement `main.py` with argument parsing and orchestration
    - Implement `build_argument_parser()` with --from-date, --to-date, --page-size, --debug, --export arguments
    - Implement `main()` orchestration: parse args → load config → init session → authenticate → fetch data → export
    - Configure logging (console always, file logging when enabled, rotating at 5MB with 5 backups)
    - Enable diagnostic mode when --debug flag is provided
    - Validate date arguments against configured format
    - Display usage instructions when required date arguments are missing
    - Return exit code 0 on success, 1 on error
    - Wire all modules together (config → session → login → API → parser → exporter)
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7, 16.1, 16.2, 16.3, 16.4, 16.5, 16.6_

  - [x] 13.2 Write unit tests for main.py
    - Test argument parsing with valid arguments
    - Test missing date arguments shows usage
    - Test invalid date format raises validation error
    - Test --debug enables diagnostic mode
    - Test orchestration flow with mocked modules
    - Test exit code 0 on success, 1 on error
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6_

- [x] 14. Integration tests and final wiring
  - [x] 14.1 Write integration test for full login flow
    - Test complete login flow with mocked HTTP server
    - Test GET login page → extract tokens → POST credentials → validate session
    - _Requirements: 1.1, 1.2, 2.1, 2.2, 2.3_

  - [x] 14.2 Write integration test for full fetch flow
    - Test complete fetch pipeline with mocked API responses
    - Test pagination across multiple pages
    - Test data parsing and record creation end-to-end
    - _Requirements: 6.1, 6.4, 7.1, 7.2, 9.1_

  - [x] 14.3 Write integration test for MySQL export
    - Test MySQL export with test database
    - Test duplicate UserId handling (skip existing)
    - _Requirements: 11.3, 11.5_

- [x] 15. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The project uses Python with pytest + hypothesis for property-based testing
- All modules communicate through well-defined interfaces (dataclasses and exceptions)
- Credentials are never hardcoded; always loaded from environment variables or `.env` file

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "3.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4", "2.5", "2.6", "3.2", "3.3", "3.4", "3.5"] },
    { "id": 3, "tasks": ["5.1", "6.1"] },
    { "id": 4, "tasks": ["5.2", "5.3", "6.2", "6.3"] },
    { "id": 5, "tasks": ["8.1", "9.1"] },
    { "id": 6, "tasks": ["8.2", "8.3", "8.4", "8.5", "9.2", "9.3", "9.4"] },
    { "id": 7, "tasks": ["11.1", "12.1"] },
    { "id": 8, "tasks": ["11.2", "11.3", "11.4", "12.2", "12.3"] },
    { "id": 9, "tasks": ["13.1"] },
    { "id": 10, "tasks": ["13.2", "14.1", "14.2", "14.3"] }
  ]
}
```
