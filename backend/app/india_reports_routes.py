"""Cached catalogue of official NCDC weekly outbreak report PDFs.

The NCDC public archive links to weekly outbreak PDFs compiled through India's
Integrated Disease Surveillance Programme (IDSP). This route catalogues official
links only. It deliberately does not parse PDF tables or modify surveillance rows.
"""
from __future__ import annotations

import re
import threading
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from fastapi import APIRouter, Query

router = APIRouter(tags=["Indian Public Source Feeds"])

NCDC_ARCHIVE_URL = "https://ncdc.mohfw.gov.in/includes/WeeklyOutbreaks.php"
NCDC_HOME_URL = "https://ncdc.mohfw.gov.in/"
ALLOWED_HOSTS = {"ncdc.mohfw.gov.in", "www.ncdc.mohfw.gov.in"}
CACHE_TTL_SECONDS = 15 * 60
MIN_FORCE_REFRESH_GAP_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 20
MAX_HTML_BYTES = 4 * 1024 * 1024

_CACHE: dict[str, Any] = {
    "items": [],
    "last_checked_at": None,
    "last_successful_fetch_at": None,
    "last_error": None,
    "archive_page_reachable": False,
}
_CACHE_LOCK = threading.Lock()


def _official_https_url(href: str, base_url: str = NCDC_ARCHIVE_URL) -> str | None:
    """Resolve a link but accept only HTTPS URLs on the official NCDC host."""
    if not href or href.strip().startswith(("#", "javascript:", "mailto:")):
        return None
    resolved = urljoin(base_url, href.strip())
    parsed = urlparse(resolved)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        return None
    return resolved


def _clean_label(value: str, max_chars: int = 220) -> str:
    return re.sub(r"\s+", " ", value or "").strip()[:max_chars].strip()


def _parse_year(text: str) -> int | None:
    # NCDC renders headings such as "2026 +", not just a bare year.
    match = re.search(r"\b(20\d{2})\b", text or "")
    return int(match.group(1)) if match else None


def _parse_week(text: str) -> int | None:
    value = _clean_label(text).lower()
    patterns = (
        r"\bweek\s*(\d{1,2})\b",
        r"\b(\d{1,2})(?:st|nd|rd|th)\s*week\b",
        r"^(\d{1,2})(?:st|nd|rd|th)$",
    )
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            week = int(match.group(1))
            return week if 1 <= week <= 53 else None
    return None


def _period_from_url(url: str) -> tuple[int | None, int | None]:
    path = urlparse(url).path
    match = re.search(r"/weekly_outbreaks/(20\d{2})/week(\d{1,2})[_\-.]", path, re.I)
    if not match:
        return None, None
    year, week = int(match.group(1)), int(match.group(2))
    return year, (week if 1 <= week <= 53 else None)


class _LinkCollector(HTMLParser):
    """Collect official report links and attach year/week from page context/URL."""

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[dict[str, Any]] = []
        self.current_year: int | None = None
        self._href: str | None = None
        self._anchor_parts: list[str] = []
        self._anchor_year_before: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            attr_map = dict(attrs)
            self._href = attr_map.get("href")
            self._anchor_parts = []
            self._anchor_year_before = self.current_year

    def handle_data(self, data: str) -> None:
        value = _clean_label(data, 500)
        if not value:
            return
        if self._href is not None:
            self._anchor_parts.append(value)
            return
        found_year = _parse_year(value)
        if found_year:
            self.current_year = found_year

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        label = _clean_label(" ".join(self._anchor_parts))
        url = _official_https_url(self._href, self.base_url)
        if url:
            url_year, url_week = _period_from_url(url)
            year = _parse_year(label) or self._anchor_year_before or self.current_year or url_year
            week = _parse_week(label) or url_week
            is_pdf = urlparse(url).path.lower().endswith(".pdf")
            looks_week_link = bool(re.search(r"\bweek\s*\d{1,2}\b|weekly\s+outbreak|outbreak\s+report", label, re.I))
            if is_pdf or looks_week_link:
                self.links.append({
                    "title": label or "NCDC Weekly Outbreak Report",
                    "url": url,
                    "year": year,
                    "week": week,
                    "report_type": "pdf" if is_pdf else "archive_entry",
                    "source": "National Centre for Disease Control (NCDC), Ministry of Health & Family Welfare; IDSP weekly outbreak report",
                })
        self._href = None
        self._anchor_parts = []
        self._anchor_year_before = None


def _parse_archive_html(html: str, base_url: str = NCDC_ARCHIVE_URL) -> list[dict[str, Any]]:
    parser = _LinkCollector(base_url)
    parser.feed(html)
    parser.close()
    # De-duplicate repeated anchor URLs in case page markup includes hidden copies.
    unique: dict[str, dict[str, Any]] = {}
    for item in parser.links:
        unique[item["url"]] = item
    return list(unique.values())


def _fetch_html(url: str) -> str:
    official_url = _official_https_url(url, NCDC_ARCHIVE_URL)
    if not official_url:
        raise ValueError("Refusing to fetch a non-NCDC URL")
    request = Request(
        official_url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "SamrakshaKendra-ResearchPrototype/1.0 (public report catalogue)",
        },
        method="GET",
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        final_url = _official_https_url(response.geturl(), NCDC_ARCHIVE_URL)
        if not final_url:
            raise ValueError("NCDC redirected to a non-NCDC host; fetch refused")
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"NCDC returned HTTP {response.status}")
        raw = response.read(MAX_HTML_BYTES + 1)
    if len(raw) > MAX_HTML_BYTES:
        raise RuntimeError("NCDC archive page exceeded the safety size limit")
    return raw.decode("utf-8", errors="replace")


def _report_title(row: dict[str, Any]) -> str:
    title = _clean_label(row.get("title") or "NCDC Weekly Outbreak Report")
    year, week = row.get("year"), row.get("week")
    if year and week and re.fullmatch(r"week\s*\d{1,2}", title, re.I):
        return f"NCDC Weekly Outbreak Report — {year} Week {week}"
    if year and week and str(year) not in title and "week" not in title.lower():
        return f"{title} — {year} Week {week}"
    return title


def _request_ncdc_reports() -> list[dict[str, Any]]:
    html = _fetch_html(NCDC_ARCHIVE_URL)
    links = _parse_archive_html(html, NCDC_ARCHIVE_URL)
    rows = [row for row in links if row["report_type"] == "pdf"]
    if not rows:
        # A reachable page without discoverable PDF links should be visible as a parser issue,
        # not mislabeled as an empty surveillance dataset.
        raise RuntimeError("NCDC archive reachable, but no official weekly PDF links were detected")

    for row in rows:
        row["title"] = _report_title(row)
        row["archive_url"] = NCDC_ARCHIVE_URL
        row["source"] = "National Centre for Disease Control (NCDC), Government of India — IDSP weekly outbreak reports"
    rows.sort(key=lambda item: (item.get("year") or 0, item.get("week") or 0, item["title"]), reverse=True)
    return rows[:100]


def _parse_cache_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _refresh_cache(force_refresh: bool) -> None:
    now = datetime.now(timezone.utc)
    with _CACHE_LOCK:
        last_success = _parse_cache_time(_CACHE.get("last_successful_fetch_at"))
        last_checked = _parse_cache_time(_CACHE.get("last_checked_at"))
        fresh = bool(last_success and (now - last_success).total_seconds() < CACHE_TTL_SECONDS)
        checked_too_recently = bool(last_checked and (now - last_checked).total_seconds() < MIN_FORCE_REFRESH_GAP_SECONDS)
        if fresh and (not force_refresh or checked_too_recently):
            return
        if checked_too_recently:
            return
        _CACHE["last_checked_at"] = now.isoformat()
        try:
            items = _request_ncdc_reports()
            _CACHE["items"] = items
            _CACHE["last_successful_fetch_at"] = datetime.now(timezone.utc).isoformat()
            _CACHE["last_error"] = None
            _CACHE["archive_page_reachable"] = True
        except (HTTPError, URLError, TimeoutError, RuntimeError, ValueError, UnicodeDecodeError) as exc:
            _CACHE["last_error"] = f"NCDC weekly-outbreak archive refresh failed ({type(exc).__name__})."
            _CACHE["archive_page_reachable"] = False


@router.get("/public/india-outbreak-reports", summary="Official NCDC/IDSP weekly outbreak report catalogue")
def public_india_outbreak_reports(
    limit: int = Query(default=30, ge=1, le=100),
    force_refresh: bool = Query(default=False),
):
    """Return official NCDC weekly outbreak PDF links, cached for 15 minutes."""
    _refresh_cache(force_refresh)
    with _CACHE_LOCK:
        items = list(_CACHE.get("items", []))
        checked = _CACHE.get("last_checked_at")
        successful = _CACHE.get("last_successful_fetch_at")
        error = _CACHE.get("last_error")
        reachable = bool(_CACHE.get("archive_page_reachable"))

    if items and not error:
        status = "available"
    elif items and error:
        status = "stale"
    elif reachable:
        status = "available"
    else:
        status = "unavailable"

    return {
        "status": status,
        "source": "National Centre for Disease Control (NCDC), Government of India — IDSP weekly outbreak reports",
        "source_url": NCDC_ARCHIVE_URL,
        "home_url": NCDC_HOME_URL,
        "items": items[:limit],
        "count": min(len(items), limit),
        "last_checked_at": checked,
        "last_successful_fetch_at": successful,
        "cache_ttl_seconds": CACHE_TTL_SECONDS,
        "refresh_interval_seconds": CACHE_TTL_SECONDS,
        "warning": (
            "This catalogue lists official weekly outbreak report PDFs. It does not automatically extract numeric case/death counts or import report rows into the surveillance database. Unknown counts remain unknown, not zero. These are periodic weekly reports, not a continuous live case-count feed."
        ),
        "source_error": error if status == "unavailable" else ("Refresh failed; showing the last successful cached copy." if status == "stale" else None),
    }
