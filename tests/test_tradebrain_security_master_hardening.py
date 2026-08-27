import os
import tempfile
import unittest

from backend.tradebrain.security_master import _archive_raw, _collect, parse_nse_equity_master
from backend.tradebrain.security_store import security_master_stats


class SecurityMasterHardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "hardening.db")
        self.old_data_dir = os.environ.get("TRADEBRAIN_DATA_DIR")
        os.environ["TRADEBRAIN_DATA_DIR"] = os.path.join(self.tmp.name, "tradebrain-data")

    def tearDown(self):
        if self.old_data_dir is None:
            os.environ.pop("TRADEBRAIN_DATA_DIR", None)
        else:
            os.environ["TRADEBRAIN_DATA_DIR"] = self.old_data_dir
        self.tmp.cleanup()

    def test_identical_raw_payload_is_archived_once(self):
        payload = b"SYMBOL,ISIN NUMBER\nABC,INE000A01001\n"
        path1, digest1 = _archive_raw("NSE", payload, "csv")
        path2, digest2 = _archive_raw("NSE", payload, "csv")

        self.assertEqual(path1, path2)
        self.assertEqual(digest1, digest2)
        directory = os.path.dirname(path1)
        self.assertEqual(len([name for name in os.listdir(directory) if name.endswith(".csv")]), 1)

    def test_nse_html_or_block_page_is_not_accepted_as_empty_success(self):
        with self.assertRaisesRegex(ValueError, "required SYMBOL/ISIN headers"):
            parse_nse_equity_master(b"<html><body>Access Denied</body></html>")

    def test_zero_valid_rows_archives_payload_but_does_not_touch_identity_store(self):
        def fetcher(timeout: int):
            return b"SYMBOL,ISIN NUMBER\nBAD,NA\n"

        with self.assertRaisesRegex(ValueError, "parsed zero valid rows"):
            _collect(
                exchange="NSE",
                source_key="NSE_EQUITY_SECURITY_MASTER",
                source_name="NSE test source",
                source_url="https://example.invalid/nse.csv",
                parser=parse_nse_equity_master,
                fetcher=fetcher,
                extension="csv",
                timeout=5,
                db_path=self.db_path,
            )

        stats = security_master_stats(self.db_path)
        self.assertEqual(stats["canonical_securities"], 0)
        self.assertEqual(stats["mapped_exchange_listings"], 0)
        self.assertEqual(stats["raw_security_master_artifacts"], 1)


if __name__ == "__main__":
    unittest.main()
