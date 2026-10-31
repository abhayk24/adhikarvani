"""Split a document into citable clauses.

Each clause gets a stable id (C1, C2, ...), its page number and the nearest
heading. Claims must cite one of these ids, which is what makes every answer
traceable back to a page of the original document.
"""
from __future__ import annotations

import regex

from . import config
from .models import Clause

ENUM_RE = regex.compile(
    r"^\s*(?:"
    r"\(?[0-9०-९]{1,3}(?:\.[0-9०-९]{1,3}){0,3}[.)]\s"      # 1. 2.1 (3)
    r"|\(?[a-zA-Z]\)\s|[a-zA-Z]\.\s"                        # (a) a.
    r"|\((?:i|ii|iii|iv|v|vi|vii|viii|ix|x|xi|xii)\)\s"     # (iv)
    r"|[•●▪■◆►✓\-–]\s"                                      # bullets
    r"|\(?[क-ह]\)\s|[क-ह]\.\s"                              # (क) क.
    r")"
)
SENTENCE_END = regex.compile(r"(?<=[.!?।॥])\s+")
HEADING_WORDS = ("eligibility", "objective", "benefit", "scope", "definition", "procedure", "documents",
                 "exclusion", "penalty", "application", "introduction", "background", "funding", "implementation",
                 "पात्रता", "उद्देश्य", "लाभ", "प्रक्रिया", "दस्तावेज", "आवेदन", "परिभाषा", "दंड", "अपात्रता")


def is_heading(line: str) -> bool:
    s = line.strip()
    if not (3 <= len(s) <= 90) or s.endswith((".", ",", ";", "।")):
        return False
    body = regex.sub(r"^(?:[0-9]{1,2}(?:\.[0-9]{1,2})*\.?|[IVX]{1,5}\.)\s*", "", s)
    if regex.search(r"\d", body):
        return False
    words = body.split()
    if not words or len(words) > 10:
        return False
    letters = [c for c in body if c.isalpha()]
    if letters and all(c.isupper() for c in letters if c.isascii()) and sum(c.isascii() for c in letters) >= 4:
        return True
    low = body.lower().rstrip(":")
    if body.endswith(":") and len(words) <= 6:
        return True
    return any(low.startswith(h) or low == h for h in HEADING_WORDS) and len(words) <= 6


def _split_long(text: str, max_len: int = 900) -> list[str]:
    if len(text) <= max_len:
        return [text]
    parts, cur = [], ""
    for sent in SENTENCE_END.split(text):
        if cur and len(cur) + len(sent) + 1 > max_len:
            parts.append(cur.strip())
            cur = sent
        else:
            cur = f"{cur} {sent}" if cur else sent
    if cur.strip():
        parts.append(cur.strip())
    out = []
    for p in parts:  # sentences longer than max_len (tables, run-on text)
        while len(p) > max_len * 1.5:
            cut = p.rfind(" ", 0, max_len)
            cut = cut if cut > max_len // 2 else max_len
            out.append(p[:cut].strip())
            p = p[cut:].strip()
        out.append(p)
    return [p for p in out if p]


def segment(pages: list[str]) -> list[Clause]:
    clauses: list[Clause] = []
    section: str | None = None
    carry = ""          # tiny fragment waiting to be merged into the next clause
    carry_page = 1

    def add(text: str, page: int) -> None:
        nonlocal carry, carry_page
        text = " ".join(text.split())
        if not text:
            return
        if carry:
            text = f"{carry} {text}"
            page = carry_page
            carry = ""
        if len(text) < 40:
            carry, carry_page = text, page
            return
        for piece in _split_long(text):
            if len(clauses) >= config.MAX_CLAUSES:
                return
            clauses.append(Clause(id=f"C{len(clauses) + 1}", text=piece, page=page, section=section))

    for pno, page_text in enumerate(pages, start=1):
        block: list[str] = []
        for raw in page_text.split("\n"):
            line = raw.strip()
            if not line:
                if block:
                    add(" ".join(block), pno)
                    block = []
                continue
            if is_heading(line):
                if block:
                    add(" ".join(block), pno)
                    block = []
                section = line.strip(" :.-–")[:80]
                continue
            if ENUM_RE.match(line) and block:
                add(" ".join(block), pno)
                block = []
            block.append(line)
        if block:
            add(" ".join(block), pno)
    if carry:
        if clauses and len(carry) < 40:
            last = clauses[-1]
            clauses[-1] = Clause(id=last.id, text=f"{last.text} {carry}", page=last.page, section=last.section)
        else:
            clauses.append(Clause(id=f"C{len(clauses) + 1}", text=carry, page=carry_page, section=section))
    return clauses
