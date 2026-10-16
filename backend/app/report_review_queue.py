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

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from .database import engine
from .auth_security import decode_access_token

router = APIRouter(prefix="/admin/ncdc-report-queue", tags=["Admin · Report review queue"])
PROJECT_ROOT = Path(__file__).resolve().parents[2]
QUEUE_PATH = Path(os.getenv("SK_NCDC_QUEUE_PATH", str(PROJECT_ROOT / "data" / "ncdc_report_review_queue.json")))
ALLOWED_HOSTS = {"ncdc.mohfw.gov.in", "www.ncdc.mohfw.gov.in"}
LOCK = threading.RLock()
MAX_ITEMS = 1000
VALID_STATUSES = {"pending_review", "reviewed", "ignored"}


# PERSISTENT_DB_REVIEW_STATE_V1

def _uses_persistent_db(path: Path) -> bool:
    try:
        return Path(path).resolve() == Path(QUEUE_PATH).resolve()
    except (OSError, TypeError):
        return False


def _ensure_review_tables() -> None:
    """Create small, additive review-state and audit tables if absent."""
    if engine.dialect.name == "postgresql":
        audit_id = "BIGSERIAL PRIMARY KEY"
        timestamp_type = "TIMESTAMPTZ"
    else:
        # Portable branch allows the same workflow to be unit-tested with SQLite.
        audit_id = "INTEGER PRIMARY KEY AUTOINCREMENT"
        timestamp_type = "TEXT"

    with engine.begin() as connection:
        connection.execute(text(f"""
            CREATE TABLE IF NOT EXISTS ncdc_report_review_state (
                report_id TEXT PRIMARY KEY,
                status TEXT NOT NULL CHECK (status IN ('pending_review','reviewed','ignored')),
                review_notes TEXT NOT NULL DEFAULT '',
                reviewed_at {timestamp_type} NULL,
                reviewed_by TEXT NOT NULL DEFAULT 'admin',
                updated_at {timestamp_type} NOT NULL
            )
        """))
        connection.execute(text(f"""
            CREATE TABLE IF NOT EXISTS ncdc_report_review_audit (
                id {audit_id},
                report_id TEXT NOT NULL,
                old_status TEXT NOT NULL,
                new_status TEXT NOT NULL CHECK (new_status IN ('pending_review','reviewed','ignored')),
                reviewer TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                source_url TEXT NULL,
                reviewed_at {timestamp_type} NOT NULL
            )
        """))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_ncdc_report_review_audit_report_time "
            "ON ncdc_report_review_audit (report_id, reviewed_at)"
        ))


def _load_persisted_review_map() -> dict[str, dict[str, Any]]:
    _ensure_review_tables()
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT report_id, status, review_notes, reviewed_at, reviewed_by, updated_at
            FROM ncdc_report_review_state
        """)).mappings().all()
    return {str(row["report_id"]): dict(row) for row in rows}


def _seed_legacy_decision(item: dict[str, Any]) -> None:
    """Migrate an existing local-file decision once, without overwriting DB state."""
    report_id = str(item.get("report_id") or "").strip()
    status = str(item.get("status") or "pending_review")
    if not report_id or status not in VALID_STATUSES or status == "pending_review":
        return
    now = _now()
    reviewed_at = item.get("reviewed_at") or now
    reviewer = str(item.get("reviewed_by") or "migrated_local_queue")[:120]
    notes = str(item.get("review_notes") or "")[:2000]
    _ensure_review_tables()
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO ncdc_report_review_state
                (report_id, status, review_notes, reviewed_at, reviewed_by, updated_at)
            VALUES (:report_id, :status, :notes, :reviewed_at, :reviewer, :updated_at)
            ON CONFLICT (report_id) DO NOTHING
        """), {
            "report_id": report_id,
            "status": status,
            "notes": notes,
            "reviewed_at": reviewed_at,
            "reviewer": reviewer,
            "updated_at": now,
        })


def _persist_review_decision(
    item: dict[str, Any],
    status: str,
    notes: str,
    reviewer: str,
) -> None:
    """Commit current decision and append an audit event in one transaction."""
    _ensure_review_tables()
    report_id = str(item.get("report_id") or "").strip()
    now = _now()
    reviewed_at = now if status != "pending_review" else None
    reviewer = (str(reviewer or "admin").strip() or "admin")[:120]
    notes = str(notes or "").strip()[:2000]
    source_url = str(item.get("url") or "")[:2048] or None

    with engine.begin() as connection:
        previous = connection.execute(text("""
            SELECT status, review_notes
            FROM ncdc_report_review_state
            WHERE report_id = :report_id
        """), {"report_id": report_id}).mappings().first()
        old_status = str(previous["status"]) if previous else "pending_review"
        old_notes = str(previous["review_notes"] or "") if previous else ""
        connection.execute(text("""
            INSERT INTO ncdc_report_review_state
                (report_id, status, review_notes, reviewed_at, reviewed_by, updated_at)
            VALUES (:report_id, :status, :notes, :reviewed_at, :reviewer, :updated_at)
            ON CONFLICT (report_id) DO UPDATE SET
                status = excluded.status,
                review_notes = excluded.review_notes,
                reviewed_at = excluded.reviewed_at,
                reviewed_by = excluded.reviewed_by,
                updated_at = excluded.updated_at
        """), {
            "report_id": report_id,
            "status": status,
            "notes": notes,
            "reviewed_at": reviewed_at,
            "reviewer": reviewer,
            "updated_at": now,
        })
        if old_status != status or old_notes != notes:
            connection.execute(text("""
                INSERT INTO ncdc_report_review_audit
                    (report_id, old_status, new_status, reviewer, notes, source_url, reviewed_at)
                VALUES (:report_id, :old_status, :new_status, :reviewer, :notes, :source_url, :reviewed_at)
            """), {
                "report_id": report_id,
                "old_status": old_status,
                "new_status": status,
                "reviewer": reviewer,
                "notes": notes,
                "source_url": source_url,
                "reviewed_at": now,
            })


def list_ncdc_review_audit(limit: int = 50) -> dict[str, Any]:
    limit = max(1, min(int(limit), 200))
    _ensure_review_tables()
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT id, report_id, old_status, new_status, reviewer, notes, source_url, reviewed_at
            FROM ncdc_report_review_audit
            ORDER BY reviewed_at DESC, id DESC
            LIMIT :limit
        """), {"limit": limit}).mappings().all()
    return {"items": [dict(row) for row in rows], "count": len(rows)}


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
        # Local temporary-path tests stay isolated. Production reads overlay durable DB decisions.
        if _uses_persistent_db(path):
            persisted = _load_persisted_review_map()
            for item in state["items"]:
                report_id = str(item.get("report_id") or "")
                saved = persisted.get(report_id)
                if saved is None:
                    _seed_legacy_decision(item)
                    continue
                item["status"] = str(saved["status"])
                item["review_notes"] = str(saved.get("review_notes") or "")
                item["reviewed_at"] = saved.get("reviewed_at")
                item["reviewed_by"] = saved.get("reviewed_by")
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
        "interpretation": "Report discovery only. Review decisions persist in PostgreSQL. Marking a report reviewed does not import case counts into PostgreSQL; use the validated staging/import workflow after checking the source PDF.",
    }



def update_ncdc_report_review(
    report_id: str,
    status: str,
    notes: str = "",
    path: Path = QUEUE_PATH,
    reviewer: str = "admin",
) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError("Unsupported report review status")
    with LOCK:
        state = _read_state(path)
        target = next((item for item in state["items"] if item.get("report_id") == report_id), None)
        if target is None:
            raise KeyError("Report not found in the NCDC review queue")
        clean_notes = str(notes or "").strip()[:2000]
        # Persist first; if PostgreSQL fails, do not tell the operator that the
        # review was saved only to an ephemeral Render filesystem.
        if _uses_persistent_db(path):
            _persist_review_decision(target, status, clean_notes, reviewer)
        target["status"] = status
        target["review_notes"] = clean_notes
        target["reviewed_at"] = _now() if status != "pending_review" else None
        target["reviewed_by"] = (str(reviewer or "admin").strip() or "admin")[:120] if status != "pending_review" else None
        _write_state(state, path)
        return dict(target)



class ReviewUpdate(BaseModel):
    status: Literal["pending_review", "reviewed", "ignored"]
    notes: str = Field(default="", max_length=2000)


@router.get("", summary="List discovered NCDC PDF reports waiting for human review")
def get_ncdc_report_queue(status: str | None = Query(default=None), limit: int = Query(default=200, ge=1, le=500)):
    try:
        return list_ncdc_report_queue(status=status, limit=limit)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="PostgreSQL review-state storage is unavailable; no durable review change was reported as successful.") from exc
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"Could not read report queue: {type(exc).__name__}") from exc



@router.post("/items/{report_id}/review", summary="Record review state for an official NCDC report")
def review_ncdc_report(report_id: str, update: ReviewUpdate, request: Request):
    auth_header = request.headers.get("authorization", "")
    scheme, _, token = auth_header.partition(" ")
    claims = decode_access_token(token.strip()) if scheme.lower() == "bearer" and token.strip() else None
    reviewer = "admin"
    if isinstance(claims, dict):
        reviewer = str(claims.get("sub") or claims.get("username") or "admin")
    try:
        return {"item": update_ncdc_report_review(report_id, update.status, update.notes, reviewer=reviewer)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="PostgreSQL review-state storage is unavailable; the decision was not reported as saved.") from exc
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"Could not update report review: {type(exc).__name__}") from exc

@router.get("/audit", summary="View recent NCDC report review audit events")
def get_ncdc_report_review_audit(limit: int = Query(default=50, ge=1, le=200)):
    try:
        return list_ncdc_review_audit(limit)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="PostgreSQL review audit is unavailable.") from exc
