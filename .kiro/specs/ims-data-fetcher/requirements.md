# Requirements Document

## Introduction

IMS Data Fetcher is a lightweight Python application that programmatically authenticates with an ISP admin panel and extracts renewal/customer data via backend API calls. The application SHALL implement a lightweight modular API extraction architecture focused on authenticated backend data retrieval. It automates login, maintains authenticated sessions, fetches paginated renewal data from the `/MISReport/UpcommingRenewal/GetData` endpoint, normalizes ASP.NET date formats, and exports results to console, CSV, or MySQL. The scope is strictly limited to backend API data extraction — no AI layer, WhatsApp automation, notifications, or CRM workflows.

## Phase 1 Scope

### Included

- Login automation (including hidden form token extraction)
- Session persistence using `requests.Session()`
- Renewal data extraction via paginated API calls
- JSON response normalization and date parsing
- CSV export and MySQL export (optional)

### Explicitly Excluded

- Distributed session management
- Browser automation (Selenium, Playwright, etc.)
- Queue workers or background job processing
- Analytics pipelines
- Notification systems (email, SMS, WhatsApp)

## Glossary

- **Session_Manager**: The module responsible for creating, persisting, and refreshing authenticated HTTP sessions using `requests.Session()`
- **Login_Handler**: The module that reverse-engineers and automates the ISP admin panel login flow, including hidden form token extraction, to obtain authenticated cookies
- **Renewal_API**: The module that constructs and sends DataTables-compatible POST requests to the `/MISReport/UpcommingRenewal/GetData` endpoint with pagination, date filtering, and search parameters
- **Date_Parser**: The utility module that converts ASP.NET `/Date(xxx)/` timestamp strings into Python `datetime` objects
- **Data_Exporter**: The module responsible for outputting normalized renewal data to console (JSON), CSV files, or MySQL database (optional)
- **Config_Loader**: The module that reads credentials and configuration from environment variables and `.env` files
- **Renewal_Record**: A normalized data object containing: UserId, CustName, MobileNo, PlanName, Amount, PlanExpiryDate, ZoneName
- **ASP.NET_Date_Format**: A timestamp format used by the backend in the pattern `/Date(milliseconds_since_epoch)/`
- **Admin_Panel**: The ISP management web application that exposes backend API endpoints for data retrieval
- **Authenticated_Session**: An HTTP session with valid cookies that grants access to protected API endpoints
- **DataTables_Payload**: A server-side request payload compatible with jQuery DataTables, containing draw, columns, order, pagination, and search parameters
- **Diagnostic_Mode**: A runtime mode that persists raw HTTP request/response data for reverse engineering and troubleshooting

## Requirements

### Requirement 1: Automated Login

**User Story:** As a service operator, I want the system to programmatically authenticate with the ISP admin panel, so that I can obtain an authenticated session without manual browser interaction.

#### Acceptance Criteria

1. WHEN valid credentials are provided via environment variables, THE Login_Handler SHALL submit a POST request to the login endpoint within the configured timeout (default 30 seconds) and obtain authenticated session cookies
2. WHEN the login HTTP response returns a status code of 200 and the response contains a valid session cookie (non-empty Set-Cookie header), THE Login_Handler SHALL store all response cookies in the Session_Manager
3. IF the login HTTP response returns a status code indicating authentication failure (401 or 403) or returns status 200 with no session cookie set, THEN THE Login_Handler SHALL raise an authentication error with a message indicating the login URL and the nature of the failure
4. IF the login request fails due to a network error (connection timeout, DNS resolution failure, or connection refused), THEN THE Login_Handler SHALL retry the request up to 2 times with exponential backoff starting at 1 second and doubling each subsequent wait, before raising a connection error
5. THE Login_Handler SHALL read the login URL, username, and password exclusively from environment variables or a `.env` file
6. IF any required credential environment variable (login URL, username, or password) is present but contains an empty or whitespace-only value, THEN THE Login_Handler SHALL raise a configuration error identifying the invalid variable

### Requirement 2: Login Form Token Extraction

**User Story:** As a service operator, I want the system to handle hidden login form tokens, so that authentication succeeds on ASP.NET applications that require anti-forgery or ViewState tokens.

#### Acceptance Criteria

1. WHEN initiating the login flow, THE Login_Handler SHALL first perform a GET request to the login page URL before submitting credentials via POST
2. WHEN hidden form fields exist in the login page HTML response, THE Login_Handler SHALL extract and preserve all hidden input field names and values
3. IF ASP.NET fields (`__VIEWSTATE`, `__VIEWSTATEGENERATOR`, `__EVENTVALIDATION`, or anti-forgery tokens) are present in the login page response, THEN THE Login_Handler SHALL include all extracted hidden field values in the login POST request payload alongside the username and password
4. IF token extraction fails due to HTML parsing errors or missing expected form elements, THEN THE Login_Handler SHALL raise a login parsing exception with diagnostic information including the login URL and the first 500 characters of the response body

### Requirement 3: Session Management

**User Story:** As a service operator, I want the system to maintain and reuse authenticated sessions, so that repeated API calls do not require re-authentication.

#### Acceptance Criteria

1. THE Session_Manager SHALL use a `requests.Session()` object to persist cookies automatically across all HTTP requests during runtime
2. WHEN an API request returns an HTTP 401 or 403 status code, THE Session_Manager SHALL trigger a re-authentication flow via the Login_Handler and retry the failed request exactly once with the refreshed session
3. WHILE an authenticated session is active, THE Session_Manager SHALL attach all stored cookies to outgoing requests automatically
4. IF re-authentication via the Login_Handler fails after an HTTP 401 or 403 response, THEN THE Session_Manager SHALL raise an authentication error to the caller without retrying the original request
5. THE Session_Manager SHALL provide a single shared session instance to all API modules
6. IF the Session_Manager has attempted re-authentication 3 consecutive times within 60 seconds, THEN THE Session_Manager SHALL raise an authentication error instead of attempting further re-authentication

### Requirement 4: Session Persistence

**User Story:** As a service operator, I want authenticated sessions to persist cookies and handle re-authentication transparently, so that long-running data extraction operations complete without manual intervention.

#### Acceptance Criteria

1. THE Session_Manager SHALL maintain authenticated sessions using a `requests.Session()` object that persists cookies automatically during runtime
2. WHILE the application is executing, THE Session_Manager SHALL persist all cookies received from the server across subsequent requests without manual cookie management
3. IF an authenticated session expires (detected by HTTP 401 or 403 response), THEN THE Session_Manager SHALL attempt re-authentication automatically via the Login_Handler before raising an error to the caller

### Requirement 5: DataTables-Compatible Payload Builder

**User Story:** As a service operator, I want the system to construct DataTables-compatible request payloads, so that the backend API returns properly paginated and filtered data.

#### Acceptance Criteria

1. THE Renewal_API SHALL dynamically construct DataTables-compatible request payloads for each API request to `/MISReport/UpcommingRenewal/GetData`
2. THE Renewal_API SHALL include the following DataTables parameters in each request payload: `draw` counter, `columns[x][data]`, `columns[x][name]`, `columns[x][searchable]`, `columns[x][orderable]`, `order[x][column]`, `order[x][dir]`, `start` offset, `length` page size, and `search[value]` filter
3. THE Renewal_API SHALL support configurable page size (default 10) and configurable column ordering (default ascending by first column)
4. IF payload generation fails due to invalid parameters, THEN THE Renewal_API SHALL log the malformed payload content for diagnostics and raise a payload construction error

### Requirement 6: Renewal Data Fetching

**User Story:** As a service operator, I want to fetch upcoming renewal data from the admin panel API, so that I can extract customer renewal information programmatically.

#### Acceptance Criteria

1. THE Renewal_API SHALL send a POST request to `/MISReport/UpcommingRenewal/GetData` with a DataTables-compatible request payload containing the pagination offset, page size, date range parameters, and search parameter
2. WHEN a date range is specified, THE Renewal_API SHALL include `FromDate` and `ToDate` parameters formatted as `yyyy/MM/dd` strings in the request payload
3. WHEN a search term is specified, THE Renewal_API SHALL include the search term as a string parameter in the request payload, with a maximum length of 200 characters
4. WHEN the response indicates that total available records exceed the number of records returned in the current page, THE Renewal_API SHALL iterate through all pages by incrementing the page offset by the page size until the cumulative records retrieved equals or exceeds the total record count reported by the API
5. IF the API request returns an HTTP 5xx status code or a connection timeout, THEN THE Renewal_API SHALL retry the request up to 2 times with exponential backoff starting at 1 second before raising an error
6. IF the API request returns an HTTP 4xx status code other than 401 or 403, THEN THE Renewal_API SHALL raise an error immediately without retrying
7. WHEN a response with HTTP status 200 and a valid JSON body is received, THE Renewal_API SHALL return the parsed JSON response body containing the record list and total record count for downstream processing

### Requirement 7: Pagination Termination

**User Story:** As a service operator, I want the system to automatically stop paginating when all records are retrieved, so that no unnecessary API requests are made.

#### Acceptance Criteria

1. THE Renewal_API SHALL continue requesting subsequent pages until all records have been retrieved
2. WHEN the cumulative number of fetched records equals the `recordsTotal` value reported in the API response, THE Renewal_API SHALL stop pagination
3. WHEN an API response returns an empty data array (zero records in the current page), THE Renewal_API SHALL stop pagination immediately regardless of the reported `recordsTotal`
4. WHILE paginating, THE Renewal_API SHALL track and log the total fetched record count after each page request

### Requirement 8: Date Format Configuration

**User Story:** As a service operator, I want configurable date formatting with sensible defaults, so that date parameters match the backend API expectations.

#### Acceptance Criteria

1. THE Config_Loader SHALL provide a configurable date format parameter with a default value of `yyyy/MM/dd`
2. WHEN a date format is configured, THE Renewal_API SHALL use the configured format for `FromDate` and `ToDate` parameters in API requests
3. IF an invalid date format string is provided (containing characters other than valid date format specifiers: y, M, d, and separator characters / or -), THEN THE Config_Loader SHALL raise a validation error identifying the invalid format string

### Requirement 9: JSON Response Parsing

**User Story:** As a service operator, I want the system to parse API responses into structured records, so that I can work with clean, normalized data.

#### Acceptance Criteria

1. WHEN a valid JSON response is received from the Renewal_API, THE Data_Parser SHALL extract the following fields from each JSON object in the response array: UserId, CustName, MobileNo, PlanName, Amount, PlanExpiryDate, ZoneName
2. IF a JSON response contains a missing or null field, THEN THE Data_Parser SHALL assign a default value of `None` for that field in the Renewal_Record
3. IF the response body is not valid JSON, THEN THE Data_Parser SHALL raise a parsing error including the first 500 characters of the raw response content for debugging
4. THE Data_Parser SHALL return a list of Renewal_Record objects for each successful parse operation, returning an empty list when the response contains zero records
5. THE Data_Parser SHALL produce Renewal_Record field values that are string-equal for string fields and numerically equal for numeric fields when compared to the original JSON response values, with None mapping to JSON null (round-trip property)
6. WHEN extracting the PlanExpiryDate field, THE Data_Parser SHALL pass the raw ASP.NET date string value to the Date_Parser for conversion to a Python datetime object before storing it in the Renewal_Record

### Requirement 10: ASP.NET Date Normalization

**User Story:** As a service operator, I want ASP.NET date timestamps converted to standard Python datetime objects, so that dates are human-readable and usable in downstream processing.

#### Acceptance Criteria

1. WHEN a date string matching the pattern `/Date(milliseconds)/` is provided, THE Date_Parser SHALL convert the milliseconds value (milliseconds since Unix epoch, 1970-01-01 00:00:00 UTC) to a Python `datetime` object in UTC with timezone info set to UTC
2. WHEN a date string matching the pattern `/Date(milliseconds±HHMM)/` is provided (where ±HHMM is a timezone offset such as +0530 or -0500), THE Date_Parser SHALL return a timezone-aware Python `datetime` object with the timezone set to the specified offset
3. IF a date string does not match the expected ASP.NET date pattern (`/Date(milliseconds)/` or `/Date(milliseconds±HHMM)/`), THEN THE Date_Parser SHALL raise a ValueError with an error message that includes the invalid input string
4. IF the millisecond value represents a date outside the range of year 2000 (946684800000 ms) through year 2100 (4102444800000 ms), THEN THE Date_Parser SHALL raise a ValueError indicating the date is out of the supported range
5. THE Date_Parser SHALL produce the original millisecond value when a valid parsed `datetime` object is converted back to ASP.NET date format (round-trip property)

### Requirement 11: Data Export

**User Story:** As a service operator, I want to export fetched renewal data to multiple formats, so that I can use the data in different downstream systems.

#### Acceptance Criteria

1. WHEN console export is requested, THE Data_Exporter SHALL print all Renewal_Records as JSON with 2-space indentation to standard output
2. WHEN CSV export is requested, THE Data_Exporter SHALL write all Renewal_Records to the caller-specified file path as a CSV file with a header row containing columns in the order: UserId, CustName, MobileNo, PlanName, Amount, PlanExpiryDate, ZoneName
3. WHEN MySQL export is requested and MySQL persistence is enabled, THE Data_Exporter SHALL insert all Renewal_Records into the configured database table, skipping records whose UserId already exists in the table
4. IF a CSV file write fails due to a filesystem error, THEN THE Data_Exporter SHALL raise an error with the file path and failure reason
5. IF a MySQL insert fails due to a connection or query error, THEN THE Data_Exporter SHALL raise an error with the connection details (excluding password) and failure reason
6. THE Data_Exporter SHALL read MySQL connection parameters exclusively from environment variables or a `.env` file
7. IF the Renewal_Records list is empty, THEN THE Data_Exporter SHALL complete the export operation without error, producing an empty JSON array for console export, a CSV file containing only the header row for CSV export, or no database inserts for MySQL export
8. THE Data_Exporter SHALL support the following export targets: console output (always available), CSV export (always available), and MySQL persistence (optional, enabled via configuration)

### Requirement 12: Configuration Management

**User Story:** As a service operator, I want all sensitive configuration stored in environment variables, so that credentials are never hardcoded in source files.

#### Acceptance Criteria

1. THE Config_Loader SHALL read the following required parameters from environment variables or a `.env` file: login URL, username, and password
2. WHEN MySQL export is enabled, THE Config_Loader SHALL additionally require MySQL connection parameters (host, port, database name, user, password) from environment variables or a `.env` file
3. IF one or more required environment variables are missing, THEN THE Config_Loader SHALL raise a configuration error listing all missing variable names
4. THE Config_Loader SHALL provide default values for optional configuration parameters (retry count: 2, timeout: 30 seconds, export format: console, MySQL enabled: false, date format: yyyy/MM/dd)
5. THE Config_Loader SHALL validate that the login URL contains an HTTP or HTTPS scheme followed by a valid host component
6. IF the login URL fails validation, THEN THE Config_Loader SHALL raise a configuration error indicating the URL is malformed
7. WHEN both a `.env` file value and a system environment variable exist for the same parameter, THE Config_Loader SHALL use the system environment variable value
8. THE Config_Loader SHALL accept the following export format values: console, csv, mysql, or any combination thereof

### Requirement 13: Error Handling and Retry Logic

**User Story:** As a service operator, I want the system to handle transient failures gracefully, so that temporary network issues do not cause permanent data loss.

#### Acceptance Criteria

1. WHEN an HTTP request fails with a connection failure, timeout error, or HTTP 5xx status code, THE Session_Manager SHALL retry the request up to 2 times with simple exponential backoff
2. WHILE retrying a failed request, THE Session_Manager SHALL wait 1 second before the first retry and double the wait time for each subsequent retry
3. WHEN all retry attempts are exhausted, THE Session_Manager SHALL log the final error response including the request URL, failure reason, and total number of attempts made, then raise an error
4. IF an HTTP request fails with a non-retryable status code (4xx other than 401, 403, or 429), THEN THE Session_Manager SHALL raise an error immediately without retrying
5. THE Session_Manager SHALL use a connection timeout of 30 seconds and a read timeout of 60 seconds for each HTTP request attempt

### Requirement 14: Logging

**User Story:** As a service operator, I want logging for all operations, so that I can diagnose issues and monitor system behavior.

#### Acceptance Criteria

1. THE IMS_Data_Fetcher SHALL log all login attempts, API requests, pagination progress, parsing errors, and authentication failures with a timestamp in ISO 8601 format, the log level, and a human-readable message
2. WHEN an error occurs, THE IMS_Data_Fetcher SHALL log the error at ERROR level with the operation name, input parameters (excluding credentials), the error message, and the exception type
3. THE IMS_Data_Fetcher SHALL write log output to the console (required)
4. WHERE file logging is enabled via configuration, THE IMS_Data_Fetcher SHALL additionally write log output to a rotating log file in the `logs/` directory, where each log file rotates at a maximum size of 5 MB and retains up to 5 backup files
5. THE IMS_Data_Fetcher SHALL exclude passwords, session cookies, and authentication tokens from all log output by masking or omitting their values
6. THE IMS_Data_Fetcher SHALL log successful operations at INFO level and retry attempts at WARNING level
7. WHILE debug mode is enabled, THE IMS_Data_Fetcher SHALL additionally log request payloads, response status codes, and raw JSON responses at DEBUG level

### Requirement 15: Diagnostic Mode

**User Story:** As a service operator, I want a diagnostic mode that captures raw HTTP data, so that I can reverse-engineer API behavior and troubleshoot authentication or data issues.

#### Acceptance Criteria

1. WHERE diagnostic mode is enabled via configuration or CLI flag, THE IMS_Data_Fetcher SHALL persist raw request payloads to the `diagnostics/` directory with timestamped filenames
2. WHERE diagnostic mode is enabled, THE IMS_Data_Fetcher SHALL persist raw HTTP response bodies and response headers to the `diagnostics/` directory
3. WHERE diagnostic mode is enabled, THE IMS_Data_Fetcher SHALL log all authentication redirects (HTTP 301, 302, 303, 307, 308 responses) with the redirect URL and response headers
4. THE IMS_Data_Fetcher SHALL exclude passwords and credentials from diagnostic output by masking their values
5. WHILE diagnostic mode is disabled, THE IMS_Data_Fetcher SHALL not persist any raw HTTP data to disk

### Requirement 16: Command-Line Execution

**User Story:** As a service operator, I want to run the data fetcher from the command line with configurable parameters, so that I can control execution without modifying configuration files.

#### Acceptance Criteria

1. THE IMS_Data_Fetcher SHALL provide a CLI entry point via `python main.py` that accepts command-line arguments
2. THE IMS_Data_Fetcher SHALL accept the following CLI arguments: `--from-date` (start date in configured format), `--to-date` (end date in configured format), `--page-size` (pagination limit, default 10), and `--debug` (enable debug/diagnostic mode)
3. WHEN `--from-date` and `--to-date` are provided, THE IMS_Data_Fetcher SHALL use the specified date range for the renewal data query
4. WHEN `--debug` flag is provided, THE IMS_Data_Fetcher SHALL enable both debug logging and diagnostic mode for the execution
5. IF a provided date argument does not match the configured date format, THEN THE IMS_Data_Fetcher SHALL raise a validation error and display usage instructions
6. WHEN no date arguments are provided, THE IMS_Data_Fetcher SHALL display usage instructions indicating that `--from-date` and `--to-date` are required parameters
