"""Unit tests for the diagnostics module."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.diagnostics import DiagnosticsManager, _mask_credentials


class TestMaskCredentials:
    """Tests for the _mask_credentials helper function."""

    def test_masks_password_key(self):
        data = {"username": "admin", "password": "secret123"}
        result = _mask_credentials(data)
        assert result["username"] == "admin"
        assert result["password"] == "***MASKED***"

    def test_masks_cookie_key(self):
        data = {"session_cookie": "abc123", "data": "value"}
        result = _mask_credentials(data)
        assert result["session_cookie"] == "***MASKED***"
        assert result["data"] == "value"

    def test_masks_token_key(self):
        data = {"auth_token": "bearer_xyz", "name": "test"}
        result = _mask_credentials(data)
        assert result["auth_token"] == "***MASKED***"
        assert result["name"] == "test"

    def test_masks_auth_key(self):
        data = {"Authorization": "Basic abc", "Content-Type": "application/json"}
        result = _mask_credentials(data)
        assert result["Authorization"] == "***MASKED***"
        assert result["Content-Type"] == "application/json"

    def test_case_insensitive_matching(self):
        data = {"PASSWORD": "secret", "Cookie": "val", "AUTH_TOKEN": "tok"}
        result = _mask_credentials(data)
        assert result["PASSWORD"] == "***MASKED***"
        assert result["Cookie"] == "***MASKED***"
        assert result["AUTH_TOKEN"] == "***MASKED***"

    def test_masks_nested_dict(self):
        data = {"headers": {"Authorization": "Bearer xyz", "Accept": "text/html"}}
        result = _mask_credentials(data)
        assert result["headers"]["Authorization"] == "***MASKED***"
        assert result["headers"]["Accept"] == "text/html"

    def test_does_not_modify_original(self):
        data = {"password": "secret"}
        _mask_credentials(data)
        assert data["password"] == "secret"


class TestDiagnosticsManagerDisabled:
    """Tests that all methods are no-ops when disabled."""

    def test_save_request_noop_when_disabled(self, tmp_path):
        mgr = DiagnosticsManager(enabled=False, output_dir=tmp_path / "diag")
        mgr.save_request("http://example.com", "POST", {"key": "val"}, {})
        assert not (tmp_path / "diag").exists()

    def test_save_response_noop_when_disabled(self, tmp_path):
        mgr = DiagnosticsManager(enabled=False, output_dir=tmp_path / "diag")
        mgr.save_response("http://example.com", 200, {}, "body")
        assert not (tmp_path / "diag").exists()

    def test_log_redirect_noop_when_disabled(self, tmp_path):
        mgr = DiagnosticsManager(enabled=False, output_dir=tmp_path / "diag")
        mgr.log_redirect("http://example.com", 302, "http://other.com", {})
        assert not (tmp_path / "diag").exists()


class TestDiagnosticsManagerEnabled:
    """Tests for enabled diagnostics manager."""

    def test_save_request_creates_directory(self, tmp_path):
        output_dir = tmp_path / "diagnostics"
        mgr = DiagnosticsManager(enabled=True, output_dir=output_dir)
        mgr.save_request("http://example.com", "POST", {"data": "val"}, {})
        assert output_dir.exists()

    def test_save_request_creates_file(self, tmp_path):
        output_dir = tmp_path / "diagnostics"
        mgr = DiagnosticsManager(enabled=True, output_dir=output_dir)
        mgr.save_request("http://example.com", "GET", {}, {})
        files = list(output_dir.glob("request_*.json"))
        assert len(files) == 1

    def test_save_request_masks_credentials(self, tmp_path):
        output_dir = tmp_path / "diagnostics"
        mgr = DiagnosticsManager(enabled=True, output_dir=output_dir)
        mgr.save_request(
            "http://example.com",
            "POST",
            {"username": "admin", "password": "secret"},
            {"Authorization": "Bearer token123", "Content-Type": "application/json"},
        )
        files = list(output_dir.glob("request_*.json"))
        content = json.loads(files[0].read_text(encoding="utf-8"))
        assert content["payload"]["username"] == "admin"
        assert content["payload"]["password"] == "***MASKED***"
        assert content["headers"]["Authorization"] == "***MASKED***"
        assert content["headers"]["Content-Type"] == "application/json"

    def test_save_request_contains_url_and_method(self, tmp_path):
        output_dir = tmp_path / "diagnostics"
        mgr = DiagnosticsManager(enabled=True, output_dir=output_dir)
        mgr.save_request("http://example.com/api", "POST", {}, {})
        files = list(output_dir.glob("request_*.json"))
        content = json.loads(files[0].read_text(encoding="utf-8"))
        assert content["url"] == "http://example.com/api"
        assert content["method"] == "POST"

    def test_save_request_timestamped_filename(self, tmp_path):
        output_dir = tmp_path / "diagnostics"
        mgr = DiagnosticsManager(enabled=True, output_dir=output_dir)
        with patch("src.diagnostics.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "20240101_120000_000000"
            mgr.save_request("http://example.com", "GET", {}, {})
        files = list(output_dir.glob("request_20240101_120000_000000.json"))
        assert len(files) == 1

    def test_save_response_creates_file(self, tmp_path):
        output_dir = tmp_path / "diagnostics"
        mgr = DiagnosticsManager(enabled=True, output_dir=output_dir)
        mgr.save_response("http://example.com", 200, {"Content-Type": "text/html"}, "<html></html>")
        files = list(output_dir.glob("response_*.json"))
        assert len(files) == 1

    def test_save_response_contains_all_fields(self, tmp_path):
        output_dir = tmp_path / "diagnostics"
        mgr = DiagnosticsManager(enabled=True, output_dir=output_dir)
        mgr.save_response(
            "http://example.com/api",
            200,
            {"Content-Type": "application/json"},
            '{"data": []}',
        )
        files = list(output_dir.glob("response_*.json"))
        content = json.loads(files[0].read_text(encoding="utf-8"))
        assert content["url"] == "http://example.com/api"
        assert content["status_code"] == 200
        assert content["headers"]["Content-Type"] == "application/json"
        assert content["body"] == '{"data": []}'

    def test_save_response_timestamped_filename(self, tmp_path):
        output_dir = tmp_path / "diagnostics"
        mgr = DiagnosticsManager(enabled=True, output_dir=output_dir)
        with patch("src.diagnostics.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "20240315_143022_123456"
            mgr.save_response("http://example.com", 404, {}, "Not Found")
        files = list(output_dir.glob("response_20240315_143022_123456.json"))
        assert len(files) == 1

    def test_log_redirect_creates_file(self, tmp_path):
        output_dir = tmp_path / "diagnostics"
        mgr = DiagnosticsManager(enabled=True, output_dir=output_dir)
        mgr.log_redirect(
            "http://example.com/login",
            302,
            "http://example.com/dashboard",
            {"Set-Cookie": "session=abc"},
        )
        files = list(output_dir.glob("redirect_*.json"))
        assert len(files) == 1

    def test_log_redirect_contains_all_fields(self, tmp_path):
        output_dir = tmp_path / "diagnostics"
        mgr = DiagnosticsManager(enabled=True, output_dir=output_dir)
        mgr.log_redirect(
            "http://example.com/old",
            301,
            "http://example.com/new",
            {"Location": "http://example.com/new"},
        )
        files = list(output_dir.glob("redirect_*.json"))
        content = json.loads(files[0].read_text(encoding="utf-8"))
        assert content["url"] == "http://example.com/old"
        assert content["status_code"] == 301
        assert content["location"] == "http://example.com/new"

    def test_log_redirect_masks_credentials_in_headers(self, tmp_path):
        output_dir = tmp_path / "diagnostics"
        mgr = DiagnosticsManager(enabled=True, output_dir=output_dir)
        mgr.log_redirect(
            "http://example.com",
            302,
            "http://example.com/home",
            {"Set-Cookie": "session=secret", "Authorization": "Bearer xyz"},
        )
        files = list(output_dir.glob("redirect_*.json"))
        content = json.loads(files[0].read_text(encoding="utf-8"))
        assert content["headers"]["Set-Cookie"] == "***MASKED***"
        assert content["headers"]["Authorization"] == "***MASKED***"

    def test_directory_created_only_on_first_write(self, tmp_path):
        output_dir = tmp_path / "diagnostics"
        mgr = DiagnosticsManager(enabled=True, output_dir=output_dir)
        assert not output_dir.exists()
        mgr.save_request("http://example.com", "GET", {}, {})
        assert output_dir.exists()
        # Second call should not fail even though dir already exists
        mgr.save_response("http://example.com", 200, {}, "ok")
        files = list(output_dir.iterdir())
        assert len(files) == 2

    def test_multiple_requests_create_separate_files(self, tmp_path):
        output_dir = tmp_path / "diagnostics"
        mgr = DiagnosticsManager(enabled=True, output_dir=output_dir)
        mgr.save_request("http://example.com/1", "GET", {}, {})
        mgr.save_request("http://example.com/2", "POST", {"a": "b"}, {})
        files = list(output_dir.glob("request_*.json"))
        assert len(files) == 2
