"""Unicode-aware text helpers shared by retrieval, verification and the agent.

Indian documents mix scripts (Devanagari, Bengali, Tamil, ...), Indic digits and
Indian number words (lakh, crore). Python's built-in ``\\w`` splits Devanagari
words at vowel signs, so we use the ``regex`` module with Unicode classes.
"""
from __future__ import annotations

import unicodedata

import regex

# Indic digit blocks -> ASCII digits
_DIGIT_BLOCKS = [0x0966, 0x09E6, 0x0A66, 0x0AE6, 0x0B66, 0x0BE6, 0x0C66, 0x0CE6, 0x0D66, 0x0660, 0x06F0]
DIGIT_MAP = {start + i: str(i) for start in _DIGIT_BLOCKS for i in range(10)}

_WORD = regex.compile(r"[\p{L}\p{M}\p{N}]+")
_NON_WORD = regex.compile(r"[^\p{L}\p{M}\p{N}]+")
_ZERO_WIDTH = regex.compile(r"[​-‍﻿]")

SCRIPT_RANGES = [
    ("hi", 0x0900, 0x097F),  # Devanagari (Hindi, Marathi, ...)
    ("bn", 0x0980, 0x09FF),
    ("pa", 0x0A00, 0x0A7F),
    ("gu", 0x0A80, 0x0AFF),
    ("or", 0x0B00, 0x0B7F),
    ("ta", 0x0B80, 0x0BFF),
    ("te", 0x0C00, 0x0C7F),
    ("kn", 0x0C80, 0x0CFF),
    ("ml", 0x0D00, 0x0D7F),
    ("ur", 0x0600, 0x06FF),
]


def to_ascii_digits(text: str) -> str:
    return text.translate(DIGIT_MAP)


def normalize_for_match(text: str) -> str:
    """Canonical form used to compare a quote with the source text."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = _ZERO_WIDTH.sub("", t)
    t = to_ascii_digits(t).lower()
    t = _NON_WORD.sub(" ", t)
    return " ".join(t.split())


def tokenize(text: str) -> list[str]:
    """Word tokens for BM25 (keeps Devanagari vowel signs inside words)."""
    t = to_ascii_digits(unicodedata.normalize("NFKC", text or "")).lower()
    return [w for w in _WORD.findall(t) if len(w) > 1 or w.isdigit()]


def detect_script_lang(text: str) -> str:
    """Rough language guess from the dominant script ('en' for Latin)."""
    counts: dict[str, int] = {}
    latin = 0
    for ch in text[:20000]:
        cp = ord(ch)
        if ch.isascii():
            if ch.isalpha():
                latin += 1
            continue
        for lang, lo, hi in SCRIPT_RANGES:
            if lo <= cp <= hi:
                counts[lang] = counts.get(lang, 0) + 1
                break
    if not counts:
        return "en"
    lang, n = max(counts.items(), key=lambda kv: kv[1])
    return lang if n >= 0.25 * (latin + n) else "en"


def clean_text(text: str) -> str:
    """Normalise whitespace and fix hyphenated line breaks from PDFs."""
    t = unicodedata.normalize("NFC", text or "")
    t = t.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n")
    t = _ZERO_WIDTH.sub("", t)
    t = regex.sub(r"(\p{Ll})-\n(\p{Ll})", r"\1\2", t)  # eligi-\nble -> eligible
    t = regex.sub(r"[ \t ]+", " ", t)
    t = regex.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


# ---------------------------------------------------------------- numbers --
MULTIPLIERS = {
    "thousand": 1e3, "hazar": 1e3, "hazaar": 1e3, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5,
    "crore": 1e7, "crores": 1e7, "million": 1e6, "billion": 1e9, "k": 1e3,
    "हजार": 1e3, "हज़ार": 1e3, "लाख": 1e5, "करोड़": 1e7, "करोड": 1e7, "कोटी": 1e7,
    "হাজার": 1e3, "লাখ": 1e5, "লক্ষ": 1e5, "কোটি": 1e7,
    "ஆயிரம்": 1e3, "லட்சம்": 1e5, "கோடி": 1e7,
    "వేలు": 1e3, "వేల": 1e3, "లక్ష": 1e5, "లక్షలు": 1e5, "కోట్లు": 1e7, "కోట్ల": 1e7,
    "હજાર": 1e3, "લાખ": 1e5, "કરોડ": 1e7,
    "ಸಾವಿರ": 1e3, "ಲಕ್ಷ": 1e5, "ಕೋಟಿ": 1e7,
    "ആയിരം": 1e3, "ലക്ഷം": 1e5, "കോടി": 1e7,
    "ਹਜ਼ਾਰ": 1e3, "ਲੱਖ": 1e5, "ਕਰੋੜ": 1e7,
    "ہزار": 1e3, "لاکھ": 1e5, "کروڑ": 1e7,
}
_NUM = regex.compile(r"(?<![\p{L}\p{N}])(\d[\d,]*(?:\.\d+)?)\s*([\p{L}\p{M}]+)?")
_DATE = regex.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})(?!\d)")


def extract_numbers(text: str, lenient: bool = False) -> set[float]:
    """Numbers mentioned in text, with '2.5 lakh' -> 250000.

    lenient=True also keeps the bare number before a multiplier word; used for
    the *source* side so a check never fails because of formatting.
    Dates like 31.03.2025 contribute 31, 3 and 2025.
    """
    t = to_ascii_digits(unicodedata.normalize("NFKC", text or ""))
    out: set[float] = set()
    for d in _DATE.finditer(t):
        out.update(float(x) for x in d.groups())
    t = _DATE.sub(" ", t)
    for m in _NUM.finditer(t):
        raw = m.group(1).rstrip(",").replace(",", "")
        try:
            val = float(raw)
        except ValueError:
            continue
        word = (m.group(2) or "").lower()
        mult = MULTIPLIERS.get(word)
        if mult:
            out.add(round(val * mult, 2))
            if lenient:
                out.add(val)
        else:
            out.add(val)
    return out


def unsupported_numbers(generated: str, source_texts, min_value: float = 10) -> list[str]:
    """Numbers (>= min_value) that appear in generated text but nowhere in the sources.

    Amounts, ages and dates are the most harmful hallucinations in a rights
    explainer, so every number we speak must exist in the verified source.
    """
    source: set[float] = set()
    for s in source_texts:
        source |= extract_numbers(s, lenient=True)
    bad = []
    for n in sorted(extract_numbers(generated)):
        if n < min_value:
            continue
        if not any(abs(n - s) <= 1e-6 * max(1.0, abs(n)) for s in source):
            bad.append(f"{n:g}")
    return bad


def slugify(text: str, max_len: int = 48) -> str:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    t = regex.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return (t[:max_len].rstrip("-")) or "policy"
