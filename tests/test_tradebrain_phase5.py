from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from backend.tradebrain.challenger import (
    create_challenger,
    evaluate_challenger,
    freeze_challenger,
    parameter_class,
    promote_challenger,
)
from backend.tradebrain.challenger_store import (
    get_experiment,
    list_decisions,
    list_soft_parameter_versions,
)
from backend.tradebrain.focus_lab_store import upsert_replay_outcome
from backend.tradebrain.identity import ExchangeListing
from backend.tradebrain.market_data_store import ensure_series, upsert_bars
from backend.tradebrain.policy import TradePlan, evaluate_trade_plan
from backend.tradebrain.regime_hardening import (
    REGIME_METHOD_VERSION,
    classify_instrument_regime_recent,
    install_phase4_regime_hardening,
)
from backend.tradebrain.store import record_plan_evaluation, upsert_listing


class Phase5Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "tradebrain.db")
        os.environ["TRADEBRAIN_DATA_DIR"] = os.path.join(self.tmp.name, "data")
        upsert_listing(
            ExchangeListing(exchange="NSE", symbol="BSE", isin="INE118H01025"),
            listing_name="BSE Limited", security_name="BSE Limited",
            listing_status="ACTIVE", source_key="TEST_MASTER",
            source_timestamp="2026-01-01T00:00:00+00:00", db_path=self.db,
        )
        self.series = ensure_series(
            exchange="NSE", symbol="BSE", source_key="TEST_VENDOR",
            source_symbol="BSE.NS", base_interval="5m", db_path=self.db,
        )

    def tearDown(self):
        os.environ.pop("TRADEBRAIN_DATA_DIR", None)
        self.tmp.cleanup()

    def record_outcome(
        self,
        *,
        when: datetime,
        rr: float,
        outcome: str,
        mode: str = "DAY",
        regime: str = "TREND_UP",
        exit_after_minutes: int = 30,
    ) -> str:
        plan = TradePlan(
            ticker="BSE", exchange="NSE", mode=mode, direction="LONG",
            entry=100.0, stop_loss=99.0, take_profit=100.0 + rr,
            crash_guard="NORMAL", broker_allows_trade=True,
            evidence=["PHASE5_TEST"], evaluated_at_ist=when,
        )
        gate = evaluate_trade_plan(plan)
        plan_id = record_plan_evaluation(plan, gate, db_path=self.db)
        evaluated = datetime.fromisoformat(gate.evaluated_at_ist).astimezone(timezone.utc)
        exit_at = evaluated + timedelta(minutes=exit_after_minutes)
        if outcome == "TP_FIRST":
            r_multiple = rr
            exit_price = 100.0 + rr
        elif outcome == "SL_FIRST":
            r_multiple = -1.0
            exit_price = 99.0
        elif outcome == "NEITHER":
            r_multiple = 0.1
            exit_price = 100.1
        else:
            r_multiple = None
            exit_price = None
        upsert_replay_outcome(
            {
                "plan_id": plan_id,
                "series_id": self.series["series_id"],
                "interval": "5m",
                "observation_kind": "HYPOTHETICAL_REPLAY",
                "outcome": outcome,
                "evaluated_at": evaluated.isoformat(),
                "observation_end": exit_at.isoformat(),
                "entry_bar_open": evaluated.isoformat(),
                "entry_fill_price": 100.0,
                "exit_bar_open": exit_at.isoformat() if outcome in {"TP_FIRST", "SL_FIRST", "AMBIGUOUS"} else None,
                "exit_timestamp": exit_at.isoformat() if outcome in {"TP_FIRST", "SL_FIRST", "AMBIGUOUS"} else exit_at.isoformat(),
                "exit_price": exit_price,
                "mae_pct": 0.5,
                "mfe_pct": rr if outcome == "TP_FIRST" else 0.5,
                "r_multiple": r_multiple,
                "time_to_event_minutes": float(exit_after_minutes),
                "bars_observed": 6,
                "sessions_observed": 1,
                "ambiguity_reason": "TEST" if outcome == "AMBIGUOUS" else None,
                "regime": regime,
                "regime_basis": "TEST_REGIME",
                "method_version": "STRICT_BAR_REPLAY_V1",
                "metadata": {},
                "computed_at": exit_at.isoformat(),
            },
            db_path=self.db,
        )
        return plan_id

    def windows(self):
        return [
            {"role": "TRAIN", "starts_at": "2026-01-01T00:00:00+00:00", "ends_at": "2026-01-11T00:00:00+00:00"},
            {"role": "VALIDATION", "starts_at": "2026-01-11T00:00:00+00:00", "ends_at": "2026-01-21T00:00:00+00:00"},
            {"role": "WALK_FORWARD", "starts_at": "2026-01-21T00:00:00+00:00", "ends_at": "2026-02-01T00:00:00+00:00"},
        ]

    def low_thresholds(self):
        return {
            "min_eligible": 2,
            "min_entered": 2,
            "min_resolved": 2,
            "max_ambiguity_pct": 50.0,
            "min_coverage_pct": 25.0,
            "min_mean_r_improvement": 0.10,
            "max_tp_rate_drop_pp": 5.0,
            "required_validation_win_fraction": 1.0,
            "required_walk_forward_win_fraction": 1.0,
            "max_single_window_mean_r_drop": 0.50,
            "min_regime_resolved": 2,
            "max_regime_mean_r_drop": 0.50,
        }

    def seed_window(self, start_day: int, *, challenger_wins: bool = True):
        base = datetime(2026, 1, start_day, 4, 0, tzinfo=timezone.utc)  # 09:30 IST
        # Low-RR arm-only observations and high-RR observations shared by both arms.
        for i in range(4):
            self.record_outcome(
                when=base + timedelta(days=i), rr=1.0,
                outcome="TP_FIRST" if not challenger_wins else "SL_FIRST",
            )
        for i in range(4):
            self.record_outcome(
                when=base + timedelta(days=i, hours=1), rr=2.0,
                outcome="TP_FIRST" if challenger_wins else "SL_FIRST",
            )

    def create_default_experiment(self, *, thresholds=None):
        return create_challenger(
            name="DAY R:R challenger",
            series_id=self.series["series_id"], interval="5m",
            parameter_key="day_min_reward_risk",
            incumbent_value=1.0, challenger_value=1.5,
            hypothesis="Higher minimum R:R should improve clean resolved R without collapsing coverage.",
            thresholds=thresholds or self.low_thresholds(),
            db_path=self.db,
        )


class ChallengerSafetyTests(Phase5Base):
    def test_protected_rule_cannot_enter_challenger_pipeline(self):
        self.assertEqual(parameter_class("day_hard_exit"), "PROTECTED_HARD_RULE")
        with self.assertRaises(ValueError):
            create_challenger(
                name="Unsafe clock challenger", series_id=self.series["series_id"], interval="5m",
                parameter_key="day_hard_exit", incumbent_value=1515, challenger_value=1520,
                hypothesis="Try changing a protected clock", db_path=self.db,
            )

    def test_unknown_parameter_is_not_fake_generic_optimization(self):
        self.assertEqual(parameter_class("magic_indicator_weight"), "UNSUPPORTED")
        with self.assertRaises(ValueError):
            create_challenger(
                name="Unknown", series_id=self.series["series_id"], interval="5m",
                parameter_key="magic_indicator_weight", incumbent_value=1, challenger_value=2,
                hypothesis="Unsupported parameters must not silently enter optimization", db_path=self.db,
            )

    def test_evaluation_requires_frozen_definition(self):
        experiment = self.create_default_experiment()
        with self.assertRaises(ValueError):
            evaluate_challenger(experiment["experiment_id"], db_path=self.db)

    def test_windows_must_be_non_overlapping_and_complete(self):
        experiment = self.create_default_experiment()
        with self.assertRaises(ValueError):
            freeze_challenger(
                experiment["experiment_id"],
                windows=[
                    {"role": "TRAIN", "starts_at": "2026-01-01T00:00:00+00:00", "ends_at": "2026-01-15T00:00:00+00:00"},
                    {"role": "VALIDATION", "starts_at": "2026-01-10T00:00:00+00:00", "ends_at": "2026-01-20T00:00:00+00:00"},
                    {"role": "WALK_FORWARD", "starts_at": "2026-01-20T00:00:00+00:00", "ends_at": "2026-02-01T00:00:00+00:00"},
                ],
                db_path=self.db,
            )

    def test_definition_becomes_immutable_after_freeze(self):
        experiment = self.create_default_experiment()
        frozen = freeze_challenger(experiment["experiment_id"], windows=self.windows(), db_path=self.db)
        self.assertTrue(frozen["definition_frozen"])
        self.assertEqual(len(frozen["experiment"]["definition_sha256"]), 64)
        with self.assertRaises(ValueError):
            freeze_challenger(experiment["experiment_id"], windows=self.windows(), db_path=self.db)


class ChallengerWalkForwardTests(Phase5Base):
    def test_training_loss_does_not_override_out_of_sample_wins(self):
        self.seed_window(2, challenger_wins=False)   # TRAIN: challenger deliberately worse
        self.seed_window(12, challenger_wins=True)  # VALIDATION
        self.seed_window(22, challenger_wins=True)  # WALK_FORWARD
        experiment = self.create_default_experiment()
        freeze_challenger(experiment["experiment_id"], windows=self.windows(), db_path=self.db)
        result = evaluate_challenger(experiment["experiment_id"], db_path=self.db)
        self.assertEqual(result["decision"], "READY_FOR_REVIEW")
        self.assertFalse(result["automatic_promotion"])
        self.assertEqual(list_soft_parameter_versions(active_only=True, db_path=self.db), [])
        train = [row for row in result["comparisons"] if row["role"] == "TRAIN"][0]
        self.assertFalse(train["win"])

    def test_low_sample_refuses_promotion_readiness(self):
        self.record_outcome(
            when=datetime(2026, 1, 12, 4, 0, tzinfo=timezone.utc), rr=2.0, outcome="TP_FIRST"
        )
        experiment = self.create_default_experiment(thresholds={
            **self.low_thresholds(), "min_eligible": 5, "min_entered": 5, "min_resolved": 5,
        })
        freeze_challenger(experiment["experiment_id"], windows=self.windows(), db_path=self.db)
        result = evaluate_challenger(experiment["experiment_id"], db_path=self.db)
        self.assertEqual(result["decision"], "NEEDS_MORE_DATA")

    def test_outcome_not_known_by_window_end_is_censored(self):
        self.seed_window(2, challenger_wins=True)
        self.seed_window(12, challenger_wins=True)
        self.seed_window(22, challenger_wins=True)
        # Evaluated inside validation but resolved after validation ended.
        self.record_outcome(
            when=datetime(2026, 1, 20, 4, 0, tzinfo=timezone.utc), rr=2.0,
            outcome="TP_FIRST", exit_after_minutes=24 * 60 * 3,
        )
        experiment = self.create_default_experiment()
        freeze_challenger(experiment["experiment_id"], windows=self.windows(), db_path=self.db)
        result = evaluate_challenger(experiment["experiment_id"], db_path=self.db)
        validation = [row for row in result["comparisons"] if row["role"] == "VALIDATION"][0]
        self.assertGreaterEqual(validation["censored_outcomes"], 1)

    def test_ready_experiment_requires_explicit_human_promotion(self):
        self.seed_window(2, challenger_wins=False)
        self.seed_window(12, challenger_wins=True)
        self.seed_window(22, challenger_wins=True)
        experiment = self.create_default_experiment()
        freeze_challenger(experiment["experiment_id"], windows=self.windows(), db_path=self.db)
        result = evaluate_challenger(experiment["experiment_id"], db_path=self.db)
        self.assertEqual(result["decision"], "READY_FOR_REVIEW")
        with self.assertRaises(ValueError):
            promote_challenger(
                experiment["experiment_id"], approved_by="x", approval_note="no",
                db_path=self.db,
            )
        promoted = promote_challenger(
            experiment["experiment_id"], approved_by="Test Reviewer",
            approval_note="Approve this soft research threshold after frozen validation.",
            db_path=self.db,
        )
        self.assertEqual(promoted["experiment"]["status"], "PROMOTED")
        self.assertFalse(promoted["runtime_policy_mutated"])
        active = list_soft_parameter_versions(active_only=True, db_path=self.db)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["value"], 1.5)
        decisions = [row["decision"] for row in list_decisions(experiment["experiment_id"], db_path=self.db)]
        self.assertEqual(decisions[-1], "PROMOTED")


class RegimeRecentWindowHardeningTests(Phase5Base):
    def test_long_history_uses_most_recent_260_completed_daily_bars(self):
        bars = []
        start = datetime(2024, 1, 1, 4, 0, tzinfo=timezone.utc)
        for i in range(300):
            opened = start + timedelta(days=i)
            close = 100.0 + i
            bars.append({
                "ts_open": opened.isoformat(),
                "ts_close": (opened + timedelta(hours=6)).isoformat(),
                "open": close - 0.5, "high": close + 1.0, "low": close - 1.0,
                "close": close, "volume": 1000 + i,
                "source_timestamp": opened.isoformat(), "is_final": True,
                "quality_flags": [],
            })
        upsert_bars(
            self.series["series_id"], "1d", bars, source_key="TEST_VENDOR", db_path=self.db
        )
        result = classify_instrument_regime_recent(
            self.series["series_id"], as_of=(start + timedelta(days=301)).isoformat(), db_path=self.db
        )
        self.assertEqual(result["basis"], REGIME_METHOD_VERSION)
        self.assertEqual(result["bars"], 260)
        self.assertEqual(result["close"], 399.0)
        self.assertEqual(result["window_selection"], "MOST_RECENT_COMPLETED_260_AT_OR_BEFORE_AS_OF")

    def test_runtime_installer_patches_phase4_core_classifier(self):
        import backend.tradebrain.focus_lab as focus_lab

        installed = install_phase4_regime_hardening()
        self.assertTrue(installed["installed"])
        self.assertIs(focus_lab.classify_instrument_regime, classify_instrument_regime_recent)


if __name__ == "__main__":
    unittest.main()
