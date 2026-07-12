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

        self.assertEqual(get_crime_no("digital-arrest"), "129011001202600001")
        self.assertEqual(get_crime_no("many-names"), "129011005202600001")
        self.assertEqual(get_crime_no("follow-money"), "129191018202600001")
        self.assertEqual(get_crime_no("surge"), "129011002202600001")
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
    def test_scenario_documents_match_public_files(self):
        """Verify each scenario's document manifest references files that exist in public/scenarios/."""
        public_dir = os.path.join(os.path.dirname(__file__), "..", "frontend", "public")
        if not os.path.isdir(public_dir):
            self.skipTest("frontend/public not found")

        expected_files = {
            "scn1": ["fir.txt", "investigation_report.txt", "evidence/call_log.csv",
                     "evidence/transaction_ledger.csv", "evidence/messaging_screenshot_1.html",
                     "evidence/README_EVIDENCE_GAP.txt"],
            "scn2": ["fir.txt", "investigation_report.txt", "evidence/bsa_63_certificate.txt",
                     "evidence/device_forensics.txt", "evidence/messaging_screenshot_1.html"],
            "scn3": ["fir.txt", "investigation_report.txt", "evidence/account_details.txt",
                     "evidence/bsa_63_certificate.txt", "evidence/transaction_ledger.csv"],
            "scn4": ["fir.txt", "investigation_report.txt", "evidence/bsa_63_certificate.txt",
                     "evidence/device_pool.csv", "evidence/messaging_screenshot_1.html"],
        }
        for scn_key, files in expected_files.items():
            for fname in files:
                path = os.path.join(public_dir, "scenarios", scn_key, fname)
                self.assertTrue(os.path.isfile(path), f"Missing: {path}")


class TestUploadValidation(unittest.TestCase):
    def test_csv_in_default_allowed_exts(self):
        from backend.app.config import settings
        self.assertIn("csv", settings.default_allowed_exts)

    def test_max_files_increased(self):
        from backend.app.config import settings
        self.assertGreaterEqual(settings.max_files_per_upload, 15)


if __name__ == "__main__":
    unittest.main()
