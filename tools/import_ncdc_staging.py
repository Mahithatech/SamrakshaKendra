#!/usr/bin/env python3
"""Validate and optionally import source-reviewed NCDC rows into a SEPARATE staging table.

Default behavior is dry-run. Pass --apply to create public.ncdc_outbreak_staging and
insert rows there. This utility never writes to the existing idsp_surveillance table.
Rows remain pending supervisor/manual review after staging.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_COLUMNS = {
    "record_id", "report_year", "report_week", "state", "district", "disease",
    "cases", "deaths", "outbreak_start_date", "reporting_date", "current_status",
    "comments_action_taken", "source_url", "source_index_url", "extracted_at_utc",
    "validation_status", "validation_note",
}

DDL = """
CREATE TABLE IF NOT EXISTS public.ncdc_outbreak_staging (
    record_id TEXT PRIMARY KEY,
    report_year INTEGER NOT NULL,
    report_week INTEGER NOT NULL CHECK (report_week BETWEEN 1 AND 53),
    state TEXT NOT NULL,
    district TEXT NOT NULL,
    disease TEXT NOT NULL,
    cases INTEGER NULL CHECK (cases IS NULL OR cases >= 0),
    deaths INTEGER NULL CHECK (deaths IS NULL OR deaths >= 0),
    outbreak_start_date DATE NULL,
    reporting_date DATE NULL,
    current_status TEXT NULL,
    comments_action_taken TEXT NULL,
    source_url TEXT NOT NULL,
    source_index_url TEXT NOT NULL,
    extracted_at_utc TIMESTAMPTZ NULL,
    source_validation_status TEXT NOT NULL,
    source_validation_note TEXT NULL,
    review_status TEXT NOT NULL DEFAULT 'pending_supervisor_review',
    imported_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

INSERT_SQL = """
INSERT INTO public.ncdc_outbreak_staging (
    record_id, report_year, report_week, state, district, disease, cases, deaths,
    outbreak_start_date, reporting_date, current_status, comments_action_taken,
    source_url, source_index_url, extracted_at_utc, source_validation_status,
    source_validation_note, review_status
) VALUES (
    :record_id, :report_year, :report_week, :state, :district, :disease, :cases, :deaths,
    :outbreak_start_date, :reporting_date, :current_status, :comments_action_taken,
    :source_url, :source_index_url, :extracted_at_utc, :source_validation_status,
    :source_validation_note, 'pending_supervisor_review'
) ON CONFLICT (record_id) DO NOTHING
"""


def _optional_int(value: str, field: str, row_id: str) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        result = int(value)
    except ValueError as exc:
        raise ValueError(f"{row_id}: {field} must be a non-negative integer or blank") from exc
    if result < 0:
        raise ValueError(f"{row_id}: {field} must not be negative")
    return result


def _optional_date(value: str, field: str, row_id: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{row_id}: {field} must be ISO YYYY-MM-DD or blank") from exc


def _optional_datetime(value: str, row_id: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{row_id}: extracted_at_utc is not a valid ISO timestamp") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def load_and_validate(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"Input CSV not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_COLUMNS - columns)
        if missing:
            raise ValueError("CSV is missing required columns: " + ", ".join(missing))
        raw_rows = list(reader)

    prepared: list[dict[str, Any]] = []
    seen: set[str] = set()
    for number, row in enumerate(raw_rows, start=2):
        rid = (row.get("record_id") or "").strip()
        if not rid:
            raise ValueError(f"CSV line {number}: record_id is blank")
        if rid in seen:
            raise ValueError(f"CSV line {number}: duplicate record_id {rid}")
        seen.add(rid)

        state = (row.get("state") or "").strip()
        district = (row.get("district") or "").strip()
        disease = (row.get("disease") or "").strip()
        if not state or not district or not disease:
            raise ValueError(f"{rid}: state, district and disease must be populated before staging")
        if not (row.get("source_url") or "").strip() or not (row.get("source_index_url") or "").strip():
            raise ValueError(f"{rid}: source_url and source_index_url are required")
        try:
            year = int((row.get("report_year") or "").strip())
            week = int((row.get("report_week") or "").strip())
        except ValueError as exc:
            raise ValueError(f"{rid}: report_year and report_week must be integers") from exc
        if year < 2000 or year > 2100:
            raise ValueError(f"{rid}: report_year is outside the allowed sanity range")
        if not 1 <= week <= 53:
            raise ValueError(f"{rid}: report_week must be between 1 and 53")

        prepared.append({
            "record_id": rid,
            "report_year": year,
            "report_week": week,
            "state": state,
            "district": district,
            "disease": disease,
            "cases": _optional_int(row.get("cases", ""), "cases", rid),
            "deaths": _optional_int(row.get("deaths", ""), "deaths", rid),
            "outbreak_start_date": _optional_date(row.get("outbreak_start_date", ""), "outbreak_start_date", rid),
            "reporting_date": _optional_date(row.get("reporting_date", ""), "reporting_date", rid),
            "current_status": (row.get("current_status") or "").strip() or None,
            "comments_action_taken": (row.get("comments_action_taken") or "").strip() or None,
            "source_url": (row.get("source_url") or "").strip(),
            "source_index_url": (row.get("source_index_url") or "").strip(),
            "extracted_at_utc": _optional_datetime(row.get("extracted_at_utc", ""), rid),
            "source_validation_status": (row.get("validation_status") or "").strip() or "candidate",
            "source_validation_note": (row.get("validation_note") or "").strip() or None,
        })
    if not prepared:
        raise ValueError("CSV contains no rows")
    return prepared


def _load_engine(project_root: Path):
    backend_path = str(project_root / "backend")
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    from app.database import engine  # project-specific; loaded only for --apply
    return engine


def import_rows(project_root: Path, rows: list[dict[str, Any]]) -> tuple[int, int]:
    from sqlalchemy import text

    engine = _load_engine(project_root)
    inserted = 0
    skipped_existing = 0
    with engine.begin() as connection:
        connection.execute(text(DDL))
        for row in rows:
            result = connection.execute(text(INSERT_SQL), row)
            if result.rowcount == 1:
                inserted += 1
            else:
                skipped_existing += 1
    return inserted, skipped_existing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", type=Path, help="source-reviewed NCDC staging CSV")
    parser.add_argument("--apply", action="store_true", help="create separate staging table and insert rows; default is dry-run")
    args = parser.parse_args()

    try:
        rows = load_and_validate(args.input_csv)
    except Exception as exc:
        print(f"VALIDATION FAILED: {exc}", file=sys.stderr)
        return 2

    print(f"CSV validation passed: {len(rows)} rows")
    print("Target table: public.ncdc_outbreak_staging")
    print("Existing table idsp_surveillance: will NOT be modified")
    print("Review status assigned: pending_supervisor_review")
    print("Blank numeric/date fields remain NULL; they will not be converted to zero")

    if not args.apply:
        print("DRY RUN ONLY. No database connection or write was made.")
        print("When the source rows have been reviewed and you are ready, rerun with --apply.")
        return 0

    project_root = Path(__file__).resolve().parents[1]
    try:
        inserted, skipped = import_rows(project_root, rows)
    except Exception as exc:
        print(f"IMPORT FAILED (transaction rolled back): {exc}", file=sys.stderr)
        return 3

    print("Staging import committed.")
    print(f"Inserted: {inserted}")
    print(f"Skipped existing record_id values: {skipped}")
    print("All imported rows remain pending_supervisor_review.")
    print("The main IDSP surveillance table was not modified.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
