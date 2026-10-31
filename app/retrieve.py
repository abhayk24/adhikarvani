"""Intent-aware BM25 retrieval with provider-sized context packing.

Long laws can have thousands of clauses but a free-tier model can only read a
few thousand tokens. We rank clauses against eight citizen intents (eligibility,
exclusions, benefits, documents, process, deadlines, obligations, rights) in
English and Hindi, fuse the rankings (reciprocal rank fusion) and pack the best
clauses into whatever character budget the chosen model allows, keeping the
original document order so the model still reads coherent text.
"""
from __future__ import annotations

import math
from collections import Counter

from .models import Clause
from .text_utils import tokenize

INTENTS: dict[str, str] = {
    "eligibility": "eligible eligibility criteria who can apply beneficiary beneficiaries qualify age years income "
                   "resident domicile family applicant पात्रता पात्र लाभार्थी आयु वर्ष आय निवासी परिवार आवेदक",
    "exclusion": "not eligible excluded exclusion shall not ineligible disqualified exempt except higher economic "
                 "status income tax payer government employee अपात्र वंचित नहीं होंगे बहिष्करण आयकर सरकारी कर्मचारी",
    "benefit": "benefit benefits assistance amount financial support subsidy rs rupees per annum instalment "
               "installment grant loan interest pension लाभ सहायता राशि रुपये किस्त अनुदान ऋण पेंशन",
    "documents": "documents required certificate proof aadhaar bank account passbook photograph income certificate "
                 "caste certificate दस्तावेज प्रमाण पत्र आधार बैंक खाता फोटो",
    "process": "how to apply application process procedure portal registration register submit online offline "
               "verification csc आवेदन प्रक्रिया पंजीकरण पोर्टल ऑनलाइन सत्यापन",
    "deadline": "date deadline last date within days months effective from with effect commencement validity "
                "तिथि अंतिम दिनांक दिनों प्रभावी",
    "obligation": "shall must required to comply obligation penalty fine punishable liable offence violation "
                  "अनिवार्य दंड जुर्माना उल्लंघन",
    "right": "right rights entitled entitlement guarantee guaranteed protection grievance redressal complaint "
             "अधिकार हकदार गारंटी शिकायत निवारण",
}


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.docs = docs
        self.k1, self.b = k1, b
        self.n = len(docs)
        self.avgdl = (sum(len(d) for d in docs) / self.n) if self.n else 0.0
        df: Counter = Counter()
        for d in docs:
            df.update(set(d))
        self.idf = {t: math.log(1 + (self.n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.tf = [Counter(d) for d in docs]

    def scores(self, query: list[str]) -> list[float]:
        out = []
        q = [t for t in query if t in self.idf]
        for i, tf in enumerate(self.tf):
            dl = len(self.docs[i]) or 1
            s = 0.0
            for t in q:
                f = tf.get(t, 0)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1)))
            out.append(s)
        return out


def rank_clauses(clauses: list[Clause]) -> tuple[list[str], dict[str, list[str]]]:
    """Return clause ids by fused relevance, plus the top hits per intent."""
    if not clauses:
        return [], {}
    bm = BM25([tokenize(f"{c.section or ''} {c.text}") for c in clauses])
    fused: dict[str, float] = {}
    top: dict[str, list[str]] = {}
    for intent, q in INTENTS.items():
        sc = bm.scores(tokenize(q))
        order = sorted(range(len(clauses)), key=lambda i: -sc[i])
        hits = [i for i in order[:25] if sc[i] > 0]
        top[intent] = [clauses[i].id for i in hits[:5]]
        for rank, i in enumerate(hits):
            cid = clauses[i].id
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (60 + rank)
            # continuation clauses in the same section usually belong to the same list
            if i + 1 < len(clauses) and clauses[i + 1].section == clauses[i].section and rank < 10:
                nid = clauses[i + 1].id
                fused[nid] = fused.get(nid, 0.0) + 0.5 / (60 + rank)
    for c in clauses[:3]:  # title and preamble give the model context
        fused[c.id] = fused.get(c.id, 0.0) + 1.0
    ranked = sorted(fused, key=lambda cid: -fused[cid])
    seen = set(ranked)
    ranked += [c.id for c in clauses if c.id not in seen]
    return ranked, top


def pack(clauses: list[Clause], ranking: list[str], budget_chars: int) -> list[Clause]:
    """Take clauses in ranking order until the budget is used, return them in document order."""
    total = sum(len(c.text) + 24 for c in clauses)
    if total <= budget_chars:
        return list(clauses)
    by_id = {c.id: c for c in clauses}
    chosen: set[str] = set()
    used = 0
    for cid in ranking:
        c = by_id.get(cid)
        if not c:
            continue
        cost = len(c.text) + 24
        if used + cost > budget_chars:
            continue
        chosen.add(cid)
        used += cost
    return [c for c in clauses if c.id in chosen]


def search(clauses: list[Clause], query: str, k: int = 6) -> list[Clause]:
    if not clauses:
        return []
    bm = BM25([tokenize(f"{c.section or ''} {c.text}") for c in clauses])
    sc = bm.scores(tokenize(query))
    order = sorted(range(len(clauses)), key=lambda i: -sc[i])
    return [clauses[i] for i in order[:k] if sc[i] > 0]


def format_clauses(clauses: list[Clause]) -> str:
    lines = []
    for c in clauses:
        sec = f", {c.section}" if c.section else ""
        lines.append(f"[{c.id}] (p.{c.page}{sec}) {c.text}")
    return "\n".join(lines)
