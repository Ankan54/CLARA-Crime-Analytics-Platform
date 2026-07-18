"""Unit tests for demo scenario logic — runs with mocked storage adapters."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestScenarioAllowlist(unittest.TestCase):
    def test_known_scenarios(self):
        from backend.app.demo_scenarios import SCENARIO_ALLOWLIST, is_allowed_scenario, get_crime_no

        self.assertEqual(len(SCENARIO_ALLOWLIST), 4)
        self.assertTrue(is_allowed_scenario("digital-arrest"))
        self.assertTrue(is_allowed_scenario("many-names"))
        self.assertTrue(is_allowed_scenario("follow-money"))
        self.assertTrue(is_allowed_scenario("surge"))
        self.assertFalse(is_allowed_scenario("unknown-scenario"))

    def test_crime_no_mapping(self):
        from backend.app.demo_scenarios import get_crime_no

        self.assertEqual(get_crime_no("digital-arrest"), "129011001202690001")
        self.assertEqual(get_crime_no("many-names"), "129011005202690002")
        self.assertEqual(get_crime_no("follow-money"), "129191018202690003")
        self.assertEqual(get_crime_no("surge"), "129011002202690004")
        self.assertIsNone(get_crime_no("nonexistent"))

    def test_unknown_scenario_cannot_trigger_cleanup(self):
        try:
            from backend.app.services.demo_scenario_reset import ResetError, prepare_scenario
        except ImportError:
            self.skipTest("sqlalchemy not available in this environment")

        mock_db = MagicMock()
        with self.assertRaises(ResetError) as ctx:
            prepare_scenario(mock_db, "not-a-real-scenario", "ikey-1")
        self.assertIn("Unknown scenario", str(ctx.exception))


class TestScenarioFileManifest(unittest.TestCase):
    def test_scenario_documents_match_asset_files(self):
        """Verify demo scenario assets exist under src/assets/live_demo."""
        assets_root = os.path.join(os.path.dirname(__file__), "..", "frontend", "src", "assets", "live_demo")
        if not os.path.isdir(assets_root):
            self.skipTest("frontend/src/assets/live_demo not found")

        expected = {
            "digital-arrest": [
                "live_scn1/fir.txt",
                "live_scn1/investigation_report.txt",
                "evidence/scenario_1/evidence/call_log.csv",
                "evidence/scenario_1/evidence/transaction_ledger.csv",
                "evidence/scenario_1/evidence/messaging_screenshot_1.html",
            ],
            "many-names": [
                "live_scn2/fir.txt",
                "live_scn2/investigation_report.txt",
                "evidence/scenario_2/evidence/bsa_63_certificate.txt",
                "evidence/scenario_2/evidence/device_forensics.txt",
                "evidence/scenario_2/evidence/messaging_screenshot_1.html",
            ],
            "follow-money": [
                "live_scn3/fir.txt",
                "live_scn3/investigation_report.txt",
                "evidence/scenario_3/evidence/account_details.txt",
                "evidence/scenario_3/evidence/bsa_63_certificate.txt",
                "evidence/scenario_3/evidence/transaction_ledger.csv",
            ],
            "surge": [
                "live_scn4/fir.txt",
                "live_scn4/investigation_report.txt",
                "evidence/scenario_4/evidence/bsa_63_certificate.txt",
                "evidence/scenario_4/evidence/device_pool.csv",
                "evidence/scenario_4/evidence/messaging_screenshot_1.html",
            ],
        }
        for scn_id, files in expected.items():
            for rel in files:
                path = os.path.join(assets_root, *rel.split("/"))
                self.assertTrue(os.path.isfile(path), f"Missing asset for {scn_id}: {path}")

    def test_scenario_masters_match_fir_expected(self):
        from backend.app.demo_scenarios import SCENARIO_ALLOWLIST

        expected_by_key = {
            "digital-arrest": (1001, 1011, "129011001202690001", "202690001", 5001, 7001),
            "many-names": (1005, 1012, "129011005202690002", "202690002", 5010, 7001),
            "follow-money": (1018, 1012, "129191018202690003", "202690003", 5007, 7007),
            "surge": (1002, 1013, "129011002202690004", "202690004", 5001, 7001),
        }
        for key, (station, minor, crime_no, case_no, emp, court) in expected_by_key.items():
            s = SCENARIO_ALLOWLIST[key]
            self.assertEqual(s.police_station_id, station)
            self.assertEqual(s.crime_minor_head_id, minor)
            self.assertEqual(s.crime_no, crime_no)
            self.assertEqual(s.case_no, case_no)
            self.assertEqual(s.police_person_id, emp)
            self.assertEqual(s.court_id, court)
            # CrimeNo embeds unit id at digits [5:9]
            self.assertEqual(s.crime_no[5:9], f"{station:04d}")


class TestUploadValidation(unittest.TestCase):
    def test_csv_in_default_allowed_exts(self):
        from backend.app.config import settings
        self.assertIn("csv", settings.default_allowed_exts)

    def test_max_files_increased(self):
        from backend.app.config import settings
        self.assertGreaterEqual(settings.max_files_per_upload, 15)


if __name__ == "__main__":
    unittest.main()
