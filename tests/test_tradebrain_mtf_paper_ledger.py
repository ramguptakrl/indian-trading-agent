import os
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.tradebrain.mtf_paper_ledger import (
    close_mtf_paper_position,
    get_mtf_paper_position,
    open_mtf_paper_position,
)
from backend.tradebrain.paper_ledger import create_paper_account, get_paper_account

IST = ZoneInfo("Asia/Kolkata")


def _setup():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    account = create_paper_account(name="mtf", starting_cash=200000, db_path=path)
    return path, account


def test_mtf_open_reserves_only_user_side_plus_cost_cushion():
    path, account = _setup()
    try:
        position = open_mtf_paper_position(
            account_id=account["account_id"],
            ticker="BSE",
            exchange="NSE",
            quantity=100,
            entry_price=1000,
            funded_amount=80000,
            mtf_eligible_verified=True,
            entry_timestamp=datetime(2026, 8, 21, 10, 0, tzinfo=IST),
            db_path=path,
        )
        assert position["position_value"] == 100000
        assert position["funded_amount"] == 80000
        assert position["own_cash_contribution"] == 20000
        assert position["reserved_cash"] > 20000
        assert position["reserved_cash"] < 100000
        updated = get_paper_account(account["account_id"], db_path=path)
        assert updated["mtf_enabled"] is True
        assert updated["cash_balance"] == 200000 - position["reserved_cash"]
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_mtf_open_requires_verified_eligibility():
    path, account = _setup()
    try:
        try:
            open_mtf_paper_position(
                account_id=account["account_id"], ticker="BSE", exchange="NSE",
                quantity=10, entry_price=1000, funded_amount=8000,
                mtf_eligible_verified=False,
                entry_timestamp=datetime(2026, 8, 21, 10, 0, tzinfo=IST), db_path=path,
            )
            raise AssertionError("expected eligibility failure")
        except ValueError as exc:
            assert "eligibility" in str(exc).lower()
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_mtf_close_requires_positive_interest_days_and_realizes_net_once():
    path, account = _setup()
    try:
        position = open_mtf_paper_position(
            account_id=account["account_id"], ticker="BSE", exchange="NSE",
            quantity=100, entry_price=1000, funded_amount=80000,
            mtf_eligible_verified=True,
            entry_timestamp=datetime(2026, 8, 21, 10, 0, tzinfo=IST), db_path=path,
        )
        try:
            close_mtf_paper_position(
                position["position_id"], exit_price=1020, interest_days=0,
                exit_timestamp=datetime(2026, 8, 24, 11, 0, tzinfo=IST), db_path=path,
            )
            raise AssertionError("expected interest-days failure")
        except ValueError as exc:
            assert "interest-days" in str(exc).lower()

        closed = close_mtf_paper_position(
            position["position_id"], exit_price=1020, interest_days=3,
            exit_timestamp=datetime(2026, 8, 24, 11, 0, tzinfo=IST), db_path=path,
        )
        assert closed["status"] == "CLOSED"
        assert closed["interest_days"] == 3
        assert closed["mtf_interest"] > 0
        assert closed["economics"]["funding_interest"] == closed["mtf_interest"]
        final_account = get_paper_account(account["account_id"], db_path=path)
        assert round(final_account["cash_balance"], 2) == round(200000 + closed["net_pnl"], 2)
        assert round(final_account["realized_net_pnl"], 2) == round(closed["net_pnl"], 2)
        assert get_mtf_paper_position(position["position_id"], db_path=path)["status"] == "CLOSED"
    finally:
        if os.path.exists(path):
            os.unlink(path)
