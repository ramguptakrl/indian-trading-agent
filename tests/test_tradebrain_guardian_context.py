from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from backend.tradebrain.guardian_context import _correction_from_regime, _event_risk, _news_risk
from backend.tradebrain.position_guardian import assess_open_trade_risk

IST = ZoneInfo("Asia/Kolkata")


def _trade(mode="SWING"):
    return {
        "trade_id": "t1",
        "status": "OPEN",
        "open_quantity": 10,
        "mode": mode,
        "direction": "LONG",
        "avg_entry_price": 100.0,
        "entry_timestamp": datetime(2026, 8, 24, 10, 0, tzinfo=IST).astimezone(timezone.utc).isoformat(),
        "stop_loss": 95.0,
        "take_profit": 110.0,
    }


def test_official_recent_critical_event_raises_critical_risk():
    now = datetime(2026, 8, 25, 6, 0, tzinfo=timezone.utc)
    result = _event_risk(
        [{
            "event_id": "e1",
            "fetched_at": "2026-08-25T05:00:00+00:00",
            "category": "REGULATORY",
            "importance": "HIGH",
            "subject": "Trading halt announced after system outage",
            "details": "",
        }],
        now=now,
    )
    assert result["risk"] == "CRITICAL"


def test_ordinary_direct_news_is_elevated_not_forced_high():
    now = datetime(2026, 8, 25, 6, 0, tzinfo=timezone.utc)
    result = _news_risk(
        [{
            "article_id": "n1",
            "first_seen_at": "2026-08-25T05:00:00+00:00",
            "title": "BSE announces routine market update",
            "summary": "Routine update",
            "source": "example",
        }],
        now=now,
    )
    assert result["risk"] == "ELEVATED"


def test_high_vol_down_alignment_maps_to_guardian_correction_state():
    assert _correction_from_regime({"regime": "HIGH_VOL", "close": 90, "sma20": 95, "sma50": 100}) == "HIGH_VOL_TREND_DOWN"
    assert _correction_from_regime({"regime": "HIGH_VOL", "close": 105, "sma20": 100, "sma50": 95}) == "HIGH_VOL"


def test_split_ex_date_outranks_raw_stop_breach():
    result = assess_open_trade_risk(
        _trade(),
        current_price=20.0,
        evaluated_at=datetime(2026, 8, 25, 11, 0, tzinfo=IST),
        corporate_action_context={
            "stock_split_ex_date": True,
            "dividend_ex_date": False,
            "mechanical_gap_risk": True,
        },
    )
    assert result["state"] == "CORPORATE_ACTION_POSITION_RECONCILIATION_REQUIRED"
    assert result["priority"] == "CRITICAL"


def test_dividend_ex_date_gets_economic_review_before_stop_interpretation():
    result = assess_open_trade_risk(
        _trade(),
        current_price=94.0,
        evaluated_at=datetime(2026, 8, 25, 11, 0, tzinfo=IST),
        corporate_action_context={
            "stock_split_ex_date": False,
            "dividend_ex_date": True,
            "mechanical_gap_risk": True,
        },
    )
    assert result["state"] == "DIVIDEND_EX_DATE_ECONOMIC_REVIEW"
    assert result["priority"] == "HIGH"
