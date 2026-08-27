"""Research-only activity bars derived from audited one-minute BSE OHLCV.

These bars are deliberately weaker than true exchange event/tick bars because the historical
input is one-minute OHLCV. A source minute is therefore an indivisible atomic observation:
it is never split across synthetic bars and no intra-minute trade sequence is reconstructed.

Two deterministic constructions are supported:
- VOLUME: cumulative one-minute reported volume.
- RUPEE_CLOSE_NOTIONAL: cumulative ``close * volume``. This is a close-price notional proxy,
  not exact exchange turnover.

The builder resets at every India-local session date, preserves exact source-minute lineage,
and emits a trailing partial bar rather than silently dropping source minutes. Downstream
research should normally use rows where ``threshold_reached`` is true and retain partial rows
for provenance/audit only.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd

from backend.tradebrain.market_data_store import query_bars

IST = ZoneInfo("Asia/Kolkata")
METHOD_VERSION = "BSE_ML_ACTIVITY_BARS_V1"
SOURCE_INTERVAL = "1m"
ACTIVITY_VOLUME = "VOLUME"
ACTIVITY_RUPEE_CLOSE_NOTIONAL = "RUPEE_CLOSE_NOTIONAL"
ACTIVITY_KINDS = (ACTIVITY_VOLUME, ACTIVITY_RUPEE_CLOSE_NOTIONAL)
ARCHITECTURES = {
    ACTIVITY_VOLUME: "ACTIVITY_BAR_VOLUME_1M_V1",
    ACTIVITY_RUPEE_CLOSE_NOTIONAL: "ACTIVITY_BAR_RUPEE_CLOSE_NOTIONAL_1M_V1",
}
_REQUIRED_COLUMNS = ("ts_open", "ts_close", "open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class ActivityBarBundle:
    bars: pd.DataFrame
    lineage: pd.DataFrame
    metadata: dict[str, Any]


def _positive_target(value: float) -> float:
    target = float(value)
    if not math.isfinite(target) or target <= 0.0:
        raise ValueError("Activity-bar target must be a finite positive number")
    return target


def _normalize_kind(kind: str) -> str:
    normalized = str(kind or "").strip().upper()
    if normalized not in ACTIVITY_KINDS:
        raise ValueError(f"Unsupported activity-bar kind: {kind!r}; expected one of {ACTIVITY_KINDS}")
    return normalized


def _empty_bundle(kind: str, target: float, *, source_rows: int = 0) -> ActivityBarBundle:
    return ActivityBarBundle(
        bars=pd.DataFrame(
            columns=[
                "activity_bar_id", "architecture", "activity_kind", "activity_target",
                "observed_activity", "activity_overshoot", "threshold_reached", "partial_reason",
                "session_date_ist", "ts_open", "ts_close", "open", "high", "low", "close",
                "volume", "source_minute_count", "source_first_ts_open", "source_last_ts_open",
                "era_id", "quality_flags",
            ]
        ),
        lineage=pd.DataFrame(
            columns=[
                "activity_bar_id", "source_minute_ordinal", "bar_source_ordinal", "source_ts_open",
                "source_ts_close", "source_key", "source_timestamp", "source_era_id",
            ]
        ),
        metadata=_metadata(kind, target, source_rows=source_rows, emitted_bars=0, completed_bars=0),
    )


def _metadata(
    kind: str,
    target: float,
    *,
    source_rows: int,
    emitted_bars: int,
    completed_bars: int,
    source_snapshot_sha256: str | None = None,
) -> dict[str, Any]:
    return {
        "method_version": METHOD_VERSION,
        "architecture": ARCHITECTURES[kind],
        "hypothesis_family_namespace": "ACTIVITY_BAR",
        "activity_kind": kind,
        "activity_target": float(target),
        "source_interval": SOURCE_INTERVAL,
        "source_rows": int(source_rows),
        "emitted_bars": int(emitted_bars),
        "completed_bars": int(completed_bars),
        "partial_bars": int(emitted_bars - completed_bars),
        "source_snapshot_sha256": source_snapshot_sha256,
        "source_minute_is_atomic": True,
        "source_minute_splitting_allowed": False,
        "threshold_overshoot_carried_into_next_bar": False,
        "trailing_partial_bar_emitted": True,
        "session_accumulator_resets_by_ist_trade_date": True,
        "cross_session_aggregation_allowed": False,
        "rupee_activity_definition": "CLOSE_X_VOLUME_NOTIONAL_PROXY" if kind == ACTIVITY_RUPEE_CLOSE_NOTIONAL else None,
        "exact_exchange_turnover_claimed": False,
        "tick_sequence_reconstructed": False,
        "intra_minute_sequence_claimed": False,
        "bid_ask_history_claimed": False,
        "spread_history_claimed": False,
        "queue_history_claimed": False,
        "level2_history_claimed": False,
        "automatic_threshold_calibration": False,
        "holdout_used_for_threshold_selection": False,
        "research_only": True,
        "automatic_policy_change": False,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


def _source_snapshot(frame: pd.DataFrame) -> str:
    payload: list[dict[str, Any]] = []
    for row in frame.itertuples(index=False):
        payload.append(
            {
                "ts_open": pd.Timestamp(row.ts_open).isoformat(),
                "ts_close": pd.Timestamp(row.ts_close).isoformat(),
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": float(row.volume),
                "source_key": getattr(row, "source_key", None),
                "source_timestamp": getattr(row, "source_timestamp", None),
                "era_id": getattr(row, "era_id", None),
            }
        )
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _normalize_source_minutes(minutes: pd.DataFrame | Iterable[dict[str, Any]]) -> pd.DataFrame:
    frame = minutes.copy() if isinstance(minutes, pd.DataFrame) else pd.DataFrame(list(minutes))
    missing = [column for column in _REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Activity-bar source is missing required one-minute columns: {missing}")
    if frame.empty:
        return frame.copy()

    frame = frame.copy()
    frame["ts_open"] = pd.to_datetime(frame["ts_open"], utc=True, errors="raise")
    frame["ts_close"] = pd.to_datetime(frame["ts_close"], utc=True, errors="raise")
    frame = frame.sort_values("ts_open", kind="stable").reset_index(drop=True)

    if frame["ts_open"].duplicated().any():
        raise ValueError("Activity-bar source contains duplicate one-minute ts_open values")
    durations = frame["ts_close"] - frame["ts_open"]
    if not bool((durations == pd.Timedelta(minutes=1)).all()):
        raise ValueError("Activity-bar source must contain indivisible one-minute bars only")
    if "interval" in frame.columns and not bool((frame["interval"].astype(str) == SOURCE_INTERVAL).all()):
        raise ValueError("Activity-bar source interval must be exactly 1m")
    if "is_final" in frame.columns and not bool(frame["is_final"].astype(bool).all()):
        raise ValueError("Activity-bar source must contain completed/final one-minute bars only")
    if "is_derived" in frame.columns and bool(frame["is_derived"].astype(bool).any()):
        raise ValueError("Activity-bar source must be native audited 1m OHLCV, not previously derived bars")

    numeric = frame.loc[:, ["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        raise ValueError("Activity-bar source contains non-numeric or missing OHLCV values")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = numeric[column].astype(float)
    finite = frame.loc[:, ["open", "high", "low", "close", "volume"]].map(math.isfinite)
    if not bool(finite.all().all()):
        raise ValueError("Activity-bar source contains non-finite OHLCV values")
    if bool((frame[["open", "high", "low", "close"]] <= 0.0).any().any()):
        raise ValueError("Activity-bar source prices must be positive")
    if bool((frame["volume"] < 0.0).any()):
        raise ValueError("Activity-bar source volume cannot be negative")
    if bool((frame["high"] < frame[["open", "close", "low"]].max(axis=1)).any()):
        raise ValueError("Activity-bar source has inconsistent high values")
    if bool((frame["low"] > frame[["open", "close", "high"]].min(axis=1)).any()):
        raise ValueError("Activity-bar source has inconsistent low values")

    local_open = frame["ts_open"].dt.tz_convert(IST)
    local_close = frame["ts_close"].dt.tz_convert(IST)
    if not bool((local_open.dt.date == local_close.dt.date).all()):
        raise ValueError("A one-minute source bar cannot cross an IST session-date boundary")
    frame["session_date_ist"] = local_open.dt.date.astype(str)

    for _, group in frame.groupby("session_date_ist", sort=False):
        diffs = group["ts_open"].diff().dropna()
        if not diffs.empty and not bool((diffs == pd.Timedelta(minutes=1)).all()):
            raise ValueError("Activity-bar source contains an intra-session one-minute continuity gap")
    return frame


def _activity_value(row: pd.Series, kind: str) -> float:
    if kind == ACTIVITY_VOLUME:
        return float(row["volume"])
    return float(row["close"]) * float(row["volume"])


def _quality_flags(rows: list[pd.Series]) -> list[str]:
    flags: set[str] = set()
    for row in rows:
        value = row.get("quality_flags", [])
        if isinstance(value, str):
            flags.add(value)
        elif isinstance(value, (list, tuple, set)):
            flags.update(str(item) for item in value if str(item))
    return sorted(flags)


def _bar_id(kind: str, target: float, session_date: str, session_index: int, first: pd.Timestamp, last: pd.Timestamp) -> str:
    raw = (
        f"{METHOD_VERSION}|{kind}|{format(float(target), '.17g')}|{session_date}|{session_index}|"
        f"{first.isoformat()}|{last.isoformat()}"
    ).encode("utf-8")
    return "ABAR_" + hashlib.sha256(raw).hexdigest()[:20].upper()


def build_activity_bars(
    minutes: pd.DataFrame | Iterable[dict[str, Any]],
    *,
    kind: str,
    target: float,
) -> ActivityBarBundle:
    """Build deterministic activity bars from atomic one-minute OHLCV rows.

    ``target`` is caller supplied and is never calibrated from the input data. This is
    important because the already-consumed historical holdout must not influence architecture
    or threshold selection.
    """
    normalized_kind = _normalize_kind(kind)
    normalized_target = _positive_target(target)
    source = _normalize_source_minutes(minutes)
    if source.empty:
        return _empty_bundle(normalized_kind, normalized_target)

    source_snapshot = _source_snapshot(source)
    bars: list[dict[str, Any]] = []
    lineage: list[dict[str, Any]] = []
    global_source_ordinal = {pd.Timestamp(ts): idx for idx, ts in enumerate(source["ts_open"].tolist())}

    for session_date, session in source.groupby("session_date_ist", sort=False):
        session = session.reset_index(drop=True)
        pending: list[pd.Series] = []
        observed = 0.0
        session_bar_index = 0
        active_era: Any = None

        def emit(*, reached: bool, partial_reason: str | None) -> None:
            nonlocal pending, observed, session_bar_index, active_era
            if not pending:
                return
            first = pending[0]
            last = pending[-1]
            identifier = _bar_id(
                normalized_kind,
                normalized_target,
                str(session_date),
                session_bar_index,
                pd.Timestamp(first["ts_open"]),
                pd.Timestamp(last["ts_open"]),
            )
            era_values = {str(row.get("era_id")) for row in pending if row.get("era_id") is not None}
            bars.append(
                {
                    "activity_bar_id": identifier,
                    "architecture": ARCHITECTURES[normalized_kind],
                    "activity_kind": normalized_kind,
                    "activity_target": normalized_target,
                    "observed_activity": float(observed),
                    "activity_overshoot": float(max(0.0, observed - normalized_target)) if reached else 0.0,
                    "threshold_reached": bool(reached),
                    "partial_reason": partial_reason,
                    "session_date_ist": str(session_date),
                    "ts_open": pd.Timestamp(first["ts_open"]),
                    "ts_close": pd.Timestamp(last["ts_close"]),
                    "open": float(first["open"]),
                    "high": float(max(float(row["high"]) for row in pending)),
                    "low": float(min(float(row["low"]) for row in pending)),
                    "close": float(last["close"]),
                    "volume": float(sum(float(row["volume"]) for row in pending)),
                    "source_minute_count": int(len(pending)),
                    "source_first_ts_open": pd.Timestamp(first["ts_open"]),
                    "source_last_ts_open": pd.Timestamp(last["ts_open"]),
                    "era_id": next(iter(era_values)) if len(era_values) == 1 else None,
                    "quality_flags": _quality_flags(pending),
                }
            )
            for bar_source_ordinal, row in enumerate(pending):
                lineage.append(
                    {
                        "activity_bar_id": identifier,
                        "source_minute_ordinal": int(global_source_ordinal[pd.Timestamp(row["ts_open"])]),
                        "bar_source_ordinal": int(bar_source_ordinal),
                        "source_ts_open": pd.Timestamp(row["ts_open"]),
                        "source_ts_close": pd.Timestamp(row["ts_close"]),
                        "source_key": row.get("source_key"),
                        "source_timestamp": row.get("source_timestamp"),
                        "source_era_id": row.get("era_id"),
                    }
                )
            session_bar_index += 1
            pending = []
            observed = 0.0
            active_era = None

        for _, row in session.iterrows():
            row_era = row.get("era_id")
            if pending and row_era != active_era:
                emit(reached=False, partial_reason="ERA_BOUNDARY")
            if not pending:
                active_era = row_era
            pending.append(row)
            observed += _activity_value(row, normalized_kind)
            if observed >= normalized_target:
                emit(reached=True, partial_reason=None)
        emit(reached=False, partial_reason="SESSION_END")

    bars_frame = pd.DataFrame(bars)
    lineage_frame = pd.DataFrame(lineage)
    if len(lineage_frame) != len(source):
        raise RuntimeError("Activity-bar lineage invariant failed: not every source minute was assigned exactly once")
    if lineage_frame["source_ts_open"].duplicated().any():
        raise RuntimeError("Activity-bar lineage invariant failed: a source minute was assigned more than once")
    known_ids = set(bars_frame["activity_bar_id"].astype(str))
    if not set(lineage_frame["activity_bar_id"].astype(str)).issubset(known_ids):
        raise RuntimeError("Activity-bar lineage invariant failed: lineage references an unknown bar")

    completed = int(bars_frame["threshold_reached"].astype(bool).sum())
    metadata = _metadata(
        normalized_kind,
        normalized_target,
        source_rows=len(source),
        emitted_bars=len(bars_frame),
        completed_bars=completed,
        source_snapshot_sha256=source_snapshot,
    )
    return ActivityBarBundle(bars=bars_frame, lineage=lineage_frame, metadata=metadata)


def load_activity_bars(
    series_id: str,
    *,
    kind: str,
    target: float,
    start: str | None = None,
    end: str | None = None,
    as_of: str | None = None,
    limit: int = 500000,
    db_path: str | None = None,
) -> ActivityBarBundle:
    """Load completed audited 1m rows with replay cutoff and derive research-only bars."""
    rows = query_bars(
        series_id,
        SOURCE_INTERVAL,
        start=start,
        end=end,
        as_of=as_of,
        limit=limit,
        db_path=db_path,
    )
    bundle = build_activity_bars(rows, kind=kind, target=target)
    bundle.metadata.update(
        {
            "series_id": str(series_id),
            "query_start": start,
            "query_end": end,
            "query_as_of": as_of,
            "replay_cutoff_enforced_by_source_query": bool(as_of),
        }
    )
    return bundle


def completed_activity_bars(bundle: ActivityBarBundle) -> pd.DataFrame:
    """Return threshold-complete bars only; partial rows remain in the bundle for audit."""
    if bundle.bars.empty:
        return bundle.bars.copy()
    return bundle.bars.loc[bundle.bars["threshold_reached"].astype(bool)].copy().reset_index(drop=True)
