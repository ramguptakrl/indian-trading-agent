"""Hard promotion-quality gates for Trade Brain v0.14 ML.

An optimizer result may be scientifically interesting without being safe enough to advance.
This module separates those concepts. It consumes only historical/OOS evidence already
produced before prospective shadow operation; it never trains, retunes, promotes, or places
orders.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


METHOD_VERSION = "BSE_ML_PROMOTION_V2"


@dataclass(frozen=True)
class PromotionThresholds:
    """Conservative minimums required before historical promotion is even possible."""

    max_oos_drawdown_pct: float = 25.0
    min_oos_2x_profit_factor: float = 1.30
    min_oos_trades: int = 100
    min_regime_expectancy_pct: float = 0.0
    min_walk_forward_blocks: int = 2
    min_walk_forward_block_trades: int = 20
    min_walk_forward_2x_profit_factor: float = 1.30
    min_shadow_sessions: int = 30

    def validate(self) -> None:
        if self.max_oos_drawdown_pct <= 0.0:
            raise ValueError("max_oos_drawdown_pct must be positive")
        if self.min_oos_2x_profit_factor <= 1.0:
            raise ValueError("min_oos_2x_profit_factor must be > 1")
        if self.min_oos_trades < 1:
            raise ValueError("min_oos_trades must be positive")
        if self.min_walk_forward_blocks < 1 or self.min_walk_forward_block_trades < 1:
            raise ValueError("walk-forward minimums must be positive")
        if self.min_walk_forward_2x_profit_factor <= 1.0:
            raise ValueError("min_walk_forward_2x_profit_factor must be > 1")
        if self.min_shadow_sessions < 1:
            raise ValueError("min_shadow_sessions must be positive")


DEFAULT_PROMOTION_THRESHOLDS = PromotionThresholds()


def _number(mapping: dict[str, Any] | None, key: str, default: float = 0.0) -> float:
    try:
        value = (mapping or {}).get(key)
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def evaluate_historical_promotion(
    result: Any,
    *,
    thresholds: PromotionThresholds = DEFAULT_PROMOTION_THRESHOLDS,
    multiple_testing_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a fail-closed verdict for historical promotion quality.

    The final configured holdout is intentionally absent from this function. A holdout that
    has already been inspected remains evidence, but can never be used to relax or tune these
    gates. Researcher-selection-bias evidence (DSR + PBO) is also mandatory.
    """

    thresholds.validate()
    failures: list[str] = []
    checks: dict[str, Any] = {}

    status = str(getattr(result, "status", ""))
    normal = getattr(result, "oos_metrics", None) or {}
    stress20 = getattr(result, "oos_stress_20x", None) or {}
    walk_forward = list(getattr(result, "walk_forward", None) or [])

    checks["optimizer_status"] = status
    if status != "OOS_PASS":
        failures.append("OPTIMIZER_DID_NOT_PASS_OOS")

    multiple_testing = dict(multiple_testing_evidence or {})
    checks["multiple_testing"] = multiple_testing or None
    if not multiple_testing:
        failures.append("MULTIPLE_TESTING_EVIDENCE_MISSING")
    elif not bool(multiple_testing.get("passed")):
        failures.append("MULTIPLE_TESTING_CLEARANCE_REJECTED")

    trades = int(_number(normal, "trades", 0.0))
    checks["oos_trades"] = trades
    if trades < thresholds.min_oos_trades:
        failures.append("OOS_SAMPLE_COUNT_BELOW_100")

    drawdown = _number(normal, "max_drawdown_pct", 999.0)
    checks["oos_max_drawdown_pct"] = drawdown
    if drawdown > thresholds.max_oos_drawdown_pct:
        failures.append("OOS_DRAWDOWN_ABOVE_25_PCT")

    stress20_expectancy = _number(stress20, "mean_net_return_pct", -999.0)
    stress20_pf = _number(stress20, "profit_factor", 0.0)
    checks["oos_2x_mean_net_return_pct"] = stress20_expectancy
    checks["oos_2x_profit_factor"] = stress20_pf
    if stress20_expectancy <= 0.0:
        failures.append("OOS_EXPECTANCY_NOT_POSITIVE_AT_2X_FRICTION")
    if stress20_pf < thresholds.min_oos_2x_profit_factor:
        failures.append("OOS_2X_PROFIT_FACTOR_BELOW_1_30")

    regimes = normal.get("regime_expectancy_pct") or {}
    checks["regime_expectancy_pct"] = {str(k): float(v) for k, v in regimes.items()}
    if not regimes:
        failures.append("REGIME_EVIDENCE_MISSING")
    else:
        bad_regimes = sorted(
            str(name)
            for name, value in regimes.items()
            if float(value) <= thresholds.min_regime_expectancy_pct
        )
        checks["non_positive_regimes"] = bad_regimes
        if bad_regimes:
            failures.append("NON_POSITIVE_EXPECTANCY_IN_OBSERVED_REGIME")

    qualifying_blocks: list[dict[str, Any]] = []
    weak_blocks: list[str] = []
    for row in walk_forward:
        normal_block = row.get("normal") or {}
        stress_block = row.get("stress_20x") or {}
        block_trades = int(_number(normal_block, "trades", 0.0))
        if block_trades < thresholds.min_walk_forward_block_trades:
            continue
        block = {
            "year": str(row.get("year") or "UNKNOWN"),
            "trades": block_trades,
            "mean_net_return_pct_2x": _number(stress_block, "mean_net_return_pct", -999.0),
            "profit_factor_2x": _number(stress_block, "profit_factor", 0.0),
        }
        qualifying_blocks.append(block)
        if (
            block["mean_net_return_pct_2x"] <= 0.0
            or block["profit_factor_2x"] < thresholds.min_walk_forward_2x_profit_factor
        ):
            weak_blocks.append(block["year"])

    checks["qualifying_walk_forward_blocks"] = qualifying_blocks
    checks["weak_walk_forward_blocks"] = weak_blocks
    if len(qualifying_blocks) < thresholds.min_walk_forward_blocks:
        failures.append("INSUFFICIENT_WALK_FORWARD_BLOCKS")
    elif weak_blocks:
        failures.append("WALK_FORWARD_BLOCK_FAILS_2X_FRICTION_GATE")

    passed = not failures
    return {
        "method_version": METHOD_VERSION,
        "passed": passed,
        "verdict": "PROMOTION_QUALITY_PASS" if passed else "PROMOTION_QUALITY_REJECTED",
        "failures": failures,
        "checks": checks,
        "thresholds": asdict(thresholds),
        "multiple_testing_required": True,
        "holdout_used_for_threshold_tuning": False,
        "automatic_promotion": False,
        "human_review_still_required": True,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
