from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.report_review_queue import (
    list_ncdc_report_queue,
    sync_ncdc_report_queue,
    update_ncdc_report_review,
)


def payload(items):
    return {
        "status": "available",
        "last_checked_at": "2026-10-16T00:00:00+00:00",
        "last_successful_fetch_at": "2026-10-16T00:00:00+00:00",
        "items": items,
    }


def report(url="https://ncdc.mohfw.gov.in/reports/weekly.pdf", title="Week 10", year=2026, week=10):
    return {"url": url, "title": title, "year": year, "week": week, "report_type": "pdf"}


def test_sync_deduplicates_and_accepts_only_official_https_pdfs(tmp_path: Path):
    path = tmp_path / "queue.json"
    result = sync_ncdc_report_queue(payload([
        report(), report(title="Duplicate title"),
        report(url="https://example.com/evil.pdf"),
        report(url="http://ncdc.mohfw.gov.in/insecure.pdf"),
        report(url="https://ncdc.mohfw.gov.in/not-a-pdf.html"),
    ]), path=path)
    assert result["added"] == 1
    data = list_ncdc_report_queue(path=path)
    assert data["total"] == 1
    assert data["items"][0]["status"] == "pending_review"
    assert data["items"][0]["url"].startswith("https://ncdc.mohfw.gov.in/")


def test_review_state_and_notes_survive_future_catalog_sync(tmp_path: Path):
    path = tmp_path / "queue.json"
    item = report()
    sync_ncdc_report_queue(payload([item]), path=path)
    initial = list_ncdc_report_queue(path=path)["items"][0]
    updated = update_ncdc_report_review(initial["report_id"], "reviewed", "Checked source PDF", path=path)
    assert updated["status"] == "reviewed"
    assert updated["review_notes"] == "Checked source PDF"
    sync_ncdc_report_queue(payload([item]), path=path)
    data = list_ncdc_report_queue(path=path)
    assert data["counts"]["reviewed"] == 1
    assert data["counts"]["pending_review"] == 0
    assert data["items"][0]["review_notes"] == "Checked source PDF"


def test_unknown_report_cannot_be_reviewed(tmp_path: Path):
    path = tmp_path / "queue.json"
    with pytest.raises(KeyError):
        update_ncdc_report_review("missing-id", "reviewed", path=path)


def test_invalid_review_state_is_rejected(tmp_path: Path):
    path = tmp_path / "queue.json"
    sync_ncdc_report_queue(payload([report()]), path=path)
    item = list_ncdc_report_queue(path=path)["items"][0]
    with pytest.raises(ValueError):
        update_ncdc_report_review(item["report_id"], "imported", path=path)
