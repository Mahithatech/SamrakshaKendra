import os
import sys
import unittest
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.ingestion_pipeline import (  # noqa: E402
    content_fingerprint,
    cron_token_matches,
    eligible_records_for_screening,
    is_allowed_source_url,
    parse_candidate_lines,
    parse_count,
    parse_report_period,
    pipeline_interval_seconds,
    source_fingerprint,
    validate_candidate,
)


class IngestionPipelineHelpersTests(unittest.TestCase):
    def test_allowlists_only_https_official_hosts(self):
        self.assertTrue(is_allowed_source_url("https://ncdc.mohfw.gov.in/uploads/weekly_outbreaks/2026/week34.pdf", "NCDC"))
        self.assertTrue(is_allowed_source_url("https://www.who.int/emergencies/disease-outbreak-news", "WHO"))
        self.assertFalse(is_allowed_source_url("http://ncdc.mohfw.gov.in/report.pdf", "NCDC"))
        self.assertFalse(is_allowed_source_url("https://ncdc.mohfw.gov.in.attacker.example/report.pdf", "NCDC"))
        self.assertFalse(is_allowed_source_url("https://user@ncdc.mohfw.gov.in/report.pdf", "NCDC"))

    def test_report_period_from_official_ncdc_url(self):
        self.assertEqual(parse_report_period("https://ncdc.mohfw.gov.in/uploads/weekly_outbreaks/2026/week34_179.pdf"), (2026, 34))
        self.assertEqual(parse_report_period("https://ncdc.mohfw.gov.in/report.pdf", "NCDC Weekly Report 2025 Week 9"), (2025, 9))
        self.assertEqual(parse_report_period("https://ncdc.mohfw.gov.in/report.pdf", "unknown report"), (None, None))

    def test_counts_preserve_unknown_not_zero(self):
        self.assertIsNone(parse_count(""))
        self.assertIsNone(parse_count("NA"))
        self.assertIsNone(parse_count("—"))
        self.assertEqual(parse_count("1,203"), 1203)
        with self.assertRaises(ValueError):
            parse_count("-4")
        with self.assertRaises(ValueError):
            parse_count("12.5")

    def test_candidate_validation_requires_source_dates_and_values(self):
        candidate = {
            "source_url": "https://ncdc.mohfw.gov.in/report.pdf", "report_year": 2026, "report_week": 34,
            "state": "Karnataka", "district": "Mysuru", "disease": "Chickenpox", "cases": 51, "deaths": 0,
        }
        errors = validate_candidate(candidate)
        self.assertIn("reporting_dates_unverified", errors)
        candidate["reporting_start_date"] = date(2026, 8, 17)
        candidate["reporting_end_date"] = date(2026, 8, 23)
        self.assertEqual(validate_candidate(candidate), [])

    def test_candidate_rejects_unsafe_source_and_negative_counts(self):
        candidate = {
            "source_url": "https://evil.example/report.pdf", "report_year": 2026, "report_week": 34,
            "state": "Karnataka", "district": "Mysuru", "disease": "Chickenpox", "cases": -1, "deaths": -1,
            "reporting_start_date": "2026-08-17", "reporting_end_date": "2026-08-23",
        }
        errors = validate_candidate(candidate)
        self.assertIn("source_url_not_allowlisted_https_ncdc", errors)
        self.assertIn("cases_negative", errors)
        self.assertIn("deaths_negative", errors)

    def test_parser_creates_pending_review_candidate_not_live_data(self):
        text = "Karnataka    Mysuru    Chickenpox    51    0\nState    District    Disease    Cases    Deaths"
        rows = parse_candidate_lines(
            text,
            "https://ncdc.mohfw.gov.in/uploads/weekly_outbreaks/2026/week34_179.pdf",
            "NCDC Weekly Outbreak Report 2026 Week 34",
            "f" * 64,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["state"], rows[0]["district"], rows[0]["disease"]), ("Karnataka", "Mysuru", "Chickenpox"))
        self.assertEqual(rows[0]["cases"], 51)
        self.assertEqual(rows[0]["deaths"], 0)
        self.assertEqual(rows[0]["validation_status"], "needs_review")
        self.assertIn("reporting_dates_unverified", rows[0]["validation_errors"])

    def test_parser_refuses_nonofficial_urls(self):
        rows = parse_candidate_lines("Karnataka    Mysuru    Chickenpox    51    0", "https://attacker.example/x.pdf", "")
        self.assertEqual(rows, [])

    def test_fingerprints_are_deterministic(self):
        self.assertEqual(source_fingerprint("WHO", "https://www.who.int/a"), source_fingerprint("who", "https://www.who.int/a"))
        self.assertNotEqual(content_fingerprint(b"a"), content_fingerprint(b"b"))

    def test_screening_never_converts_missing_cases_to_zero(self):
        rows = [
            {"state": "Karnataka", "disease": "Chickenpox", "year": 2026, "week": 34, "cases": None},
            {"state": "Karnataka", "disease": "Chickenpox", "year": 2026, "week": 35, "cases": "51"},
            {"state": "Karnataka", "disease": "Chickenpox", "year": 2026, "week": 36, "cases": -2},
        ]
        eligible = eligible_records_for_screening(rows)
        self.assertEqual(len(eligible), 1)
        self.assertEqual(eligible[0]["cases"], 51)
        self.assertEqual(eligible[0]["week"], 35)

    def test_scheduler_token_is_required_and_compared_exactly(self):
        self.assertTrue(cron_token_matches("a-long-secret", "a-long-secret"))
        self.assertFalse(cron_token_matches("a-long-secret", "wrong-secret"))
        self.assertFalse(cron_token_matches("", "a-long-secret"))
        self.assertFalse(cron_token_matches("a-long-secret", ""))

    def test_interval_is_bounded(self):
        old = os.environ.get("SK_INGESTION_INTERVAL_SECONDS")
        try:
            os.environ["SK_INGESTION_INTERVAL_SECONDS"] = "10"
            self.assertEqual(pipeline_interval_seconds(), 300)
            os.environ["SK_INGESTION_INTERVAL_SECONDS"] = "900000"
            self.assertEqual(pipeline_interval_seconds(), 86400)
            os.environ["SK_INGESTION_INTERVAL_SECONDS"] = "garbage"
            self.assertGreaterEqual(pipeline_interval_seconds(), 300)
        finally:
            if old is None:
                os.environ.pop("SK_INGESTION_INTERVAL_SECONDS", None)
            else:
                os.environ["SK_INGESTION_INTERVAL_SECONDS"] = old


if __name__ == "__main__":
    unittest.main()
