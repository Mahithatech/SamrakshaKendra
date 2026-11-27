"""Conservative discovery of replacements for unavailable NCDC PDFs."""
from urllib.error import HTTPError

from .ingestion_pipeline import (
    _download_official_pdf, _fetch_ncdc_catalogue,
    is_allowed_source_url, parse_report_period,
)


def discover_replacements(source_url, year, week):
    """Return official same-period alternatives only after a confirmed 404/410.

    Discovery alone never changes database records. The existing repair
    endpoint must verify the outbreak identity and all seven fields.
    """
    if not is_allowed_source_url(source_url, "NCDC"):
        return []
    if not isinstance(year, int) or not isinstance(week, int):
        return []
    if not 2000 <= year <= 2100 or not 1 <= week <= 53:
        return []
    try:
        _download_official_pdf(source_url)
        return []
    except HTTPError as exc:
        if exc.code not in (404, 410):
            return []
    urls = set()
    for item in _fetch_ncdc_catalogue():
        url = str(item.get("url") or item.get("source_url") or "").strip()
        if url != source_url and is_allowed_source_url(url, "NCDC"):
            if parse_report_period(url) == (year, week):
                urls.add(url)
    return sorted(urls)


def recover_pending_candidate(row):
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
    if not record_id:
        return False
    fields = ("state", "district", "disease", "cases", "deaths",
              "reporting_start_date", "reporting_end_date")
    normalize = lambda value: str(value).strip().casefold()
    verified = []
    for url in discover_replacements(row["source_url"], row["report_year"], row["report_week"])[:3]:
        content = _download_official_pdf(url)
        sha = content_fingerprint(content)
        matches = [c for c in parse_candidate_pdf(content, url, "", sha)
                   if normalize(c.get("source_record_id")) == normalize(record_id)]
        if len(matches) == 1 and matches[0].get("source_page") and all(
            normalize(row.get(f)) == normalize(matches[0].get(f)) for f in fields
        ):
            verified.append((url, sha, matches[0]["source_page"]))
    if len(verified) != 1:
        return False
    url, sha, page = verified[0]
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
