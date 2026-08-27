"""Persistent research-trial ledger for Trade Brain v0.14 ML.

A rejected experiment must not disappear from the multiple-testing denominator just because a
new process starts tomorrow. The ledger deduplicates exact candidate configurations while also
tracking broader hypothesis families separately from parameter/threshold sweeps.

Kill budgets apply *within* a scientific hypothesis family. Exhausting one family must not
silently ban a genuinely different, predeclared research hypothesis.

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

METHOD_VERSION = "BSE_ML_RESEARCH_LEDGER_V2"


@dataclass(frozen=True)
class ResearchBudget:
    max_candidates_per_hypothesis_family: int = 50

    def validate(self) -> None:
        if self.max_candidates_per_hypothesis_family < 5:
            raise ValueError("max_candidates_per_hypothesis_family is too small")


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
                "selected_dsr_passed": None,
                "selected_dsr_probability": None,
            }
        existing["last_seen_at"] = now
        existing["seen_count"] = int(existing.get("seen_count") or 0) + 1
        existing["latest_status"] = str(trial.get("status") or "UNKNOWN")
        existing["latest_reason"] = str(trial.get("reason") or "")[:300]
        validation = trial.get("validation") or {}
        existing["latest_validation_trade_sharpe"] = validation.get("trade_sharpe")
        existing["latest_validation_profit_factor"] = validation.get("profit_factor")
        existing["latest_validation_mean_net_return_pct"] = validation.get("mean_net_return_pct")
        existing["latest_validation_trades"] = validation.get("trades")
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


def record_selected_dsr(
    *,
    task: str,
    winner: dict[str, Any],
    dsr_evidence: dict[str, Any],
    architecture: str | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Attach DSR evidence to the exact validation-selected ledger candidate."""
    ledger_path = default_ledger_path(path)
    ledger = _load(ledger_path)
    candidates = dict(ledger.get("candidates") or {})
    identity = candidate_identity(task=task, trial=winner, architecture=architecture)
    key = identity["candidate_fingerprint"]
    existing = candidates.get(key)
    if existing is None:
        # Fail closed: do not manufacture a trial record that was never in the search ledger.
        summary = research_ledger_summary(task=task, path=ledger_path)
        summary["selected_dsr_recorded"] = False
        summary["selected_dsr_reason"] = "WINNER_NOT_FOUND_IN_PERSISTENT_LEDGER"
        return summary
    row = dict(existing)
    row["selected_dsr_passed"] = bool(dsr_evidence.get("passed"))
    row["selected_dsr_probability"] = (dsr_evidence.get("deflated_sharpe_probability"))
    row["selected_dsr_verdict"] = dsr_evidence.get("verdict")
    row["selected_dsr_method_version"] = dsr_evidence.get("method_version")
    row["selected_dsr_recorded_at"] = datetime.now(timezone.utc).isoformat()
    candidates[key] = row
    ledger["candidates"] = candidates
    ledger["method_version"] = METHOD_VERSION
    ledger["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save(ledger_path, ledger)
    summary = research_ledger_summary(task=task, path=ledger_path)
    summary["selected_dsr_recorded"] = True
    summary["selected_dsr_candidate_fingerprint"] = key
    return summary


def _finite_number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in {float("inf"), float("-inf")}:
        return None
    return parsed


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

    sharpes: list[float] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        family_key = str(row.get("hypothesis_family_fingerprint") or "")
        if family_key:
            grouped.setdefault(family_key, []).append(row)
        value = _finite_number(row.get("latest_validation_trade_sharpe"))
        if value is not None:
            sharpes.append(value)

    family_summaries: list[dict[str, Any]] = []
    for family_key, family_rows in sorted(grouped.items()):
        sharpes_family = [
            value for value in (_finite_number(row.get("latest_validation_trade_sharpe")) for row in family_rows)
            if value is not None
        ]
        pfs = [
            value for value in (_finite_number(row.get("latest_validation_profit_factor")) for row in family_rows)
            if value is not None
        ]
        dsr_passes = [row for row in family_rows if row.get("selected_dsr_passed") is True]
        candidate_count = len(family_rows)
        exhausted = candidate_count >= budget.max_candidates_per_hypothesis_family and not dsr_passes
        family_summaries.append(
            {
                "hypothesis_family_fingerprint": family_key,
                "hypothesis_family": dict(family_rows[0].get("hypothesis_family") or {}),
                "distinct_candidate_configurations": candidate_count,
                "best_validation_trade_sharpe": max(sharpes_family) if sharpes_family else None,
                "best_validation_profit_factor": max(pfs) if pfs else None,
                "any_selected_candidate_passed_dsr": bool(dsr_passes),
                "budget_exhausted_without_dsr_pass": exhausted,
                "new_parameter_search_allowed": not exhausted,
            }
        )

    exhausted_families = [
        row for row in family_summaries if row["budget_exhausted_without_dsr_pass"]
    ]
    return {
        "method_version": METHOD_VERSION,
        "task": task,
        "distinct_candidate_configurations": len(rows),
        "distinct_hypothesis_families": len(grouped),
        "validation_trade_sharpes": sharpes,
        "research_budget": asdict(budget),
        "hypothesis_families": family_summaries,
        "exhausted_hypothesis_families": exhausted_families,
        "exhausted_hypothesis_family_count": len(exhausted_families),
        "research_budget_exhausted": bool(exhausted_families),
        "new_parameter_search_in_exhausted_family_allowed": False,
        "new_predeclared_hypothesis_family_allowed": True,
        "human_review_required_to_reopen_exhausted_family": bool(exhausted_families),
        "candidate_count_is_multiple_testing_denominator": True,
        "family_candidate_count_is_kill_budget_denominator": True,
        "automatic_promotion": False,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
