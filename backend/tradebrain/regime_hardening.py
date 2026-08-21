"""Phase 5 compatibility hardening for the Phase-4 audited instrument regime.

Phase 4 queried ascending daily bars with LIMIT 260, which can select the *oldest*
260 rows on a long history. This module deliberately queries the newest completed
260 daily rows at/before `as_of`, reverses them back to chronological order, and can
install the corrected classifier into the Phase-4 module at application startup.
"""

from __future__ import annotations

import math
import os
import sqlite3
from datetime import datetime, timezone
from statistics import median, pstdev
from typing import Any

from backend.db import DB_PATH
from backend.tradebrain.market_data_store import ensure_market_data_schema, get_series

REGIME_METHOD_VERSION = "AUDITED_INSTRUMENT_REGIME_V2_RECENT_WINDOW"


def _parse_dt(value: str | datetime) -> datetime:
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _recent_completed_daily_bars(
    series_id: str,
    *,
    as_of: str,
    limit: int = 260,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    ensure_market_data_schema(db_path)
    path = db_path or DB_PATH
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT * FROM tb_ohlcv_bars
            WHERE series_id=? AND interval='1d' AND is_final=1 AND ts_close<=?
            ORDER BY ts_open DESC
            LIMIT ?
            """,
            (series_id, _parse_dt(as_of).isoformat(), max(1, min(int(limit), 5000))),
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in reversed(rows)]


def classify_instrument_regime_recent(
    series_id: str,
    *,
    as_of: str,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Classify an instrument from the newest completed daily history at `as_of`."""
    if get_series(series_id, db_path=db_path) is None:
        raise ValueError(f"Unknown market series: {series_id}")
    bars = _recent_completed_daily_bars(series_id, as_of=as_of, limit=260, db_path=db_path)
    if len(bars) < 50:
        return {
            "regime": "UNKNOWN",
            "basis": REGIME_METHOD_VERSION,
            "bars": len(bars),
            "reason": "At least 50 completed daily bars are required",
            "as_of": _parse_dt(as_of).isoformat(),
        }

    closes = [float(bar["close"]) for bar in bars]
    close = closes[-1]
    sma20 = sum(closes[-20:]) / 20
    sma50 = sum(closes[-50:]) / 50

    def ann_vol(values: list[float]) -> float:
        if len(values) < 21:
            return 0.0
        rets = [(values[i] / values[i - 1]) - 1 for i in range(len(values) - 20, len(values))]
        return pstdev(rets) * math.sqrt(252) * 100 if len(rets) > 1 else 0.0

    current_vol = ann_vol(closes)
    baselines: list[float] = []
    start = max(50, len(closes) - 140)
    for end in range(start, len(closes) - 20, 5):
        value = ann_vol(closes[: end + 1])
        if value > 0:
            baselines.append(value)
    baseline = median(baselines) if baselines else current_vol

    if baseline > 0 and current_vol > baseline * 1.5:
        regime = "HIGH_VOL"
        reason = f"20-session realized vol {current_vol:.2f}% > 1.5x baseline {baseline:.2f}%"
    elif close > sma20 > sma50:
        regime = "TREND_UP"
        reason = "close > SMA20 > SMA50"
    elif close < sma20 < sma50:
        regime = "TREND_DOWN"
        reason = "close < SMA20 < SMA50"
    else:
        regime = "RANGE"
        reason = "close/SMA20/SMA50 are not directionally aligned"

    return {
        "regime": regime,
        "basis": REGIME_METHOD_VERSION,
        "bars": len(bars),
        "window_selection": "MOST_RECENT_COMPLETED_260_AT_OR_BEFORE_AS_OF",
        "close": round(close, 4),
        "sma20": round(sma20, 4),
        "sma50": round(sma50, 4),
        "annualized_vol_pct": round(current_vol, 4),
        "vol_baseline_pct": round(baseline, 4),
        "reason": reason,
        "as_of": _parse_dt(as_of).isoformat(),
    }


def install_phase4_regime_hardening() -> dict[str, Any]:
    """Install the V2 classifier into Phase-4 runtime call sites.

    This keeps the additive reframe small while fixing both internal outcome calls and
    the Phase-4 API endpoint. Direct callers should import the V2 classifier from this
    module for an explicit dependency.
    """
    from backend.tradebrain import focus_lab

    focus_lab.classify_instrument_regime = classify_instrument_regime_recent
    patched = ["backend.tradebrain.focus_lab.classify_instrument_regime"]
    try:
        from backend.routers import tradebrain_phase4

        tradebrain_phase4.classify_instrument_regime = classify_instrument_regime_recent
        patched.append("backend.routers.tradebrain_phase4.classify_instrument_regime")
    except Exception:
        # The router may not be imported in library/test contexts. The core Phase-4
        # module patch above is the important runtime safety fix.
        pass
    return {
        "installed": True,
        "basis": REGIME_METHOD_VERSION,
        "patched": patched,
    }
