"""Research kill criteria for Trade Brain v0.14 ML.

A disciplined research process must stop parameter-mining a hypothesis that has exhausted its
statistical budget. These rules distinguish killing one candidate or one hypothesis family
from banning an entire BSE trading task. A genuinely new, predeclared hypothesis may still be
researched and receives its own ledger family.

No rule in this module changes trading policy or places orders.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import inf, sqrt
from statistics import NormalDist
from typing import Any

METHOD_VERSION = "BSE_ML_KILL_CRITERIA_V1"
_NORMAL = NormalDist()


@dataclass(frozen=True)
class KillCriteriaConfig:
    confidence_probability: float = 0.95
    max_provability_years: float = 5.0
    min_baseline_profit_factor: float = 1.0

    def validate(self) -> None:
        if not 0.50 < self.confidence_probability < 1.0:
            raise ValueError("confidence_probability must be in (0.5,1)")
        if self.max_provability_years <= 0.0:
            raise ValueError("max_provability_years must be positive")
        if self.min_baseline_profit_factor < 1.0:
            raise ValueError("min_baseline_profit_factor must be >= 1")


DEFAULT_KILL_CRITERIA = KillCriteriaConfig()


def minimum_track_record_length(
    *,
    sharpe: float,
    skewness: float,
    kurtosis: float,
    benchmark_sharpe: float = 0.0,
    confidence_probability: float = 0.95,
) -> dict[str, Any]:
    """Invert the probabilistic-Sharpe statistic to estimate required trade observations."""
    sr = float(sharpe)
    benchmark = float(benchmark_sharpe)
    skew = float(skewness)
    kurt = max(float(kurtosis), 1.0)
    if not 0.50 < float(confidence_probability) < 1.0:
        raise ValueError("confidence_probability must be in (0.5,1)")
    denominator_term = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr
    edge = sr - benchmark
    if edge <= 0.0 or denominator_term <= 0.0:
        required = inf
    else:
        z = float(_NORMAL.inv_cdf(float(confidence_probability)))
        required = float(1.0 + (z * sqrt(denominator_term) / edge) ** 2)
    return {
        "method_version": METHOD_VERSION,
        "sharpe": sr,
        "benchmark_sharpe": benchmark,
        "skewness": skew,
        "kurtosis": kurt,
        "confidence_probability": float(confidence_probability),
        "minimum_required_trades": required,
        "finite": required != inf,
    }


def _family_for_winner(
    ledger_summary: dict[str, Any],
    winner: dict[str, Any] | None,
    *,
    architecture: str,
) -> dict[str, Any] | None:
    if not winner:
        return None
    target = {
        "architecture": str(architecture),
        "feature_set": str(winner.get("feature_set") or "UNKNOWN"),
        "family": str(winner.get("family") or "UNKNOWN"),
    }
    for family in ledger_summary.get("hypothesis_families") or []:
        payload = family.get("hypothesis_family") or {}
        if all(str(payload.get(key)) == value for key, value in target.items()):
            return family
    return None


def evaluate_research_kill_criteria(
    result: Any,
    ledger_summary: dict[str, Any],
    *,
    architecture: str = "BASELINE_OPTIMIZER",
    config: KillCriteriaConfig = DEFAULT_KILL_CRITERIA,
) -> dict[str, Any]:
    """Return candidate/family stop signals without declaring an entire task impossible."""
    config.validate()
    winner = getattr(result, "winner", None) or {}
    normal = getattr(result, "oos_metrics", None) or {}
    stress20 = getattr(result, "oos_stress_20x", None) or {}
    family = _family_for_winner(ledger_summary, winner, architecture=architecture)

    candidate_reasons: list[str] = []
    family_reasons: list[str] = []

    baseline_pf = float(normal.get("profit_factor") or 0.0) if normal else 0.0
    if normal and baseline_pf <= config.min_baseline_profit_factor:
        candidate_reasons.append("BASELINE_FRICTION_PROFIT_FACTOR_NOT_ABOVE_ONE")

    annual_trades = int(normal.get("trades") or 0) if normal else 0
    if stress20 and annual_trades > 0:
        min_trl = minimum_track_record_length(
            sharpe=float(stress20.get("trade_sharpe") or 0.0),
            skewness=float(stress20.get("return_skewness") or 0.0),
            kurtosis=float(stress20.get("return_kurtosis") or 3.0),
            benchmark_sharpe=0.0,
            confidence_probability=config.confidence_probability,
        )
        required_trades = float(min_trl["minimum_required_trades"])
        required_years = required_trades / annual_trades if required_trades != inf else inf
        if required_years > config.max_provability_years:
            candidate_reasons.append("MINIMUM_TRACK_RECORD_EXCEEDS_FIVE_YEARS")
    else:
        min_trl = None
        required_years = None

    if family:
        candidate_count = int(family.get("distinct_candidate_configurations") or 0)
        family_budget_exhausted = bool(family.get("budget_exhausted_without_dsr_pass"))
        best_pf = family.get("best_validation_profit_factor")
        if family_budget_exhausted:
            family_reasons.append("HYPOTHESIS_FAMILY_50_CANDIDATE_BUDGET_EXHAUSTED_WITHOUT_DSR_PASS")
        try:
            best_pf_value = float(best_pf)
        except (TypeError, ValueError):
            best_pf_value = None
        if family_budget_exhausted and best_pf_value is not None and best_pf_value <= config.min_baseline_profit_factor:
            family_reasons.append("NO_FAMILY_CANDIDATE_EXCEEDED_BASELINE_FRICTION_PF_ONE")
    else:
        candidate_count = 0
        family_budget_exhausted = False

    family_killed = bool(family_reasons)
    candidate_killed = bool(candidate_reasons) or family_killed
    if family_killed:
        verdict = "HALT_HYPOTHESIS_FAMILY"
    elif candidate_killed:
        verdict = "HALT_CURRENT_CANDIDATE"
    else:
        verdict = "CONTINUE_RESEARCH"

    return {
        "method_version": METHOD_VERSION,
        "verdict": verdict,
        "candidate_killed": candidate_killed,
        "hypothesis_family_killed": family_killed,
        "candidate_reasons": candidate_reasons,
        "hypothesis_family_reasons": family_reasons,
        "winner_hypothesis_family": family,
        "family_distinct_candidate_count": candidate_count,
        "family_budget_exhausted": family_budget_exhausted,
        "baseline_oos_profit_factor": baseline_pf if normal else None,
        "minimum_track_record": min_trl,
        "observed_oos_trades_per_year_proxy": annual_trades,
        "estimated_years_required_for_95pct_confidence": required_years,
        "config": asdict(config),
        "whole_task_declared_dead": False,
        "new_predeclared_hypothesis_family_allowed": True,
        "automatic_promotion": False,
        "automatic_execution": False,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
