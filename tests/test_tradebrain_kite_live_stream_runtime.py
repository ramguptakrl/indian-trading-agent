from __future__ import annotations

import json

import requests

from scripts.tradebrain_kite_live_stream import _emit_failure, _is_auth_rejection


def _http_error(status_code: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status_code
    error = requests.HTTPError(f"HTTP {status_code}")
    error.response = response
    return error


def test_kite_auth_rejection_detects_rest_403() -> None:
    assert _is_auth_rejection(_http_error(403)) is True
    assert _is_auth_rejection(_http_error(401)) is True
    assert _is_auth_rejection(_http_error(500)) is False


def test_kite_auth_rejection_detects_websocket_403_text() -> None:
    exc = RuntimeError("server rejected WebSocket connection: HTTP 403")
    assert _is_auth_rejection(exc) is True


def test_expired_session_emits_clean_auth_required_message(capsys) -> None:
    code = _emit_failure(_http_error(403))
    captured = capsys.readouterr()
    payload = json.loads(captured.err.strip())

    assert code == 2
    assert payload["status"] == "KITE_AUTH_REQUIRED"
    assert payload["reason"] == "ZERODHA_SESSION_REJECTED"
    assert "tradebrain_kite_auth.py" in payload["refresh_command"]
    assert payload["order_api_enabled"] is False
    assert "Traceback" not in captured.err


def test_non_auth_stream_failure_remains_distinct(capsys) -> None:
    code = _emit_failure(RuntimeError("network unavailable"))
    captured = capsys.readouterr()
    payload = json.loads(captured.err.strip())

    assert code == 1
    assert payload["status"] == "KITE_STREAM_FAILED"
    assert payload["error_type"] == "RuntimeError"
    assert payload["order_api_enabled"] is False
