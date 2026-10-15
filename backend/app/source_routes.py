"""Cached proxy for the WHO public Disease Outbreak News feed.

This is a public publication feed, not a case-level surveillance API. The cache
limits upstream requests and keeps the React client from calling WHO directly.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import APIRouter, Query

router = APIRouter(tags=["Public Source Feeds"])

WHO_API_BASE = "https://www.who.int/api/hubs/diseaseoutbreaknews"
WHO_DON_PAGE = "https://www.who.int/emergencies/disease-outbreak-news"
CACHE_TTL_SECONDS = 10 * 60
MIN_FORCE_REFRESH_GAP_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 20
MAX_UPSTREAM_ITEMS = 100

_CACHE: dict[str, Any] = {
    "items": [],
    "last_checked_at": None,
    "last_successful_fetch_at": None,
    "last_error": None,
}
_CACHE_LOCK = threading.Lock()


class _PlainTextParser(HTMLParser):
    """Extract readable text while excluding script/style content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._suppressed = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._suppressed += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._suppressed:
            self._suppressed -= 1

    def handle_data(self, data: str) -> None:
        if not self._suppressed and data.strip():
            self.parts.append(data.strip())


def _plain_text(value: Any, max_chars: int = 520) -> str:
    if not value:
        return ""
    parser = _PlainTextParser()
    try:
        parser.feed(str(value))
        parser.close()
        text = " ".join(parser.parts)
    except Exception:
        text = re.sub(r"<[^>]*>", " ", str(value))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 1].rsplit(" ", 1)[0] + "…"
    return text


def _parse_datetime(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _publication_datetime(row: dict[str, Any]) -> datetime | None:
    for key in ("PublicationDateAndTime", "PublicationDate", "DateCreated", "LastModified"):
        parsed = _parse_datetime(row.get(key))
        if parsed is not None:
            return parsed
    return None


def _detail_url(row: dict[str, Any]) -> str:
    """Build the official WHO DON detail URL only from a safe report slug."""
    direct = row.get("ItemDefaultUrl")
    if isinstance(direct, str) and direct.startswith("https://www.who.int/"):
        return direct
    slug = row.get("UrlName")
    if isinstance(slug, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,160}", slug):
        return f"{WHO_DON_PAGE}/item/{slug}"
    return WHO_DON_PAGE


def _normalise_rows(payload: Any) -> list[dict[str, Any]]:
    raw_items = payload.get("value", []) if isinstance(payload, dict) else payload
    if not isinstance(raw_items, list):
        raise ValueError("WHO response did not contain an item list")

    normalised: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in raw_items:
        if not isinstance(row, dict):
            continue
        title = row.get("OverrideTitle") if row.get("UseOverrideTitle") else row.get("Title")
        title = str(title or row.get("Title") or row.get("UrlName") or "WHO outbreak notice").strip()
        published = _publication_datetime(row)
        slug = str(row.get("UrlName") or row.get("DonId") or row.get("Id") or title)
        stable_id = str(row.get("Id") or row.get("DonId") or slug)
        if stable_id in seen:
            continue
        seen.add(stable_id)

        summary = _plain_text(row.get("Summary"))
        if not summary:
            summary = _plain_text(row.get("Overview") or row.get("Response") or row.get("Epidemiology"))
        normalised.append({
            "id": stable_id,
            "title": title,
            "summary": summary or "The WHO report does not provide a short summary in the feed. Open the source report for details.",
            "publication_date": published.isoformat() if published else None,
            "source": "WHO Disease Outbreak News",
            "url": _detail_url(row),
        })

    normalised.sort(
        key=lambda item: item["publication_date"] or "",
        reverse=True,
    )
    return normalised


def _request_who_feed() -> list[dict[str, Any]]:
    # WHO documents the public /api/hubs/diseaseoutbreaknews endpoint. Sitefinity's
    # OData options request the newest publications first; if unsupported, fall back
    # to the base collection and sort the returned records locally.
    query = urlencode({"$orderby": "PublicationDateAndTime desc", "$top": str(MAX_UPSTREAM_ITEMS)})
    urls = [f"{WHO_API_BASE}?{query}", WHO_API_BASE]
    last_exception: Exception | None = None

    for url in urls:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "SamrakshaKendra-ResearchPrototype/1.0",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                if response.status < 200 or response.status >= 300:
                    raise RuntimeError(f"WHO feed returned HTTP {response.status}")
                payload = json.loads(response.read().decode("utf-8"))
            rows = _normalise_rows(payload)
            if not rows and url == urls[0]:
                continue
            return rows[:MAX_UPSTREAM_ITEMS]
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError, RuntimeError, ValueError) as exc:
            last_exception = exc
            continue

    if last_exception:
        raise RuntimeError(f"Unable to refresh WHO public feed ({type(last_exception).__name__})") from last_exception
    raise RuntimeError("WHO public feed is temporarily unavailable")


def _refresh_cache(force_refresh: bool) -> None:
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    with _CACHE_LOCK:
        last_success = _parse_datetime(_CACHE.get("last_successful_fetch_at"))
        last_checked = _parse_datetime(_CACHE.get("last_checked_at"))
        fresh = bool(last_success and (now - last_success).total_seconds() < CACHE_TTL_SECONDS)
        checked_too_recently = bool(last_checked and (now - last_checked).total_seconds() < MIN_FORCE_REFRESH_GAP_SECONDS)
        forced_too_soon = bool(force_refresh and checked_too_recently)
        if fresh and (not force_refresh or forced_too_soon):
            return
        # Avoid hammering the upstream feed during an outage.
        if checked_too_recently:
            return
        _CACHE["last_checked_at"] = now_iso
        try:
            items = _request_who_feed()
            _CACHE["items"] = items
            _CACHE["last_successful_fetch_at"] = datetime.now(timezone.utc).isoformat()
            _CACHE["last_error"] = None
        except Exception as exc:  # a public info page must degrade gracefully if source is unavailable
            _CACHE["last_error"] = str(exc)


@router.get("/public/global-outbreaks", summary="Latest public WHO outbreak notices")
def public_global_outbreaks(
    limit: int = Query(default=25, ge=1, le=50),
    force_refresh: bool = Query(default=False),
):
    """Return cached WHO publication notices; it does not represent live case counts."""
    _refresh_cache(force_refresh)
    with _CACHE_LOCK:
        items = list(_CACHE.get("items", []))
        fetched_at = _CACHE.get("last_successful_fetch_at")
        checked_at = _CACHE.get("last_checked_at")
        error = _CACHE.get("last_error")

    if items and error:
        status = "stale"
    elif items:
        status = "available"
    else:
        status = "unavailable"

    return {
        "status": status,
        "source": "WHO Disease Outbreak News",
        "source_url": WHO_DON_PAGE,
        "api_url": WHO_API_BASE,
        "items": items[:limit],
        "count": min(len(items), limit),
        "last_checked_at": checked_at,
        "last_successful_fetch_at": fetched_at,
        "cache_ttl_seconds": CACHE_TTL_SECONDS,
        "refresh_interval_seconds": CACHE_TTL_SECONDS,
        "warning": (
            "WHO notices update when WHO publishes them. This feed is not a continuous or district-level case-count stream."
            if status != "unavailable" else
            "WHO feed is unavailable right now. Existing IDSP historical data remains available."
        ),
        "source_error": error if status == "unavailable" else ("Refresh failed; showing the last successful cached copy." if status == "stale" else None),
    }
