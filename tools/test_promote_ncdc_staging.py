import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("promote_ncdc_staging.py")
spec = importlib.util.spec_from_file_location("promote_ncdc_staging", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)

class PromotionHelperTests(unittest.TestCase):
    def test_empty_template_rows_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "manifest.csv"
            p.write_text("record_id,approved_by,approved_at_utc,source_pdf_checked,approval_note\nID-1,,,,\n", encoding="utf-8")
            self.assertEqual(mod.read_approval_manifest(p), [])

    def test_approval_requires_pdf_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "manifest.csv"
            p.write_text("record_id,approved_by,approved_at_utc,source_pdf_checked,approval_note\nID-1,reviewer,2026-10-16T10:00:00+05:30,false,Checked all fields\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must be true"):
                mod.read_approval_manifest(p)

    def test_approval_requires_timezone(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "manifest.csv"
            p.write_text("record_id,approved_by,approved_at_utc,source_pdf_checked,approval_note\nID-1,reviewer,2026-10-16T10:00:00,true,Checked all fields\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "include a timezone"):
                mod.read_approval_manifest(p)

    def test_week_one_reporting_dates(self):
        row = {
            "record_id": "AP/SRI/2026/01/01", "report_year": 2026, "report_week": 1,
            "state": "Andhra Pradesh", "district": "Sri Sathya Sai", "disease": "Suspected Food Poisoning",
            "cases": 15, "deaths": 0, "current_status": "Under Surveillance",
            "source_url": "https://ncdc.mohfw.gov.in/uploads/weekly_outbreaks/2026/week1_1788853592.pdf",
            "source_validation_status": "source_reviewed_core_fields", "review_status": "pending_supervisor_review"
        }
        result = mod.prepare_live_record(row)
        self.assertEqual(str(result["reporting_start_date"]), "2025-12-29")
        self.assertEqual(str(result["reporting_end_date"]), "2026-01-04")

    def test_unknown_cases_are_not_imputed(self):
        row = {
            "record_id": "AP/SRI/2026/01/01", "report_year": 2026, "report_week": 1,
            "state": "Andhra Pradesh", "district": "Sri Sathya Sai", "disease": "Suspected Food Poisoning",
            "cases": None, "deaths": 0, "current_status": "Under Surveillance",
            "source_url": "https://ncdc.mohfw.gov.in/uploads/weekly_outbreaks/2026/week1_1788853592.pdf",
            "source_validation_status": "source_reviewed_core_fields", "review_status": "pending_supervisor_review"
        }
        with self.assertRaisesRegex(ValueError, "cases is missing"):
            mod.prepare_live_record(row)

if __name__ == "__main__":
    unittest.main()
