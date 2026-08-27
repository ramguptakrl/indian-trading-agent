"""Persistent research-trial ledger for Trade Brain v0.14 ML.

A rejected experiment must not disappear from the multiple-testing denominator just because a
new process starts tomorrow. The ledger deduplicates exact candidate configurations while also
tracking broader hypothesis families separately from parameter/threshold sweeps.

The ledger is research governance only. It cannot promote a model or place orders.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

METHOD_VERSION = "BSE_ML_RESEARCH_LEDGER_V1"


@dataclass(frozen=True)
class ResearchBudget:
    max_hypothesis_families: int = 50

    def validate(self) -> None:
        if self.max_hypothesis_families < 5:
            raise ValueError("max_hypothesis_families is too small")


DEFAULT_RESEARCH_BUDGET = ResearchBudget()


def default_ledger_path(path: str | Path | None = None) -> Path:
    if path is not None:
        target = Path(path).expanduser()
    else:
        configured = os.getenv("TRADEBRAIN_DATA_DIR")
        base = Path(configured).expanduser() if configured else Path.home() / ".tradingagents" / "tradebrain"
        target = base / "ml_research_ledger.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"method_version": METHOD_VERSION, "candidates": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"method_version": METHOD_VERSION, "candidates": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("candidates"), dict):
        return {"method_version": METHOD_VERSION, "candidates": {}}
    return payload


def _save(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    temp.replace(path)


def _digest(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _architecture(trial: dict[str, Any], architecture: str | None) -> str:
    return str(architecture or trial.get("variant") or trial.get("architecture") or "BASELINE")


def candidate_identity(
    *,
    task: str,
    trial: dict[str, Any],
    architecture: str | None = None,
) -> dict[str, Any]:
    arch = _architecture(trial, architecture)
    family_payload = {
        "task": str(task),
        "architecture": arch,
        "feature_set": str(trial.get("feature_set") or "UNKNOWN"),
        "family": str(trial.get("family") or "UNKNOWN"),
    }
    candidate_payload = {
        **family_payload,
        "params": dict(trial.get("params") or {}),
        "threshold": trial.get("threshold"),
        "feature_schema_hash": trial.get("feature_schema_hash"),
    }
    return {
        "candidate_fingerprint": _digest(candidate_payload),
        "hypothesis_family_fingerprint": _digest(family_payload),
        "candidate": candidate_payload,
        "hypothesis_family": family_payload,
    }


def record_trials(
    *,
    task: str,
    trials: Iterable[dict[str, Any]],
    dataset_snapshot_hash: str | None,
    code_version: str,
    architecture: str | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    ledger_path = default_ledger_path(path)
    ledger = _load(ledger_path)
    candidates = dict(ledger.get("candidates") or {})
    now = datetime.now(timezone.utc).isoformat()
    newly_recorded = 0

    for trial in trials:
        identity = candidate_identity(task=task, trial=trial, architecture=architecture)
        key = identity["candidate_fingerprint"]
        existing = dict(candidates.get(key) or {})
        if not existing:
            newly_recorded += 1
            existing = {
                **identity,
                "first_seen_at": now,
                "seen_count": 0,
            }
        existing["last_seen_at"] = now
        existing["seen_count"] = int(existing.get("seen_count") or 0) + 1
        existing["latest_status"] = str(trial.get("status") or "UNKNOWN")
        existing["latest_reason"] = str(trial.get("reason") or "")[:300]
        validation = trial.get("validation") or {}
        existing["latest_validation_trade_sharpe"] = validation.get("trade_sharpe")
        existing["latest_robustness_score"] = trial.get("robustness_score")
        existing["dataset_snapshot_hash"] = dataset_snapshot_hash
        existing["code_version"] = str(code_version)
        candidates[key] = existing

    ledger = {
        "method_version": METHOD_VERSION,
        "updated_at": now,
        "candidates": candidates,
        "automatic_promotion": False,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
    _save(ledger_path, ledger)
    summary = research_ledger_summary(task=task, path=ledger_path)
    summary["newly_recorded_candidates"] = newly_recorded
    summary["ledger_path"] = str(ledger_path)
    return summary


def research_ledger_summary(
    *,
    task: str | None = None,
    path: str | Path | None = None,
    budget: ResearchBudget = DEFAULT_RESEARCH_BUDGET,
) -> dict[str, Any]:
    budget.validate()
    ledger_path = default_ledger_path(path)
    ledger = _load(ledger_path)
    rows = list((ledger.get("candidates") or {}).values())
    if task is not None:
        rows = [row for row in rows if str((row.get("candidate") or {}).get("task")) == str(task)]
    families = {
        str(row.get("hypothesis_family_fingerprint"))
        for row in rows
        if row.get("hypothesis_family_fingerprint")
    }
    sharpes = []
    for row in rows:
        value = row.get("latest_validation_trade_sharpe")
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if value == value and value not in {float("inf"), float("-inf")}:
            sharpes.append(value)
    family_count = len(families)
    exhausted = family_count >= budget.max_hypothesis_families
    return {
        "method_version": METHOD_VERSION,
        "task": task,
        "distinct_candidate_configurations": len(rows),
        "distinct_hypothesis_families": family_count,
        "validation_trade_sharpes": sharpes,
        "research_budget": asdict(budget),
        "research_budget_exhausted": exhausted,
        "new_automatic_hypothesis_search_allowed": not exhausted,
        "human_review_required_to_expand_budget": exhausted,
        "candidate_count_is_multiple_testing_denominator": True,
        "hypothesis_family_count_is_kill_budget_denominator": True,
        "automatic_promotion": False,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
