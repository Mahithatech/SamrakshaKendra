"""Scheduled public-source ingestion, staged validation, anomaly screening and event delivery.

NCDC PDF rows are quarantined as candidates. Each candidate retains its original
source URL, SHA-256, report period, PDF page and (when detected) source record ID.
No candidate is automatically promoted into official surveillance data.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import threading
import uuid
from datetime import date, datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sqlalchemy import text
from sqlalchemy.orm import Session

from .database import SessionLocal, engine, direct_engine
from .models import IDSPSurveillance
from .synthetic_ingestion import ensure_synthetic_schema, generate_synthetic_records
from .anomaly_service import detect_case_anomalies
from .websocket_manager import manager

logger = logging.getLogger("samraksha.ingestion")

NCDC_ALLOWED_HOSTS = {"ncdc.mohfw.gov.in", "www.ncdc.mohfw.gov.in"}
WHO_ALLOWED_HOSTS = {"www.who.int", "who.int"}
MAX_PDF_BYTES = int(os.getenv("SK_INGESTION_MAX_PDF_BYTES", "20971520"))
MAX_PDFS_PER_CYCLE = int(os.getenv("SK_INGESTION_MAX_PDFS_PER_CYCLE", "2"))
DOWNLOAD_TIMEOUT_SECONDS = int(os.getenv("SK_INGESTION_TIMEOUT_SECONDS", "25"))
MAX_PDF_PAGES = int(os.getenv("SK_INGESTION_MAX_PDF_PAGES", "80"))
MAX_EXTRACTED_CHARS = int(os.getenv("SK_INGESTION_MAX_EXTRACTED_CHARS", "1500000"))
DEFAULT_INTERVAL_SECONDS = int(os.getenv("SK_INGESTION_INTERVAL_SECONDS", "900"))
SYNTHETIC_GENERATION_ENABLED = os.getenv(
    "SK_SYNTHETIC_GENERATION_ENABLED", "false"
).strip().lower() in {"1", "true", "yes", "on"}

_SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS public.sk_ingestion_runs (
        run_id TEXT PRIMARY KEY, status TEXT NOT NULL, started_at TIMESTAMPTZ NOT NULL,
        finished_at TIMESTAMPTZ NULL, who_seen INTEGER NOT NULL DEFAULT 0,
        ncdc_seen INTEGER NOT NULL DEFAULT 0, pdf_attempted INTEGER NOT NULL DEFAULT 0,
        pdf_extracted INTEGER NOT NULL DEFAULT 0, candidates_added INTEGER NOT NULL DEFAULT 0,
        candidates_flagged INTEGER NOT NULL DEFAULT 0, anomalies_found INTEGER NOT NULL DEFAULT 0,
        events_created INTEGER NOT NULL DEFAULT 0, details JSONB NOT NULL DEFAULT '{}'::jsonb,
        error_summary TEXT NULL)""",
    """CREATE TABLE IF NOT EXISTS public.sk_source_documents (
        source_url TEXT PRIMARY KEY, source_code TEXT NOT NULL, title TEXT NOT NULL,
        publication_date TIMESTAMPTZ NULL, report_year INTEGER NULL, report_week INTEGER NULL,
        source_index_url TEXT NULL, source_sha256 TEXT NULL, content_sha256 TEXT NULL,
        byte_size BIGINT NULL, page_count INTEGER NULL, extracted_characters INTEGER NULL,
        text_excerpt TEXT NULL, extraction_status TEXT NOT NULL DEFAULT 'metadata_only',
        validation_status TEXT NOT NULL DEFAULT 'not_applicable', last_error TEXT NULL,
        first_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_attempt_at TIMESTAMPTZ NULL, last_success_at TIMESTAMPTZ NULL)""",
    """CREATE TABLE IF NOT EXISTS public.sk_ingestion_candidates (
        candidate_id TEXT PRIMARY KEY, source_url TEXT NOT NULL, source_sha256 TEXT NOT NULL,
        report_year INTEGER NULL, report_week INTEGER NULL, state TEXT NULL, district TEXT NULL,
        disease TEXT NULL, reporting_start_date DATE NULL, reporting_end_date DATE NULL,
        cases INTEGER NULL, deaths INTEGER NULL, raw_excerpt TEXT NOT NULL,
        validation_status TEXT NOT NULL, validation_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
        review_status TEXT NOT NULL DEFAULT 'pending_supervisor_review',
        reviewed_by TEXT NULL, reviewed_at TIMESTAMPTZ NULL, reviewer_note TEXT NULL,
        promoted_record_id TEXT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT sk_candidate_cases_nonnegative CHECK (cases IS NULL OR cases >= 0),
        CONSTRAINT sk_candidate_deaths_nonnegative CHECK (deaths IS NULL OR deaths >= 0),
        CONSTRAINT sk_candidate_week_range CHECK (report_week IS NULL OR report_week BETWEEN 1 AND 53))""",
    # Additive migrations: existing candidate/review rows are retained unchanged.
    "ALTER TABLE public.sk_ingestion_candidates ADD COLUMN IF NOT EXISTS reporting_start_date DATE NULL",
    "ALTER TABLE public.sk_ingestion_candidates ADD COLUMN IF NOT EXISTS reporting_end_date DATE NULL",
    "ALTER TABLE public.sk_ingestion_candidates ADD COLUMN IF NOT EXISTS source_page INTEGER NULL",
    "ALTER TABLE public.sk_ingestion_candidates ADD COLUMN IF NOT EXISTS source_record_id TEXT NULL",
    "CREATE INDEX IF NOT EXISTS ix_sk_candidates_review_status ON public.sk_ingestion_candidates (review_status, created_at DESC)",
    """CREATE TABLE IF NOT EXISTS public.sk_pipeline_events (
        event_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, event_type TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL, payload JSONB NOT NULL, broadcast_at TIMESTAMPTZ NULL)""",
    "CREATE INDEX IF NOT EXISTS ix_sk_events_created_at ON public.sk_pipeline_events (created_at DESC)",
    """CREATE TABLE IF NOT EXISTS public.sk_candidate_audit (
        audit_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, action TEXT NOT NULL,
        actor TEXT NOT NULL, action_at TIMESTAMPTZ NOT NULL, note TEXT NULL,
        details JSONB NOT NULL DEFAULT '{}'::jsonb)""",
    "CREATE INDEX IF NOT EXISTS ix_sk_candidate_audit_candidate ON public.sk_candidate_audit (candidate_id, action_at DESC)",
]
_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False
_WORKER_TASK: asyncio.Task | None = None
_STOP_EVENT: asyncio.Event | None = None

def ensure_pipeline_schema() -> None:
    """Create pipeline tables and safely apply missing columns."""
    global _SCHEMA_READY

    with _SCHEMA_LOCK:
        try:
            with engine.begin() as conn:
                for statement in _SCHEMA_STATEMENTS:
                    conn.execute(text(statement))

            _SCHEMA_READY = True
            logger.info("Ingestion pipeline schema and migrations verified.")

        except Exception:
            _SCHEMA_READY = False
            logger.exception("Failed to initialize ingestion pipeline schema.")
            raise
def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def is_allowed_source_url(url: str, source_code: str | None = None) -> bool:
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return False
    host = parsed.hostname.lower().rstrip(".")
    if source_code == "NCDC":
        return host in NCDC_ALLOWED_HOSTS
    if source_code == "WHO":
        return host in WHO_ALLOWED_HOSTS
    return host in (NCDC_ALLOWED_HOSTS | WHO_ALLOWED_HOSTS)


def source_fingerprint(source_code: str, url: str) -> str:
    return hashlib.sha256(f"{source_code.strip().upper()}\n{url.strip()}".encode()).hexdigest()


def content_fingerprint(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def parse_report_period(url: str, title: str = "") -> tuple[int | None, int | None]:
    joined = f"{url} {title}"
    patterns = (
        r"/weekly_outbreaks/(20\d{2})/week[_ -]?(\d{1,2})(?:[_\-.]|\b)",
        r"\b(20\d{2})\D{0,20}(?:week\s*|wk\s*)(\d{1,2})\b",
    )
    match = next((m for p in patterns if (m := re.search(p, joined, re.I))), None)
    if not match:
        return None, None
    year, week = int(match.group(1)), int(match.group(2))
    return (year, week) if 2000 <= year <= 2100 and 1 <= week <= 53 else (None, None)


def parse_count(value: str | None) -> int | None:
    value = (value or "").strip().replace(",", "")
    if not value or value.lower() in {"-", "—", "na", "n/a", "not available", "unknown", "nil"}:
        return None
    if not re.fullmatch(r"\d{1,8}", value):
        raise ValueError("count must be a non-negative whole number or blank")
    result = int(value)
    if result > 10_000_000:
        raise ValueError("count exceeds sanity limit")
    return result


def validate_candidate(candidate: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    year, week = candidate.get("report_year"), candidate.get("report_week")
    if not isinstance(year, int) or not 2000 <= year <= 2100:
        errors.append("report_year_missing_or_out_of_range")
    if not isinstance(week, int) or not 1 <= week <= 53:
        errors.append("report_week_missing_or_out_of_range")
    for field in ("state", "district", "disease"):
        value = candidate.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field}_missing")
        elif len(value.strip()) > 180:
            errors.append(f"{field}_too_long")
    for field in ("cases", "deaths"):
        value = candidate.get(field)
        if value is not None:
            try:
                if int(value) < 0:
                    errors.append(f"{field}_negative")
            except (TypeError, ValueError):
                errors.append(f"{field}_not_integer")
    if candidate.get("cases") is None:
        errors.append("cases_unknown_requires_manual_review")
    if not is_allowed_source_url(str(candidate.get("source_url") or ""), "NCDC"):
        errors.append("source_url_not_allowlisted_https_ncdc")
    start, end = candidate.get("reporting_start_date"), candidate.get("reporting_end_date")
    if not start or not end:
        errors.append("reporting_dates_unverified")
    else:
        try:
            start = date.fromisoformat(str(start)) if not isinstance(start, date) else start
            end = date.fromisoformat(str(end)) if not isinstance(end, date) else end
            if start > end:
                errors.append("reporting_start_after_end")
            elif (end - start).days > 14:
                errors.append("reporting_period_exceeds_15_days")
        except (TypeError, ValueError):
            errors.append("reporting_dates_invalid")
    # A source page is mandatory for traceability.  Do not call int() blindly:
    # malformed values such as None, "page 2", 0, -1 or 1.5 must be rejected
    # as validation errors rather than crashing the entire PDF ingestion cycle.
    raw_source_page = candidate.get("source_page")
    valid_source_page = False
    if isinstance(raw_source_page, int) and not isinstance(raw_source_page, bool):
        valid_source_page = raw_source_page >= 1
    elif isinstance(raw_source_page, str):
        page_text = raw_source_page.strip()
        valid_source_page = bool(re.fullmatch(r"[1-9]\d*", page_text))

    if not valid_source_page:
        errors.append("source_page_missing")
    return errors


def _date_from_text(value: str) -> str | None:
    """Parse NCDC dates in DD-MM-YY, DD/MM/YY, DD-MM-YYYY or DD/MM/YYYY form."""
    match = re.search(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b", value or "")
    if not match:
        return None
    raw = match.group(1)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y"):
        try:
            parsed = datetime.strptime(raw, fmt).date()
            # NCDC weekly reports use modern dates; interpret two-digit years as 20xx.
            year_token = raw.rsplit("/", 1)[-1].rsplit("-", 1)[-1]
            if len(year_token) == 2 and parsed.year < 2000:
                parsed = parsed.replace(year=parsed.year + 100)
            return parsed.isoformat()
        except ValueError:
            continue
    return None


def parse_candidate_pdf(content: bytes, source_url: str, title: str = "", source_sha256: str = "") -> list[dict[str, Any]]:
    """Extract NCDC rows from actual table cells, with a geometry fallback.

    The PDF has separate narrow Cases and Deaths columns. The old fixed ranges
    overlapped those columns, causing values such as "127 0" to be parsed as a
    single invalid count. The old row window also began at the ID word's top,
    which dropped state/district words printed above the vertically-centred ID.
    """
    if not is_allowed_source_url(source_url, "NCDC"):
        return []
    if not content.startswith(b"%PDF-") or len(content) > MAX_PDF_BYTES:
        raise ValueError("Invalid or oversized PDF")
    try:
        import io
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("pdfplumber is not installed; install backend requirements") from exc

    year, week = parse_report_period(source_url, title)
    record_re = re.compile(r"^[A-Z]{2}/[A-Z]{2,4}/\d{4}/\d+/\d+$")
    candidates_by_identity: dict[str, dict[str, Any]] = {}

    def clean_cell(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()

    def header_indexes(header: list[Any]) -> dict[str, int]:
        normalized = [re.sub(r"[^a-z]", "", clean_cell(v).lower()) for v in header]
        indexes: dict[str, int] = {}
        for index, value in enumerate(normalized):
            if "unique" in value and "id" in value:
                indexes.setdefault("record", index)
            elif "state" in value or value.endswith("stateut"):
                indexes.setdefault("state", index)
            elif "district" in value:
                indexes.setdefault("district", index)
            elif "disease" in value or "illness" in value:
                indexes.setdefault("disease", index)
            elif "cases" in value and "death" not in value:
                indexes.setdefault("cases", index)
            elif "deaths" in value:
                indexes.setdefault("deaths", index)
            elif "date" in value and ("start" in value or "outbreak" in value):
                indexes.setdefault("start", index)
            elif "reporting" in value and "date" in value:
                indexes.setdefault("end", index)
        # NCDC continuation pages often omit the header row. Their standard
        # table order is ID, State, District, Disease, Cases, Deaths, Start date.
        defaults = {"record": 0, "state": 1, "district": 2, "disease": 3,
                    "cases": 4, "deaths": 5, "start": 6, "end": 7}
        for key, value in defaults.items():
            indexes.setdefault(key, value)
        return indexes

    def make_candidate(record_id: str, state: str, district: str, disease: str,
                       cases_text: str, deaths_text: str, start_text: str,
                       end_text: str, excerpt: str, page_number: int,
                       extraction_method: str) -> dict[str, Any]:
        try:
            cases = parse_count(cases_text)
        except ValueError:
            cases = None
        try:
            deaths = parse_count(deaths_text)
        except ValueError:
            deaths = None

        state = clean_cell(state)
        district = clean_cell(district)
        disease = clean_cell(disease)
        disease = re.sub(r"\bGastroente\s+ritis\b", "Gastroenteritis", disease, flags=re.I)
        candidate = {
            "source_url": source_url,
            "source_sha256": source_sha256,
            "report_year": year,
            "report_week": week,
            "source_page": page_number,
            "source_record_id": record_id,
            "state": state[:180] or None,
            "district": district[:180] or None,
            "disease": disease[:180] or None,
            "cases": cases,
            "deaths": deaths,
            "reporting_start_date": _date_from_text(start_text),
            "reporting_end_date": _date_from_text(end_text),
            "raw_excerpt": clean_cell(excerpt)[:1000] or record_id,
        }
        errors = validate_candidate(candidate)
        errors.append(f"{extraction_method}_requires_supervisor_review")
        candidate["validation_errors"] = sorted(set(errors))
        candidate["validation_status"] = "needs_review"
        identity = "|".join(str(candidate.get(k) if candidate.get(k) is not None else "") for k in (
            "source_url", "source_sha256", "source_page", "source_record_id",
            "state", "district", "disease", "cases", "deaths",
        ))
        candidate["candidate_id"] = hashlib.sha256(identity.casefold().encode()).hexdigest()
        return candidate

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page_number, page in enumerate(pdf.pages[:MAX_PDF_PAGES], start=1):
            page_candidates: dict[str, dict[str, Any]] = {}

            # Preferred path: use the PDF's drawn table borders, not guessed x
            # coordinates. Header labels identify columns even when page 9 has
            # a different layout from the current-week table.
            try:
                tables = page.extract_tables(table_settings={
                    "vertical_strategy": "lines",
                    "horizontal_strategy": "lines",
                    "snap_tolerance": 4,
                    "join_tolerance": 4,
                    "intersection_tolerance": 5,
                    "edge_min_length": 15,
                }) or []
            except (TypeError, AttributeError):
                tables = []
            except Exception:
                logger.debug("NCDC table-cell extraction failed on PDF page %s", page_number, exc_info=True)
                tables = []

            for table in tables:
                if not table:
                    continue
                header = None
                for possible_header in table[:5]:
                    joined = " ".join(clean_cell(cell) for cell in (possible_header or []))
                    if "unique" in joined.lower() and "district" in joined.lower():
                        header = possible_header
                        break
                indexes = header_indexes(header or [])

                for row in table:
                    if not row:
                        continue
                    cells = [clean_cell(cell) for cell in row]
                    record_id = next((re.sub(r"\s+", "", cell) for cell in cells
                                      if record_re.fullmatch(re.sub(r"\s+", "", cell))), None)
                    if not record_id:
                        continue

                    def cell(key: str) -> str:
                        index = indexes.get(key)
                        return cells[index] if index is not None and index < len(cells) else ""

                    excerpt = " | ".join(value for value in cells if value)

                    values = [
                        cell("state"), cell("district"), cell("disease"),
                        cell("cases"), cell("deaths"), cell("start"), cell("end")
                    ]

                    # Recover shifted columns only when the compact row
                    # contains a complete, recognizable outbreak structure.
                    record_index = next(
                        (i for i, value in enumerate(cells)
                         if re.sub(r"\s+", "", value) == record_id),
                        None,
                    )

                    if record_index is not None:
                        compact = [
                            value for value in cells[record_index + 1:]
                            if value.strip()
                        ]

                        if len(compact) >= 7:
                            proposed = compact[:7]

                            try:
                                proposed_cases = parse_count(proposed[3])
                                proposed_deaths = parse_count(proposed[4])
                                proposed_start = _date_from_text(proposed[5])
                                proposed_end = _date_from_text(proposed[6])

                                valid_structure = (
                                    all(re.search(r"[A-Za-z]", v)
                                        for v in proposed[:3])
                                    and proposed_cases is not None
                                    and proposed_deaths is not None
                                    and 0 <= proposed_deaths <= proposed_cases
                                    and proposed_start is not None
                                    and proposed_end is not None
                                    and proposed_start <= proposed_end
                                    and (datetime.fromisoformat(proposed_end) - datetime.fromisoformat(proposed_start)).days <= 14
                                )

                                original_incomplete = (
                                    not all(values[:3])
                                    or not values[3]
                                    or not values[4]
                                    or not _date_from_text(values[5])
                                    or not _date_from_text(values[6])
                                )

                                if valid_structure and original_incomplete:
                                    values = proposed

                            except (ValueError, TypeError):
                                pass

                    candidate = make_candidate(
                        record_id, *values,
                        excerpt, page_number, "table_cell_extraction",
                    )
                    page_candidates[record_id] = candidate

            # Fallback for PDF pages where pdfplumber cannot reconstruct the
            # bordered table. Assign words to the closest record-row band so
            # text above/below the vertically-centred ID is not discarded.
            try:
                words = page.extract_words(x_tolerance=2, y_tolerance=3, keep_blank_chars=False)
            except Exception:
                words = []
            if words:
                page_width = float(getattr(page, "width", 0) or max(float(w.get("x1", 0)) for w in words) or 842)
                page_height = float(getattr(page, "height", 0) or max(float(w.get("bottom", w.get("top", 0))) for w in words) or 595)
                markers = sorted(
                    (w for w in words
                     if float(w.get("x0", page_width)) < page_width * 0.16
                     and record_re.fullmatch(re.sub(r"\s+", "", str(w.get("text", "")).strip()))),
                    key=lambda w: float(w.get("top", 0)),
                )
                centres = [float(w.get("top", 0)) + float(w.get("height", 0)) / 2 for w in markers]
                for marker_index, marker in enumerate(markers):
                    record_id = re.sub(r"\s+", "", str(marker.get("text", "")).strip())
                    if record_id in page_candidates:
                        continue
                    centre = centres[marker_index]
                    previous_gap = centre - centres[marker_index - 1] if marker_index else 0
                    next_gap = centres[marker_index + 1] - centre if marker_index + 1 < len(centres) else 0
                    upper = (centres[marker_index - 1] + centre) / 2 if marker_index else max(0, centre - (next_gap / 2 if next_gap else 30))
                    lower = (centre + centres[marker_index + 1]) / 2 if marker_index + 1 < len(centres) else min(page_height, centre + (previous_gap / 2 if previous_gap else 30))
                    row_words = [w for w in words
                                 if upper <= float(w.get("top", 0)) + float(w.get("height", 0)) / 2 < lower]

                    def fraction_col(left: float, right: float) -> str:
                        selected = sorted(
                            (w for w in row_words
                             if left <= float(w.get("x0", -1)) / page_width < right),
                            key=lambda w: (round(float(w.get("top", 0)) / 3), float(w.get("x0", 0))),
                        )
                        return " ".join(str(w.get("text", "")) for w in selected).strip()

                    # Normalized boundaries measured from the NCDC table grid.
                    # Cases and deaths are separate, narrow cells.
                    candidate = make_candidate(
                        record_id,
                        fraction_col(0.160, 0.248),
                        fraction_col(0.248, 0.337),
                        fraction_col(0.337, 0.424),
                        fraction_col(0.424, 0.466),
                        fraction_col(0.466, 0.508),
                        fraction_col(0.508, 0.585),
                        fraction_col(0.585, 0.659),
                        " ".join(str(w.get("text", "")) for w in sorted(row_words, key=lambda w: (float(w.get("top", 0)), float(w.get("x0", 0))))),
                        page_number,
                        "coordinate_extraction",
                    )
                    page_candidates[record_id] = candidate

            for record_id, candidate in page_candidates.items():
                candidates_by_identity[record_id + "|" + str(page_number)] = candidate

    return list(candidates_by_identity.values())


def extract_pdf(content: bytes) -> tuple[str, int]:
    """Return bounded PDF text and total page count (for document-level metadata)."""
    if not content.startswith(b"%PDF-") or len(content) > MAX_PDF_BYTES:
        raise ValueError("Invalid or oversized PDF")
    try:
        import io
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is not installed; install backend requirements") from exc
    reader = PdfReader(io.BytesIO(content), strict=False)
    if reader.is_encrypted and reader.decrypt("") == 0:
        raise ValueError("encrypted PDF cannot be extracted without credentials")
    page_count = len(reader.pages)
    sections: list[str] = []
    total = 0
    for page_no, page in enumerate(reader.pages[:MAX_PDF_PAGES], start=1):
        segment = page.extract_text(extraction_mode="layout") or ""
        remaining = MAX_EXTRACTED_CHARS - total
        if remaining <= 0:
            break
        segment = segment[:remaining]
        if segment:
            sections.append(f"[PDF PAGE {page_no}]\n{segment}")
            total += len(segment)
    return "\n".join(sections), page_count


class _AllowlistedRedirectHandler(HTTPRedirectHandler):
    def __init__(self, source_code: str):
        super().__init__()
        self.source_code = source_code

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_allowed_source_url(newurl, self.source_code):
            raise ValueError(f"blocked redirect outside allowlisted {self.source_code} hosts")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_allowlisted(request: Request, source_code: str):
    return build_opener(_AllowlistedRedirectHandler(source_code)).open(request, timeout=DOWNLOAD_TIMEOUT_SECONDS)


def _fetch_who_publications() -> list[dict[str, Any]]:
    from urllib.parse import urlencode
    from .source_routes import WHO_API_BASE, MAX_UPSTREAM_ITEMS, _normalise_rows
    params = urlencode({"$orderby": "PublicationDateAndTime desc", "$top": str(MAX_UPSTREAM_ITEMS)})
    urls = [f"{WHO_API_BASE}?{params}", WHO_API_BASE]
    last_error = None
    for url in urls:
        try:
            req = Request(url, headers={"Accept": "application/json", "User-Agent": "SamrakshaKendra-ResearchPrototype/1.0"})
            with _open_allowlisted(req, "WHO") as response:
                body = response.read(8 * 1024 * 1024 + 1)
            if len(body) > 8 * 1024 * 1024:
                raise ValueError("WHO feed response exceeded 8 MiB limit")
            rows = _normalise_rows(json.loads(body.decode("utf-8")))
            if rows or url == urls[-1]:
                return rows[:MAX_UPSTREAM_ITEMS]
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"WHO source discovery failed ({type(last_error).__name__ if last_error else 'UnknownError'})")


def _fetch_ncdc_catalogue() -> list[dict[str, Any]]:
    from .india_reports_routes import NCDC_ARCHIVE_URL, _parse_archive_html, _report_title
    req = Request(NCDC_ARCHIVE_URL, headers={"Accept": "text/html,application/xhtml+xml", "User-Agent": "SamrakshaKendra-ResearchPrototype/1.0"})
    with _open_allowlisted(req, "NCDC") as response:
        body = response.read(4 * 1024 * 1024 + 1)
    if len(body) > 4 * 1024 * 1024:
        raise ValueError("NCDC archive page exceeded 4 MiB limit")
    rows = [r for r in _parse_archive_html(body.decode("utf-8", errors="replace"), NCDC_ARCHIVE_URL) if r.get("report_type") == "pdf"]
    if not rows:
        raise RuntimeError("NCDC archive reachable, but no official weekly PDF links were detected")
    for row in rows:
        row["title"] = _report_title(row)
        row["archive_url"] = NCDC_ARCHIVE_URL
        row["source"] = "National Centre for Disease Control (NCDC), Government of India — IDSP weekly outbreak reports"
    rows.sort(key=lambda x: (x.get("year") or 0, x.get("week") or 0, x["title"]), reverse=True)
    return rows


def _download_official_pdf(url: str) -> bytes:
    if not is_allowed_source_url(url, "NCDC"):
        raise ValueError("refusing non-allowlisted NCDC PDF URL")
    req = Request(url, headers={"User-Agent": "SamrakshaKendra-ResearchPrototype/1.0", "Accept": "application/pdf"})
    with _open_allowlisted(req, "NCDC") as response:
        if not is_allowed_source_url(response.geturl(), "NCDC"):
            raise ValueError("NCDC PDF redirected outside allowlisted hosts")
        body = response.read(MAX_PDF_BYTES + 1)
    if len(body) > MAX_PDF_BYTES or not body.startswith(b"%PDF-"):
        raise ValueError("NCDC link did not return a valid PDF within the size limit")
    return body


def _json_param(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _insert_event(fingerprint: str, event_type: str, payload: dict[str, Any]) -> bool:
    event_id = str(payload.get("event_id") or uuid.uuid4())
    payload = {**payload, "event_id": event_id}
    with engine.begin() as conn:
        result = conn.execute(text("""
            INSERT INTO public.sk_pipeline_events (event_id,fingerprint,event_type,created_at,payload)
            VALUES (:id,:fp,:type,:created,CAST(:payload AS JSONB))
            ON CONFLICT (fingerprint) DO NOTHING
        """), {"id": event_id, "fp": fingerprint, "type": event_type, "created": utc_now(), "payload": _json_param(payload)})
        return result.rowcount == 1


def _save_document(item: dict[str, Any], source_code: str, source_index_url: str) -> bool:
    url = str(item.get("url") or item.get("source_url") or "").strip()
    if not is_allowed_source_url(url, source_code):
        raise ValueError(f"source returned a non-allowlisted URL ({source_code})")
    title = str(item.get("title") or "Untitled official publication").strip()[:500]
    excerpt = str(item.get("summary") or item.get("description") or "").strip()[:4000] or None
    published = item.get("publication_date") or item.get("published_at")
    year, week = parse_report_period(url, title)
    try:
        pub_dt = datetime.fromisoformat(str(published).replace("Z", "+00:00")) if published else None
        if pub_dt and pub_dt.tzinfo is None:
            pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        if pub_dt:
            pub_dt = pub_dt.astimezone(timezone.utc)
    except ValueError:
        pub_dt = None
    with engine.begin() as conn:
        existing = conn.execute(text("SELECT source_url FROM public.sk_source_documents WHERE source_url=:url"), {"url": url}).first()
        conn.execute(text("""
            INSERT INTO public.sk_source_documents
            (source_url,source_code,title,publication_date,report_year,report_week,source_index_url,
             text_excerpt,extracted_characters,last_seen_at,extraction_status,validation_status)
            VALUES (:url,:code,:title,:pub,:year,:week,:index,:excerpt,:chars,:now,:status,:validation)
            ON CONFLICT (source_url) DO UPDATE SET
              title=EXCLUDED.title,
              publication_date=COALESCE(EXCLUDED.publication_date,sk_source_documents.publication_date),
              report_year=COALESCE(EXCLUDED.report_year,sk_source_documents.report_year),
              report_week=COALESCE(EXCLUDED.report_week,sk_source_documents.report_week),
              source_index_url=EXCLUDED.source_index_url,
              text_excerpt=COALESCE(EXCLUDED.text_excerpt,sk_source_documents.text_excerpt),
              extracted_characters=COALESCE(EXCLUDED.extracted_characters,sk_source_documents.extracted_characters),
              last_seen_at=EXCLUDED.last_seen_at
        """), {"url": url, "code": source_code, "title": title, "pub": pub_dt, "year": year, "week": week,
               "index": source_index_url, "excerpt": excerpt, "chars": len(excerpt) if excerpt else None,
               "now": utc_now(), "status": "metadata_only" if source_code == "WHO" else "pending_download",
               "validation": "not_applicable" if source_code == "WHO" else "awaiting_pdf_extraction"})
    recent = bool(pub_dt and 0 <= (utc_now() - pub_dt).total_seconds() <= 14 * 86400)
    if source_code == "NCDC" and year and week:
        try:
            age = (utc_now().date() - date.fromisocalendar(year, week, 1)).days
            recent = 0 <= age <= 14
        except ValueError:
            recent = False
    if recent:
        _insert_event(f"source:{source_code}:{url}", "source_publication_discovered", {
            "type": "source_publication_discovered", "created_at": utc_now().isoformat(),
            "source_code": source_code, "title": title, "source_url": url,
            "publication_date": pub_dt.isoformat() if pub_dt else None,
            "message": f"A new {source_code} source publication was discovered. Review the official source before using it as case data.",
            "is_synthetic": False})
    return existing is None


def _get_docs_pending_pdf(max_count: int) -> list[dict[str, Any]]:
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT source_url,title,report_year,report_week,source_index_url,extraction_status,last_attempt_at
            FROM public.sk_source_documents
            WHERE source_code='NCDC'
              AND extraction_status IN ('pending_download','download_failed','dependency_missing')
              AND (last_attempt_at IS NULL OR last_attempt_at < CURRENT_TIMESTAMP - INTERVAL '6 hours')
            ORDER BY report_year DESC NULLS LAST,report_week DESC NULLS LAST,first_seen_at DESC
            LIMIT :limit
        """), {"limit": max(0, min(max_count, 10))}).mappings().all()
    return [dict(r) for r in rows]


def _update_document_extraction(url: str, fields: dict[str, Any]) -> None:
    allowed = {"source_sha256","content_sha256","byte_size","page_count","extracted_characters",
               "text_excerpt","extraction_status","validation_status","last_error","last_attempt_at","last_success_at"}
    payload = {k: v for k, v in fields.items() if k in allowed}
    if payload:
        assignments = ", ".join(f"{k}=:{k}" for k in payload)
        with engine.begin() as conn:
            conn.execute(text(f"UPDATE public.sk_source_documents SET {assignments} WHERE source_url=:url"), {**payload,"url":url})


def _same_ncdc_candidate_version(old: dict, new: dict) -> bool:
    """Recognize replayed PDFs or identical outbreak fields across source URLs."""
    if old.get("source_sha256") and old["source_sha256"] == new.get("source_sha256"):
        return True
    fields = ("report_year", "report_week", "state", "district", "disease",
              "cases", "deaths", "reporting_start_date", "reporting_end_date")
    def normalized(value):
        return None if value is None else str(value).strip().casefold()
    return all(normalized(old.get(field)) == normalized(new.get(field)) for field in fields)


def _insert_candidates(candidates: list[dict[str, Any]]) -> tuple[int, int]:
    inserted = invalid_inserted = 0
    if not candidates:
        return 0, 0
    with engine.begin() as conn:
        # Acquire all identity locks in one deterministic order. A later
        # report with revised fields is retained, never applied to live data.
        record_ids = sorted({str(c.get("source_record_id") or "").strip().upper()
                             for c in candidates} - {""})
        for record_id in record_ids:
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:record_key))"),
                         {"record_key": "ncdc:" + record_id})
        for c in candidates:
            record_id = str(c.get("source_record_id") or "").strip().upper()
            errors = list(c.get("validation_errors") or [])
            revision = False
            if record_id:
                existing = conn.execute(text("""
                    SELECT candidate_id, source_sha256, report_year, report_week,
                           state, district, disease, cases, deaths,
                           reporting_start_date, reporting_end_date
                    FROM public.sk_ingestion_candidates
                    WHERE UPPER(TRIM(source_record_id)) = :record_id
                """), {"record_id": record_id}).mappings().all()
                if any(_same_ncdc_candidate_version(old, c) for old in existing):
                    logger.info("Existing NCDC outbreak version retained: %s", record_id)
                    continue
                if existing:
                    revision = True
                    errors = sorted(set(errors + ["revised_ncdc_report_requires_supervisor_review"]))
                    logger.info("Staging revised NCDC outbreak for review: %s", record_id)

            result = conn.execute(text("""
                INSERT INTO public.sk_ingestion_candidates
                (candidate_id,source_url,source_sha256,report_year,report_week,state,district,disease,
                 reporting_start_date,reporting_end_date,cases,deaths,raw_excerpt,validation_status,
                 validation_errors,review_status,source_page,source_record_id)
                VALUES (:candidate_id,:source_url,:source_sha256,:report_year,:report_week,:state,:district,
                 :disease,:start_date,:end_date,:cases,:deaths,:excerpt,:status,CAST(:errors AS JSONB),
                 'pending_supervisor_review',:source_page,:source_record_id)
                ON CONFLICT (candidate_id) DO NOTHING
            """), {"candidate_id":c["candidate_id"],"source_url":c["source_url"],"source_sha256":c["source_sha256"],
                   "report_year":c.get("report_year"),"report_week":c.get("report_week"),"state":c.get("state"),
                   "district":c.get("district"),"disease":c.get("disease"),"start_date":c.get("reporting_start_date"),
                   "end_date":c.get("reporting_end_date"),"cases":c.get("cases"),"deaths":c.get("deaths"),
                   "excerpt":c["raw_excerpt"],"status":"needs_review" if revision else c["validation_status"],"errors":_json_param(errors),
                   "source_page":c.get("source_page"),"source_record_id":c.get("source_record_id")})
            if result.rowcount == 1:
                inserted += 1
                if errors:
                    invalid_inserted += 1
    return inserted, invalid_inserted


def _extract_pending_pdfs(limit: int) -> tuple[int, int, int, int, list[str]]:
    attempted = extracted = added_total = flagged_total = 0
    errors: list[str] = []
    for doc in _get_docs_pending_pdf(limit):
        url = doc["source_url"]
        attempted += 1
        _update_document_extraction(url, {"last_attempt_at":utc_now(),"last_error":None})
        try:
            content = _download_official_pdf(url)
            sha = content_fingerprint(content)
            with engine.begin() as conn:
                duplicate = conn.execute(text("""
                    SELECT source_url FROM public.sk_source_documents
                    WHERE content_sha256=:sha AND source_url<>:url LIMIT 1
                """), {"sha":sha,"url":url}).first()
            if duplicate:
                _update_document_extraction(url, {"source_sha256":sha,"content_sha256":sha,
                    "byte_size":len(content),"extraction_status":"duplicate_content",
                    "validation_status":"duplicate_document","last_success_at":utc_now(),"last_error":None})
                continue
            extracted_text, page_count = extract_pdf(content)
            candidates = parse_candidate_pdf(content,url,doc.get("title",""),sha)
            added, flagged = _insert_candidates(candidates)
            added_total += added
            flagged_total += flagged
            _update_document_extraction(url, {"source_sha256":sha,"content_sha256":sha,
                "byte_size":len(content),"page_count":page_count,"extracted_characters":len(extracted_text),
                "text_excerpt":extracted_text[:4000],
                "extraction_status":"extracted" if extracted_text else "extracted_no_text",
                "validation_status":"candidate_rows_staged" if candidates else "manual_table_review_required",
                "last_success_at":utc_now(),"last_error":None})
            extracted += 1
        except RuntimeError as exc:
            msg = str(exc)[:500]
            status = "dependency_missing" if ("pdfplumber is not installed" in msg or "pypdf is not installed" in msg) else "download_failed"
            _update_document_extraction(url, {"extraction_status":status,"validation_status":"not_validated","last_error":msg})
            errors.append(f"NCDC extraction {type(exc).__name__}")
        except (HTTPError,URLError,TimeoutError,ValueError,OSError) as exc:
            msg = f"NCDC PDF processing failed ({type(exc).__name__})"
            _update_document_extraction(url, {"extraction_status":"download_failed","validation_status":"not_validated","last_error":msg})
            errors.append(msg)
        except Exception as exc:
            logger.exception("Unexpected error extracting NCDC PDF")
            msg = f"Unexpected NCDC extraction error ({type(exc).__name__})"
            _update_document_extraction(url, {"extraction_status":"download_failed","validation_status":"not_validated","last_error":msg})
            errors.append(msg)
    return attempted, extracted, added_total, flagged_total, errors


def eligible_records_for_screening(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    eligible = []
    for row in records:
        try:
            if row.get("cases") is None:
                continue
            cases, year, week = int(row["cases"]), int(row.get("year")), int(row.get("week"))
            state, disease = str(row.get("state") or "").strip(), str(row.get("disease") or "").strip()
            if cases >= 0 and 2000 <= year <= 2100 and 1 <= week <= 53 and state and disease:
                eligible.append({**row,"cases":cases,"year":year,"week":week,"state":state,"disease":disease})
        except (TypeError,ValueError):
            continue
    return eligible


def _latest_anomalies(db: Session) -> list[dict[str, Any]]:
    rows = db.query(IDSPSurveillance).all()
    records = eligible_records_for_screening([{"state":r.state,"district":r.district,"disease":r.disease,
        "year":r.year,"week":r.week,"cases":r.cases,"deaths":r.deaths} for r in rows])
    latest: dict[tuple[str,str],tuple[int,int]] = {}
    for row in records:
        key = (row["state"].casefold(),row["disease"].casefold())
        latest[key] = max(latest.get(key,(0,0)),(row["year"],row["week"]))
    screened = detect_case_anomalies(records)
    return [a for a in screened if latest.get((str(a.get("state","")).strip().casefold(),
        str(a.get("disease","")).strip().casefold())) == (a.get("year"),a.get("week"))]


def _persist_anomaly_events(anomalies: list[dict[str, Any]]) -> int:
    created = 0
    for anomaly in anomalies:
        raw = "|".join(str(anomaly.get(k,"")) for k in ("state","disease","year","week","cases","severity","method"))
        fingerprint = "anomaly:" + hashlib.sha256(raw.casefold().encode()).hexdigest()
        event = {"type":"historical_anomaly_screening","created_at":utc_now().isoformat(),
            "is_synthetic":False,"source":"automated_ingestion_pipeline",
            "message":anomaly.get("message") or "Historical anomaly candidate requires review.",**anomaly}
        created += int(_insert_event(fingerprint,"historical_anomaly_screening",event))
    return created


def _run_pipeline_cycle_locked() -> dict[str, Any]:
    ensure_pipeline_schema()
    run_id, started = str(uuid.uuid4()), utc_now()
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO public.sk_ingestion_runs (run_id,status,started_at,details) VALUES (:id,'running',:started,'{}'::jsonb)"),
                     {"id":run_id,"started":started})
    who_items: list[dict[str,Any]] = []
    ncdc_items: list[dict[str,Any]] = []
    errors: list[str] = []
    who_ok = ncdc_ok = False
    new_docs = {"WHO":0,"NCDC":0}
    attempted = extracted = candidates_added = candidates_flagged = anomaly_count = 0
    try:
        try:
            who_items = _fetch_who_publications()
            who_ok = True
        except Exception as exc:
            logger.warning("WHO discovery failed: %s",type(exc).__name__)
            errors.append(f"WHO source discovery failed ({type(exc).__name__})")
        try:
            ncdc_items = _fetch_ncdc_catalogue()
            ncdc_ok = True
        except Exception as exc:
            logger.warning("NCDC discovery failed: %s",type(exc).__name__)
            errors.append(f"NCDC source discovery failed ({type(exc).__name__})")
        for item in who_items:
            try:
                new_docs["WHO"] += int(_save_document(item,"WHO","https://www.who.int/emergencies/disease-outbreak-news"))
            except Exception as exc:
                errors.append(f"WHO metadata rejected ({type(exc).__name__})")
        for item in ncdc_items:
            try:
                item = {**item,"publication_date":None}
                new_docs["NCDC"] += int(_save_document(item,"NCDC",str(item.get("archive_url") or "https://ncdc.mohfw.gov.in/includes/WeeklyOutbreaks.php")))
            except Exception as exc:
                errors.append(f"NCDC metadata rejected ({type(exc).__name__})")
        attempted,extracted,candidates_added,candidates_flagged,pdf_errors = _extract_pending_pdfs(MAX_PDFS_PER_CYCLE)
        errors.extend(pdf_errors)
        recovery = {"checked": 0, "repaired": 0, "errors": 0}
        if ncdc_ok and os.getenv("SK_AUTO_SOURCE_RECOVERY_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}:
            try:
                from .source_recovery import scan_pending_recovery
                recovery = scan_pending_recovery(ncdc_items)
                if recovery["errors"]:
                    errors.append("Automatic source recovery encountered candidate errors")
            except Exception:
                logger.exception("Automatic source recovery scan failed")
                errors.append("Automatic source recovery scan failed")
        try:
            with SessionLocal() as db:
                anomalies = _latest_anomalies(db)
            anomaly_count = len(anomalies)
            _persist_anomaly_events(anomalies)
        except Exception as exc:
            logger.exception("Anomaly screening failed")
            errors.append(f"Anomaly screening failed ({type(exc).__name__})")
        with engine.begin() as conn:
            events = int(conn.execute(text("SELECT COUNT(*) FROM public.sk_pipeline_events WHERE created_at>=:start"),{"start":started}).scalar() or 0)
        status = "success" if not errors else ("partial_success" if who_ok or ncdc_ok or extracted else "failed")
        summary = {"who_seen":len(who_items),"ncdc_seen":len(ncdc_items),"new_who_documents":new_docs["WHO"],
            "new_ncdc_documents":new_docs["NCDC"],"pdf_attempted":attempted,"pdf_extracted":extracted,
            "candidates_added":candidates_added,"candidates_flagged":candidates_flagged,
            "anomalies_found":anomaly_count,"source_recovery":recovery,"errors":errors[:20],
            "note":"Extracted candidates retain source PDF/page traceability and remain quarantined for supervisor review. No automatic promotion occurs."}
        with engine.begin() as conn:
            conn.execute(text("""UPDATE public.sk_ingestion_runs SET status=:status,finished_at=:finished,
                who_seen=:who,ncdc_seen=:ncdc,pdf_attempted=:attempted,pdf_extracted=:extracted,
                candidates_added=:added,candidates_flagged=:flagged,anomalies_found=:anomalies,
                events_created=:events,details=CAST(:details AS JSONB),error_summary=:error WHERE run_id=:id"""),
                {"id":run_id,"status":status,"finished":utc_now(),"who":len(who_items),"ncdc":len(ncdc_items),
                 "attempted":attempted,"extracted":extracted,"added":candidates_added,"flagged":candidates_flagged,
                 "anomalies":anomaly_count,"events":events,"details":_json_param(summary),
                 "error":"; ".join(errors[:8])[:1000] or None})
        return {"run_id":run_id,"status":status,"started_at":started.isoformat(),**summary}
    except Exception as exc:
        logger.exception("Fatal ingestion pipeline error")
        message = f"Pipeline cycle failed ({type(exc).__name__})"
        with engine.begin() as conn:
            conn.execute(text("""UPDATE public.sk_ingestion_runs SET status='failed',finished_at=:finished,
                error_summary=:error,details=CAST(:details AS JSONB) WHERE run_id=:id"""),
                {"id":run_id,"finished":utc_now(),"error":message,"details":_json_param({"errors":[message]})})
        return {"run_id":run_id,"status":"failed","started_at":started.isoformat(),"error":message}


def run_pipeline_cycle() -> dict[str, Any]:
    ensure_pipeline_schema()
    if direct_engine is None:
        raise RuntimeError("DATABASE_DIRECT_URL is required for the ingestion pipeline lock.")
    lock_key = 0x534B50495046
    with direct_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        acquired = bool(conn.execute(text("SELECT pg_try_advisory_lock(:key)"),{"key":lock_key}).scalar())
        if not acquired:
            return {"status":"skipped_locked","message":"Another API worker is processing this cycle."}
        try:
            return _run_pipeline_cycle_locked()
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:key)"),{"key":lock_key})


async def emit_pending_events(limit: int = 100) -> dict[str,int]:
    ensure_pipeline_schema()
    with engine.begin() as conn:
        rows = conn.execute(text("""SELECT event_id,payload FROM public.sk_pipeline_events
            WHERE broadcast_at IS NULL ORDER BY created_at ASC LIMIT :limit"""),
            {"limit":max(1,min(limit,200))}).mappings().all()
    delivered_events = delivered_clients = 0
    for row in rows:
        payload = row["payload"] if isinstance(row["payload"],dict) else json.loads(row["payload"])
        delivered = await manager.broadcast(payload)
        delivered_clients += delivered
        if delivered > 0:
            with engine.begin() as conn:
                conn.execute(text("UPDATE public.sk_pipeline_events SET broadcast_at=:now WHERE event_id=:id AND broadcast_at IS NULL"),
                             {"now":utc_now(),"id":row["event_id"]})
            delivered_events += 1
    return {"pending_events_seen":len(rows),"events_delivered":delivered_events,"clients_delivered":delivered_clients}


def cron_token_matches(configured_token: str | None, supplied_token: str | None) -> bool:
    expected, supplied = (configured_token or "").strip(), (supplied_token or "").strip()
    return bool(expected and supplied and hmac.compare_digest(expected,supplied))


def pipeline_enabled() -> bool:
    return os.getenv("SK_AUTO_INGESTION_ENABLED","true").strip().lower() not in {"0","false","no","off"}


def pipeline_interval_seconds() -> int:
    try:
        value = int(os.getenv("SK_INGESTION_INTERVAL_SECONDS",str(DEFAULT_INTERVAL_SECONDS)))
    except ValueError:
        value = DEFAULT_INTERVAL_SECONDS
    return max(300,min(value,86400))


async def _worker_loop() -> None:
    global _STOP_EVENT
    interval = pipeline_interval_seconds()
    while _STOP_EVENT is not None and not _STOP_EVENT.is_set():
        try:
            result = await asyncio.to_thread(run_pipeline_cycle)
            logger.info("Ingestion cycle %s status=%s",result.get("run_id"),result.get("status"))
            await emit_pending_events()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Background ingestion failed: %s",type(exc).__name__)
        if SYNTHETIC_GENERATION_ENABLED:
            try:
                await asyncio.to_thread(ensure_synthetic_schema)
                result = await asyncio.to_thread(generate_synthetic_records, records_per_cycle=48)
                logger.info("Synthetic generation status=%s created=%s",result.get("status"),result.get("created"))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Synthetic generation failed: %s",type(exc).__name__)
        try:
            await asyncio.wait_for(_STOP_EVENT.wait(),timeout=interval)
        except asyncio.TimeoutError:
            pass


async def start_pipeline_worker() -> None:
    global _WORKER_TASK,_STOP_EVENT
    if not pipeline_enabled():
        logger.info("Automatic ingestion disabled by SK_AUTO_INGESTION_ENABLED")
        return
    if _WORKER_TASK is not None and not _WORKER_TASK.done():
        return
    _STOP_EVENT = asyncio.Event()
    _WORKER_TASK = asyncio.create_task(_worker_loop(),name="samraksha-ingestion-worker")
    logger.info("Automatic source ingestion enabled; interval=%ss",pipeline_interval_seconds())


async def stop_pipeline_worker() -> None:
    global _WORKER_TASK,_STOP_EVENT
    if _STOP_EVENT is not None:
        _STOP_EVENT.set()
    if _WORKER_TASK is not None:
        _WORKER_TASK.cancel()
        try:
            await _WORKER_TASK
        except asyncio.CancelledError:
            pass
    _WORKER_TASK = None
    _STOP_EVENT = None
