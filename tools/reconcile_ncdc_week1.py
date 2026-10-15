#!/usr/bin/env python3
"""Create a source-reviewed staging CSV for NCDC 2026 Week 1.

The source PDF's main outbreak table and its "previous weeks reported late" table
have different schemas. The previous extractor also misaligned a few cells and
split wrapped words. This script applies a manually transcribed core-field review
against the official NCDC Week 1 PDF. It creates a NEW review file and summary;
it never edits the original CSV or writes to PostgreSQL.

Narrative comments are deliberately blank in this output because they need a
separate review/re-extraction pass. For the late-reported table, reporting_date is
blank because that table does not publish a reporting-date column.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SOURCE_INDEX_URL = "https://ncdc.mohfw.gov.in/includes/WeeklyOutbreaks.php"
SOURCE_PDF_URL = "https://ncdc.mohfw.gov.in/uploads/weekly_outbreaks/2026/week1_1788853592.pdf"

# Core fields checked against the official NCDC weekly report's event tables.
# Dates are ISO-8601 (YYYY-MM-DD). The final two entries are in the separate
# "Disease outbreaks of previous weeks reported late" table, which has no
# reporting-date column.
VERIFIED: dict[str, dict[str, Any]] = {
    "AP/SRI/2026/01/01": dict(state="Andhra Pradesh", district="Sri Sathya Sai", disease="Suspected Food Poisoning", cases=15, deaths=0, outbreak_start_date="2026-01-01", reporting_date="2026-01-02", current_status="Under Surveillance"),
    "AP/SRI/2026/01/02": dict(state="Andhra Pradesh", district="Sri Sathya Sai", disease="Suspected Food Poisoning", cases=17, deaths=0, outbreak_start_date="2026-01-01", reporting_date="2026-01-02", current_status="Under Surveillance"),
    "AS/JOR/2026/01/03": dict(state="Assam", district="Jorhat", disease="Suspected Food Poisoning", cases=13, deaths=0, outbreak_start_date="2026-01-04", reporting_date="2026-01-04", current_status="Under Surveillance"),
    "CT/BAL/2026/01/04": dict(state="Chhattisgarh", district="Balod", disease="Chickenpox", cases=8, deaths=0, outbreak_start_date="2026-01-01", reporting_date="2026-01-01", current_status="Under Surveillance"),
    "GJ/ANA/2026/01/05": dict(state="Gujarat", district="Anand", disease="Suspected Food Poisoning", cases=11, deaths=0, outbreak_start_date="2026-01-01", reporting_date="2026-01-01", current_status="Under Control"),
    "GJ/ARV/2026/01/06": dict(state="Gujarat", district="Arvalli", disease="Crimean-Congo Haemorrhagic Fever", cases=1, deaths=1, outbreak_start_date="2025-12-30", reporting_date="2026-01-01", current_status="Under Surveillance"),
    "GJ/BAN/2026/01/07": dict(state="Gujarat", district="Banas Kantha", disease="Measles", cases=37, deaths=0, outbreak_start_date="2025-12-29", reporting_date="2025-12-29", current_status="Under Surveillance"),
    "GJ/GAN/2026/01/08": dict(state="Gujarat", district="Gandhinagar", disease="Acute Diarrhoeal Disease", cases=29, deaths=0, outbreak_start_date="2026-01-02", reporting_date="2026-01-04", current_status="Under Surveillance"),
    "GJ/GAN/2026/01/09": dict(state="Gujarat", district="Gandhinagar", disease="Suspected Typhoid", cases=189, deaths=0, outbreak_start_date="2025-12-29", reporting_date="2025-12-31", current_status="Under Surveillance"),
    "GJ/NAR/2026/01/10": dict(state="Gujarat", district="Narmada", disease="Acute Diarrhoeal Disease", cases=16, deaths=0, outbreak_start_date="2026-01-03", reporting_date="2026-01-03", current_status="Under Surveillance"),
    "KL/ERN/2026/01/11": dict(state="Kerala", district="Ernakulam", disease="Acute Gastroenteritis", cases=19, deaths=0, outbreak_start_date="2025-12-31", reporting_date="2025-12-31", current_status="Under Surveillance"),
    "KL/ERN/2026/01/12": dict(state="Kerala", district="Ernakulam", disease="Acute Gastroenteritis", cases=28, deaths=3, outbreak_start_date="2025-12-30", reporting_date="2025-12-31", current_status="Under Surveillance"),
    "KL/PAL/2026/01/13": dict(state="Kerala", district="Palakkad", disease="Acute Gastroenteritis", cases=11, deaths=0, outbreak_start_date="2025-12-30", reporting_date="2026-01-02", current_status="Under Surveillance"),
    "KL/THR/2026/01/14": dict(state="Kerala", district="Thrissur", disease="Suspected Food Poisoning", cases=44, deaths=0, outbreak_start_date="2026-01-01", reporting_date="2026-01-01", current_status="Under Surveillance"),
    "KL/THR/2026/01/15": dict(state="Kerala", district="Thrissur", disease="Dengue", cases=19, deaths=0, outbreak_start_date="2026-01-01", reporting_date="2026-01-01", current_status="Under Surveillance"),
    "MP/IND/2026/01/16": dict(state="Madhya Pradesh", district="Indore", disease="Acute Diarrhoeal Disease", cases=227, deaths=0, outbreak_start_date="2025-12-29", reporting_date="2025-12-29", current_status="Under Surveillance"),
    "MP/RAJ/2026/01/17": dict(state="Madhya Pradesh", district="Rajgarh", disease="Acute Gastroenteritis", cases=13, deaths=0, outbreak_start_date="2025-12-30", reporting_date="2025-12-30", current_status="Under Surveillance"),
    "MP/UJJ/2026/01/18": dict(state="Madhya Pradesh", district="Ujjain", disease="Fever", cases=11, deaths=0, outbreak_start_date="2025-12-29", reporting_date="2026-01-01", current_status="Under Surveillance"),
    "MH/JAL/2026/01/19": dict(state="Maharashtra", district="Jalgaon", disease="Suspected Food Poisoning", cases=173, deaths=0, outbreak_start_date="2025-12-31", reporting_date="2025-12-31", current_status="Under Surveillance"),
    "MH/PAR/2026/01/20": dict(state="Maharashtra", district="Parbhani", disease="Measles", cases=6, deaths=0, outbreak_start_date="2025-12-31", reporting_date="2026-01-02", current_status="Under Surveillance"),
    "OR/KAL/2026/01/21": dict(state="Odisha", district="Kalahandi", disease="Suspected Food Poisoning", cases=16, deaths=0, outbreak_start_date="2025-12-31", reporting_date="2025-12-31", current_status="Under Control"),
    "OR/KEN/2026/01/22": dict(state="Odisha", district="Kendrapara", disease="Suspected Food Poisoning", cases=17, deaths=0, outbreak_start_date="2026-01-02", reporting_date="2026-01-02", current_status="Under Surveillance"),
    "OR/KHO/2026/01/23": dict(state="Odisha", district="Khordha", disease="Hepatitis A", cases=63, deaths=0, outbreak_start_date="2026-01-04", reporting_date="2026-01-04", current_status="Under Surveillance"),
    "TN/COI/2026/01/24": dict(state="Tamil Nadu", district="Coimbatore", disease="Chickenpox", cases=26, deaths=0, outbreak_start_date="2025-12-31", reporting_date="2025-12-31", current_status="Under Surveillance"),
    "TN/THI/2026/01/25": dict(state="Tamil Nadu", district="Thiruvallur", disease="Acute Diarrhoeal Disease", cases=41, deaths=0, outbreak_start_date="2025-12-26", reporting_date="2025-12-29", current_status="Under Surveillance"),
    "TN/TIR/2026/01/26": dict(state="Tamil Nadu", district="Tiruchirappalli", disease="Suspected Food Poisoning", cases=41, deaths=0, outbreak_start_date="2025-12-31", reporting_date="2025-12-31", current_status="Under Surveillance"),
    "WB/JHA/2026/01/27": dict(state="West Bengal", district="Jhargram", disease="Fever with Rash", cases=90, deaths=0, outbreak_start_date="2025-12-29", reporting_date="2025-12-31", current_status="Under Surveillance"),
    "BH/PUR/2026/01/28": dict(state="Bihar", district="Purbi Champaran", disease="Measles", cases=5, deaths=0, outbreak_start_date="2025-12-03", reporting_date="", current_status="Under Surveillance"),
    "UP/SAM/2026/01/29": dict(state="Uttar Pradesh", district="Sambhal", disease="Measles", cases=5, deaths=0, outbreak_start_date="2025-11-15", reporting_date="", current_status="Under Control"),
}

FIELD_ORDER = [
    "record_id", "report_year", "report_week", "state", "district", "disease",
    "cases", "deaths", "outbreak_start_date", "reporting_date", "current_status",
    "comments_action_taken", "source_url", "source_index_url", "extracted_at_utc",
    "validation_status", "validation_note",
]


def reconcile(input_csv: Path, output_csv: Path, summary_path: Path) -> dict[str, Any]:
    with input_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        source_fields = reader.fieldnames or []
    ids = [str(row.get("record_id", "")).strip() for row in rows]
    missing_ids = sorted(set(VERIFIED) - set(ids))
    unexpected_ids = sorted(set(ids) - set(VERIFIED))
    duplicates = sorted({rid for rid in ids if rid and ids.count(rid) > 1})
    if missing_ids or unexpected_ids or duplicates:
        raise ValueError(
            "Input CSV does not match the reviewed NCDC Week 1 set. "
            f"missing={missing_ids}; unexpected={unexpected_ids}; duplicate={duplicates}"
        )

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    original_by_id = {str(row["record_id"]).strip(): row for row in rows}
    output_rows: list[dict[str, Any]] = []
    for record_id, verified in VERIFIED.items():
        old = original_by_id[record_id]
        row = {field: old.get(field, "") for field in (source_fields or FIELD_ORDER)}
        row.update({
            "record_id": record_id,
            "report_year": 2026,
            "report_week": 1,
            **verified,
            # Narrative cell parsing was inconsistent in the original extraction;
            # leave it blank rather than preserve text in a potentially wrong column.
            "comments_action_taken": "",
            "source_url": SOURCE_PDF_URL,
            "source_index_url": SOURCE_INDEX_URL,
            "extracted_at_utc": now,
            "validation_status": "source_reviewed_core_fields",
            "validation_note": (
                "Core fields manually reconciled to the official NCDC 2026 Week 1 PDF. "
                "Narrative comments intentionally blank pending separate review. "
                + ("Source table is 'previous weeks reported late'; no reporting-date field is published." if record_id in {"BH/PUR/2026/01/28", "UP/SAM/2026/01/29"} else "")
                + " This remains a staging/review file; no database import performed."
            ),
        })
        output_rows.append(row)

    fieldnames = list(dict.fromkeys((source_fields or []) + FIELD_ORDER))
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(output_rows)

    summary = {
        "generated_at_utc": now,
        "source_pdf_url": SOURCE_PDF_URL,
        "source_index_url": SOURCE_INDEX_URL,
        "input_csv": str(input_csv.resolve()),
        "output_csv": str(output_csv.resolve()),
        "source_reviewed_core_rows": len(output_rows),
        "unmatched_or_duplicate_record_ids": False,
        "rows_with_reporting_date_blank_due_source_schema": 2,
        "narrative_comments_included": False,
        "database_modified": False,
        "note": "Core fields were transcribed/reconciled against the official NCDC Week 1 PDF. Keep as staging; obtain supervisor/source review before operational use. The PDF is a weekly outbreak report, not a continuously updating case-level feed.",
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print("NCDC Week 1 core-field reconciliation complete.")
    print(f"Input candidate rows: {len(rows)}")
    print(f"Source-reviewed core rows: {len(output_rows)}")
    print("Narrative comments included: no (left blank pending separate review)")
    print("Database modified: no")
    print(f"CSV: {output_csv.resolve()}")
    print(f"Summary: {summary_path.resolve()}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", type=Path, help="Original week 1 staging CSV")
    parser.add_argument("--output", type=Path, default=Path("data/ncdc_outbreak_week1_source_reviewed.csv"))
    parser.add_argument("--summary", type=Path, default=Path("data/ncdc_outbreak_week1_source_reviewed.summary.json"))
    args = parser.parse_args()
    try:
        reconcile(args.input_csv, args.output, args.summary)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
