"""Fetch and read official documents: PDFs (text or scanned), web pages and images.

Robustness features the demo relies on:
  * SSRF guard: never fetch private/loopback addresses, including after redirects.
  * Size cap, retries with backoff, and a fallback for government sites whose TLS
    certificate chain is incomplete (recorded on the card as tls_verified=false).
  * Scanned PDFs and legacy-font Hindi PDFs (Kruti Dev etc. extract as gibberish)
    are detected and sent through Tesseract OCR with automatic script detection.
  * Landing pages that only link to a PDF are followed one hop automatically.
"""
from __future__ import annotations

import hashlib
import io
import ipaddress
import socket
import time
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse

import httpx
import regex

from . import config
from .text_utils import clean_text, detect_script_lang

Trace = Optional[Callable[[dict], None]]


class IngestError(RuntimeError):
    pass


@dataclass
class FetchedDoc:
    data: bytes
    kind: str
    url: Optional[str] = None
    final_url: Optional[str] = None
    filename: Optional[str] = None
    content_type: str = ""
    tls_verified: bool = True
    followed_from: Optional[str] = None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    @property
    def domain(self) -> Optional[str]:
        u = self.final_url or self.url
        return urlparse(u).hostname if u else None


@dataclass
class ParsedDoc:
    pages: list[str]
    kind: str
    language: str = "en"
    ocr_used: bool = False
    ocr_pages: int = 0
    title_hint: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    pdf_links: list[tuple[str, str]] = field(default_factory=list)  # (url, anchor text) for HTML pages

    @property
    def text(self) -> str:
        return "\n\n".join(self.pages)


def _emit(trace: Trace, **event) -> None:
    if trace:
        trace({"type": "tool", **event})


# ------------------------------------------------------------------ fetch --
def _assert_public(url: str) -> None:
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        raise IngestError("Only http(s) links are supported.")
    host = u.hostname
    if not host:
        raise IngestError("That link has no host name.")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise IngestError(f"Could not find the website '{host}'. Check the link.") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise IngestError("Refusing to fetch an internal network address.")


def sniff_kind(data: bytes, content_type: str = "", name: str = "") -> str:
    ct = (content_type or "").lower()
    n = (name or "").lower()
    head = data[:2048].lstrip().lower()
    if data[:5] == b"%PDF-" or "application/pdf" in ct or n.endswith(".pdf"):
        return "pdf"
    if data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff" or ct.startswith("image/") \
            or n.endswith((".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff")):
        return "image"
    if "html" in ct or head.startswith((b"<!doctype html", b"<html")) or b"<html" in head or n.endswith((".htm", ".html")):
        return "html"
    if data[:4] == b"PK\x03\x04":
        return "unsupported"
    try:
        data[:4000].decode("utf-8")
        return "text"
    except UnicodeDecodeError:
        return "unsupported"


def fetch_url(url: str, trace: Trace = None) -> FetchedDoc:
    url = url.strip()
    if not urlparse(url).scheme:
        url = "https://" + url
    _assert_public(url)
    verify: bool | str = True
    tls_ok = True
    last_err = "unknown error"
    for attempt in range(3):
        try:
            with httpx.Client(
                follow_redirects=True, verify=verify,
                timeout=httpx.Timeout(35.0, connect=15.0),
                headers={"User-Agent": config.USER_AGENT, "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
                         "Accept": "text/html,application/pdf,application/xhtml+xml,*/*;q=0.8"},
                event_hooks={"request": [lambda req: _assert_public(str(req.url))]},
            ) as client:
                with client.stream("GET", url) as r:
                    if r.status_code >= 400:
                        if r.status_code >= 500 and attempt < 2:
                            last_err = f"HTTP {r.status_code}"
                            time.sleep(1.5 * (attempt + 1))
                            continue
                        raise IngestError(f"The website answered HTTP {r.status_code} for that link.")
                    buf = bytearray()
                    for chunk in r.iter_bytes():
                        buf += chunk
                        if len(buf) > config.MAX_DOWNLOAD_BYTES:
                            raise IngestError("Document is larger than 25 MB.")
                    ct = r.headers.get("content-type", "")
                    final = str(r.url)
                    name = urlparse(final).path.rsplit("/", 1)[-1]
                    kind = sniff_kind(bytes(buf), ct, name)
                    _emit(trace, tool="fetch", status="ok",
                          detail=f"{len(buf) / 1024:.0f} KB {kind.upper()} from {urlparse(final).hostname}"
                                 + ("" if tls_ok else " (TLS chain incomplete)"))
                    return FetchedDoc(bytes(buf), kind, url=url, final_url=final, filename=name or None,
                                      content_type=ct, tls_verified=tls_ok)
        except IngestError:
            raise
        except httpx.ConnectError as e:
            msg = str(e)
            if ("CERTIFICATE_VERIFY_FAILED" in msg or "certificate" in msg.lower()) and verify is not False:
                # Many .gov.in sites ship an incomplete certificate chain. Retry without
                # verification and record it; the document hash is stored on the card.
                verify, tls_ok = False, False
                _emit(trace, tool="fetch", status="warn", detail="Site's TLS certificate chain is incomplete; retrying")
                continue
            last_err = "connection failed"
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as e:
            last_err = type(e).__name__
        _emit(trace, tool="fetch", status="retry", detail=f"attempt {attempt + 1} failed: {last_err}")
        time.sleep(1.5 * (attempt + 1))
    raise IngestError(f"Could not download the document ({last_err}). The site may be down or blocking "
                      "cloud servers; try uploading the PDF instead.")


# ------------------------------------------------------------------ parse --
LEGACY_MARKERS = ["vkSj", "ljdkj", "Hkkjr", " gS", "esa ", " dk ", " ds ", " dh ", " dks ", "fd;k",
                  "izns'k", ";kstuk", "fu;e", "vf/kd", "ykHk"]


def looks_legacy_font(text: str) -> bool:
    """Detect Hindi typed in legacy fonts (Kruti Dev/DevLys) that extract as Latin gibberish."""
    if len(text) < 200:
        return False
    deva = len(regex.findall(r"\p{Devanagari}", text))
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    if deva > 0.2 * max(latin, 1):
        return False
    hits = sum(text.count(m) for m in LEGACY_MARKERS)
    return hits / (len(text) / 1000) > 3


_SCRIPT_TO_TESS = {"Devanagari": "hin", "Bengali": "ben", "Tamil": "tam", "Telugu": "tel", "Gujarati": "guj",
                   "Kannada": "kan", "Malayalam": "mal", "Gurmukhi": "pan", "Oriya": "ori", "Arabic": "urd"}


def _tess_langs() -> set[str]:
    try:
        import pytesseract
        return set(pytesseract.get_languages(config=""))
    except Exception:
        return set()


def ocr_image(img, trace: Trace = None, lang: Optional[str] = None) -> tuple[str, str]:
    """OCR a PIL image. Detects the script first (Tesseract OSD) when no hint is given."""
    import pytesseract
    available = _tess_langs()
    if not available:
        raise IngestError("OCR engine is not installed on this server.")
    if not lang:
        lang = "eng+hin" if "hin" in available else "eng"
        try:
            osd = pytesseract.image_to_osd(img, config="--psm 0 -c min_characters_to_try=20")
            m = regex.search(r"Script:\s*(\w+)", osd)
            script = m.group(1) if m else ""
            code = _SCRIPT_TO_TESS.get(script)
            if code and code in available:
                lang = f"{code}+eng"
        except Exception:
            pass
    lang = "+".join(x for x in lang.split("+") if x in available) or "eng"
    text = pytesseract.image_to_string(img, lang=lang, config="--psm 3")
    return text, lang


def parse_pdf(data: bytes, trace: Trace = None) -> ParsedDoc:
    import pypdfium2 as pdfium
    try:
        pdf = pdfium.PdfDocument(data)
    except Exception as e:
        raise IngestError("This PDF could not be opened (it may be corrupt or password-protected).") from e
    n = len(pdf)
    pages: list[str] = []
    for i in range(min(n, config.MAX_PDF_PAGES)):
        page = pdf[i]
        tp = page.get_textpage()
        pages.append(clean_text(tp.get_text_range()))
        tp.close()
        page.close()
    title = None
    try:
        meta = pdf.get_metadata_dict()
        title = (meta.get("Title") or "").strip() or None
    except Exception:
        pass
    warnings: list[str] = []
    if n > config.MAX_PDF_PAGES:
        warnings.append(f"Only the first {config.MAX_PDF_PAGES} of {n} pages were read.")
    weak = [i for i, p in enumerate(pages) if len(p) < 80 or looks_legacy_font(p)]
    legacy = any(looks_legacy_font(p) for p in pages)
    ocr_pages = 0
    if pages and len(weak) >= max(1, len(pages) // 2):
        reason = "legacy Hindi font detected" if legacy else "scanned pages detected"
        _emit(trace, tool="ocr", status="start", detail=f"{reason}; running OCR on up to {config.MAX_OCR_PAGES} pages")
        lang = None
        for i in weak[: config.MAX_OCR_PAGES]:
            try:
                img = pdf[i].render(scale=2.6).to_pil()
                txt, lang = ocr_image(img, trace, lang)
                pages[i] = clean_text(txt)
                ocr_pages += 1
                _emit(trace, tool="ocr", status="ok", detail=f"page {i + 1}: {len(pages[i])} chars ({lang})")
            except IngestError:
                raise
            except Exception as e:
                _emit(trace, tool="ocr", status="warn", detail=f"page {i + 1} failed: {type(e).__name__}")
        if len(weak) > config.MAX_OCR_PAGES:
            warnings.append(f"OCR limited to {config.MAX_OCR_PAGES} pages.")
    pdf.close()
    text = "\n".join(pages)
    return ParsedDoc(pages=pages, kind="pdf", language=detect_script_lang(text), ocr_used=ocr_pages > 0,
                     ocr_pages=ocr_pages, title_hint=title, warnings=warnings)


PDF_LINK_HINTS = ("guideline", "scheme", "notification", "yojana", "rules", "circular", "order", "gazette",
                  "policy", "act", "bye", "दिशा", "योजना", "अधिसूचना", "नियम", "शासनादेश")


def _decode_html(data: bytes) -> str:
    m = regex.search(rb'charset=["\']?([A-Za-z0-9_\-]+)', data[:3000])
    for enc in ([m.group(1).decode()] if m else []) + ["utf-8", "windows-1252"]:
        try:
            return data.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", "ignore")


def parse_html(data: bytes, url: Optional[str] = None) -> ParsedDoc:
    from bs4 import BeautifulSoup
    html = _decode_html(data)
    text = ""
    try:
        import trafilatura
        text = trafilatura.extract(html, include_tables=True, include_comments=False, favor_recall=True,
                                   url=url) or ""
    except Exception:
        text = ""
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else None
    links: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if ".pdf" in href.lower():
            links.append((urljoin(url or "", href), a.get_text(" ", strip=True)[:120]))
    if len(text) < 300:
        for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "form"]):
            tag.decompose()
        alt = soup.get_text("\n")
        if len(alt) > len(text):
            text = alt
    text = clean_text(text)
    return ParsedDoc(pages=[text], kind="html", language=detect_script_lang(text), title_hint=title,
                     pdf_links=links)


def best_pdf_link(links: list[tuple[str, str]]) -> Optional[str]:
    if not links:
        return None
    for href, anchor in links:
        blob = (href + " " + anchor).lower()
        if any(h in blob for h in PDF_LINK_HINTS):
            return href
    return links[0][0]


def parse_document(doc: FetchedDoc, trace: Trace = None) -> ParsedDoc:
    if doc.kind == "pdf":
        parsed = parse_pdf(doc.data, trace)
    elif doc.kind == "html":
        parsed = parse_html(doc.data, doc.final_url or doc.url)
    elif doc.kind == "image":
        from PIL import Image
        try:
            img = Image.open(io.BytesIO(doc.data))
            img.load()
        except Exception as e:
            raise IngestError("This image could not be opened.") from e
        _emit(trace, tool="ocr", status="start", detail="image document; running OCR")
        txt, lang = ocr_image(img.convert("RGB"), trace)
        txt = clean_text(txt)
        _emit(trace, tool="ocr", status="ok", detail=f"{len(txt)} chars ({lang})")
        parsed = ParsedDoc(pages=[txt], kind="image", language=detect_script_lang(txt), ocr_used=True, ocr_pages=1)
    elif doc.kind == "text":
        txt = clean_text(doc.data.decode("utf-8", "ignore"))
        parsed = ParsedDoc(pages=[txt], kind="text", language=detect_script_lang(txt))
    else:
        raise IngestError("Unsupported file type. Please use a PDF, a web page link, an image or a text file.")
    return parsed


INJECTION_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above) instructions", r"disregard (the|all) (above|previous)",
    r"you are now", r"system prompt", r"act as an? (ai|assistant)", r"reveal your (instructions|prompt)",
]


def injection_warnings(text: str) -> list[str]:
    hits = [p for p in INJECTION_PATTERNS if regex.search(p, text, flags=regex.I)]
    return ["The document contains text that looks like instructions to an AI system; it was treated as data "
            "and every claim was verified against the source."] if hits else []
