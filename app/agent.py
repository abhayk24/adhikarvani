"""The citizen voice agent: one conversational turn.

    speech --ASR--> transcript --LLM--> facts (+ evidence) --verify--> profile
           --rules engine--> verdict per policy --planner--> next question
           --LLM--> reply in the citizen's language --numeric check--> TTS

The LLM never decides eligibility. It only (1) turns speech into structured
facts, each of which must quote the citizen's own words, and (2) phrases the
engine's verdict in the citizen's language. The server keeps no personal data:
the profile lives in the browser and is sent back with each turn.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from . import llm, voice
from .engine import all_var_defs, condition_vars, evaluate, plan_next_question
from .languages import LANGS, describe, lang_or_default
from .models import PolicyCard, VariableDef
from .text_utils import unsupported_numbers
from .variables import CANONICAL, catalog_lines, coerce_value
from .verify import evidence_in

REPLY_AUDIO_DIR = Path("/tmp/adhikarvani-replies")
Trace = Optional[Callable[[dict], None]]


class AgentError(RuntimeError):
    pass


FACTS_SYSTEM = """You extract facts that a citizen states about THEMSELVES or their family from one short message. The message may be in any Indian language, in Latin transliteration (e.g. "meri umar 34 saal hai"), or mixed with English. Only extract facts that are explicitly stated, or that directly answer the question we asked. Never infer or guess. For every fact copy the exact words from the message that state it into "evidence". Convert lakh / crore / thousand into a plain rupee number. Reply with JSON only."""

FACTS_USER = """QUESTION WE ASKED: {last_q}
MESSAGE: \"\"\"{text}\"\"\"

VARIABLES YOU MAY FILL:
{catalog}

Return JSON:
{{"facts": [{{"var": "age", "value": 34, "unit": null, "evidence": "34 saal"}}],
  "question": null,
  "language": "hi"}}
- "question": if the citizen asks something about the scheme or law, write their question in English; otherwise null.
- income: give unit "per_month" or "per_year" as the citizen said it. land: unit "acre", "hectare" or "bigha".
- yes/no variables: true or false. enum variables: exactly one of the listed options."""

REPLY_SYSTEM = """You are AdhikarVani, a warm, respectful helper who explains Indian government schemes to citizens by voice, in {lang}. You receive the result of a deterministic eligibility check. Write what to say next in {lang} (native script), at most 70 words, simple spoken language. Never contradict the check result. Never invent facts, amounts, dates or conditions. Reply with JSON only."""

REPLY_USER = """SITUATION:
{situation}

Write the reply:
0. If "greeting" is true, begin with a one-line greeting and say what you will check. Otherwise do not greet again.
1. If "user_question" is present, first answer it using ONLY "facts_for_question"; if they do not answer it, say you are not sure and suggest asking the issuing office.
2. Then state the result naturally (eligible / not eligible and the main reason / still checking).
3. If "next_question" is present, end by asking it in simple words.
Return JSON: {{"say": "..."}}"""


@dataclass
class TurnInput:
    mode: str = "policy"                # policy | radar
    policy_id: Optional[str] = None
    lang: str = "hi"
    text: Optional[str] = None
    audio: Optional[bytes] = None
    audio_name: Optional[str] = None
    state: dict = field(default_factory=dict)


def _relevant_vars(cards: list[PolicyCard]) -> list[str]:
    names: list[str] = []
    for c in cards:
        for r in c.rules:
            names += condition_vars(r.condition)
    return list(dict.fromkeys(names))


def _fmt(v: Any) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def extract_facts(text: str, last_var: Optional[str], var_defs: dict[str, VariableDef], names: list[str],
                  trace: Trace) -> tuple[list[dict], list[dict], Optional[str]]:
    """Returns (accepted facts, rejected facts, user's question)."""
    if not text.strip():
        return [], [], None
    allowed = [n for n in names if n in var_defs]
    if last_var and last_var in var_defs and last_var not in allowed:
        allowed.insert(0, last_var)
    canon = [n for n in allowed if n in CANONICAL]
    extra = [var_defs[n] for n in allowed if n not in CANONICAL]
    last_q = f"{var_defs[last_var].question} (fills '{last_var}')" if last_var in var_defs else "none"
    user = FACTS_USER.format(last_q=last_q, text=text[:1500], catalog=catalog_lines(canon, extra) or "(none)")
    data, _ = llm.chat_json(task="understand citizen", profile="fast", system=FACTS_SYSTEM, user=user,
                            max_tokens=1200, trace=trace, deadline_s=45)
    accepted, rejected = [], []
    for f in (data.get("facts") or []) if isinstance(data, dict) else []:
        if not isinstance(f, dict):
            continue
        name, ev = str(f.get("var") or ""), str(f.get("evidence") or "")
        vd = var_defs.get(name)
        if not vd or name not in allowed:
            continue
        if not evidence_in(ev, text):
            rejected.append({"var": name, "value": f.get("value"), "reason": "not found in what you said"})
            continue
        try:
            value = coerce_value(vd, f.get("value"), f.get("unit"))
        except ValueError as e:
            rejected.append({"var": name, "value": f.get("value"), "reason": str(e)})
            continue
        accepted.append({"var": name, "value": value, "evidence": ev, "label": vd.description})
    q = data.get("question") if isinstance(data, dict) else None
    return accepted, rejected, (str(q)[:300] if q else None)


def _fallback_say(sit: dict) -> str:
    parts = []
    if sit.get("mode") == "radar":
        if sit.get("eligible"):
            parts.append("You appear eligible for: " + ", ".join(sit["eligible"]) + ".")
        if sit.get("still_checking"):
            parts.append(f"Still checking {len(sit['still_checking'])} more.")
    else:
        r = sit.get("result")
        if r == "eligible":
            parts.append(f"Based on what you told me, you meet every condition of {sit.get('scheme')}.")
        elif r == "not_eligible":
            parts.append("You do not meet this condition: " + "; ".join(sit.get("failed_conditions", [])[:2]) + ".")
        elif r == "no_rules":
            parts.append("This document has no eligibility conditions to check.")
    if sit.get("next_question"):
        parts.append(sit["next_question"])
    return " ".join(parts) or "Please tell me a little about yourself."


def run_turn(inp: TurnInput, store, trace: Trace = None) -> dict:
    t0 = time.time()
    lang = lang_or_default(inp.lang)
    state = dict(inp.state or {})
    profile: dict[str, Any] = dict(state.get("profile") or {})
    asked: dict[str, int] = {k: int(v) for k, v in (state.get("asked") or {}).items()}
    last_var = state.get("last_var")

    if inp.mode == "radar":
        cards = [c for c in store.all_cards() if c.rules]
        if not cards:
            raise AgentError("No compiled policy has eligibility rules yet. Compile a scheme document first.")
    else:
        card = store.get(inp.policy_id or "")
        if not card:
            raise AgentError("That policy was not found.")
        cards = [card]
    var_defs = all_var_defs(cards)

    transcript, asr = (inp.text or "").strip(), None
    if inp.audio:
        asr = voice.transcribe(inp.audio, inp.audio_name or "speech.webm", lang, trace)
        transcript = asr["text"]
        if not transcript:
            raise AgentError("I could not hear anything. Please try again closer to the microphone.")

    accepted, rejected, user_q = [], [], None
    if transcript:
        try:
            accepted, rejected, user_q = extract_facts(transcript, last_var, var_defs, _relevant_vars(cards), trace)
        except llm.LLMError as e:
            raise AgentError("The AI service is busy right now; please try again in a few seconds.") from e
    for f in accepted:
        profile[f["var"]] = f["value"]
    if trace and (accepted or rejected):
        trace({"type": "guard", "detail": f"evidence check: {len(accepted)} fact(s) accepted, "
                                          f"{len(rejected)} rejected (not in your words)"})

    evals = [evaluate(c, profile) for c in cards]
    next_var = plan_next_question(evals, asked, var_defs)
    if next_var:
        asked[next_var] = asked.get(next_var, 0) + 1
    next_q = var_defs[next_var].question if next_var else None

    understood = [f"{var_defs[k].description}: {_fmt(v)}" for k, v in profile.items() if k in var_defs]
    if inp.mode == "radar":
        sit = {"mode": "radar", "eligible": [e["title"] for e in evals if e["status"] == "eligible"],
               "not_eligible": [{"scheme": e["title"], "reason": next((r["description"] for r in e["rules"]
                                                                        if r["passes"] is False), "")}
                                for e in evals if e["status"] == "not_eligible"],
               "still_checking": [e["title"] for e in evals if e["status"] == "needs_info"],
               "understood": understood, "next_question": next_q, "user_question": user_q,
               "facts_for_question": []}
        source_claims = [cl for c in cards for cl in c.claims]
    else:
        ev, card = evals[0], cards[0]
        sit = {"scheme": card.title, "result": ev["status"], "understood": understood,
               "met_conditions": [r["description"] for r in ev["rules"] if r["passes"] is True],
               "failed_conditions": [r["description"] for r in ev["rules"] if r["passes"] is False],
               "fixable": ev["fixable"], "next_question": next_q, "user_question": user_q,
               "facts_for_question": [f"{c.kind}: {c.text}" for c in card.claims] if user_q else []}
        source_claims = card.claims
    if not transcript and not profile:
        sit["greeting"] = True

    sources = [c.quote for c in source_claims] + [c.text for c in source_claims] + [transcript] + \
              [json.dumps(profile)] + [r.description for c in cards for r in c.rules]
    say, warn = None, None
    for attempt in range(2):
        try:
            data, _ = llm.chat_json(task=f"reply in {LANGS[lang]['name']}", profile="chat",
                                    system=REPLY_SYSTEM.format(lang=describe(lang)),
                                    user=REPLY_USER.format(situation=json.dumps(sit, ensure_ascii=False, indent=1)),
                                    max_tokens=900, temperature=0.3, trace=trace, deadline_s=50)
            say = str(data.get("say") or "").strip() if isinstance(data, dict) else ""
        except llm.LLMError:
            say = None
            break
        bad = unsupported_numbers(say or "", sources)
        if not bad:
            warn = None
            break
        warn = f"unverified number(s) in reply: {', '.join(bad)}"
        if trace:
            trace({"type": "guard", "detail": f"numeric fidelity check failed ({', '.join(bad)}); rephrasing"})
        sit["avoid_numbers"] = bad
    if not say or warn:
        say = _fallback_say(sit)
        lang_used = "en"
    else:
        lang_used = lang

    audio_url = None
    try:
        REPLY_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        _cleanup_replies()
        name = f"{uuid.uuid4().hex}.mp3"
        voice.synthesize(say, lang_used, REPLY_AUDIO_DIR / name, trace)
        audio_url = f"/audio/r/{name}"
    except voice.VoiceError:
        pass

    return {
        "transcript": transcript, "asr": asr, "facts": accepted, "rejected_facts": rejected,
        "user_question": user_q, "profile": profile, "evaluations": evals, "next_var": next_var,
        "next_question": next_q, "say": say, "say_lang": lang_used, "audio_url": audio_url,
        "state": {"profile": profile, "asked": asked, "last_var": next_var},
        "ms": int((time.time() - t0) * 1000),
    }


def _cleanup_replies(max_age_s: int = 3600) -> None:
    now = time.time()
    for f in REPLY_AUDIO_DIR.glob("*.mp3"):
        try:
            if now - f.stat().st_mtime > max_age_s:
                f.unlink()
        except OSError:
            pass
