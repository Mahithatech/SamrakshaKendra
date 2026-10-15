#!/usr/bin/env python3
"""Download selected official NCDC weekly outbreak PDFs and create a review-only CSV.

This tool DOES NOT modify PostgreSQL. Every extracted row is a staging candidate for
human review because PDF table extraction can be imperfect and outbreak-event data
has different semantics from the existing weekly surveillance time-series table.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import pdfplumber
import requests

INDEX_URL = "https://ncdc.mohfw.gov.in/includes/WeeklyOutbreaks.php"
BASE_URL = "https://ncdc.mohfw.gov.in/"
USER_AGENT = "SamrakshaKendra-NCDCPreview/1.0 (academic public-health research; contact via repository)"
MAX_PDF_BYTES = 25 * 1024 * 1024

# NCDC reports commonly use IDs such as AP/SRI/2026/01/01.
RECORD_ID_RE = re.compile(r"^[A-Z0-9-]+/[A-Z0-9.-]+/\d{4}/\d{1,2}/\d{1,4}$", re.I)
PDF_PATH_RE = re.compile(
    r"(?:^|/)uploads/weekly_outbreaks/(?P<year>20\d{2})/week(?P<week>\d{1,2})_[^\s?#]+\.pdf(?:$|[?#])",
    re.I,
)
DATE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*-\s*(\d{1,2})\s*-\s*(\d{4})(?!\d)")

CSV_FIELDS = [
    "record_id",
    "report_year",
    "report_week",
    "state",
    "district",
    "disease",
    "cases",
    "deaths",
    "outbreak_start_date",
    "reporting_date",
    "current_status",
    "comments_action_taken",
    "source_url",
    "source_index_url",
    "extracted_at_utc",
    "validation_status",
    "validation_note",
]


def clean_text(value: Any) -> str:
    """Normalize PDF/HTML cell text while preserving unknown values as blank."""
    if value is None:
        return ""
    text = html.unescape(str(value)).replace("\xa0", " ")
    text = re.sub(r"[\r\n\t]+", " ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def parse_optional_integer(value: Any) -> int | None:
    """Return an integer only when the entire cleaned cell is a valid count."""
    text = clean_text(value).replace(",", "")
    if not text or text.lower() in {"-", "—", "na", "n/a", "not available", "nil", "unknown"}:
        return None
    if re.fullmatch(r"\d+", text):
        return int(text)
    return None


def parse_date(value: Any) -> str:
    """Convert DD-MM-YYYY (including line-wrapped PDF values) to ISO date or blank."""
    text = clean_text(value)
    match = DATE_RE.search(text)
    if not match:
        return ""
    day, month, year = map(int, match.groups())
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return ""


class AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.hrefs.append(href.strip())


def parse_archive_links(page_html: str, index_url: str = INDEX_URL) -> list[dict[str, Any]]:
    """Extract direct PDF links and year/week from the official NCDC archive HTML."""
    parser = AnchorParser()
    parser.feed(page_html)
    found: dict[str, dict[str, Any]] = {}
    for raw_href in parser.hrefs:
        absolute = urljoin(index_url, html.unescape(raw_href))
        parsed = urlparse(absolute)
        path_query = parsed.path + (("?" + parsed.query) if parsed.query else "")
        match = PDF_PATH_RE.search(path_query)
        if not match:
            continue
        year, week = int(match.group("year")), int(match.group("week"))
        # Only accept the official NCDC host; do not follow arbitrary links from source HTML.
        if parsed.scheme != "https" or parsed.hostname not in {"ncdc.mohfw.gov.in", "www.ncdc.mohfw.gov.in"}:
            continue
        found[absolute] = {"year": year, "week": week, "url": absolute}
    return sorted(found.values(), key=lambda item: (item["year"], item["week"], item["url"]))


def _looks_like_record_id(value: Any) -> bool:
    return bool(RECORD_ID_RE.fullmatch(clean_text(value)))


def row_to_candidate(
    row: list[Any] | tuple[Any, ...],
    *,
    year: int,
    week: int,
    source_url: str,
    extracted_at_utc: str,
    source_index_url: str = INDEX_URL,
) -> dict[str, Any] | None:
    """Map the 10-column NCDC outbreak-event table into a review staging row.

    Column semantics follow the report's table header: ID, state, district, disease,
    cases, deaths, outbreak start date, reporting date, current status, comments.
    No missing number is converted into zero.
    """
    if len(row) < 10 or not _looks_like_record_id(row[0]):
        return None
    record_id = clean_text(row[0])
    state = clean_text(row[1])
    district = clean_text(row[2])
    disease = clean_text(row[3])
    cases = parse_optional_integer(row[4])
    deaths = parse_optional_integer(row[5])
    start_date = parse_date(row[6])
    reporting_date = parse_date(row[7])
    status = clean_text(row[8])
    comments = clean_text(row[9])

    missing = [name for name, value in (("state", state), ("district", district), ("disease", disease)) if not value]
    if cases is None:
        missing.append("cases")
    # Death count is allowed to stay blank if the source cell is unavailable; do not assume zero.
    validation_status = "candidate" if not missing else "needs_review"
    note = "Table row extracted; human review required before database import."
    if missing:
        note += " Missing/unparsed fields: " + ", ".join(missing) + "."
    return {
        "record_id": record_id,
        "report_year": year,
        "report_week": week,
        "state": state,
        "district": district,
        "disease": disease,
        "cases": "" if cases is None else cases,
        "deaths": "" if deaths is None else deaths,
        "outbreak_start_date": start_date,
        "reporting_date": reporting_date,
        "current_status": status,
        "comments_action_taken": comments,
        "source_url": source_url,
        "source_index_url": source_index_url,
        "extracted_at_utc": extracted_at_utc,
        "validation_status": validation_status,
        "validation_note": note,
    }


def extract_candidates_from_pdf(
    pdf_bytes: bytes,
    *,
    year: int,
    week: int,
    source_url: str,
    source_index_url: str = INDEX_URL,
    debug: bool = False,
) -> list[dict[str, Any]]:
    """Extract NCDC table records using visible table grid lines in the PDF."""
    if not pdf_bytes.startswith(b"%PDF"):
        raise ValueError("Downloaded content does not start with a PDF signature.")
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise ValueError(f"PDF exceeds the safety limit of {MAX_PDF_BYTES // (1024 * 1024)} MB.")

    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    table_settings = {
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
        "intersection_tolerance": 5,
        "snap_tolerance": 3,
        "join_tolerance": 3,
        "edge_min_length": 3,
    }
    with pdfplumber.open(__import__("io").BytesIO(pdf_bytes)) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            try:
                tables = page.extract_tables(table_settings=table_settings) or []
            except Exception as exc:  # one malformed page shouldn't conceal all others
                errors.append(f"page {page_no}: table extraction failed ({type(exc).__name__})")
                continue
            if debug:
                print(f"page {page_no}: {len(tables)} table(s)")
            for table in tables:
                for row in table or []:
                    if not row or not _looks_like_record_id(row[0] if row else ""):
                        continue
                    candidate = row_to_candidate(
                        row,
                        year=year,
                        week=week,
                        source_url=source_url,
                        extracted_at_utc=stamp,
                        source_index_url=source_index_url,
                    )
                    if candidate:
                        records.append(candidate)
    # Keep the first occurrence; unique ID is the primary key within the source archive.
    unique: dict[str, dict[str, Any]] = {}
    for record in records:
        unique.setdefault(record["record_id"], record)
    if not unique and errors and debug:
        print("Extraction diagnostics: " + "; ".join(errors), file=sys.stderr)
    return list(unique.values())


def fetch_bytes(session: requests.Session, url: str, timeout: int = 45) -> bytes:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    content = response.content
    if len(content) > MAX_PDF_BYTES:
        raise ValueError(f"Response from {url} exceeds the {MAX_PDF_BYTES // (1024 * 1024)} MB safety limit.")
    return content


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf,*/*;q=0.8"})
    return session


def run(args: argparse.Namespace) -> int:
    session = build_session()
    print(f"Fetching official archive: {INDEX_URL}")
    try:
        index_response = session.get(INDEX_URL, timeout=45)
        index_response.raise_for_status()
        links = parse_archive_links(index_response.text, INDEX_URL)
    except Exception as exc:
        print(f"ERROR: Could not fetch/parse NCDC archive ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 2

    years = set(args.year)
    selected = [item for item in links if item["year"] in years]
    if args.week:
        weeks = set(args.week)
        selected = [item for item in selected if item["week"] in weeks]
    selected.sort(key=lambda item: (item["year"], item["week"]), reverse=True)
    if args.limit and not args.week:
        selected = selected[: args.limit]
    if args.max_reports:
        selected = selected[: args.max_reports]

    print(f"Archive PDF links found: {len(links)}; selected reports: {len(selected)}")
    if not selected:
        print("No PDF links matched the requested year/week. Check the year/week arguments or archive HTML.", file=sys.stderr)
        return 3

    all_rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    downloaded_count = 0
    for link in selected:
        print(f"Downloading {link['year']} week {link['week']}: {link['url']}")
        try:
            pdf_bytes = fetch_bytes(session, link["url"])
            downloaded_count += 1
            rows = extract_candidates_from_pdf(
                pdf_bytes,
                year=link["year"],
                week=link["week"],
                source_url=link["url"],
                source_index_url=INDEX_URL,
                debug=args.debug,
            )
            print(f"  candidate rows extracted: {len(rows)}")
            all_rows.extend(rows)
            if not rows:
                failures.append({"url": link["url"], "error": "PDF downloaded but no table rows matching the expected NCDC record-ID format were extracted."})
        except Exception as exc:
            failures.append({"url": link["url"], "error": f"{type(exc).__name__}: {exc}"})
            print(f"  WARNING: {type(exc).__name__}: {exc}", file=sys.stderr)

    # Cross-report duplicate guard.
    deduped: dict[str, dict[str, Any]] = {}
    for row in all_rows:
        deduped.setdefault(row["record_id"], row)
    rows = sorted(deduped.values(), key=lambda row: (int(row["report_year"]), int(row["report_week"]), row["record_id"]))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_index_url": INDEX_URL,
        "requested_years": sorted(years),
        "requested_weeks": sorted(set(args.week)) if args.week else None,
        "reports_selected": len(selected),
        "reports_downloaded": downloaded_count,
        "candidate_rows_extracted_before_dedupe": len(all_rows),
        "unique_candidate_rows": len(rows),
        "candidate_rows_needing_review": sum(1 for row in rows if row["validation_status"] == "needs_review"),
        "failures": failures,
        "csv_output": str(output.resolve()),
        "database_modified": False,
        "warning": "Staging only. Verify each row against its source PDF before any database import. Blank numeric values are unknown, not zero.",
    }
    summary_path = output.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nPreview extraction complete.")
    print(f"Reports downloaded: {downloaded_count}/{len(selected)}")
    print(f"Unique candidate rows: {len(rows)}")
    print(f"Review rows: {summary['candidate_rows_needing_review']}")
    print(f"CSV: {output.resolve()}")
    print(f"Summary: {summary_path.resolve()}")
    print("IMPORTANT: PostgreSQL was not modified. This CSV is a review/staging artifact only.")
    return 0 if downloaded_count > 0 else 4


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, action="append", required=True, help="Report year; repeat for multiple years.")
    parser.add_argument("--week", type=int, action="append", help="Specific week number; repeat to select more than one week.")
    parser.add_argument("--limit", type=int, default=3, help="When no --week is supplied, download this many latest reports from selected year(s) (default: 3).")
    parser.add_argument("--max-reports", type=int, default=10, help="Safety cap on selected PDFs (default: 10).")
    parser.add_argument("--output", default="data/ncdc_outbreak_staging.csv", help="Review CSV output path (default: data/ncdc_outbreak_staging.csv).")
    parser.add_argument("--debug", action="store_true", help="Print table count per PDF page.")
    args = parser.parse_args(argv)
    if any(year < 2009 or year > 2100 for year in args.year):
        parser.error("--year values must be between 2009 and 2100")
    if args.week and any(week < 1 or week > 53 for week in args.week):
        parser.error("--week values must be between 1 and 53")
    if args.limit < 1 or args.max_reports < 1:
        parser.error("--limit and --max-reports must be positive")
    return args


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
