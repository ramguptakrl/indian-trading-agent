"""Windows Unicode regression tests for Trade Brain runtime launch paths."""

from __future__ import annotations

import unittest
from pathlib import Path

import sitecustomize


class _ReconfigurableStream:
    def __init__(self):
        self.calls = []

    def reconfigure(self, **kwargs):
        self.calls.append(kwargs)


class TradeBrainWindowsUtf8Tests(unittest.TestCase):
    def test_runtime_stream_guard_requests_utf8(self):
        stream = _ReconfigurableStream()
        sitecustomize._configure_stream(stream)
        self.assertEqual(stream.calls[-1]["encoding"], "utf-8")
        self.assertEqual(stream.calls[-1]["errors"], "backslashreplace")

    def test_non_breaking_hyphen_is_utf8_encodable(self):
        text = "SWING ‑ Zerodha MTF"
        encoded = text.encode("utf-8")
        self.assertIn(b"\xe2\x80\x91", encoded)

    def test_windows_launchers_force_python_utf8(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("Start-TradeBrain.bat", "Study-TradeBrain.bat"):
            source = (root / name).read_text(encoding="utf-8")
            self.assertIn("PYTHONUTF8=1", source)
            self.assertIn("PYTHONIOENCODING=utf-8", source)


if __name__ == "__main__":
    unittest.main()
