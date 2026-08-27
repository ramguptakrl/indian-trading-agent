import unittest

from backend.tradebrain.corporate_events import parse_bse_announcements


class BseCorporateEventHardeningTests(unittest.TestCase):
    def test_bare_empty_object_is_not_a_verified_empty_feed(self):
        with self.assertRaises(ValueError):
            parse_bse_announcements(b"{}")

    def test_schema_confirmed_zero_row_feed_is_valid(self):
        events, rejected, total = parse_bse_announcements(
            b'{"Table": [], "Table1": [{"ROWCNT": 0}]}'
        )
        self.assertEqual(events, [])
        self.assertEqual(rejected, [])
        self.assertEqual(total, 0)


if __name__ == "__main__":
    unittest.main()
