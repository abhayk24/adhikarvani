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
from .text_utils import detect_script_lang

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


def _fetch_feed(url: str) -> list[dict]:
    import feedparser
    parsed = feedparser.parse(_get(url))
    items = []
    for e in parsed.entries:
        link = (e.get("link") or "").strip().replace("http://", "https://")
        if not link:
            continue
        pub: Optional[str] = None
        if e.get("published_parsed"):
            pub = datetime(*e.published_parsed[:6], tzinfo=timezone.utc).isoformat()
        title = _strip(e.get("title", ""))[:300]
        items.append({"title": title, "link": link, "published": pub, "summary": _strip(e.get("summary", ""))[:300],
                      "lang": "hi" if detect_script_lang(title) == "hi" else "en"})
    return items


def pib_feed(lang: str = "en", limit: int = 30) -> dict:
    """Latest PIB releases in the requested language.

    PIB's feeds do not always respect their language parameter, so both feeds are
    read, merged, and each release is sorted into English or Hindi by its script.
    """
    lang = lang if lang in PIB_FEEDS else "en"
    with _lock:
        hit = _cache.get("all")
    if hit and time.time() - hit[0] < TTL:
        merged, fetched_at, stale = hit[1]["items"], hit[1]["fetched_at"], False
    else:
        merged, errors, seen = [], [], set()
        for url in PIB_FEEDS.values():
            try:
                for it in _fetch_feed(url):
                    if it["link"] not in seen:
                        seen.add(it["link"])
                        merged.append(it)
            except SourceError as e:
                errors.append(str(e))
        if merged:
            merged.sort(key=lambda it: it["published"] or "", reverse=True)
            fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            with _lock:
                _cache["all"] = (time.time(), {"items": merged, "fetched_at": fetched_at})
            stale = False
        elif hit:  # PIB is down: serve the last good copy
            merged, fetched_at, stale = hit[1]["items"], hit[1]["fetched_at"], True
        else:
            raise SourceError("; ".join(errors) or "PIB feed returned no items")
    chosen = [it for it in merged if it["lang"] == lang]
    note = None
    if not chosen:
        chosen, note = merged, f"PIB has no {'English' if lang == 'en' else 'Hindi'} releases in its feed right now"
    return {"source": "https://pib.gov.in (RSS)", "lang": lang, "items": chosen[:limit], "fetched_at": fetched_at,
            "stale": stale, "note": note}
