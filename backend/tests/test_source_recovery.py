"""Isolated recovery unit tests: no network or database access.

Real PDF extraction and PostgreSQL concurrency need separate integration tests.
"""
import importlib.util
import hashlib
import json
import re
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

BASE = "https://ncdc.mohfw.gov.in/uploads/weekly_outbreaks/2026/"
OLD, NEW, OTHER = (BASE + name for name in ("week34_old.pdf", "week34_new.pdf", "week34_other.pdf"))
PATH = Path(__file__).resolve().parents[1] / "app" / "source_recovery.py"

def http_error(code):
    return HTTPError(OLD, code, "test", {}, None)

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        pipeline = types.ModuleType("recovery_test_app.ingestion_pipeline")
        pipeline._download_official_pdf = MagicMock(side_effect=http_error(404))
        pipeline._fetch_ncdc_catalogue = MagicMock(return_value=[{"url": NEW}])
        pipeline.is_allowed_source_url = lambda u, _: urlparse(u).scheme == "https" and urlparse(u).hostname == "ncdc.mohfw.gov.in"
        pipeline.parse_report_period = lambda u: (2026, int(re.search(r"week(\d+)",u).group(1)))
        pipeline.engine = MagicMock()
        pipeline.parse_candidate_pdf = MagicMock()
        pipeline.content_fingerprint = lambda data: hashlib.sha256(data).hexdigest()
        package = types.ModuleType("recovery_test_app")
        package.__path__ = []
        sql = types.ModuleType("sqlalchemy")
        sql.text = lambda x: x
        self.modules = patch.dict(sys.modules, {
            "recovery_test_app": package,
            "recovery_test_app.ingestion_pipeline": pipeline,
            "sqlalchemy": sql,
        })
        self.modules.start()
        self.addCleanup(self.modules.stop)
        spec = importlib.util.spec_from_file_location("recovery_test_app.source_recovery", PATH)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.pipeline = pipeline
        self.row = dict(candidate_id="candidate", review_status="pending_supervisor_review",
            source_url=OLD, source_sha256="original", source_page=3, updated_at="original-time",
            source_record_id="KL/ERA/2026/34/1389", report_year=2026, report_week=34,
            state="Kerala", district="Ernakulam", disease="Dengue", cases=20, deaths=0,
            reporting_start_date="2026-08-19", reporting_end_date="2026-08-20")
        self.conn = pipeline.engine.begin.return_value.__enter__.return_value
        self.conn.execute.return_value.rowcount = 1
        pipeline.parse_candidate_pdf.return_value = [{**self.row, "source_page": 12}]

    def setup_download(self, old_status=404):
        def download(url):
            if url == OLD:
                raise http_error(old_status)
            return b"%PDF-test"
        self.mod._download_official_pdf.side_effect = download

    def test_discovery_only_same_period_and_host(self):
        catalogue = [{"url": NEW}, {"url": NEW}, {"url": OLD},
                     {"url": BASE+"week35_new.pdf"}, {"url": "https://evil.example/week34_new.pdf"}]
        self.assertEqual(self.mod.discover_replacements(OLD, 2026, 34, catalogue), [NEW])

    def test_410(self):
        self.setup_download(410)
        self.assertEqual(self.mod.discover_replacements(OLD, 2026, 34), [NEW])

    def test_transient_http_errors_do_not_repair(self):
        for status in (403, 429, 500, 503):
            with self.subTest(status=status):
                self.setup_download(status)
                self.assertFalse(self.mod.recover_pending_candidate(self.row))
        self.pipeline.engine.begin.assert_not_called()

    def test_available_original_not_repaired(self):
        self.mod._download_official_pdf.side_effect = None
        self.mod._download_official_pdf.return_value = b"%PDF-test"
        self.assertFalse(self.mod.recover_pending_candidate(self.row))
        self.pipeline.engine.begin.assert_not_called()

    def test_network_failure_does_not_write(self):
        self.mod._download_official_pdf.side_effect = URLError("timeout")
        with self.assertRaises(URLError):
            self.mod.recover_pending_candidate(self.row)
        self.pipeline.engine.begin.assert_not_called()

    def test_exact_repair_and_audit(self):
        self.setup_download()
        self.assertTrue(self.mod.recover_pending_candidate(self.row))
        update, catalogue, audit = self.conn.execute.call_args_list
        self.assertIn("INSERT INTO public.sk_source_documents", catalogue.args[0])
        self.assertEqual(catalogue.args[1]["url"], NEW)
        self.assertEqual(catalogue.args[1]["size"], len(b"%PDF-test"))
        self.assertIn("UPDATE public.sk_ingestion_candidates", update.args[0])
        self.assertIn("review_status='pending_supervisor_review'", update.args[0])
        self.assertEqual(update.args[1]["page"], 12)
        self.assertEqual(update.args[1]["old_sha"], "original")
        self.assertEqual(update.args[1]["updated"], "original-time")
        self.assertIn("INSERT INTO public.sk_candidate_audit", audit.args[0])
        details = json.loads(audit.args[1]["details"])
        self.assertEqual(details["old_source_url"], OLD)
        self.assertEqual(details["new_source_url"], NEW)
        self.assertEqual(len(details["verified_fields"]), 7)

    def test_each_mismatching_field_prevents_write(self):
        self.setup_download()
        for field in ("state", "district", "disease", "cases", "deaths",
                      "reporting_start_date", "reporting_end_date"):
            with self.subTest(field=field):
                self.pipeline.parse_candidate_pdf.return_value = [{**self.row, field: "different"}]
                self.assertFalse(self.mod.recover_pending_candidate(self.row))
        self.pipeline.engine.begin.assert_not_called()

    def test_multiple_matching_pdfs_prevent_write(self):
        self.setup_download()
        self.assertFalse(self.mod.recover_pending_candidate(self.row, [{"url": NEW}, {"url": OTHER}]))
        self.pipeline.engine.begin.assert_not_called()

    def test_duplicate_outbreak_id_prevents_write(self):
        self.setup_download()
        self.pipeline.parse_candidate_pdf.return_value = [self.row, self.row]
        self.assertFalse(self.mod.recover_pending_candidate(self.row))
        self.pipeline.engine.begin.assert_not_called()

    def test_ineligible_candidates_prevent_write(self):
        self.setup_download()
        for changes in ({"review_status":"promoted"}, {"review_status":"approved"},
                        {"cases":None}, {"source_record_id":"invalid"}):
            with self.subTest(changes=changes):
                self.assertFalse(self.mod.recover_pending_candidate({**self.row, **changes}))
        self.pipeline.engine.begin.assert_not_called()

    def test_concurrent_change_prevents_audit(self):
        self.setup_download()
        self.conn.execute.return_value.rowcount = 0
        self.assertFalse(self.mod.recover_pending_candidate(self.row))
        self.assertEqual(self.conn.execute.call_count, 1)

    def test_scan_is_bounded_and_continues_after_error(self):
        rows = [{**self.row, "candidate_id":"a"}, {**self.row, "candidate_id":"b"}]
        conn = self.pipeline.engine.connect.return_value.__enter__.return_value
        conn.execute.return_value.mappings.return_value.all.return_value = rows
        with patch.object(self.mod, "recover_pending_candidate", side_effect=[RuntimeError("test"), True]):
            with self.assertLogs(self.mod.logger, level="ERROR"):
                result = self.mod.scan_pending_recovery([{"url":NEW}], limit=99)
        self.assertEqual(result, {"checked":2,"repaired":1,"errors":1})
        self.assertEqual(conn.execute.call_args.args[1]["limit"], 2)
        self.assertEqual(self.mod._scan_cursor, "b")

if __name__ == "__main__":
    unittest.main()
