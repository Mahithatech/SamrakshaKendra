#!/usr/bin/env python3
"""Add PostgreSQL-backed persistence and audit for the existing NCDC link review queue.

Safe, additive patch for the current Samraksha Kendra project. It leaves the
queue's API response shape intact, keeps NCDC report links separate from live
surveillance totals, and backs review states with PostgreSQL so Render deploys
or instance restarts do not lose administrator decisions.
"""
from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "backend" / "app" / "report_review_queue.py"
TESTS = ROOT / "backend" / "tests" / "test_persistent_report_review_queue.py"
DOC = ROOT / "docs" / "persistent-report-review-queue.md"
MARKER = "PERSISTENT_DB_REVIEW_STATE_V1"

HELPERS = r'''# PERSISTENT_DB_REVIEW_STATE_V1

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

'''

LIST_FUNCTION = r'''def list_ncdc_report_queue(status: str | None = None, limit: int = 200, path: Path = QUEUE_PATH) -> dict[str, Any]:
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
'''

UPDATE_FUNCTION = r'''def update_ncdc_report_review(
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
'''

GET_ROUTE = r'''def get_ncdc_report_queue(status: str | None = Query(default=None), limit: int = Query(default=200, ge=1, le=500)):
    try:
        return list_ncdc_report_queue(status=status, limit=limit)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="PostgreSQL review-state storage is unavailable; no durable review change was reported as successful.") from exc
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"Could not read report queue: {type(exc).__name__}") from exc
'''

REVIEW_ROUTE = r'''def review_ncdc_report(report_id: str, update: ReviewUpdate, request: Request):
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
'''


AUDIT_ROUTE = r"""
@router.get("/audit", summary="View recent NCDC report review audit events")
def get_ncdc_report_review_audit(limit: int = Query(default=50, ge=1, le=200)):
    try:
        return list_ncdc_review_audit(limit)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="PostgreSQL review audit is unavailable.") from exc
"""


def _replace_function(source: str, name: str, replacement: str) -> str:
    tree = ast.parse(source)
    matches = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one top-level function {name}, found {len(matches)}")
    node = matches[0]
    lines = source.splitlines(keepends=True)
    start = sum(len(line) for line in lines[:node.lineno - 1])
    end = sum(len(line) for line in lines[:node.end_lineno])
    # Preserve the function's decorators, which appear before node.lineno.
    return source[:start] + replacement.strip("\n") + "\n\n" + source[end:]


def main() -> int:
    if not MODULE.is_file():
        print(f"STOP: {MODULE} not found. Run this tool from inside the current SamrakshaKendra project copy.", file=sys.stderr)
        return 2

    source = MODULE.read_text(encoding="utf-8")
    if MARKER in source:
        print("Persistent review-state patch already appears installed; no files changed.")
        return 0

    for function_name in ("list_ncdc_report_queue", "update_ncdc_report_review", "get_ncdc_report_queue", "review_ncdc_report"):
        if not any(isinstance(n, ast.FunctionDef) and n.name == function_name for n in ast.parse(source).body):
            print(f"STOP: expected function {function_name} not found; no files changed.", file=sys.stderr)
            return 2
    if "from .database import engine" in source or "PERSISTENT_DB_REVIEW_STATE" in source:
        print("STOP: module has partial persistence code; inspect manually, no files changed.", file=sys.stderr)
        return 2

    patched = source
    patched = patched.replace(
        "from fastapi import APIRouter, HTTPException, Query",
        "from fastapi import APIRouter, HTTPException, Query, Request",
        1,
    )
    # Add dependencies directly after the existing Pydantic import.
    pydantic_import = "from pydantic import BaseModel, Field"
    if pydantic_import not in patched:
        print("STOP: expected Pydantic import not found; no files changed.", file=sys.stderr)
        return 2
    patched = patched.replace(
        pydantic_import,
        pydantic_import + "\nfrom sqlalchemy import text\nfrom sqlalchemy.exc import SQLAlchemyError\nfrom .database import engine\nfrom .auth_security import decode_access_token",
        1,
    )

    try:
        patched = _replace_function(patched, "list_ncdc_report_queue", LIST_FUNCTION)
        patched = _replace_function(patched, "update_ncdc_report_review", UPDATE_FUNCTION)
        patched = _replace_function(patched, "get_ncdc_report_queue", GET_ROUTE)
        patched = _replace_function(patched, "review_ncdc_report", REVIEW_ROUTE)
        insertion = patched.find("def _now()")
        if insertion < 0:
            raise ValueError("Could not locate _now() helper for safe persistence helpers")
        patched = patched[:insertion] + HELPERS + "\n" + patched[insertion:]
        if '@router.get("/audit"' not in patched:
            patched = patched.rstrip() + "\n\n" + AUDIT_ROUTE.strip() + "\n"
        ast.parse(patched)
    except Exception as exc:
        print(f"STOP: patch validation failed ({type(exc).__name__}: {exc}); no files changed.", file=sys.stderr)
        return 2

    test_text = r'''from __future__ import annotations

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
'''

    docs_text = r"""# Durable NCDC report review state

The signed-in administrator's NCDC **publication-link** review decisions are persisted in PostgreSQL and audit events are append-only. The local JSON file remains a cache/source-discovery queue; its loss on a Render redeploy no longer resets saved review status for matching stable report IDs.

## New database tables
- `ncdc_report_review_state`: current status, notes, reviewer, timestamps.
- `ncdc_report_review_audit`: append-only status/notes change history.

The API response shape remains compatible with the existing React queue. `GET /admin/ncdc-report-queue/audit` lists the latest audit events. A database error returns HTTP 503 rather than falsely reporting a durable review as saved.

This workflow tracks review of official PDF links only. It does **not** parse case counts, promote candidate rows, or modify `idsp_surveillance`. Use the validated staging/import workflow separately after field-by-field PDF verification.

## Apply and verify
Run the patch installer from the project root with the existing venv, then run:

```powershell
$env:PYTHONPATH = "$PWD\backend"
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests .\tools\test_promote_ncdc_staging.py -q
Remove-Item Env:PYTHONPATH
cd .\frontend-react
npm.cmd run build
```

Commit and push only after both checks pass. The existing FastAPI process needs a redeploy/restart for the changed code to take effect. The new tables are created additively on first queue access.
"""

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = ROOT / "backups" / f"persistent_review_state_{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(MODULE, backup_dir / (MODULE.name + ".bak"))
    # Existing unit tests are preserved; create a separate test file.
    patched_test = test_text
    try:
        compile(patched, str(MODULE), "exec")
        compile(patched_test, str(TESTS), "exec")
    except SyntaxError as exc:
        print(f"STOP: generated code has a syntax error: {exc}; original files untouched.", file=sys.stderr)
        shutil.rmtree(backup_dir, ignore_errors=True)
        return 2

    MODULE.write_text(patched, encoding="utf-8", newline="")
    TESTS.parent.mkdir(parents=True, exist_ok=True)
    TESTS.write_text(patched_test, encoding="utf-8", newline="")
    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text(docs_text, encoding="utf-8", newline="")
    print("Persistent PostgreSQL review state and append-only audit installed.")
    print(f"Backup: {backup_dir}")
    print("Added: backend/tests/test_persistent_report_review_queue.py, docs/persistent-report-review-queue.md")
    print("Review decisions remain separate from live surveillance totals.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
