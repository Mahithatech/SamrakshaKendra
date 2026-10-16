from __future__ import annotations

from pathlib import Path
from sqlalchemy import create_engine, text

from app import report_review_queue as queue


def sample_payload():
    return {
        "status": "available",
        "last_checked_at": "2026-10-16T12:00:00+00:00",
        "last_successful_fetch_at": "2026-10-16T12:00:00+00:00",
        "items": [{
            "url": "https://ncdc.mohfw.gov.in/uploads/weekly_outbreaks/2026/week34_test.pdf",
            "title": "NCDC Weekly Outbreak Report 2026 Week 34",
            "year": 2026,
            "week": 34,
        }],
    }


def test_review_decision_survives_queue_file_loss(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    path = tmp_path / "ncdc_report_review_queue.json"
    monkeypatch.setattr(queue, "engine", engine)
    monkeypatch.setattr(queue, "QUEUE_PATH", path)
    try:
        queue.sync_ncdc_report_queue(sample_payload(), path=path)
        item = queue.list_ncdc_report_queue(path=path)["items"][0]
        saved = queue.update_ncdc_report_review(
            item["report_id"], "reviewed", "Checked the official source PDF.",
            path=path, reviewer="root",
        )
        assert saved["status"] == "reviewed"
        assert saved["reviewed_by"] == "root"

        # Simulate a Render deploy clearing its local filesystem.
        path.unlink()
        queue.sync_ncdc_report_queue(sample_payload(), path=path)
        after_restart = queue.list_ncdc_report_queue(path=path)
        assert after_restart["counts"]["reviewed"] == 1
        assert after_restart["counts"]["pending_review"] == 0
        assert after_restart["items"][0]["review_notes"] == "Checked the official source PDF."
        assert after_restart["items"][0]["reviewed_by"] == "root"

        audit = queue.list_ncdc_review_audit()
        assert audit["count"] == 1
        assert audit["items"][0]["new_status"] == "reviewed"
    finally:
        engine.dispose()


def test_temporary_test_queue_does_not_touch_database(tmp_path, monkeypatch):
    path = tmp_path / "isolated.json"
    def fail_if_called():
        raise AssertionError("temporary queue tests must not use the database")
    monkeypatch.setattr(queue, "_ensure_review_tables", fail_if_called)
    queue.sync_ncdc_report_queue(sample_payload(), path=path)
    item = queue.list_ncdc_report_queue(path=path)["items"][0]
    queue.update_ncdc_report_review(item["report_id"], "ignored", "duplicate report", path=path)
    assert queue.list_ncdc_report_queue(path=path)["counts"]["ignored"] == 1
