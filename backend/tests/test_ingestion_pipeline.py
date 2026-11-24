
import os
import sys
import unittest
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.ingestion_pipeline import (
    content_fingerprint,
    cron_token_matches,
    eligible_records_for_screening,
    is_allowed_source_url,
    parse_candidate_pdf,
    parse_count,
    parse_report_period,
    pipeline_interval_seconds,
    source_fingerprint,
    validate_candidate,
)

OFFICIAL_NCDC_URL = (
    "https://ncdc.mohfw.gov.in/uploads/"
    "weekly_outbreaks/2026/week34_179.pdf"
)


class IngestionPipelineHelpersTests(unittest.TestCase):

    def test_allowlists_only_https_official_hosts(self):
        self.assertTrue(
            is_allowed_source_url(
                "https://ncdc.mohfw.gov.in/uploads/weekly_outbreaks/2026/week34.pdf",
                "NCDC",
            )
        )
        self.assertTrue(
            is_allowed_source_url(
                "https://www.who.int/emergencies/disease-outbreak-news",
                "WHO",
            )
        )
        self.assertFalse(
            is_allowed_source_url("http://ncdc.mohfw.gov.in/report.pdf", "NCDC")
        )
        self.assertFalse(
            is_allowed_source_url(
                "https://ncdc.mohfw.gov.in.attacker.example/report.pdf",
                "NCDC",
            )
        )
        self.assertFalse(
            is_allowed_source_url(
                "https://user@ncdc.mohfw.gov.in/report.pdf",
                "NCDC",
            )
        )

    def test_report_period_from_official_ncdc_url(self):
        self.assertEqual(parse_report_period(OFFICIAL_NCDC_URL), (2026, 34))
        self.assertEqual(
            parse_report_period(
                "https://ncdc.mohfw.gov.in/report.pdf",
                "NCDC Weekly Report 2025 Week 9",
            ),
            (2025, 9),
        )
        self.assertEqual(
            parse_report_period(
                "https://ncdc.mohfw.gov.in/report.pdf",
                "unknown report",
            ),
            (None, None),
        )

    def test_counts_preserve_unknown_not_zero(self):
        self.assertIsNone(parse_count(""))
        self.assertIsNone(parse_count("NA"))
        self.assertIsNone(parse_count("-"))
        self.assertEqual(parse_count("1,203"), 1203)

        with self.assertRaises(ValueError):
            parse_count("-4")

        with self.assertRaises(ValueError):
            parse_count("12.5")

    def test_candidate_validation_requires_source_dates_and_values(self):
        candidate = {
            "source_url": "https://ncdc.mohfw.gov.in/report.pdf",
            "report_year": 2026,
            "report_week": 34,
            "state": "Karnataka",
            "district": "Mysuru",
            "disease": "Chickenpox",
            "cases": 51,
            "deaths": 0,
            "source_page": 1,
        }

        errors = validate_candidate(candidate)
        self.assertIn("reporting_dates_unverified", errors)

        candidate["reporting_start_date"] = date(2026, 8, 17)
        candidate["reporting_end_date"] = date(2026, 8, 23)

        self.assertEqual(validate_candidate(candidate), [])

    def test_candidate_rejects_unsafe_source_and_negative_counts(self):
        candidate = {
            "source_url": "https://evil.example/report.pdf",
            "report_year": 2026,
            "report_week": 34,
            "state": "Karnataka",
            "district": "Mysuru",
            "disease": "Chickenpox",
            "cases": -1,
            "deaths": -1,
            "reporting_start_date": "2026-08-17",
            "reporting_end_date": "2026-08-23",
            "source_page": 1,
        }

        errors = validate_candidate(candidate)

        self.assertIn("source_url_not_allowlisted_https_ncdc", errors)
        self.assertIn("cases_negative", errors)
        self.assertIn("deaths_negative", errors)

    def test_parser_refuses_nonofficial_urls(self):
        rows = parse_candidate_pdf(
            b"not a PDF",
            "https://attacker.example/x.pdf",
            "Untrusted report",
        )
        self.assertEqual(rows, [])

    def test_parser_rejects_non_pdf_content(self):
        with self.assertRaises(ValueError):
            parse_candidate_pdf(
                b"This is not a PDF file",
                OFFICIAL_NCDC_URL,
                "NCDC Weekly Outbreak Report 2026 Week 34",
                "f" * 64,
            )

    def test_fingerprints_are_deterministic(self):
        self.assertEqual(
            source_fingerprint("WHO", "https://www.who.int/a"),
            source_fingerprint("who", "https://www.who.int/a"),
        )
        self.assertNotEqual(
            content_fingerprint(b"a"),
            content_fingerprint(b"b"),
        )

    def test_screening_never_converts_missing_cases_to_zero(self):
        rows = [
            {
                "state": "Karnataka",
                "disease": "Chickenpox",
                "year": 2026,
                "week": 34,
                "cases": None,
            },
            {
                "state": "Karnataka",
                "disease": "Chickenpox",
                "year": 2026,
                "week": 35,
                "cases": "51",
            },
            {
                "state": "Karnataka",
                "disease": "Chickenpox",
                "year": 2026,
                "week": 36,
                "cases": -2,
            },
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


class NCDCWeek30PDFRegressionTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.pdf_path = BACKEND / "test_data" / "week30_2024.pdf"
        if not cls.pdf_path.is_file():
            raise FileNotFoundError(f"PDF fixture missing: {cls.pdf_path}")

        cls.pdf_bytes = cls.pdf_path.read_bytes()
        cls.source_url = (
            "https://ncdc.mohfw.gov.in/uploads/"
            "weekly_outbreaks/2024/week30_1788951797.pdf"
        )
        cls.candidates = parse_candidate_pdf(
            cls.pdf_bytes,
            cls.source_url,
            "NCDC Weekly Outbreak Report 2024 Week 30",
            content_fingerprint(cls.pdf_bytes),
        )
        cls.by_record_id = {
            row["source_record_id"]: row for row in cls.candidates
        }

    def test_all_134_official_record_ids_are_extracted_once(self):
        self.assertEqual(len(self.candidates), 134)
        self.assertEqual(len(self.by_record_id), 134)
        self.assertEqual(
            len({row["candidate_id"] for row in self.candidates}), 134
        )

    def test_all_candidates_have_required_fields_and_traceability(self):
        for row in self.candidates:
            with self.subTest(record=row.get("source_record_id")):
                self.assertTrue(row["source_record_id"])
                self.assertIsInstance(row["source_page"], int)
                self.assertGreater(row["source_page"], 0)
                self.assertTrue(row["state"])
                self.assertTrue(row["district"])
                self.assertTrue(row["disease"])
                self.assertIsNotNone(row["cases"])
                self.assertIsNotNone(row["deaths"])

    def test_missing_dates_remain_flagged_for_review(self):
        expected = {
            "AP/NTR/2024/30/1769",
            "CT/SRJ/2024/30/1770",
            "KL/CNR/2024/30/1771",
            "MP/SAT/2024/30/1772",
        }

        for record_id in expected:
            row = self.by_record_id[record_id]
            self.assertIn("reporting_dates_unverified", row["validation_errors"])
            self.assertTrue(
                row["reporting_start_date"] is None
                or row["reporting_end_date"] is None
            )

    def test_long_reporting_periods_remain_flagged(self):
        expected = {
            "HP/SIM/2024/30/1671",
            "MH/NSK/2024/30/1730",
        }

        for record_id in expected:
            row = self.by_record_id[record_id]
            self.assertIn(
                "reporting_period_exceeds_15_days",
                row["validation_errors"],
            )

    def test_extracted_table_rows_remain_quarantined(self):
        for row in self.candidates:
            self.assertIn(
                "table_cell_extraction_requires_supervisor_review",
                row["validation_errors"],
            )
            self.assertEqual(
                row["validation_status"], "needs_review"
            )


if __name__ == "__main__":
    unittest.main()
