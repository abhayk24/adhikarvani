"""Data model of a compiled policy ("Rights Card").

A card is the output of the compiler. Every claim points to a clause of the
original document and carries the exact quote that proves it; every rule points
to a verified claim. That chain (rule -> claim -> quote -> clause -> page) is
what lets a citizen, an official or a judge audit any answer.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

ClaimKind = Literal["benefit", "right", "eligibility", "exclusion", "document", "process",
                    "deadline", "obligation", "penalty", "impact", "other"]
CLAIM_KINDS = list(ClaimKind.__args__)  # type: ignore[attr-defined]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Clause(BaseModel):
    id: str
    text: str
    page: int = 1
    section: Optional[str] = None


class Verification(BaseModel):
    quote_found: bool = False
    method: str = "none"          # exact | fuzzy | relocated | none
    score: float = 0.0
    entailed: Optional[bool] = None
    reason: str = ""
    corrected: bool = False

    @property
    def passed(self) -> bool:
        return self.quote_found and self.entailed is not False


class Claim(BaseModel):
    id: str
    kind: ClaimKind = "other"
    text: str
    quote: str
    clause_id: str
    audience: Literal["citizen", "business", "both"] = "citizen"
    verification: Verification = Field(default_factory=Verification)


class VariableDef(BaseModel):
    name: str
    type: Literal["number", "boolean", "enum", "text"]
    question: str
    unit: Optional[str] = None
    options: Optional[list[str]] = None
    actionable: bool = False
    description: str = ""


class Rule(BaseModel):
    id: str
    kind: Literal["eligibility", "exclusion"]
    description: str
    condition: dict[str, Any]
    claim_id: str
    clause_id: str = ""
    quote: str = ""


class Explainer(BaseModel):
    lang: str
    title: str = ""
    script: str = ""
    bullets: dict[str, list[str]] = Field(default_factory=dict)
    audio: Optional[str] = None
    audio_provider: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    model: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)


class SourceMeta(BaseModel):
    url: Optional[str] = None
    final_url: Optional[str] = None
    filename: Optional[str] = None
    kind: str = "pdf"
    sha256: str = ""
    fetched_at: str = Field(default_factory=now_iso)
    tls_verified: bool = True
    pages: int = 0
    language: str = "en"
    ocr_used: bool = False
    ocr_pages: int = 0
    domain: Optional[str] = None
    official: bool = False
    chars: int = 0
    followed_from: Optional[str] = None
    via: Optional[str] = None
    via_url: Optional[str] = None


class Stats(BaseModel):
    clauses: int = 0
    clauses_used: int = 0
    extracted: int = 0
    verified: int = 0
    corrected: int = 0
    rejected: int = 0
    rules: int = 0
    rules_rejected: int = 0
    llm_calls: int = 0
    seconds: float = 0.0


COMPILER_VERSION = 3  # bump when the compiler improves; ingestion recompiles older cards once


class PolicyCard(BaseModel):
    id: str
    compiler_version: int = 1
    title: str
    doc_type: str = "other"
    issuing_authority: Optional[str] = None
    jurisdiction: Optional[str] = None
    effective_date: Optional[str] = None
    summary: str = ""
    audience: list[str] = Field(default_factory=list)
    is_policy_document: bool = True
    source: SourceMeta
    claims: list[Claim] = Field(default_factory=list)
    rejected: list[dict[str, Any]] = Field(default_factory=list)
    rules: list[Rule] = Field(default_factory=list)
    variables: list[VariableDef] = Field(default_factory=list)
    not_compilable: list[dict[str, Any]] = Field(default_factory=list)
    rule_issues: list[str] = Field(default_factory=list)
    explainers: dict[str, Explainer] = Field(default_factory=dict)
    clauses: list[Clause] = Field(default_factory=list)
    stats: Stats = Field(default_factory=Stats)
    warnings: list[str] = Field(default_factory=list)
    models_used: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)

    def summary_row(self) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "doc_type": self.doc_type,
            "issuing_authority": self.issuing_authority, "jurisdiction": self.jurisdiction,
            "verified": self.stats.verified, "rejected": self.stats.rejected, "rules": len(self.rules),
            "languages": sorted(self.explainers.keys()), "official": self.source.official,
            "domain": self.source.domain, "created_at": self.created_at, "summary": self.summary[:280],
        }
