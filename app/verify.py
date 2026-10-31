"""Deterministic verification: the 'hallucination firewall'.

An LLM may only state a fact if it can point to the exact words in the document
that prove it. Here we check those words really exist, with tolerance only for
whitespace/punctuation/OCR noise. Claims that cite the wrong clause but quote
real text elsewhere are relocated to the right clause instead of being lost.
"""
from __future__ import annotations

from rapidfuzz import fuzz, process

from .models import Claim, Clause, Verification
from .text_utils import normalize_for_match

EXACT, FUZZY, RELOCATED = "exact", "fuzzy", "relocated"
FUZZY_MIN = 90.0
RELOCATE_MIN = 92.0


class ClauseIndex:
    def __init__(self, clauses: list[Clause]):
        self.clauses = clauses
        self.pos = {c.id: i for i, c in enumerate(clauses)}
        self.norm = [normalize_for_match(c.text) for c in clauses]

    def window(self, i: int) -> str:
        """Clause plus neighbours, because quotes sometimes straddle a split point."""
        lo, hi = max(0, i - 1), min(len(self.clauses), i + 2)
        return " ".join(self.norm[lo:hi])


def _match(q: str, text: str) -> float:
    if not q or not text:
        return 0.0
    if q in text:
        return 100.0
    if len(text) < len(q):
        return float(fuzz.ratio(q, text))
    return float(fuzz.partial_ratio(q, text))


def verify_quote(claim: Claim, idx: ClauseIndex) -> Verification:
    q = normalize_for_match(claim.quote)
    if len(q) < 12 or len(q.split()) < 3:
        return Verification(quote_found=False, reason="Quote too short to be a verifiable citation")
    i = idx.pos.get(claim.clause_id)
    if i is not None:
        own = idx.norm[i]
        if q in own:
            return Verification(quote_found=True, method=EXACT, score=100.0)
        s = _match(q, idx.window(i))
        if s >= FUZZY_MIN:
            return Verification(quote_found=True, method=FUZZY, score=s)
    # Wrong clause id? Look for the quote anywhere in the document.
    best = process.extractOne(q, idx.norm, scorer=fuzz.partial_ratio,
                              processor=None, score_cutoff=RELOCATE_MIN)
    if best:
        _, score, j = best
        if len(idx.norm[j]) >= 0.8 * len(q) or q in idx.norm[j]:
            claim.clause_id = idx.clauses[j].id
            return Verification(quote_found=True, method=RELOCATED, score=float(score),
                                reason=f"quote found in {claim.clause_id}")
    return Verification(quote_found=False, score=0.0, reason="Quote not found in the document")


def evidence_in(evidence: str, transcript: str) -> bool:
    """Is a fact's evidence really in what the citizen said? (blocks invented profile facts)"""
    e, t = normalize_for_match(evidence), normalize_for_match(transcript)
    if not e or not t:
        return False
    if e in t:
        return True
    if len(e) < 6:
        return e in t.split()
    return fuzz.partial_ratio(e, t) >= 85
