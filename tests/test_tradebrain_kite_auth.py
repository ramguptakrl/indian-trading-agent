from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.tradebrain_kite_auth import read_env, update_env


class TradeBrainKiteAuthTests(unittest.TestCase):
    def test_new_env_writes_runtime_fields_but_not_api_secret(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / ".env"
            update_env(
                path,
                {
                    "KITE_API_KEY": "key123",
                    "KITE_ACCESS_TOKEN": "token123",
                    "KITE_LIVE_SUBSCRIPTIONS": "NSE:BSE",
                },
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn("KITE_API_KEY=key123", text)
            self.assertIn("KITE_ACCESS_TOKEN=token123", text)
            self.assertIn("KITE_LIVE_SUBSCRIPTIONS=NSE:BSE", text)
            self.assertNotIn("KITE_API_SECRET", text)

    def test_existing_unrelated_env_content_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / ".env"
            path.write_text("ANTHROPIC_API_KEY=keep-me\nOTHER_VALUE=yes\n", encoding="utf-8")
            update_env(
                path,
                {
                    "KITE_API_KEY": "new-key",
                    "KITE_ACCESS_TOKEN": "new-token",
                    "KITE_LIVE_SUBSCRIPTIONS": "NSE:BSE",
                },
            )
            values = read_env(path)
            self.assertEqual(values["ANTHROPIC_API_KEY"], "keep-me")
            self.assertEqual(values["OTHER_VALUE"], "yes")
            self.assertEqual(values["KITE_API_KEY"], "new-key")
            self.assertEqual(values["KITE_ACCESS_TOKEN"], "new-token")

    def test_existing_api_secret_is_preserved_but_not_created_or_echoed_elsewhere(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / ".env"
            path.write_text("KITE_API_SECRET=local-only-secret\nKITE_API_KEY=old\n", encoding="utf-8")
            update_env(
                path,
                {
                    "KITE_API_KEY": "new",
                    "KITE_ACCESS_TOKEN": "session",
                    "KITE_LIVE_SUBSCRIPTIONS": "NSE:BSE",
                },
            )
            values = read_env(path)
            self.assertEqual(values["KITE_API_SECRET"], "local-only-secret")
            self.assertEqual(values["KITE_API_KEY"], "new")
            self.assertEqual(values["KITE_ACCESS_TOKEN"], "session")


if __name__ == "__main__":
    unittest.main()
