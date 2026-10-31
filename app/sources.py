"""Live official sources: the Press Information Bureau (PIB) release feed.

PIB publishes every Government of India press release as RSS, in English and
Hindi. The "Civic Pulse" screen reads it live, and any release can be compiled
into a Rights Card with one click.
"""
from __future__ import annotations

import html
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
import regex

from . import config

PIB_FEEDS = {
    "en": "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3",
    "hi": "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=2&Regid=3",
}
_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()
TTL = 600


class SourceError(RuntimeError):
    pass


def _get(url: str) -> bytes:
    last = ""
    for verify in (True, False):  # some government servers ship incomplete TLS chains
        try:
            r = httpx.get(url, timeout=25, follow_redirects=True, verify=verify,
                          headers={"User-Agent": config.USER_AGENT, "Accept": "application/rss+xml, application/xml, */*"})
            r.raise_for_status()
            return r.content
        except httpx.ConnectError as e:
            last = str(e)
            if "certificate" not in last.lower():
                break
        except httpx.HTTPError as e:
            last = type(e).__name__
            break
    raise SourceError(f"PIB feed unreachable ({last[:80]})")


def _strip(s: str) -> str:
    return " ".join(html.unescape(regex.sub(r"<[^>]+>", " ", s or "")).split())


def pib_feed(lang: str = "en", limit: int = 30) -> dict:
    lang = lang if lang in PIB_FEEDS else "en"
    with _lock:
        hit = _cache.get(lang)
        if hit and time.time() - hit[0] < TTL:
            return hit[1] | {"cached": True}
    import feedparser
    url = PIB_FEEDS[lang]
    try:
        parsed = feedparser.parse(_get(url))
    except SourceError:
        if hit:  # serve the last good copy when PIB is down
            return hit[1] | {"cached": True, "stale": True}
        raise
    items = []
    for e in parsed.entries[:limit]:
        link = (e.get("link") or "").strip().replace("http://", "https://")
        if not link:
            continue
        pub: Optional[str] = None
        if e.get("published_parsed"):
            pub = datetime(*e.published_parsed[:6], tzinfo=timezone.utc).isoformat()
        items.append({"title": _strip(e.get("title", ""))[:300], "link": link, "published": pub,
                      "summary": _strip(e.get("summary", ""))[:300]})
    if not items:
        if hit:
            return hit[1] | {"cached": True, "stale": True}
        raise SourceError("PIB feed returned no items")
    out = {"source": url, "lang": lang, "items": items,
           "fetched_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    with _lock:
        _cache[lang] = (time.time(), out)
    return out | {"cached": False}
