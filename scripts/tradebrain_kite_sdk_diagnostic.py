#!/usr/bin/env python3
"""Independent Zerodha Kite Connect SDK diagnostic for Trade Brain.

This uses Zerodha's official Python client for the token exchange and a read-only LTP
request. It never places, modifies, or cancels orders. Secrets are never printed or
written by this script.
"""

from __future__ import annotations

import getpass
import hashlib
import sys
import urllib.parse
import webbrowser


def extract_request_token(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    if "request_token=" in raw:
        candidate = raw if "://" in raw else f"http://local/?{raw.lstrip('?')}"
        parsed = urllib.parse.urlparse(candidate)
        return urllib.parse.parse_qs(parsed.query).get("request_token", [""])[0].strip()
    return raw


def main() -> int:
    try:
        from kiteconnect import KiteConnect
    except ImportError:
        print("[NEEDS_PACKAGE] Zerodha official SDK is not installed in this venv.")
        print(r"Run: .\venv\Scripts\python.exe -m pip install kiteconnect")
        return 3

    api_key = input("Kite API key: ").strip()
    secret1 = getpass.getpass("Kite API secret (hidden): ").strip()
    secret2 = getpass.getpass("Paste Kite API secret again to confirm (hidden): ").strip()
    if not api_key or not secret1:
        print("[FAIL] API key and secret are required.")
        return 2
    if secret1 != secret2:
        print("[FAIL] The two API secret entries do not match.")
        return 2

    print(f"[SAFE_DIAGNOSTIC] api_key_length={len(api_key)}")
    print(f"[SAFE_DIAGNOSTIC] api_secret_length={len(secret1)}")
    print(f"[SAFE_DIAGNOSTIC] api_secret_fingerprint={hashlib.sha256(secret1.encode()).hexdigest()[:12]}")
    print("The fingerprint is one-way diagnostic text; it is not the secret.")

    kite = KiteConnect(api_key=api_key)
    login_url = kite.login_url()
    print(f"\nLogin URL: {login_url}")
    try:
        webbrowser.open(login_url)
    except Exception:
        pass

    pasted = input("\nPaste the fresh redirected URL or request_token: ")
    request_token = extract_request_token(pasted)
    if len(request_token) < 10:
        print("[FAIL] No valid fresh request_token found.")
        return 2

    try:
        session = kite.generate_session(request_token, api_secret=secret1)
    except Exception as exc:
        print(f"[SDK_EXCHANGE_FAIL] {type(exc).__name__}: {exc}")
        print("[INTERPRETATION] Zerodha's official SDK also rejected the credential/token combination.")
        print("This rules out Trade Brain's custom checksum transport as the cause.")
        return 1

    access_token = str(session.get("access_token") or "").strip()
    if not access_token:
        print("[FAIL] Official SDK returned no access_token.")
        return 1
    kite.set_access_token(access_token)

    try:
        quote = kite.ltp(["NSE:BSE"])
    except Exception as exc:
        print(f"[SDK_LTP_FAIL] {type(exc).__name__}: {exc}")
        return 1

    if "NSE:BSE" not in quote:
        print("[FAIL] Official SDK session worked but NSE:BSE LTP was not returned.")
        return 1

    print("\n[PASS] Zerodha official SDK generated the session successfully.")
    print("[PASS] Read-only NSE:BSE LTP request succeeded.")
    print("[SAFE] Access token and API secret were not printed or saved by this diagnostic.")
    print("[NEXT] If this passes while the Trade Brain helper fails, fix the helper. If both fail, investigate the Kite app credential pair/account state.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
