#!/usr/bin/env python3
"""Promote explicitly approved NCDC staging rows into live IDSP surveillance.

Default is dry-run. A record is eligible only when it appears in an approval manifest
with source_pdf_checked=true, an approving person, an approval timestamp, and a note.
No case counts are inferred. Week reporting dates use the ISO week containing the
report_year/report_week. Already-live record IDs are skipped idempotently.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIRM_TEXT = "PROMOTE-APPROVED-NCDC-ROWS"
MANIFEST_FIELDS = {
    "record_id", "approved_by", "approved_at_utc", "source_pdf_checked", "approval_note"
}


def read_approval_manifest(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"Approval manifest not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or [])
        missing = sorted(MANIFEST_FIELDS - fields)
        if missing:
            raise ValueError("Approval manifest missing columns: " + ", ".join(missing))
        raw = list(reader)

    approvals: list[dict[str, str]] = []
    seen: set[str] = set()
    for line_no, row in enumerate(raw, start=2):
        item = {k: str(row.get(k) or "").strip() for k in MANIFEST_FIELDS}
        rid = item["record_id"]
        if not rid:
            # Empty template rows are permitted and ignored.
            if any(item[k] for k in MANIFEST_FIELDS - {"record_id"}):
                raise ValueError(f"Manifest line {line_no}: approval fields filled but record_id is blank")
            continue
        if rid in seen:
            raise ValueError(f"Manifest line {line_no}: duplicate record_id {rid}")
        seen.add(rid)

        # A completely unfilled approval row means 'not approved yet'.
        approval_values = [item[k] for k in ("approved_by", "approved_at_utc", "source_pdf_checked", "approval_note")]
        if not any(approval_values):
            continue
        if not all(approval_values):
            raise ValueError(f"Manifest line {line_no} ({rid}): partially completed approval; fill all approval columns or leave all blank")
        if item["source_pdf_checked"].casefold() != "true":
            raise ValueError(f"Manifest line {line_no} ({rid}): source_pdf_checked must be true")
        if len(item["approval_note"]) < 10:
            raise ValueError(f"Manifest line {line_no} ({rid}): approval_note must be at least 10 characters")
        try:
            approved_at = datetime.fromisoformat(item["approved_at_utc"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Manifest line {line_no} ({rid}): approved_at_utc must be ISO-8601") from exc
        if approved_at.tzinfo is None or approved_at.utcoffset() is None:
            raise ValueError(f"Manifest line {line_no} ({rid}): approved_at_utc must include a timezone")
        approvals.append(item)
    return approvals


def _as_nonnegative_int(value: Any, field: str, rid: str, required: bool = False) -> int | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValueError(f"{rid}: {field} is missing; refusing to infer a value")
        return None
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{rid}: {field} must be a non-negative integer") from exc
    if number < 0:
        raise ValueError(f"{rid}: {field} must not be negative")
    return number


def prepare_live_record(row: dict[str, Any]) -> dict[str, Any]:
    rid = str(row.get("record_id") or "").strip()
    if not rid:
        raise ValueError("Staging row has no record_id")
    for field in ("state", "district", "disease", "source_url"):
        if not str(row.get(field) or "").strip():
            raise ValueError(f"{rid}: {field} is blank")
    source_url = str(row["source_url"]).strip()
    parsed = urlparse(source_url)
    if parsed.scheme != "https" or parsed.hostname not in {"ncdc.mohfw.gov.in", "www.ncdc.mohfw.gov.in"} or not parsed.path.lower().endswith(".pdf"):
        raise ValueError(f"{rid}: source_url is not a verified-format official NCDC HTTPS PDF URL")
    if str(row.get("source_validation_status") or "").strip() != "source_reviewed_core_fields":
        raise ValueError(f"{rid}: core fields are not marked source_reviewed_core_fields")
    if str(row.get("review_status") or "").strip() != "pending_supervisor_review":
        raise ValueError(f"{rid}: expected pending_supervisor_review; found {row.get('review_status')!r}")
    year = int(row["report_year"])
    week = int(row["report_week"])
    if year < 2000 or year > 2100 or not 1 <= week <= 53:
        raise ValueError(f"{rid}: invalid report year/week")
    try:
        week_start = date.fromisocalendar(year, week, 1)
        week_end = date.fromisocalendar(year, week, 7)
    except ValueError as exc:
        raise ValueError(f"{rid}: invalid ISO reporting week {year}-W{week:02d}") from exc
    cases = _as_nonnegative_int(row.get("cases"), "cases", rid, required=True)
    deaths = _as_nonnegative_int(row.get("deaths"), "deaths", rid, required=False)
    return {
        "record_id": rid,
        "year": year,
        "week": week,
        "reporting_start_date": week_start,
        "reporting_end_date": week_end,
        "state": str(row["state"]).strip(),
        "district": str(row["district"]).strip(),
        "disease": str(row["disease"]).strip(),
        "cases": cases,
        "deaths": deaths,
        "outbreak_status": (str(row.get("current_status") or "").strip() or None),
        "source": f"NCDC/IDSP weekly outbreak report {year}-W{week:02d}",
        "source_url": source_url,
    }


def _load_engine():
    # Prefer the project's own DB setup and local backend/.env configuration.
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / "backend" / ".env")
    except ImportError:
        pass
    backend = str(PROJECT_ROOT / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from app.database import engine
    return engine


def execute(manifest_path: Path, apply: bool = False, confirm: str | None = None) -> int:
    approvals = read_approval_manifest(manifest_path)
    if not approvals:
        print("No approved rows found in manifest. No database writes made.")
        print("After manually checking the official PDF, fill approval fields for selected records in the manifest.")
        return 0
    if apply and confirm != CONFIRM_TEXT:
        raise ValueError(f"Live writes require --confirm {CONFIRM_TEXT}")

    from sqlalchemy import text
    engine = _load_engine()
    plans: list[tuple[dict[str, Any], dict[str, Any]]] = []
    skipped_live: list[str] = []
    with engine.connect() as conn:
        for approval in approvals:
            rid = approval["record_id"]
            stage = conn.execute(text("""
                SELECT record_id, report_year, report_week, state, district, disease,
                       cases, deaths, current_status, source_url, source_validation_status,
                       review_status, source_validation_note
                FROM public.ncdc_outbreak_staging WHERE record_id = :rid
            """), {"rid": rid}).mappings().first()
            if stage is None:
                raise ValueError(f"Approved record is absent from ncdc_outbreak_staging: {rid}")
            live_record = prepare_live_record(dict(stage))
            existing = conn.execute(text("SELECT 1 FROM public.idsp_surveillance WHERE record_id = :rid"), {"rid": rid}).first()
            if existing:
                skipped_live.append(rid)
                continue
            plans.append((live_record, approval))

    print(f"Approval manifest records: {len(approvals)}")
    print(f"Eligible new live records: {len(plans)}")
    print(f"Already-live records skipped: {len(skipped_live)}")
    for live, approval in plans:
        print(f"  {live['record_id']} | {live['state']} | {live['district']} | {live['disease']} | cases={live['cases']} | deaths={live['deaths']} | approved_by={approval['approved_by']}")
    if not apply:
        print("DRY RUN ONLY. No database writes were made.")
        print(f"To apply only this explicit approval manifest, rerun with --apply --confirm {CONFIRM_TEXT}")
        return 0

    insert_sql = text("""
        INSERT INTO public.idsp_surveillance
        (record_id, year, week, reporting_start_date, reporting_end_date,
         state, district, disease, cases, deaths, outbreak_status, source, source_url)
        VALUES
        (:record_id, :year, :week, :reporting_start_date, :reporting_end_date,
         :state, :district, :disease, :cases, :deaths, :outbreak_status, :source, :source_url)
        ON CONFLICT (record_id) DO NOTHING
    """)
    inserted = 0
    with engine.begin() as conn:
        for live, approval in plans:
            result = conn.execute(insert_sql, live)
            if result.rowcount == 1:
                inserted += 1
                # Preserve a trace that records were explicitly promoted; do not silently overwrite other statuses.
                note = f"Supervisor approval by {approval['approved_by']} at {approval['approved_at_utc']}: {approval['approval_note']}"
                conn.execute(text("""
                    UPDATE public.ncdc_outbreak_staging
                    SET review_status = 'promoted_to_live_surveillance',
                        source_validation_note = COALESCE(source_validation_note, '') || :approval_note
                    WHERE record_id = :rid AND review_status = 'pending_supervisor_review'
                """), {"rid": live["record_id"], "approval_note": "\n" + note})
    print(f"Inserted into live surveillance: {inserted}")
    print("Staging review status updated for inserted rows only.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=PROJECT_ROOT / "data" / "ncdc_week1_approval_manifest.csv", help="explicit record-level approval manifest")
    parser.add_argument("--apply", action="store_true", help="perform live PostgreSQL inserts (default is dry-run)")
    parser.add_argument("--confirm", default=None, help=f"required with --apply: {CONFIRM_TEXT}")
    args = parser.parse_args()
    try:
        return execute(args.manifest, apply=args.apply, confirm=args.confirm)
    except Exception as exc:
        print(f"PROMOTION FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
