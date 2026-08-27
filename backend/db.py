"""Relocatable SQLite database surface for Trade Brain.

The historical implementation is preserved in ``backend.db_impl``. This module owns
only runtime-path selection so Trade Brain can keep its local database beside the
project instead of hard-coding the Windows user profile.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from backend import db_impl as _impl


def resolve_db_path(data_root: str | os.PathLike[str] | None = None) -> str:
    """Return the active SQLite path.

    ``TRADEBRAIN_DATA_DIR`` is authoritative when configured. Without it, retain the
    historical ``~/.tradingagents/trading_agent.db`` fallback for compatibility.
    """
    if data_root is None:
        raw = (os.getenv("TRADEBRAIN_DATA_DIR") or "").strip()
    else:
        raw = str(data_root).strip()

    if raw:
        expanded = os.path.expandvars(os.path.expanduser(raw))
        return str(Path(expanded).resolve() / "trading_agent.db")
    return str(Path.home() / ".tradingagents" / "trading_agent.db")


def configure_db_path(data_root: str | os.PathLike[str] | None = None) -> str:
    """Apply one database path to both the compatibility surface and implementation."""
    path = resolve_db_path(data_root)
    _impl.DB_PATH = path
    globals()["DB_PATH"] = path
    return path


DB_PATH = configure_db_path()

# Preserve the existing public backend.db API. Function objects continue to execute
# against backend.db_impl, whose DB_PATH was set above before callers import them.
from backend.db_impl import *  # noqa: E402,F401,F403

# ``import *`` re-exports the implementation DB_PATH; keep both modules explicit and
# synchronized for callers that inspect the value directly.
DB_PATH = _impl.DB_PATH
