# TradingAgents/graph/signal_processing.py

from typing import Any


class SignalProcessor:
    """Extract a non-authorizing research label from structured Trade Brain output.

    The original upstream processor used another LLM call to collapse the final report
    into BUY/SELL/HOLD. Trade Brain deliberately removes that authorization-like seam.
    Parsing is deterministic and fail-closed; actual plan validity belongs to the
    deterministic final advisory pipeline.
    """

    def __init__(self, quick_thinking_llm: Any):
        # Retained in the constructor for upstream compatibility. No LLM is used here.
        self.quick_thinking_llm = quick_thinking_llm

    def process_signal(self, full_signal: str) -> str:
        """Return LONG_CANDIDATE / SHORT_CANDIDATE / EXIT_CANDIDATE / WAIT / NO_TRADE."""
        try:
            from backend.tradebrain.advisory_pipeline import research_label

            return research_label(full_signal)
        except Exception:
            # A parser/import failure must never degrade into a bullish/bearish command.
            return "NO_TRADE"
