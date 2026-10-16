"""Persistent review queue for newly discovered official NCDC weekly reports.

This queue discovers official report links; it never infers case counts or writes
surveillance observations to PostgreSQL. A human-reviewed report must still flow
through the project's validated staging/import tools before affecting map totals.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/admin/ncdc-report-queue", tags=["Admin · Report review queue"])
PROJECT_ROOT = Path(__file__).resolve().parents[2]
QUEUE_PATH = Path(os.getenv("SK_NCDC_QUEUE_PATH", str(PROJECT_ROOT / "data" / "ncdc_report_review_queue.json")))
ALLOWED_HOSTS = {"ncdc.mohfw.gov.in", "www.ncdc.mohfw.gov.in"}
LOCK = threading.RLock()
MAX_ITEMS = 1000
VALID_STATUSES = {"pending_review", "reviewed", "ignored"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_official_pdf_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        return None
    if not parsed.path.lower().endswith(".pdf"):
        return None
    return url


def _empty_state() -> dict[str, Any]:
    return {"version": 1, "last_sync_at": None, "source_status": "not_checked", "source_last_checked_at": None, "source_last_successful_fetch_at": None, "items": []}


def _read_state(path: Path = QUEUE_PATH) -> dict[str, Any]:
    if not path.exists():
        return _empty_state()
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read NCDC queue file ({type(exc).__name__}).") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("items", []), list):
        raise RuntimeError("NCDC queue file has an unsupported structure; preserve it and inspect manually.")
    state = _empty_state()
    state.update(parsed)
    state["items"] = [item for item in state["items"] if isinstance(item, dict)]
    return state


def _write_state(state: dict[str, Any], path: Path = QUEUE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def sync_ncdc_report_queue(payload: dict[str, Any], path: Path = QUEUE_PATH) -> dict[str, Any]:
    """Add newly seen official NCDC PDF links while retaining prior review state."""
    if not isinstance(payload, dict):
        return {"added": 0, "total": 0, "status": "invalid_payload"}
    incoming = payload.get("items")
    if not isinstance(incoming, list):
        incoming = []
    with LOCK:
        state = _read_state(path)
        by_url = {item.get("url"): item for item in state["items"] if item.get("url")}
        added = 0
        seen_at = _now()
        for raw in incoming[:MAX_ITEMS]:
            if not isinstance(raw, dict):
                continue
            url = _valid_official_pdf_url(raw.get("url"))
            if not url:
                continue
            report_id = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
            existing = by_url.get(url)
            if existing:
                existing["last_seen_at"] = seen_at
                # Keep human-entered status/notes even when catalogue sync repeats.
                if raw.get("title"):
                    existing["title"] = str(raw["title"])[:220]
                continue
            row = {
                "report_id": report_id,
                "title": str(raw.get("title") or "NCDC weekly outbreak report")[:220],
                "url": url,
                "year": raw.get("year") if isinstance(raw.get("year"), int) else None,
                "week": raw.get("week") if isinstance(raw.get("week"), int) else None,
                "source": "NCDC / IDSP weekly outbreak report",
                "archive_url": "https://ncdc.mohfw.gov.in/includes/WeeklyOutbreaks.php",
                "first_seen_at": seen_at,
                "last_seen_at": seen_at,
                "status": "pending_review",
                "review_notes": "",
                "reviewed_at": None,
                "reviewed_by": None,
            }
            state["items"].append(row)
            by_url[url] = row
            added += 1
        state["items"] = state["items"][-MAX_ITEMS:]
        state["last_sync_at"] = seen_at
        state["source_status"] = str(payload.get("status") or "unknown")[:40]
        state["source_last_checked_at"] = payload.get("last_checked_at")
        state["source_last_successful_fetch_at"] = payload.get("last_successful_fetch_at")
        _write_state(state, path)
        return {"added": added, "total": len(state["items"]), "status": state["source_status"], "last_sync_at": state["last_sync_at"]}


def list_ncdc_report_queue(status: str | None = None, limit: int = 200, path: Path = QUEUE_PATH) -> dict[str, Any]:
    if status is not None and status not in VALID_STATUSES:
        raise ValueError("status must be pending_review, reviewed, or ignored")
    limit = max(1, min(int(limit), 500))
    with LOCK:
        state = _read_state(path)
    counts = {value: sum(1 for item in state["items"] if item.get("status") == value) for value in VALID_STATUSES}
    rows = [item for item in state["items"] if status is None or item.get("status") == status]
    rows.sort(key=lambda item: (item.get("year") or 0, item.get("week") or 0, item.get("first_seen_at") or ""), reverse=True)
    return {
        "items": rows[:limit],
        "total": len(rows),
        "counts": counts,
        "last_sync_at": state.get("last_sync_at"),
        "source_status": state.get("source_status", "not_checked"),
        "source_last_checked_at": state.get("source_last_checked_at"),
        "source_last_successful_fetch_at": state.get("source_last_successful_fetch_at"),
        "interpretation": "Report discovery only. Marking a report reviewed does not import case counts into PostgreSQL; use the validated staging/import workflow after checking the source PDF.",
    }


def update_ncdc_report_review(report_id: str, status: str, notes: str = "", path: Path = QUEUE_PATH) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError("Unsupported report review status")
    with LOCK:
        state = _read_state(path)
        target = next((item for item in state["items"] if item.get("report_id") == report_id), None)
        if target is None:
            raise KeyError("Report not found in the NCDC review queue")
        target["status"] = status
        target["review_notes"] = str(notes or "").strip()[:2000]
        target["reviewed_at"] = _now() if status != "pending_review" else None
        target["reviewed_by"] = "local_admin" if status != "pending_review" else None
        _write_state(state, path)
        return dict(target)


class ReviewUpdate(BaseModel):
    status: Literal["pending_review", "reviewed", "ignored"]
    notes: str = Field(default="", max_length=2000)


@router.get("", summary="List discovered NCDC PDF reports waiting for human review")
def get_ncdc_report_queue(status: str | None = Query(default=None), limit: int = Query(default=200, ge=1, le=500)):
    try:
        return list_ncdc_report_queue(status=status, limit=limit)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"Could not read report queue: {type(exc).__name__}") from exc


@router.post("/items/{report_id}/review", summary="Record review state for an official NCDC report")
def review_ncdc_report(report_id: str, update: ReviewUpdate):
    try:
        return {"item": update_ncdc_report_review(report_id, update.status, update.notes)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"Could not update report review: {type(exc).__name__}") from exc
