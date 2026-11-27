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
