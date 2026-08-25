#!/usr/bin/env python3
"""Secure local Zerodha Kite login/token-exchange helper for Trade Brain.

This script never places, modifies, or cancels orders. It performs only the documented
Kite login/token exchange, saves the resulting session values to the repository-local
ignored .env file, and validates the session with a read-only quote request.

The API secret is prompted without echo unless it already exists in the local process
or local .env. It is NOT written to .env by this helper. The short-lived redirect URL
or request_token is accepted through a normal console input so Windows clipboard paste
works reliably.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

KITE_LOGIN_URL = "https://kite.zerodha.com/connect/login"
KITE_TOKEN_URL = "https://api.kite.trade/session/token"
KITE_LTP_URL = "https://api.kite.trade/quote/ltp"
ENV_KEYS_TO_SAVE = ("KITE_API_KEY", "KITE_ACCESS_TOKEN", "KITE_LIVE_SUBSCRIPTIONS")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _strip_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            values[key] = _strip_env_value(value)
    return values


def update_env(path: Path, updates: dict[str, str]) -> None:
    """Update selected keys while preserving unrelated local .env content."""
    existing_lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.exists() else []
    remaining = dict(updates)
    out: list[str] = []
    for raw in existing_lines:
        if "=" not in raw or raw.lstrip().startswith("#"):
            out.append(raw)
            continue
        key = raw.split("=", 1)[0].strip()
        if key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(raw)
    if out and out[-1] != "":
        out.append("")
    if remaining:
        out.append("# Trade Brain Zerodha Kite MARKET_DATA_ONLY session")
        for key in ENV_KEYS_TO_SAVE:
            if key in remaining:
                out.append(f"{key}={remaining.pop(key)}")
        for key, value in remaining.items():
            out.append(f"{key}={value}")
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def extract_request_token(value: str) -> str:
    """Accept either the raw request_token or the complete redirect URL."""
    raw = value.strip()
    if not raw:
        return ""
    if "request_token=" in raw:
        candidate = raw
        if "://" not in candidate:
            candidate = f"http://local/?{candidate.lstrip('?')}"
        parsed = urllib.parse.urlparse(candidate)
        token = urllib.parse.parse_qs(parsed.query).get("request_token", [""])[0].strip()
        if token:
            return token
    return raw


def _post_form(url: str, data: dict[str, str]) -> dict[str, Any]:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=encoded,
        method="POST",
        headers={"X-Kite-Version": "3", "Accept": "application/json", "User-Agent": "TradeBrain/KiteAuth"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8", errors="replace"))
            message = payload.get("message") or payload.get("error_type") or f"HTTP {exc.code}"
        except Exception:
            message = f"HTTP {exc.code}"
        raise RuntimeError(f"Kite token exchange failed: {message}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Kite token endpoint: {exc.reason}") from exc
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise RuntimeError(f"Unexpected Kite token response: {payload.get('message') if isinstance(payload, dict) else 'invalid response'}")
    data_obj = payload.get("data")
    if not isinstance(data_obj, dict) or not data_obj.get("access_token"):
        raise RuntimeError("Kite token response did not contain access_token")
    return data_obj


def _validate_ltp(api_key: str, access_token: str, instrument: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"i": instrument})
    request = urllib.request.Request(
        f"{KITE_LTP_URL}?{query}",
        headers={
            "X-Kite-Version": "3",
            "Authorization": f"token {api_key}:{access_token}",
            "Accept": "application/json",
            "User-Agent": "TradeBrain/KiteAuth",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8", errors="replace"))
            message = payload.get("message") or payload.get("error_type") or f"HTTP {exc.code}"
        except Exception:
            message = f"HTTP {exc.code}"
        raise RuntimeError(f"Kite read-only validation failed: {message}") from exc
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise RuntimeError("Kite read-only validation returned an unexpected response")
    data = payload.get("data")
    if not isinstance(data, dict) or instrument not in data:
        raise RuntimeError(f"Kite read-only validation did not return {instrument}")
    return data[instrument]


def _audit_success(instrument: str, quote: dict[str, Any], env_path: Path) -> None:
    try:
        from backend.tradebrain.audit_txt import append_audit_record

        append_audit_record(
            category="KITE",
            event="READ_ONLY_SESSION_VALIDATED",
            payload={
                "instrument": instrument,
                "last_price": quote.get("last_price"),
                "env_path": str(env_path),
                "market_data_only": True,
                "order_execution_enabled": False,
            },
            rationale_summary="Kite session accepted a read-only LTP request for the configured focus instrument.",
            interpretation="Authentication and read-only market-data transport are working; this does not enable broker order execution.",
            source="scripts.tradebrain_kite_auth",
        )
    except Exception as exc:
        print(f"[warn] Session validated, but audit TXT write failed: {type(exc).__name__}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure Trade Brain Kite MARKET_DATA_ONLY session locally")
    parser.add_argument("--env-file", default=str(_repo_root() / ".env"))
    parser.add_argument("--instrument", default="NSE:BSE", help="Read-only quote used to validate the session")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    env_path = Path(args.env_file).expanduser().resolve()
    local_env = read_env(env_path)

    api_key = (os.getenv("KITE_API_KEY") or local_env.get("KITE_API_KEY") or input("Kite API key: ")).strip()
    if not api_key:
        print("Kite API key is required.", file=sys.stderr)
        return 2

    api_secret = (os.getenv("KITE_API_SECRET") or local_env.get("KITE_API_SECRET") or getpass.getpass("Kite API secret (hidden): ")).strip()
    if not api_secret:
        print("Kite API secret is required for token exchange.", file=sys.stderr)
        return 2

    login_url = f"{KITE_LOGIN_URL}?{urllib.parse.urlencode({'v': '3', 'api_key': api_key})}"
    print("\n1) Complete the Zerodha login in your browser.")
    print("2) After redirect, copy the ENTIRE address-bar URL (easiest), or only the request_token value.")
    print("3) Return here, paste it at the normal prompt, then press Enter immediately.")
    print("   The pasted URL WILL be visible locally so Windows Ctrl+V works reliably.")
    print("   Do not share a screenshot containing the URL/request_token before completing the exchange.")
    print("   If your redirect is http://127.0.0.1/ and the browser says it cannot connect, that is okay; copy the address bar anyway.\n")
    print(f"Login URL: {login_url}\n")
    if not args.no_browser:
        try:
            webbrowser.open(login_url)
        except Exception:
            pass

    pasted = input("Paste redirect URL or request_token: ")
    request_token = extract_request_token(pasted)
    if len(request_token) < 10:
        print("No valid request_token was pasted. Re-run the helper, complete a fresh Zerodha login, paste the full redirected URL at the prompt, and press Enter.", file=sys.stderr)
        return 2

    checksum = hashlib.sha256(f"{api_key}{request_token}{api_secret}".encode("utf-8")).hexdigest()
    try:
        session = _post_form(
            KITE_TOKEN_URL,
            {"api_key": api_key, "request_token": request_token, "checksum": checksum},
        )
        access_token = str(session["access_token"]).strip()
        quote = _validate_ltp(api_key, access_token, args.instrument.strip().upper())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    updates = {
        "KITE_API_KEY": api_key,
        "KITE_ACCESS_TOKEN": access_token,
        "KITE_LIVE_SUBSCRIPTIONS": local_env.get("KITE_LIVE_SUBSCRIPTIONS") or "NSE:BSE",
    }
    update_env(env_path, updates)
    _audit_success(args.instrument.strip().upper(), quote, env_path)

    print("\n[PASS] Kite MARKET_DATA_ONLY session validated.")
    print(f"[PASS] Read-only quote received for {args.instrument.strip().upper()}.")
    print(f"[PASS] KITE_API_KEY + KITE_ACCESS_TOKEN saved to local ignored file: {env_path}")
    print("[SAFE] API secret was not written by this helper and no order endpoint was used.")
    print("\nYou can now start Trade Brain with Start-TradeBrain.bat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
