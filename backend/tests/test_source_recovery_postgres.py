"""Real PostgreSQL integration checks, restricted to the disposable CI database."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from uuid import uuid4
from unittest.mock import patch
from urllib.error import HTTPError


@unittest.skipUnless(os.getenv("SK_TEST_POSTGRES") == "1", "disposable PostgreSQL CI only")
class SourceRecoveryPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import ingestion_pipeline as pipeline
        url = pipeline.engine.url
        if url.host not in ("localhost", "127.0.0.1") or url.database != "sk_ci":
            raise RuntimeError("Refusing integration test outside the disposable sk_ci database")
        cls.pipeline = pipeline
        pipeline.ensure_pipeline_schema()

    def candidate(self):
        suffix = str(uuid4().int % 10**16)
        return dict(
            candidate_id=uuid4().hex,
            source_record_id="KL/ERA/2026/34/" + suffix,
            source_url="https://ncdc.mohfw.gov.in/uploads/weekly_outbreaks/2026/week34_old_" + suffix + ".pdf",
            source_sha256="old-" + suffix, source_page=3,
            report_year=2026, report_week=34, state="Kerala",
            district="Ernakulam", disease="Dengue", cases=20, deaths=0,
            reporting_start_date=date(2026,8,19), reporting_end_date=date(2026,8,20),
            raw_excerpt="test outbreak", validation_status="needs_review",
            validation_errors=["table_cell_extraction_requires_supervisor_review"],
        )

    def test_concurrent_replays_and_revision(self):
        from sqlalchemy import text
        p = self.pipeline
        first = self.candidate()
        second = self.candidate()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(p._insert_candidates, batch)
                       for batch in ([first, second], [second, first])]
            inserted = sum(f.result(timeout=30)[0] for f in futures)
        self.assertEqual(inserted, 2)
        revision = {**first, "candidate_id":uuid4().hex,
                    "source_sha256":"revised-" + first["source_sha256"], "cases":25}
        self.assertEqual(p._insert_candidates([revision]), (1,1))
        self.assertEqual(p._insert_candidates([revision]), (0,0))
        with p.engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT cases, review_status, validation_errors
                FROM public.sk_ingestion_candidates
                WHERE source_record_id=:id ORDER BY cases
            """), {"id": first["source_record_id"]}).mappings().all()
        self.assertEqual([r["cases"] for r in rows], [20,25])
        self.assertTrue(all(r["review_status"] == "pending_supervisor_review" for r in rows))
        self.assertIn("revised_ncdc_report_requires_supervisor_review", rows[1]["validation_errors"])

    def test_repair_and_metadata_audit_real_transaction(self):
        from sqlalchemy import text
        from app import source_recovery as recovery
        p = self.pipeline
        original = self.candidate()
        self.assertEqual(p._insert_candidates([original]), (1,1))
        old_url = original["source_url"]
        new_url = old_url.replace("week34_old_", "week34_new_")
        with p.engine.connect() as conn:
            row = dict(conn.execute(text("""
                SELECT * FROM public.sk_ingestion_candidates WHERE candidate_id=:id
            """), {"id": original["candidate_id"]}).mappings().one())
        def download(url):
            if url == old_url:
                raise HTTPError(url,404,"test",{},None)
            return b"%PDF-disposable-integration-fixture"
        extracted = {**original, "source_page":12}
        with patch.object(recovery,"_download_official_pdf",side_effect=download), \
             patch.object(p,"parse_candidate_pdf",return_value=[extracted]):
            self.assertTrue(recovery.recover_pending_candidate(row,[{"url":new_url}]))
        with p.engine.connect() as conn:
            updated = conn.execute(text("""
                SELECT * FROM public.sk_ingestion_candidates WHERE candidate_id=:id
            """), {"id":original["candidate_id"]}).mappings().one()
            doc = conn.execute(text("""
                SELECT * FROM public.sk_source_documents WHERE source_url=:url
            """), {"url":new_url}).mappings().one()
            audit = conn.execute(text("""
                SELECT details FROM public.sk_candidate_audit WHERE candidate_id=:id AND action='source_repaired'
            """), {"id":original["candidate_id"]}).mappings().one()
        self.assertEqual(updated["source_url"],new_url)
        self.assertEqual(updated["source_page"],12)
        self.assertEqual(updated["review_status"],"pending_supervisor_review")
        self.assertEqual(updated["cases"],original["cases"])
        self.assertEqual(doc["content_sha256"],updated["source_sha256"])
        self.assertEqual(doc["extraction_status"],"pending_download")
        self.assertEqual(audit["details"]["old_source_url"],old_url)

if __name__ == "__main__":
    unittest.main()
