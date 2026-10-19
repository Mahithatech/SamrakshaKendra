"""Scheduled public-source ingestion, staged validation, anomaly screening and event delivery.

Safety model:
- WHO notices and NCDC catalogue entries are ingested as source metadata.
- Official NCDC PDFs are downloaded only from allowlisted HTTPS hosts and bounded by size/time.
- PDF text is only parsed into *candidate* rows; candidate rows stay in a separate table pending human review.
- Nothing here automatically promotes a candidate into idsp_surveillance.
- Alert fingerprints and source URLs are unique, so repeated runs are idempotent.
- Results are screening signals, not official outbreak determinations.
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
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from sqlalchemy import text
from sqlalchemy.orm import Session

from .database import SessionLocal, engine
from .models import IDSPSurveillance
from .anomaly_service import detect_case_anomalies
from .websocket_manager import manager

logger = logging.getLogger("samraksha.ingestion")

NCDC_ALLOWED_HOSTS = {"ncdc.mohfw.gov.in", "www.ncdc.mohfw.gov.in"}
WHO_ALLOWED_HOSTS = {"www.who.int", "who.int"}
MAX_PDF_BYTES = int(os.getenv("SK_INGESTION_MAX_PDF_BYTES", "20971520"))  # 20 MiB
MAX_PDFS_PER_CYCLE = int(os.getenv("SK_INGESTION_MAX_PDFS_PER_CYCLE", "2"))
DOWNLOAD_TIMEOUT_SECONDS = int(os.getenv("SK_INGESTION_TIMEOUT_SECONDS", "25"))
MAX_PDF_PAGES = int(os.getenv("SK_INGESTION_MAX_PDF_PAGES", "80"))
MAX_EXTRACTED_CHARS = int(os.getenv("SK_INGESTION_MAX_EXTRACTED_CHARS", "1500000"))
DEFAULT_INTERVAL_SECONDS = int(os.getenv("SK_INGESTION_INTERVAL_SECONDS", "900"))

_SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS public.sk_ingestion_runs (
        run_id TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        started_at TIMESTAMPTZ NOT NULL,
        finished_at TIMESTAMPTZ NULL,
        who_seen INTEGER NOT NULL DEFAULT 0,
        ncdc_seen INTEGER NOT NULL DEFAULT 0,
        pdf_attempted INTEGER NOT NULL DEFAULT 0,
        pdf_extracted INTEGER NOT NULL DEFAULT 0,
        candidates_added INTEGER NOT NULL DEFAULT 0,
        candidates_flagged INTEGER NOT NULL DEFAULT 0,
        anomalies_found INTEGER NOT NULL DEFAULT 0,
        events_created INTEGER NOT NULL DEFAULT 0,
        details JSONB NOT NULL DEFAULT '{}'::jsonb,
        error_summary TEXT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS public.sk_source_documents (
        source_url TEXT PRIMARY KEY,
        source_code TEXT NOT NULL,
        title TEXT NOT NULL,
        publication_date TIMESTAMPTZ NULL,
        report_year INTEGER NULL,
        report_week INTEGER NULL,
        source_index_url TEXT NULL,
        source_sha256 TEXT NULL,
        content_sha256 TEXT NULL,
        byte_size BIGINT NULL,
        page_count INTEGER NULL,
        extracted_characters INTEGER NULL,
        text_excerpt TEXT NULL,
        extraction_status TEXT NOT NULL DEFAULT 'metadata_only',
        validation_status TEXT NOT NULL DEFAULT 'not_applicable',
        last_error TEXT NULL,
        first_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_attempt_at TIMESTAMPTZ NULL,
        last_success_at TIMESTAMPTZ NULL
    )""",
    """CREATE TABLE IF NOT EXISTS public.sk_ingestion_candidates (
        candidate_id TEXT PRIMARY KEY,
        source_url TEXT NOT NULL,
        source_sha256 TEXT NOT NULL,
        report_year INTEGER NULL,
        report_week INTEGER NULL,
        state TEXT NULL,
        district TEXT NULL,
        disease TEXT NULL,
        reporting_start_date DATE NULL,
        reporting_end_date DATE NULL,
        cases INTEGER NULL,
        deaths INTEGER NULL,
        raw_excerpt TEXT NOT NULL,
        validation_status TEXT NOT NULL,
        validation_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
        review_status TEXT NOT NULL DEFAULT 'pending_supervisor_review',
        reviewed_by TEXT NULL,
        reviewed_at TIMESTAMPTZ NULL,
        reviewer_note TEXT NULL,
        promoted_record_id TEXT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT sk_candidate_cases_nonnegative CHECK (cases IS NULL OR cases >= 0),
        CONSTRAINT sk_candidate_deaths_nonnegative CHECK (deaths IS NULL OR deaths >= 0),
        CONSTRAINT sk_candidate_week_range CHECK (report_week IS NULL OR report_week BETWEEN 1 AND 53)
    )""",
    """ALTER TABLE public.sk_ingestion_candidates ADD COLUMN IF NOT EXISTS reporting_start_date DATE NULL""",
    """ALTER TABLE public.sk_ingestion_candidates ADD COLUMN IF NOT EXISTS reporting_end_date DATE NULL""",
    """CREATE INDEX IF NOT EXISTS ix_sk_candidates_review_status
       ON public.sk_ingestion_candidates (review_status, created_at DESC)""",
    """CREATE TABLE IF NOT EXISTS public.sk_pipeline_events (
        event_id TEXT PRIMARY KEY,
        fingerprint TEXT NOT NULL UNIQUE,
        event_type TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        payload JSONB NOT NULL,
        broadcast_at TIMESTAMPTZ NULL
    )""",
    """CREATE INDEX IF NOT EXISTS ix_sk_events_created_at
       ON public.sk_pipeline_events (created_at DESC)""",
    """CREATE TABLE IF NOT EXISTS public.sk_candidate_audit (
        audit_id TEXT PRIMARY KEY,
        candidate_id TEXT NOT NULL,
        action TEXT NOT NULL,
        actor TEXT NOT NULL,
        action_at TIMESTAMPTZ NOT NULL,
        note TEXT NULL,
        details JSONB NOT NULL DEFAULT '{}'::jsonb
    )""",
    """CREATE INDEX IF NOT EXISTS ix_sk_candidate_audit_candidate
       ON public.sk_candidate_audit (candidate_id, action_at DESC)""",
]

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False
_WORKER_TASK: asyncio.Task | None = None
_STOP_EVENT: asyncio.Event | None = None


def ensure_pipeline_schema() -> None:
    """Create only the pipeline's own tables; never changes legacy surveillance rows."""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        with engine.begin() as connection:
            for statement in _SCHEMA_STATEMENTS:
                connection.execute(text(statement))
        _SCHEMA_READY = True


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
    return hashlib.sha256(f"{source_code.strip().upper()}\n{url.strip()}".encode("utf-8")).hexdigest()


def content_fingerprint(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def parse_report_period(url: str, title: str = "") -> tuple[int | None, int | None]:
    joined = f"{url} {title}"
    url_match = re.search(r"/weekly_outbreaks/(20\d{2})/week[_ -]?(\d{1,2})(?:[_\-.]|\b)", joined, re.I)
    title_match = re.search(r"\b(20\d{2})\D{0,20}(?:week\s*|wk\s*)(\d{1,2})\b", joined, re.I)
    match = url_match or title_match
    if not match:
        return None, None
    year, week = int(match.group(1)), int(match.group(2))
    if not 2000 <= year <= 2100 or not 1 <= week <= 53:
        return None, None
    return year, week


def parse_count(value: str | None) -> int | None:
    """Strictly parse a count while preserving blank/dash/NA as unknown, not zero."""
    value = (value or "").strip().replace(",", "")
    if not value or value.lower() in {"-", "—", "na", "n/a", "not available", "unknown", "nil"}:
        return None
    if not re.fullmatch(r"\d{1,8}", value):
        raise ValueError("count must be a non-negative whole number or blank")
    parsed = int(value)
    if parsed > 10_000_000:
        raise ValueError("count exceeds sanity limit")
    return parsed


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
    if candidate.get("cases") is None:
        errors.append("cases_unknown_requires_manual_review")
    else:
        try:
            if int(candidate["cases"]) < 0:
                errors.append("cases_negative")
        except (TypeError, ValueError):
            errors.append("cases_not_integer")
    if candidate.get("deaths") is not None:
        try:
            if int(candidate["deaths"]) < 0:
                errors.append("deaths_negative")
        except (TypeError, ValueError):
            errors.append("deaths_not_integer")
    if not is_allowed_source_url(str(candidate.get("source_url") or ""), "NCDC"):
        errors.append("source_url_not_allowlisted_https_ncdc")
    start_date, end_date = candidate.get("reporting_start_date"), candidate.get("reporting_end_date")
    if not start_date or not end_date:
        errors.append("reporting_dates_unverified")
    else:
        try:
            start_date = date.fromisoformat(str(start_date)) if not isinstance(start_date, date) else start_date
            end_date = date.fromisoformat(str(end_date)) if not isinstance(end_date, date) else end_date
            if start_date > end_date:
                errors.append("reporting_start_after_end")
            elif (end_date - start_date).days > 14:
                errors.append("reporting_period_exceeds_15_days")
        except (TypeError, ValueError):
            errors.append("reporting_dates_invalid")
    return errors


def parse_candidate_lines(text_content: str, source_url: str, title: str = "", source_sha256: str = "") -> list[dict[str, Any]]:
    """Parse recognizable NCDC outbreak records; all records remain review-only."""
    if not is_allowed_source_url(source_url, "NCDC"):
        return []

    year, week = parse_report_period(source_url, title)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    states = {
        "AP": "Andhra Pradesh", "AR": "Arunachal Pradesh", "AS": "Assam",
        "BR": "Bihar", "CT": "Chhattisgarh", "CG": "Chhattisgarh",
        "GA": "Goa", "GJ": "Gujarat", "HR": "Haryana",
        "HP": "Himachal Pradesh", "JH": "Jharkhand", "KA": "Karnataka",
        "KN": "Karnataka", "KL": "Kerala", "MP": "Madhya Pradesh",
        "MH": "Maharashtra", "MN": "Manipur", "ML": "Meghalaya",
        "MZ": "Mizoram", "NL": "Nagaland", "OD": "Odisha",
        "OR": "Odisha", "PB": "Punjab", "RJ": "Rajasthan",
        "SK": "Sikkim", "TN": "Tamil Nadu", "TS": "Telangana",
        "TR": "Tripura", "UP": "Uttar Pradesh", "UK": "Uttarakhand",
        "UT": "Uttarakhand", "WB": "West Bengal", "DL": "Delhi",
        "JK": "Jammu and Kashmir", "LA": "Ladakh",
    }

    diseases = sorted({
        "Acute Gastroenteritis", "Acute Diarrhoeal Disease",
        "Acute Diarrheal Disease", "Suspected Food Poisoning",
        "Food Poisoning", "Hand Foot and Mouth Disease",
        "Scrub Typhus", "Viral Fever", "Unusual Fever",
        "Chickenpox", "Chikungunya", "Dengue", "Measles",
        "Malaria", "Typhoid", "Cholera", "Jaundice",
        "Hepatitis", "Leptospirosis", "Mumps", "Diphtheria",
        "Diarrhoea", "Diarrhea", "Fever", "Rabies",
    }, key=len, reverse=True)

    def add_candidate(state, district, disease, cases, deaths, start, end, excerpt):
        candidate = {
            "source_url": source_url,
            "source_sha256": source_sha256,
            "report_year": year,
            "report_week": week,
            "state": state[:180],
            "district": district[:180],
            "disease": disease[:180],
            "cases": cases,
            "deaths": deaths,
            "reporting_start_date": start,
            "reporting_end_date": end,
            "raw_excerpt": excerpt[:1000],
        }
        candidate["validation_errors"] = validate_candidate(candidate)
        candidate["validation_status"] = (
            "needs_review" if candidate["validation_errors"]
            else "passed_preliminary_checks"
        )
        key_raw = "|".join(str(candidate.get(field) or "") for field in (
            "source_url", "report_year", "report_week", "state", "district",
            "disease", "cases", "deaths", "raw_excerpt"
        ))
        candidate["candidate_id"] = hashlib.sha256(
            key_raw.casefold().encode("utf-8")
        ).hexdigest()
        if candidate["candidate_id"] not in seen:
            result.append(candidate)
            seen.add(candidate["candidate_id"])

    # Normalize PDF line wrapping without treating descriptions as case records.
    text = (text_content or "").replace("\x00", " ")
    text = re.sub(r"(?m)(/[0-9]{1,3})[ \t]*\n[ \t]*([0-9]{1,2})(?=\s)", r"\1\2", text)
    id_pattern = re.compile(
        r"(?<![A-Z0-9])([A-Z]{2})/([A-Z0-9]{2,})/(20\d{2})/(\d{1,2})/(\d+)"
    )
    matches = list(id_pattern.finditer(text))

    for i, match in enumerate(matches):
        chunk = text[match.start():matches[i + 1].start() if i + 1 < len(matches) else len(text)]
        flat = re.sub(r"\s+", " ", chunk).strip()

        # Cases, deaths and both dates must be explicitly present.
        tail = re.search(
            r"\b(?P<cases>\d{1,7})\s+(?P<deaths>\d{1,6})\s+"
            r"(?P<start>\d{2}-\d{2}-\s*\d{4})\s+"
            r"(?P<end>\d{2}-\d{2}-\s*\d{4})\b",
            flat,
        )
        if not tail:
            continue

        state = states.get(match.group(1))
        if not state:
            continue

        before_counts = flat[match.end() - match.start():tail.start()].strip()
        # Match the official state name before attempting to split district/disease.
        if not before_counts.casefold().startswith(state.casefold() + " "):
            continue
        remainder = before_counts[len(state):].strip()

        disease = next(
            (d for d in diseases if remainder.casefold().endswith(d.casefold())),
            None,
        )
        if not disease:
            continue

        district = remainder[:-len(disease)].strip()
        if not district or len(district) > 180:
            continue

        try:
            cases = int(tail.group("cases"))
            deaths = int(tail.group("deaths"))
            start = datetime.strptime(
                re.sub(r"\s+", "", tail.group("start")), "%d-%m-%Y"
            ).date().isoformat()
            end = datetime.strptime(
                re.sub(r"\s+", "", tail.group("end")), "%d-%m-%Y"
            ).date().isoformat()
        except (ValueError, OverflowError):
            continue

        if cases < 0 or deaths < 0 or deaths > cases or start > end:
            continue

        add_candidate(state, district, disease, cases, deaths, start, end, flat)

    # Preserve compatibility with simple tabular text and existing tests.
    if not result:
        for raw in (text_content or "").splitlines():
            line = re.sub(r"\s+", " ", raw).strip()
            if len(line) < 12 or len(line) > 1000:
                continue
            cells = [
                part.strip()
                for part in re.split(r"\t+|\s{2,}|\s*\|\s*", raw.strip())
                if part.strip()
            ]
            if cells and cells[0].isdigit():
                cells = cells[1:]
            if len(cells) < 5:
                continue
            try:
                cases = parse_count(cells[-2])
                deaths = parse_count(cells[-1])
            except ValueError:
                continue
            state, district = cells[0], cells[1]
            disease = " ".join(cells[2:-2]).strip()
            if not disease or cases is None:
                continue
            add_candidate(state, district, disease, cases, deaths, None, None, line)

    return result


def extract_pdf(content: bytes) -> tuple[str, int]:
    """Extract bounded text. A missing PDF library is an explicit error state."""
    if not content.startswith(b"%PDF-"):
        raise ValueError("downloaded content does not have a PDF signature")
    if len(content) > MAX_PDF_BYTES:
        raise ValueError("PDF exceeds configured download size limit")
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise RuntimeError("pypdf is not installed; install backend requirements to enable extraction") from exc
    import io
    reader = PdfReader(io.BytesIO(content), strict=False)
    if getattr(reader, "is_encrypted", False):
        try:
            if reader.decrypt("") == 0:
                raise ValueError("encrypted PDF cannot be extracted without credentials")
        except Exception as exc:
            raise ValueError("encrypted PDF cannot be extracted without credentials") from exc
    page_count = len(reader.pages)
    sections: list[str] = []
    total = 0
    for page in reader.pages[:MAX_PDF_PAGES]:
        segment = page.extract_text() or ""
        if segment:
            remaining = MAX_EXTRACTED_CHARS - total
            if remaining <= 0:
                break
            segment = segment[:remaining]
            sections.append(segment)
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
    opener = build_opener(_AllowlistedRedirectHandler(source_code))
    return opener.open(request, timeout=DOWNLOAD_TIMEOUT_SECONDS)


def _fetch_who_publications() -> list[dict[str, Any]]:
    """Fetch WHO feed while restricting every redirect to the official WHO host."""
    from urllib.parse import urlencode
    from .source_routes import WHO_API_BASE, MAX_UPSTREAM_ITEMS, _normalise_rows

    params = urlencode({"$orderby": "PublicationDateAndTime desc", "$top": str(MAX_UPSTREAM_ITEMS)})
    urls = [f"{WHO_API_BASE}?{params}", WHO_API_BASE]
    last_error: Exception | None = None
    for url in urls:
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "SamrakshaKendra-ResearchPrototype/1.0"}, method="GET")
        try:
            with _open_allowlisted(request, "WHO") as response:
                if response.status < 200 or response.status >= 300:
                    raise RuntimeError(f"WHO feed returned HTTP {response.status}")
                content = response.read(8 * 1024 * 1024 + 1)
            if len(content) > 8 * 1024 * 1024:
                raise ValueError("WHO feed response exceeded 8 MiB limit")
            payload = json.loads(content.decode("utf-8"))
            rows = _normalise_rows(payload)
            if rows or url == urls[-1]:
                return rows[:MAX_UPSTREAM_ITEMS]
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"WHO source discovery failed ({type(last_error).__name__ if last_error else 'UnknownError'})")


def _fetch_ncdc_catalogue() -> list[dict[str, Any]]:
    """Fetch the official NCDC index with redirect restrictions and a bounded body."""
    from .india_reports_routes import NCDC_ARCHIVE_URL, _parse_archive_html, _report_title

    request = Request(NCDC_ARCHIVE_URL, headers={"Accept": "text/html,application/xhtml+xml", "User-Agent": "SamrakshaKendra-ResearchPrototype/1.0"}, method="GET")
    with _open_allowlisted(request, "NCDC") as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"NCDC archive returned HTTP {response.status}")
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
    rows.sort(key=lambda item: (item.get("year") or 0, item.get("week") or 0, item["title"]), reverse=True)
    return rows[:100]

def _download_official_pdf(url: str) -> bytes:
    if not is_allowed_source_url(url, "NCDC"):
        raise ValueError("refusing non-allowlisted NCDC PDF URL")
    req = Request(url, headers={"User-Agent": "SamrakshaKendra-ResearchPrototype/1.0", "Accept": "application/pdf"})
    with _open_allowlisted(req, "NCDC") as response:
        final_url = response.geturl()
        if not is_allowed_source_url(final_url, "NCDC"):
            raise ValueError("NCDC PDF redirected outside the allowlisted hosts")
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"NCDC PDF request returned HTTP {response.status}")
        body = response.read(MAX_PDF_BYTES + 1)
    if len(body) > MAX_PDF_BYTES:
        raise ValueError("NCDC PDF exceeds maximum allowed download size")
    if not body.startswith(b"%PDF-"):
        raise ValueError("NCDC link did not return a PDF file")
    return body


def _json_param(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _insert_event(fingerprint: str, event_type: str, payload: dict[str, Any]) -> bool:
    event_id = str(payload.get("event_id") or uuid.uuid4())
    payload = {**payload, "event_id": event_id}
    with engine.begin() as connection:
        result = connection.execute(text("""
            INSERT INTO public.sk_pipeline_events (event_id, fingerprint, event_type, created_at, payload)
            VALUES (:event_id, :fingerprint, :event_type, :created_at, CAST(:payload AS JSONB))
            ON CONFLICT (fingerprint) DO NOTHING
        """), {
            "event_id": event_id,
            "fingerprint": fingerprint,
            "event_type": event_type,
            "created_at": utc_now(),
            "payload": _json_param(payload),
        })
        return result.rowcount == 1


def _save_document(item: dict[str, Any], source_code: str, source_index_url: str) -> bool:
    url = str(item.get("url") or item.get("source_url") or "").strip()
    if not is_allowed_source_url(url, source_code):
        raise ValueError(f"source returned a non-allowlisted URL ({source_code})")
    title = str(item.get("title") or "Untitled official publication").strip()[:500]
    excerpt = str(item.get("summary") or item.get("description") or "").strip()[:4000] or None
    published = item.get("publication_date") or item.get("published_at")
    report_year, report_week = parse_report_period(url, title)
    try:
        pub_dt = datetime.fromisoformat(str(published).replace("Z", "+00:00")) if published else None
        if pub_dt and pub_dt.tzinfo is None:
            pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        if pub_dt:
            pub_dt = pub_dt.astimezone(timezone.utc)
    except ValueError:
        pub_dt = None
    with engine.begin() as connection:
        existing = connection.execute(text("SELECT source_sha256, extraction_status FROM public.sk_source_documents WHERE source_url=:url"), {"url": url}).mappings().first()
        connection.execute(text("""
          INSERT INTO public.sk_source_documents (
            source_url, source_code, title, publication_date, report_year, report_week,
            source_index_url, text_excerpt, extracted_characters, last_seen_at, extraction_status, validation_status
          ) VALUES (
            :url, :source_code, :title, :publication_date, :year, :week,
            :index_url, :excerpt, :excerpt_len, :now, :extract_status, :validation_status
          )
          ON CONFLICT (source_url) DO UPDATE SET
            title=EXCLUDED.title,
            publication_date=COALESCE(EXCLUDED.publication_date, public.sk_source_documents.publication_date),
            report_year=COALESCE(EXCLUDED.report_year, public.sk_source_documents.report_year),
            report_week=COALESCE(EXCLUDED.report_week, public.sk_source_documents.report_week),
            source_index_url=EXCLUDED.source_index_url,
            text_excerpt=COALESCE(EXCLUDED.text_excerpt, public.sk_source_documents.text_excerpt),
            extracted_characters=COALESCE(EXCLUDED.extracted_characters, public.sk_source_documents.extracted_characters),
            last_seen_at=EXCLUDED.last_seen_at
        """), {
            "url": url, "source_code": source_code, "title": title, "publication_date": pub_dt,
            "year": report_year, "week": report_week, "index_url": source_index_url,
            "excerpt": excerpt, "excerpt_len": len(excerpt) if excerpt else None,
            "now": utc_now(), "extract_status": "metadata_only" if source_code == "WHO" else "pending_download",
            "validation_status": "not_applicable" if source_code == "WHO" else "awaiting_pdf_extraction",
        })
    is_new = existing is None
    is_recent = bool(pub_dt and 0 <= (utc_now() - pub_dt).total_seconds() <= 14 * 24 * 3600)
    if source_code == "NCDC" and report_year and report_week:
        # NCDC publishes weekly. Only send discovery alerts for reports from the last two ISO weeks;
        # older catalogue entries are still stored but should not flood alerts on first install.
        from datetime import date as _date
        try:
            report_monday = _date.fromisocalendar(report_year, report_week, 1)
            today = utc_now().date()
            is_recent = 0 <= (today - report_monday).days <= 14
        except ValueError:
            is_recent = False
    if is_recent:
        event_type = "source_publication_discovered"
        _insert_event(f"source:{source_code}:{url}", event_type, {
            "type": event_type, "created_at": utc_now().isoformat(), "source_code": source_code,
            "title": title, "source_url": url, "publication_date": pub_dt.isoformat() if pub_dt else None,
            "message": f"A new {source_code} source publication was discovered. Review the official source before using it as case data.",
            "is_synthetic": False,
        })
    return is_new


def _get_docs_pending_pdf(max_count: int) -> list[dict[str, Any]]:
    with engine.begin() as connection:
        rows = connection.execute(text("""
          SELECT source_url, title, report_year, report_week, source_index_url, extraction_status, last_attempt_at
          FROM public.sk_source_documents
          WHERE source_code='NCDC'
            AND extraction_status IN ('pending_download','download_failed','dependency_missing')
            AND (last_attempt_at IS NULL OR last_attempt_at < CURRENT_TIMESTAMP - INTERVAL '6 hours')
          ORDER BY report_year DESC NULLS LAST, report_week DESC NULLS LAST, first_seen_at DESC
          LIMIT :limit
        """), {"limit": max(0, min(max_count, 10))}).mappings().all()
    return [dict(row) for row in rows]


def _update_document_extraction(url: str, fields: dict[str, Any]) -> None:
    allowed = {
        "source_sha256", "content_sha256", "byte_size", "page_count", "extracted_characters", "text_excerpt",
        "extraction_status", "validation_status", "last_error", "last_attempt_at", "last_success_at",
    }
    payload = {key: value for key, value in fields.items() if key in allowed}
    if not payload:
        return
    assignments = ", ".join(f"{key}=:{key}" for key in payload)
    params = {**payload, "url": url}
    with engine.begin() as connection:
        connection.execute(text(f"UPDATE public.sk_source_documents SET {assignments} WHERE source_url=:url"), params)


def _insert_candidates(candidates: list[dict[str, Any]]) -> tuple[int, int]:
    inserted = invalid = 0
    if not candidates:
        return 0, 0
    with engine.begin() as connection:
        for candidate in candidates:
            errors = candidate.get("validation_errors") or []
            if errors:
                invalid += 1
            result = connection.execute(text("""
              INSERT INTO public.sk_ingestion_candidates (
                candidate_id, source_url, source_sha256, report_year, report_week,
                state, district, disease, reporting_start_date, reporting_end_date, cases, deaths, raw_excerpt,
                validation_status, validation_errors, review_status
              ) VALUES (
                :candidate_id, :source_url, :source_sha256, :report_year, :report_week,
                :state, :district, :disease, :reporting_start_date, :reporting_end_date, :cases, :deaths, :raw_excerpt,
                :validation_status, CAST(:validation_errors AS JSONB), 'pending_supervisor_review'
              ) ON CONFLICT (candidate_id) DO NOTHING
            """), {
                **{key: candidate.get(key) for key in (
                    "candidate_id", "source_url", "source_sha256", "report_year", "report_week",
                    "state", "district", "disease", "reporting_start_date", "reporting_end_date", "cases", "deaths", "raw_excerpt", "validation_status"
                )},
                "validation_errors": _json_param(errors),
            })
            inserted += max(0, result.rowcount or 0)
    return inserted, invalid


def _extract_pending_pdfs(limit: int) -> tuple[int, int, int, int, list[str]]:
    attempted = extracted = candidates_added = invalid = 0
    errors: list[str] = []
    docs = _get_docs_pending_pdf(limit)
    for doc in docs:
        url = doc["source_url"]
        attempted += 1
        _update_document_extraction(url, {"last_attempt_at": utc_now(), "last_error": None})
        try:
            content = _download_official_pdf(url)
            sha = content_fingerprint(content)
            with engine.begin() as connection:
                dupe = connection.execute(text("""
                    SELECT source_url FROM public.sk_source_documents
                    WHERE content_sha256=:sha AND source_url<>:url LIMIT 1
                """), {"sha": sha, "url": url}).first()
            if dupe:
                _update_document_extraction(url, {
                    "content_sha256": sha, "source_sha256": sha, "byte_size": len(content),
                    "extraction_status": "duplicate_content", "validation_status": "duplicate_document",
                    "last_success_at": utc_now(), "last_error": None,
                })
                continue
            extracted_text, page_count = extract_pdf(content)
            cands = parse_candidate_lines(extracted_text, url, doc.get("title", ""), sha)
            added, invalid_n = _insert_candidates(cands)
            candidates_added += added
            invalid += invalid_n
            _update_document_extraction(url, {
                "source_sha256": sha, "content_sha256": sha, "byte_size": len(content),
                "page_count": page_count, "extracted_characters": len(extracted_text),
                "text_excerpt": extracted_text[:4000],
                "extraction_status": "extracted" if extracted_text else "extracted_no_text",
                "validation_status": "candidate_rows_staged" if cands else "manual_table_review_required",
                "last_success_at": utc_now(), "last_error": None,
            })
            extracted += 1
        except RuntimeError as exc:
            msg = str(exc)[:500]
            status = "dependency_missing" if "pypdf is not installed" in msg else "download_failed"
            _update_document_extraction(url, {"extraction_status": status, "validation_status": "not_validated", "last_error": msg})
            errors.append(f"NCDC extraction {type(exc).__name__}")
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
            msg = f"NCDC PDF processing failed ({type(exc).__name__})"[:500]
            _update_document_extraction(url, {"extraction_status": "download_failed", "validation_status": "not_validated", "last_error": msg})
            errors.append(msg)
        except Exception as exc:
            logger.exception("Unexpected error extracting an NCDC PDF")
            msg = f"Unexpected NCDC extraction error ({type(exc).__name__})"[:500]
            _update_document_extraction(url, {"extraction_status": "download_failed", "validation_status": "not_validated", "last_error": msg})
            errors.append(msg)
    return attempted, extracted, candidates_added, invalid, errors



def eligible_records_for_screening(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only well-formed rows with an observed case count; never turn missing into zero."""
    eligible: list[dict[str, Any]] = []
    for row in records:
        try:
            if row.get("cases") is None:
                continue
            cases = int(row["cases"])
            year, week = int(row.get("year")), int(row.get("week"))
            state = str(row.get("state") or "").strip()
            disease = str(row.get("disease") or "").strip()
            if cases < 0 or not 2000 <= year <= 2100 or not 1 <= week <= 53 or not state or not disease:
                continue
            eligible.append({**row, "cases": cases, "year": year, "week": week, "state": state, "disease": disease})
        except (TypeError, ValueError):
            continue
    return eligible

def _latest_anomalies(db: Session) -> list[dict[str, Any]]:
    rows = db.query(IDSPSurveillance).all()
    records = eligible_records_for_screening([
        {"state": r.state, "district": r.district, "disease": r.disease, "year": r.year, "week": r.week, "cases": r.cases, "deaths": r.deaths}
        for r in rows
    ])
    latest: dict[tuple[str, str], tuple[int, int]] = {}
    for row in records:
        try:
            key = (str(row["state"]).strip().casefold(), str(row["disease"]).strip().casefold())
            period = (int(row["year"]), int(row["week"]))
        except (TypeError, ValueError):
            continue
        if period > latest.get(key, (0, 0)):
            latest[key] = period
    screened = detect_case_anomalies(records)
    return [a for a in screened if latest.get((str(a.get("state", "")).strip().casefold(), str(a.get("disease", "")).strip().casefold())) == (a.get("year"), a.get("week"))]


def _persist_anomaly_events(anomalies: list[dict[str, Any]]) -> int:
    created = 0
    for anomaly in anomalies:
        fingerprint = "anomaly:" + hashlib.sha256("|".join(str(anomaly.get(k, "")) for k in (
            "state", "disease", "year", "week", "cases", "severity", "method"
        )).casefold().encode("utf-8")).hexdigest()
        event_type = "historical_anomaly_screening"
        event = {
            "type": event_type, "created_at": utc_now().isoformat(), "is_synthetic": False,
            "source": "automated_ingestion_pipeline", "message": anomaly.get("message") or "Historical anomaly candidate requires review.",
            **anomaly,
        }
        if _insert_event(fingerprint, event_type, event):
            created += 1
    return created


def _run_pipeline_cycle_locked() -> dict[str, Any]:
    """Run one idempotent source-discovery / extraction / validation / screening cycle."""
    ensure_pipeline_schema()
    run_id = str(uuid.uuid4())
    started = utc_now()
    with engine.begin() as connection:
        connection.execute(text("""
          INSERT INTO public.sk_ingestion_runs (run_id, status, started_at, details)
          VALUES (:id, 'running', :started, CAST(:details AS JSONB))
        """), {"id": run_id, "started": started, "details": "{}"})
    who_items: list[dict[str, Any]] = []
    ncdc_items: list[dict[str, Any]] = []
    errors: list[str] = []
    who_ok = False
    ncdc_ok = False
    new_docs = {"WHO": 0, "NCDC": 0}
    extracted = attempted = candidates_added = candidates_flagged = anomaly_count = events_created = 0
    try:
        # These helpers already implement source-specific request handling and caching logic is bypassed here.
        try:
            who_items = _fetch_who_publications()
            who_ok = True
        except Exception as exc:
            logger.warning("WHO source discovery failed: %s", type(exc).__name__)
            errors.append(f"WHO source discovery failed ({type(exc).__name__})")
        try:
            ncdc_items = _fetch_ncdc_catalogue()
            ncdc_ok = True
        except Exception as exc:
            logger.warning("NCDC source discovery failed: %s", type(exc).__name__)
            errors.append(f"NCDC source discovery failed ({type(exc).__name__})")

        for item in who_items:
            try:
                if _save_document(item, "WHO", "https://www.who.int/emergencies/disease-outbreak-news"):
                    new_docs["WHO"] += 1
            except Exception as exc:
                errors.append(f"WHO metadata rejected ({type(exc).__name__})")
        for item in ncdc_items:
            try:
                item = {**item, "publication_date": None}
                if _save_document(item, "NCDC", str(item.get("archive_url") or "https://ncdc.mohfw.gov.in/includes/WeeklyOutbreaks.php")):
                    new_docs["NCDC"] += 1
            except Exception as exc:
                errors.append(f"NCDC metadata rejected ({type(exc).__name__})")

        attempted, extracted, candidates_added, candidates_flagged, extraction_errors = _extract_pending_pdfs(MAX_PDFS_PER_CYCLE)
        errors.extend(extraction_errors)

        try:
            with SessionLocal() as db:
                anomalies = _latest_anomalies(db)
            anomaly_count = len(anomalies)
            events_created += _persist_anomaly_events(anomalies)
        except Exception as exc:
            logger.exception("Anomaly screening failed during pipeline cycle")
            errors.append(f"Anomaly screening failed ({type(exc).__name__})")

        # Events for newly discovered publications have already been persisted by _save_document.
        with engine.begin() as connection:
            events_created = int(connection.execute(text("SELECT COUNT(*) FROM public.sk_pipeline_events WHERE created_at >= :start"), {"start": started}).scalar() or 0)
        status = "success" if not errors else ("partial_success" if who_ok or ncdc_ok or extracted > 0 else "failed")
        summary = {
            "who_seen": len(who_items), "ncdc_seen": len(ncdc_items), "new_who_documents": new_docs["WHO"],
            "new_ncdc_documents": new_docs["NCDC"], "pdf_attempted": attempted, "pdf_extracted": extracted,
            "candidates_added": candidates_added, "candidates_flagged": candidates_flagged,
            "anomalies_found": anomaly_count, "errors": errors[:20],
            "note": "Extracted candidates are quarantined for human review. No candidate is automatically promoted to idsp_surveillance.",
        }
        with engine.begin() as connection:
            connection.execute(text("""
              UPDATE public.sk_ingestion_runs SET status=:status, finished_at=:finished,
                who_seen=:who, ncdc_seen=:ncdc, pdf_attempted=:attempted, pdf_extracted=:extracted,
                candidates_added=:added, candidates_flagged=:flagged, anomalies_found=:anomalies,
                events_created=:events, details=CAST(:details AS JSONB), error_summary=:error
              WHERE run_id=:id
            """), {
                "id": run_id, "status": status, "finished": utc_now(), "who": len(who_items), "ncdc": len(ncdc_items),
                "attempted": attempted, "extracted": extracted, "added": candidates_added, "flagged": candidates_flagged,
                "anomalies": anomaly_count, "events": events_created, "details": _json_param(summary),
                "error": "; ".join(errors[:8])[:1000] or None,
            })
        return {"run_id": run_id, "status": status, "started_at": started.isoformat(), **summary}
    except Exception as exc:
        logger.exception("Fatal error in ingestion pipeline cycle")
        message = f"Pipeline cycle failed ({type(exc).__name__})"
        with engine.begin() as connection:
            connection.execute(text("""
              UPDATE public.sk_ingestion_runs SET status='failed', finished_at=:finished, error_summary=:error,
                details=CAST(:details AS JSONB) WHERE run_id=:id
            """), {"id": run_id, "finished": utc_now(), "error": message, "details": _json_param({"errors": [message]} )})
        return {"run_id": run_id, "status": "failed", "started_at": started.isoformat(), "error": message}


def run_pipeline_cycle() -> dict[str, Any]:
    """Acquire a PostgreSQL advisory lock so multiple API workers do not duplicate a run."""
    ensure_pipeline_schema()
    lock_key = 0x534B50495045  # stable integer key: "SKPIPE"
    with engine.connect() as lock_connection:
        acquired = bool(lock_connection.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_key}).scalar())
        if not acquired:
            return {"status": "skipped_locked", "message": "Another API worker is processing this cycle."}
        try:
            return _run_pipeline_cycle_locked()
        finally:
            try:
                lock_connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key})
            except Exception:
                logger.exception("Could not explicitly release the ingestion advisory lock; connection close will release it")


async def emit_pending_events(limit: int = 100) -> dict[str, int]:
    ensure_pipeline_schema()
    with engine.begin() as connection:
        rows = connection.execute(text("""
          SELECT event_id, payload FROM public.sk_pipeline_events
          WHERE broadcast_at IS NULL ORDER BY created_at ASC LIMIT :limit
        """), {"limit": max(1, min(limit, 200))}).mappings().all()
    delivered_events = delivered_clients = 0
    for row in rows:
        payload = row["payload"] if isinstance(row["payload"], dict) else json.loads(row["payload"])
        delivered = await manager.broadcast(payload)
        delivered_clients += delivered
        if delivered > 0:
            with engine.begin() as connection:
                connection.execute(text("UPDATE public.sk_pipeline_events SET broadcast_at=:now WHERE event_id=:id AND broadcast_at IS NULL"), {"now": utc_now(), "id": row["event_id"]})
            delivered_events += 1
    return {"pending_events_seen": len(rows), "events_delivered": delivered_events, "clients_delivered": delivered_clients}


def cron_token_matches(configured_token: str | None, supplied_token: str | None) -> bool:
    """Constant-time comparison for the optional GitHub Actions / external scheduler secret."""
    expected = (configured_token or "").strip()
    supplied = (supplied_token or "").strip()
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


def pipeline_enabled() -> bool:
    return os.getenv("SK_AUTO_INGESTION_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


def pipeline_interval_seconds() -> int:
    try:
        value = int(os.getenv("SK_INGESTION_INTERVAL_SECONDS", str(DEFAULT_INTERVAL_SECONDS)))
    except ValueError:
        value = DEFAULT_INTERVAL_SECONDS
    return max(300, min(value, 86400))


async def _worker_loop() -> None:
    global _STOP_EVENT
    interval = pipeline_interval_seconds()
    while _STOP_EVENT is not None and not _STOP_EVENT.is_set():
        try:
            result = await asyncio.to_thread(run_pipeline_cycle)
            logger.info("Ingestion cycle %s status=%s", result.get("run_id"), result.get("status"))
            await emit_pending_events()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Background ingestion cycle failed: %s", type(exc).__name__)
        try:
            await asyncio.wait_for(_STOP_EVENT.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


async def start_pipeline_worker() -> None:
    global _WORKER_TASK, _STOP_EVENT
    if not pipeline_enabled():
        logger.info("Automatic ingestion disabled by SK_AUTO_INGESTION_ENABLED")
        return
    if _WORKER_TASK is not None and not _WORKER_TASK.done():
        return
    _STOP_EVENT = asyncio.Event()
    _WORKER_TASK = asyncio.create_task(_worker_loop(), name="samraksha-ingestion-worker")
    logger.info("Automatic source ingestion enabled; interval=%ss", pipeline_interval_seconds())


async def stop_pipeline_worker() -> None:
    global _WORKER_TASK, _STOP_EVENT
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
