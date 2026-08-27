from __future__ import annotations

from pathlib import Path

import backend.db as db
import backend.db_impl as db_impl


def test_tradebrain_data_root_resolves_database_inside_configured_root(tmp_path):
    resolved = Path(db.resolve_db_path(tmp_path))
    assert resolved == tmp_path.resolve() / "trading_agent.db"


def test_configure_db_path_updates_public_and_implementation_modules(tmp_path):
    original_public = db.DB_PATH
    original_impl = db_impl.DB_PATH
    try:
        resolved = db.configure_db_path(tmp_path)
        expected = str(tmp_path.resolve() / "trading_agent.db")
        assert resolved == expected
        assert db.DB_PATH == expected
        assert db_impl.DB_PATH == expected
    finally:
        db.DB_PATH = original_public
        db_impl.DB_PATH = original_impl


def test_legacy_database_fallback_is_preserved_when_no_data_root_is_given(monkeypatch):
    monkeypatch.delenv("TRADEBRAIN_DATA_DIR", raising=False)
    expected = Path.home() / ".tradingagents" / "trading_agent.db"
    assert Path(db.resolve_db_path()) == expected


def test_after_market_script_loads_dotenv_before_tradebrain_import():
    source = (Path(__file__).resolve().parents[1] / "scripts" / "tradebrain_after_market_study.py").read_text(
        encoding="utf-8"
    )
    load_marker = 'load_dotenv(ROOT / ".env", override=True)'
    import_marker = "from backend.tradebrain.study_cycle_v2 import run_after_market_study_v2"
    assert source.index(load_marker) < source.index(import_marker)
