"""Conservative discovery of replacements for unavailable NCDC PDFs."""
import logging
from urllib.error import HTTPError

logger = logging.getLogger(__name__)
_scan_cursor = ""

from .ingestion_pipeline import (
    _download_official_pdf, _fetch_ncdc_catalogue,
    is_allowed_source_url, parse_report_period,
)


def discover_replacements(source_url, year, week, catalogue=None):
    """Return official same-period alternatives only after a confirmed 404/410."""
    if not is_allowed_source_url(source_url, "NCDC"):
        return []
    if not isinstance(year, int) or not isinstance(week, int):
        return []
    if not 2000 <= year <= 2100 or not 1 <= week <= 53:
        return []
    urls = set()
    for item in (_fetch_ncdc_catalogue() if catalogue is None else catalogue):
        url = str(item.get("url") or item.get("source_url") or "").strip()
        if url != source_url and is_allowed_source_url(url, "NCDC"):
            if parse_report_period(url) == (year, week):
                urls.add(url)
    # Do not select a subset when several possible replacements exist.
    if not urls or len(urls) > 3:
        return []
    try:
        _download_official_pdf(source_url)
        return []
    except HTTPError as exc:
        if exc.code not in (404, 410):
            return []
    return sorted(urls)


def record_verified_source(conn, url, sha, byte_size, year, week):
    """Register verified bytes without claiming full-document extraction.

    Preserve the old catalogue row and its historical fingerprint. A newly
    discovered or changed PDF remains eligible for ordinary extraction.
    """
    from sqlalchemy import text
    conn.execute(text("""
        INSERT INTO public.sk_source_documents
            (source_url, source_code, title, report_year, report_week,
             source_sha256, content_sha256, byte_size, extraction_status,
             validation_status, last_success_at)
        VALUES (:url,'NCDC',:title,:year,:week,:sha,:sha,:size,
                'pending_download','awaiting_pdf_extraction',NOW())
        ON CONFLICT (source_url) DO UPDATE SET
            source_sha256=EXCLUDED.source_sha256,
            content_sha256=EXCLUDED.content_sha256,
            byte_size=EXCLUDED.byte_size,
            extraction_status=CASE WHEN sk_source_documents.content_sha256
                IS DISTINCT FROM EXCLUDED.content_sha256 THEN 'pending_download'
                ELSE sk_source_documents.extraction_status END,
            validation_status=CASE WHEN sk_source_documents.content_sha256
                IS DISTINCT FROM EXCLUDED.content_sha256 THEN 'awaiting_pdf_extraction'
                ELSE sk_source_documents.validation_status END,
            last_attempt_at=CASE WHEN sk_source_documents.content_sha256
                IS DISTINCT FROM EXCLUDED.content_sha256 THEN NULL
                ELSE sk_source_documents.last_attempt_at END
    """), {"url":url,"sha":sha,"size":byte_size,"year":year,"week":week,
           "title":f"NCDC weekly outbreak report {year}, week {week}"})


def recover_pending_candidate(row, catalogue=None):
    """Repair a pending candidate only after exact source verification."""
    import re
    import uuid
    import json
    from sqlalchemy import text
    from .ingestion_pipeline import engine, parse_candidate_pdf, content_fingerprint

    if row.get("review_status") != "pending_supervisor_review":
        return False
    record_id = row.get("source_record_id")
    if not record_id:
        match = re.search(r"[A-Z]{2}/[A-Z]{2,4}/[0-9]{4}/[0-9]+/[0-9]+", row.get("raw_excerpt") or "")
        record_id = match.group(0) if match else None
    if not record_id or not re.fullmatch(r"[A-Z]{2}/[A-Z]{2,4}/[0-9]{4}/[0-9]+/[0-9]+", str(record_id).strip().upper()):
        return False
    fields = ("state", "district", "disease", "cases", "deaths",
              "reporting_start_date", "reporting_end_date")
    if any(row.get(f) is None or not str(row[f]).strip() for f in fields):
        return False
    normalize = lambda value: str(value).strip().casefold()
    verified = []
    for url in discover_replacements(row["source_url"], row["report_year"], row["report_week"], catalogue):
        content = _download_official_pdf(url)
        sha = content_fingerprint(content)
        matches = [c for c in parse_candidate_pdf(content, url, "", sha)
                   if normalize(c.get("source_record_id")) == normalize(record_id)]
        if len(matches) == 1 and matches[0].get("source_page") and all(
            normalize(row.get(f)) == normalize(matches[0].get(f)) for f in fields
        ):
            verified.append((url, sha, matches[0]["source_page"], len(content)))
    if len(verified) != 1:
        return False
    url, sha, page, byte_size = verified[0]
    with engine.begin() as conn:
        result = conn.execute(text("""
            UPDATE public.sk_ingestion_candidates
            SET source_url=:url, source_sha256=:sha, source_page=:page,
                source_record_id=:record_id, updated_at=NOW()
            WHERE candidate_id=:id AND review_status='pending_supervisor_review'
              AND updated_at=:updated AND source_url=:old_url AND source_sha256=:old_sha
        """), {"url":url,"sha":sha,"page":page,"record_id":record_id,
               "id":row["candidate_id"],"updated":row["updated_at"],
               "old_url":row["source_url"],"old_sha":row["source_sha256"]})
        if result.rowcount != 1:
            return False
        record_verified_source(conn, url, sha, byte_size, row["report_year"], row["report_week"])
        details = {"old_source_url":row["source_url"],"old_source_sha256":row["source_sha256"],
                   "old_source_page":row.get("source_page"),"old_source_record_id":row.get("source_record_id"),
                   "new_source_url":url,"new_source_sha256":sha,"new_source_page":page,
                   "source_record_id":record_id,"verified_fields":list(fields)}
        conn.execute(text("""
            INSERT INTO public.sk_candidate_audit
            (audit_id,candidate_id,action,actor,action_at,note,details)
            VALUES (:audit,:id,'source_repaired','automatic_source_recovery',NOW(),
                    'Confirmed unavailable source; exact official replacement verified.',CAST(:details AS JSONB))
        """), {"audit":str(uuid.uuid4()),"id":row["candidate_id"],"details":json.dumps(details)})
    return True


def scan_pending_recovery(catalogue, limit=2):
    """Bound work per ingestion cycle and rotate through pending candidates.

    No live surveillance rows are changed. The existing ingestion advisory
    lock serializes scheduled cycles; compare-and-set protects manual reviews.
    Cursor is process-local and starts again after a restart.
    """
    from sqlalchemy import text
    from .ingestion_pipeline import engine

    global _scan_cursor
    if not catalogue:
        return {"checked": 0, "repaired": 0, "errors": 0}
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT * FROM public.sk_ingestion_candidates
            WHERE review_status='pending_supervisor_review'
              AND candidate_id > :cursor
            ORDER BY candidate_id LIMIT :limit
        """), {"cursor": _scan_cursor, "limit": max(1, min(int(limit), 2))}).mappings().all()
    if not rows:
        _scan_cursor = ""
        return {"checked": 0, "repaired": 0, "errors": 0}
    summary = {"checked": 0, "repaired": 0, "errors": 0}
    for row in rows:
        _scan_cursor = row["candidate_id"]
        summary["checked"] += 1
        try:
            summary["repaired"] += int(recover_pending_candidate(dict(row), catalogue))
        except Exception:
            summary["errors"] += 1
            logger.exception("Automatic NCDC source recovery failed for candidate %s", row["candidate_id"])
    return summary
