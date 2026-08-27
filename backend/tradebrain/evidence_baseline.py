"""Auditable descriptive evidence baseline for Trade Brain.

This is deliberately not a strategy optimizer. It summarizes only observed, completed
market bars from the audited Phase-3 store so later challenger hypotheses can be
predeclared from evidence instead of invented after seeing backtest results.

Core constraints:
- no BUY/SELL recommendation
- no win-rate claim
- no cross-price-era close-to-close return calculation
- only completed bars at/before the requested as_of cutoff
- intraday session summaries use completed regular-session coverage only
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import uuid
from collections import Counter, defaultdict
from datetime import datetime, time, timezone
from statistics import mean, median
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from backend.db import DB_PATH
from backend.tradebrain.market_data_store import (
    ensure_market_data_schema,
    get_series,
    list_issues,
    query_bars,
)
from backend.tradebrain.regime_hardening import classify_instrument_regime_recent

IST = ZoneInfo("Asia/Kolkata")
METHOD_VERSION = "BSE_DESCRIPTIVE_EVIDENCE_BASELINE_V1"
SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)


def _db_path(db_path: str | None) -> str:
    return db_path or DB_PATH


def ensure_evidence_schema(db_path: str | None = None) -> None:
    ensure_market_data_schema(db_path)
    path = _db_path(db_path)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tb_evidence_baselines (
                run_id TEXT PRIMARY KEY,
                series_id TEXT NOT NULL,
                as_of TEXT NOT NULL,
                method_version TEXT NOT NULL,
                report_sha256 TEXT NOT NULL,
                report_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(series_id, as_of, method_version, report_sha256),
                FOREIGN KEY(series_id) REFERENCES tb_market_series(series_id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tb_evidence_baselines_series ON tb_evidence_baselines(series_id, created_at DESC)"
        )
        conn.commit()
    finally:
        conn.close()


def _parse_dt(value: str | datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _pct(value: float) -> float:
    return round(value * 100.0, 6)


def _q(values: list[float], p: float) -> float | None:
    if not values:
        return None
    xs = sorted(float(v) for v in values)
    if len(xs) == 1:
        return round(xs[0], 6)
    pos = (len(xs) - 1) * p
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return round(xs[lo], 6)
    weight = pos - lo
    return round(xs[lo] * (1 - weight) + xs[hi] * weight, 6)


def _distribution(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": round(mean(values), 6),
        "median": round(median(values), 6),
        "p10": _q(values, 0.10),
        "p25": _q(values, 0.25),
        "p75": _q(values, 0.75),
        "p90": _q(values, 0.90),
        "min": round(min(values), 6),
        "max": round(max(values), 6),
    }


def _local_date(bar: dict[str, Any]) -> str:
    return datetime.fromisoformat(bar["ts_open"]).astimezone(IST).date().isoformat()


def _local_time(bar: dict[str, Any]) -> time:
    return datetime.fromisoformat(bar["ts_open"]).astimezone(IST).time().replace(tzinfo=None)


def _bucket_name(local_t: time) -> str:
    if local_t < time(10, 0):
        return "09:15-10:00"
    if local_t < time(12, 0):
        return "10:00-12:00"
    if local_t < time(14, 0):
        return "12:00-14:00"
    if local_t < time(15, 15):
        return "14:00-15:15"
    return "15:15-15:30"


def _same_price_era(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_era = left.get("era_id")
    right_era = right.get("era_id")
    if left_era is None and right_era is None:
        return True
    return bool(left_era and right_era and left_era == right_era)


def _daily_summary(bars: list[dict[str, Any]]) -> dict[str, Any]:
    close_to_close: list[float] = []
    gaps: list[float] = []
    intraday_returns: list[float] = []
    ranges: list[float] = []
    true_ranges: list[float] = []
    cross_era_excluded = 0

    for i, bar in enumerate(bars):
        o = float(bar["open"])
        h = float(bar["high"])
        l = float(bar["low"])
        c = float(bar["close"])
        if o > 0:
            intraday_returns.append(_pct(c / o - 1.0))
            ranges.append(_pct((h - l) / o))
        if i == 0:
            continue
        prev = bars[i - 1]
        prev_close = float(prev["close"])
        if not _same_price_era(prev, bar):
            cross_era_excluded += 1
            continue
        if prev_close > 0:
            close_to_close.append(_pct(c / prev_close - 1.0))
            gaps.append(_pct(o / prev_close - 1.0))
            tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
            true_ranges.append(_pct(tr / prev_close))

    up_intraday = sum(1 for x in intraday_returns if x > 0)
    down_intraday = sum(1 for x in intraday_returns if x < 0)
    gap_abs = [abs(x) for x in gaps]
    return {
        "bars": len(bars),
        "first_bar": bars[0]["ts_open"] if bars else None,
        "last_bar": bars[-1]["ts_close"] if bars else None,
        "close_to_close_return_pct": _distribution(close_to_close),
        "opening_gap_pct": _distribution(gaps),
        "absolute_opening_gap_pct": _distribution(gap_abs),
        "open_to_close_return_pct": _distribution(intraday_returns),
        "session_range_pct_of_open": _distribution(ranges),
        "true_range_pct_of_prev_close": _distribution(true_ranges),
        "positive_open_to_close_share_pct": round(up_intraday / len(intraday_returns) * 100, 3) if intraday_returns else None,
        "negative_open_to_close_share_pct": round(down_intraday / len(intraday_returns) * 100, 3) if intraday_returns else None,
        "cross_price_era_transitions_excluded": cross_era_excluded,
    }


def _intraday_summary(bars: list[dict[str, Any]], interval: str) -> dict[str, Any]:
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for bar in bars:
        by_day[_local_date(bar)].append(bar)
        by_bucket[_bucket_name(_local_time(bar))].append(bar)

    full_sessions: list[dict[str, Any]] = []
    incomplete_sessions: list[dict[str, Any]] = []
    for day, session_bars in sorted(by_day.items()):
        session_bars.sort(key=lambda b: b["ts_open"])
        first_open = _local_time(session_bars[0])
        last_close = datetime.fromisoformat(session_bars[-1]["ts_close"]).astimezone(IST).time().replace(tzinfo=None)
        item = {"date": day, "bars": len(session_bars), "first_open": first_open.isoformat(), "last_close": last_close.isoformat()}
        if first_open == SESSION_OPEN and last_close >= SESSION_CLOSE:
            full_sessions.append({**item, "bars_data": session_bars})
        else:
            incomplete_sessions.append(item)

    session_returns: list[float] = []
    session_ranges: list[float] = []
    mfe_from_open: list[float] = []
    mae_from_open: list[float] = []
    for session in full_sessions:
        xs = session["bars_data"]
        o = float(xs[0]["open"])
        c = float(xs[-1]["close"])
        h = max(float(b["high"]) for b in xs)
        l = min(float(b["low"]) for b in xs)
        if o > 0:
            session_returns.append(_pct(c / o - 1.0))
            session_ranges.append(_pct((h - l) / o))
            mfe_from_open.append(_pct(max(0.0, h / o - 1.0)))
            mae_from_open.append(_pct(max(0.0, 1.0 - l / o)))

    buckets: dict[str, Any] = {}
    for name in ("09:15-10:00", "10:00-12:00", "12:00-14:00", "14:00-15:15", "15:15-15:30"):
        xs = by_bucket.get(name, [])
        bar_returns: list[float] = []
        bar_ranges: list[float] = []
        volumes: list[float] = []
        for bar in xs:
            o = float(bar["open"])
            if o <= 0:
                continue
            bar_returns.append(abs(_pct(float(bar["close"]) / o - 1.0)))
            bar_ranges.append(_pct((float(bar["high"]) - float(bar["low"])) / o))
            volumes.append(float(bar.get("volume") or 0.0))
        buckets[name] = {
            "bars": len(xs),
            "absolute_bar_return_pct": _distribution(bar_returns),
            "bar_range_pct": _distribution(bar_ranges),
            "volume": _distribution(volumes),
        }

    return {
        "interval": interval,
        "bars": len(bars),
        "sessions_seen": len(by_day),
        "full_regular_sessions": len(full_sessions),
        "incomplete_or_special_sessions": len(incomplete_sessions),
        "incomplete_session_examples": incomplete_sessions[:10],
        "full_session_open_to_close_return_pct": _distribution(session_returns),
        "full_session_range_pct_of_open": _distribution(session_ranges),
        "full_session_long_mfe_from_open_pct": _distribution(mfe_from_open),
        "full_session_long_mae_from_open_pct": _distribution(mae_from_open),
        "time_of_day": buckets,
    }


def _quality_summary(issues: list[dict[str, Any]]) -> dict[str, Any]:
    by_type = Counter(str(item.get("issue_type") or "UNKNOWN") for item in issues)
    by_severity = Counter(str(item.get("severity") or "UNKNOWN") for item in issues)
    return {
        "unresolved_issues": len(issues),
        "by_type": dict(sorted(by_type.items())),
        "by_severity": dict(sorted(by_severity.items())),
    }


def _canonical_report_bytes(report: dict[str, Any]) -> bytes:
    return json.dumps(report, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


def persist_evidence_baseline(report: dict[str, Any], *, db_path: str | None = None) -> dict[str, str]:
    ensure_evidence_schema(db_path)
    payload = _canonical_report_bytes(report)
    digest = hashlib.sha256(payload).hexdigest()
    run_id = "evidence:" + digest
    path = _db_path(db_path)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO tb_evidence_baselines(
                run_id, series_id, as_of, method_version, report_sha256, report_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                report["series"]["series_id"],
                report["as_of"],
                report["method_version"],
                digest,
                payload.decode("utf-8"),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {"run_id": run_id, "report_sha256": digest}


def latest_evidence_baseline(series_id: str, *, db_path: str | None = None) -> dict[str, Any] | None:
    ensure_evidence_schema(db_path)
    conn = sqlite3.connect(_db_path(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM tb_evidence_baselines WHERE series_id=? ORDER BY created_at DESC LIMIT 1",
            (series_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    item = dict(row)
    item["report"] = json.loads(item.pop("report_json"))
    return item


def build_evidence_baseline(
    series_id: str,
    *,
    daily_interval: str = "1d",
    intraday_interval: str = "5m",
    as_of: str | datetime | None = None,
    persist: bool = True,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Build a descriptive, non-authorizing market evidence baseline."""
    series = get_series(series_id, db_path=db_path)
    if series is None:
        raise ValueError(f"Unknown market series: {series_id}")
    cutoff = _parse_dt(as_of)
    cutoff_iso = cutoff.isoformat()

    daily = query_bars(series_id, daily_interval, as_of=cutoff_iso, limit=500000, db_path=db_path)
    intraday = query_bars(series_id, intraday_interval, as_of=cutoff_iso, limit=500000, db_path=db_path)
    issues = list_issues(series_id, unresolved_only=True, db_path=db_path)

    unique_eras = sorted({str(b.get("era_id")) for b in daily if b.get("era_id")})
    regime = classify_instrument_regime_recent(series_id, as_of=cutoff_iso, db_path=db_path)
    intraday_summary = _intraday_summary(intraday, intraday_interval)

    report: dict[str, Any] = {
        "method_version": METHOD_VERSION,
        "as_of": cutoff_iso,
        "series": {
            "series_id": series_id,
            "exchange": series.get("exchange"),
            "symbol": series.get("symbol"),
            "isin": series.get("isin"),
            "source_key": series.get("source_key"),
            "source_symbol": series.get("source_symbol"),
            "price_mode": series.get("price_mode"),
            "source_official": bool((series.get("source_metadata") or {}).get("official")),
        },
        "coverage": {
            "daily_bars": len(daily),
            "daily_first": daily[0]["ts_open"] if daily else None,
            "daily_last": daily[-1]["ts_close"] if daily else None,
            "intraday_interval": intraday_interval,
            "intraday_bars": len(intraday),
            "intraday_first": intraday[0]["ts_open"] if intraday else None,
            "intraday_last": intraday[-1]["ts_close"] if intraday else None,
            "intraday_full_regular_sessions": intraday_summary["full_regular_sessions"],
        },
        "comparability": {
            "price_eras_present": len(unique_eras),
            "era_ids": unique_eras,
            "rule": "close-to-close and opening-gap calculations exclude transitions between different assigned raw-price eras",
        },
        "daily": _daily_summary(daily),
        "intraday": intraday_summary,
        "regime_at_cutoff": regime,
        "data_quality": _quality_summary(issues),
        "evidence_readiness": {
            "daily_descriptive_ready": len(daily) >= 250,
            "intraday_descriptive_ready": intraday_summary["full_regular_sessions"] >= 10,
            "walk_forward_intraday_candidate_ready": intraday_summary["full_regular_sessions"] >= 30,
            "note": "readiness indicates sample coverage only; it is not evidence of profitability",
        },
        "hypothesis_queue": [
            "Predeclare and test opening-gap continuation versus gap-fill behavior by gap-size bucket and regime.",
            "Predeclare and test first-hour range breakout versus fade behavior, stratified by regime and realized range quartile.",
            "Compare candidate entry windows by time-of-day after resident transaction costs; do not select the best window on the same sample used to discover it.",
            "Evaluate prior-session high/low and audited support/resistance reaction reliability with strict next-bar ordering.",
            "Compare INTRADAY and SWING candidate outcomes only through frozen chronological TRAIN/VALIDATION/WALK_FORWARD windows.",
        ],
        "claims": {
            "strategy_edge_claimed": False,
            "win_rate_claimed": False,
            "trade_authorization": False,
            "order_execution_allowed": False,
            "description": "Descriptive evidence only; no strategy is selected by this report.",
        },
    }
    if persist:
        report["persistence"] = persist_evidence_baseline(report, db_path=db_path)
    return report


def render_evidence_markdown(report: dict[str, Any]) -> str:
    d = report["daily"]
    i = report["intraday"]
    c = report["coverage"]
    q = report["data_quality"]
    r = report["regime_at_cutoff"]
    lines = [
        "# Trade Brain — BSE Descriptive Evidence Baseline",
        "",
        f"Method: `{report['method_version']}`  ",
        f"Cutoff: `{report['as_of']}`  ",
        f"Series: `{report['series']['exchange']}:{report['series']['symbol']}` / `{report['series']['source_symbol']}`  ",
        f"Source official: `{report['series']['source_official']}`  ",
        "",
        "## Coverage",
        f"- Daily bars: **{c['daily_bars']}** ({c['daily_first']} → {c['daily_last']})",
        f"- {c['intraday_interval']} bars: **{c['intraday_bars']}** ({c['intraday_first']} → {c['intraday_last']})",
        f"- Full regular intraday sessions: **{c['intraday_full_regular_sessions']}**",
        "",
        "## Daily behavior",
        f"- Median close-to-close return: **{d['close_to_close_return_pct'].get('median')}%**",
        f"- Median absolute opening gap: **{d['absolute_opening_gap_pct'].get('median')}%**",
        f"- 90th percentile absolute opening gap: **{d['absolute_opening_gap_pct'].get('p90')}%**",
        f"- Median session range: **{d['session_range_pct_of_open'].get('median')}% of open**",
        f"- Positive open-to-close sessions: **{d.get('positive_open_to_close_share_pct')}%**",
        f"- Cross-price-era transitions excluded: **{d['cross_price_era_transitions_excluded']}**",
        "",
        "## Intraday behavior",
        f"- Median full-session range: **{i['full_session_range_pct_of_open'].get('median')}% of open**",
        f"- Median long MFE from session open: **{i['full_session_long_mfe_from_open_pct'].get('median')}%**",
        f"- Median long MAE from session open: **{i['full_session_long_mae_from_open_pct'].get('median')}%**",
        "",
        "## Current historical-cutoff regime",
        f"- Regime: **{r.get('regime')}**",
        f"- Basis: `{r.get('basis')}`",
        f"- Reason: {r.get('reason')}",
        "",
        "## Data quality",
        f"- Unresolved issues: **{q['unresolved_issues']}**",
        f"- By type: `{json.dumps(q['by_type'], sort_keys=True)}`",
        "",
        "## Research contract",
        "This report is descriptive only. It makes **no profitability, win-rate, trade-authorization, or execution claim**.",
        "",
        "## Predeclared hypothesis queue",
    ]
    lines.extend(f"- {item}" for item in report["hypothesis_queue"])
    return "\n".join(lines) + "\n"
