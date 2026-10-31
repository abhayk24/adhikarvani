"""Exercise every live dependency with the real API keys and write a Markdown report.

Run by GitHub Actions on every push (keys come from repository secrets), so the
team can see at a glance that the free AI providers, speech, the PIB feed and
official document sources all work, plus one full compile of a real scheme.

    python scripts/live_check.py --report report.md [--full]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OFFICIAL_DOCS = [
    ("PM-KISAN operational guidelines (PDF, English)",
     "https://pmkisan.gov.in/Documents/RevisedPM-KISANOperationalGuidelines(English).pdf"),
    ("PM-SYM scheme page (West Bengal portal, HTML)",
     "https://wb.gov.in/government-schemes-details-pradhan-mantri-shram-yogi-mandhan.aspx"),
    ("Meghalaya pension scheme press note (PDF)",
     "https://www.meghalaya.gov.in/sites/default/files/press_release/Pension_Scheme_0.pdf"),
    ("PM-KISAN guidelines (PDF, Hindi)",
     "https://pmkisan.gov.in/Documents/%E0%A4%AA%E0%A5%8D%E0%A4%B0%E0%A4%A7%E0%A4%BE%E0%A4%A8%E0%A4%AE%E0%A4%82%E0%A4%A4%E0%A5%8D%E0%A4%B0%E0%A5%80%20%E0%A4%95%E0%A4%BF%E0%A4%B8%E0%A4%BE%E0%A4%A8%20%E0%A4%B8%E0%A4%AE%E0%A5%8D%E0%A4%AE%E0%A4%BE%E0%A4%A8%20%E0%A4%A8%E0%A4%BF%E0%A4%A7%E0%A4%BF.pdf"),
    ("PM Vishwakarma explainer (Andhra Pradesh MSME, PDF)",
     "https://apmsmeone.ap.gov.in/Downloads/PMVishwakarmaProjectExplainer.pdf"),
    ("PM Vishwakarma (UP MSME portal, PDF)",
     "https://msme1connect.up.gov.in/GovernmentScheme/GovernmentScheme638769634969101318.pdf"),
    ("Atal Pension Yojana brochure (PFRDA, PDF)",
     "https://www.pfrda.org.in/documents/33652/307349/APY%20Subscriber%20Information%20Brochure%20English"),
]


def gemini_diagnostics(say) -> None:
    """Time to first token and total time per Gemini model and option set (streamed)."""
    from app import llm
    import httpx
    p = llm.PROVIDER_BY_NAME["gemini"]
    if not p.key():
        return
    say("- Gemini latency by model (streamed; json = JSON mode, low = reasoning_effort low):")
    tests = [("gemini-2.5-flash", True, "low"), ("gemini-2.5-flash", False, None), ("gemini-3.5-flash", True, "low"),
             ("gemini-3.5-flash", False, None), ("gemini-3.8-flash", True, "low"), ("gemini-flash-latest", True, "low"),
             ("gemini-2.5-flash-lite", True, "low"), ("gemini-3.5-flash-lite", True, "low")]
    for model, js, eff in tests:
        body = {"model": model, "stream": True, "max_tokens": 400,
                "messages": [{"role": "user", "content": 'Reply with the JSON object {"ok": true}'}]}
        if js:
            body["response_format"] = {"type": "json_object"}
        if eff:
            body["reasoning_effort"] = eff
        t0, first, text, status = time.time(), None, "", None
        try:
            with httpx.stream("POST", f"{p.base_url}/chat/completions", headers=llm._headers(p), json=body,
                              timeout=httpx.Timeout(connect=10, read=35, write=10, pool=10)) as r:
                status = r.status_code
                if status != 200:
                    r.read()
                    text = r.text[:140].replace("\n", " ")
                else:
                    for line in r.iter_lines():
                        if line.startswith("data:") and first is None:
                            first = time.time() - t0
                        if line.startswith("data:") and "[DONE]" not in line:
                            try:
                                for ch in json.loads(line[5:]).get("choices") or []:
                                    text += (ch.get("delta") or {}).get("content") or ""
                            except Exception:
                                pass
            fb = f"{first:.1f}s" if first is not None else "none"
            say(f"  - {model} json={js} effort={eff}: HTTP {status}, first chunk {fb}, total {time.time() - t0:.1f}s → {text[:60]!r}")
        except Exception as e:
            say(f"  - {model} json={js} effort={eff}: {type(e).__name__} after {time.time() - t0:.1f}s")
    try:
        t0 = time.time()
        r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
                       headers={"x-goog-api-key": p.key()}, timeout=40,
                       json={"contents": [{"parts": [{"text": "Say ok"}]}]})
        say(f"  - native generateContent gemini-2.5-flash: HTTP {r.status_code} in {time.time() - t0:.1f}s")
    except Exception as e:
        say(f"  - native generateContent: {type(e).__name__}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default="report.md")
    ap.add_argument("--full", action="store_true", help="also compile a real document end to end")
    args = ap.parse_args()
    os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="av-live-"))

    from app import llm, sources, voice
    from app.compiler import CompileInput, compile_policy
    from app.ingest import fetch_url, parse_document
    from app.store import Store

    out = open(args.report, "a", encoding="utf-8")

    def say(line: str = "") -> None:
        print(line, flush=True)
        out.write(line + "\n")

    say(f"## Live dependency check ({time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())})\n")

    # 1. AI providers
    say("### AI providers")
    for p in llm.PROVIDERS:
        if not p.key():
            say(f"- {p.label}: no key")
            continue
        models = llm.list_models(p, force=True)
        say(f"- {p.label}: {len(models) if models is not None else 'discovery failed'} models visible")
        for prof in ("heavy", "write", "fast"):
            say(f"  - {prof}: {', '.join(llm.resolve_models(p, prof)) or 'none'}")
        if models:
            interesting = sorted(m for m in models if any(k in m for k in ("flash", "gpt-oss", "llama", "qwen", "kimi", "whisper")))
            say(f"  - visible: {', '.join(interesting[:30])}")
    for prof in ("heavy", "fast", "write"):
        try:
            data, meta = llm.chat_json(task=f"ping {prof}", profile=prof, system="Reply with JSON only.",
                                       user='Return {"ok": true, "hindi": "<the Hindi word for rights>"}',
                                       max_tokens=200, deadline_s=60)
            say(f"- ping {prof}: ✅ {meta['provider']} {meta['model']} {meta['ms']} ms → {json.dumps(data, ensure_ascii=False)[:80]}")
        except Exception as e:
            say(f"- ping {prof}: ❌ {e}")

    gemini_diagnostics(say)

    # 2. Speech
    say("\n### Speech")
    try:
        import asyncio
        import edge_tts
        voices = asyncio.run(edge_tts.list_voices())
        indian = sorted(v["ShortName"] for v in voices if v["ShortName"].split("-")[1:2] == ["IN"])
        say(f"- Edge voices for India ({len(indian)}): {', '.join(indian)}")
    except Exception as e:
        say(f"- Edge voice list: ❌ {type(e).__name__}: {e}")
    sample = Path(tempfile.mkdtemp()) / "sample.mp3"
    try:
        prov = voice.synthesize("मेरी उम्र चौंतीस साल है और मैं किसान हूँ।", "hi", sample)
        say(f"- TTS Hindi: ✅ {prov} ({sample.stat().st_size // 1024} KB)")
        tr = voice.transcribe(sample.read_bytes(), "sample.mp3", "hi")
        say(f"- ASR round-trip: ✅ {tr['provider']} {tr['model']} {tr['ms']} ms → “{tr['text']}”")
    except Exception as e:
        say(f"- TTS/ASR: ❌ {type(e).__name__}: {e}")
    for lang in ("ta", "bn", "pa"):
        try:
            text = {"ta": "வணக்கம்", "bn": "নমস্কার", "pa": "ਸਤ ਸ੍ਰੀ ਅਕਾਲ"}[lang]
            prov = voice.synthesize(text, lang, sample)
            say(f"- TTS {lang}: ✅ {prov}")
        except Exception as e:
            say(f"- TTS {lang}: ❌ {e}")

    # 3. Live official sources
    say("\n### Official sources (fetched from this CI runner)")
    for line in sources.feed_probe():
        say(f"- PIB probe: {line}")
    for lang in ("en", "hi"):
        try:
            feed = sources.pib_feed(lang)
            first = feed["items"][0]
            say(f"- PIB feed {lang}: ✅ {len(feed['items'])} items{' (' + feed['note'] + ')' if feed.get('note') else ''}; "
                f"latest: {first['title'][:90]}")
            if lang == "en":
                doc = fetch_url(first["link"])
                parsed = parse_document(doc)
                say(f"  - first release page: ✅ {len(parsed.text):,} chars ({doc.kind})")
        except Exception as e:
            say(f"- PIB feed {lang}: ❌ {type(e).__name__}: {e}")
    for name, url in OFFICIAL_DOCS:
        try:
            doc = fetch_url(url)
            parsed = parse_document(doc)
            say(f"- {name}: ✅ {doc.kind}, {len(parsed.pages)} page(s), {len(parsed.text):,} chars, "
                f"script={parsed.language}, OCR={parsed.ocr_used}, TLS verified={doc.tls_verified}")
        except Exception as e:
            say(f"- {name}: ❌ {type(e).__name__}: {e}")

    # 4. One real end-to-end compile
    if args.full:
        say("\n### Full compile of a real document")
        store = Store(Path(os.environ["DATA_DIR"]))
        events = []
        url = os.getenv("E2E_URL", "").strip() or OFFICIAL_DOCS[0][1]
        try:
            t0 = time.time()
            card = compile_policy(CompileInput(url=url, lang="hi"), events.append, store)
            say(f"- ✅ “{card.title}” in {time.time() - t0:.0f} s: {card.stats.verified} verified, "
                f"{card.stats.corrected} repaired, {card.stats.rejected} rejected, {len(card.rules)} rules, "
                f"models: {', '.join(card.models_used)}")
            for c in card.claims[:6]:
                say(f"  - [{c.kind}] {c.text}  _(quote {c.verification.method}, {c.clause_id})_")
            for r in card.rules[:6]:
                say(f"  - {r.id} {r.kind}: `{json.dumps(r.condition)}`")
            for rj in card.rejected[:4]:
                say(f"  - rejected: {rj['text']} ({rj['reason']})")
            ex = card.explainers.get("hi")
            if ex:
                say(f"  - Hindi explainer ({ex.audio_provider}): {ex.script[:220]}…")
        except Exception as e:
            say(f"- ❌ {type(e).__name__}: {e}")
            say("```\n" + traceback.format_exc()[-1500:] + "\n```")
        dbg: dict = {}
        try:
            doc = fetch_url(OFFICIAL_DOCS[3][1])
            sample = parse_document(doc).pages[0][:240]
            say(f"- Hindi PDF text sample: {sample!r}")
        except Exception as e:
            say(f"- Hindi PDF sample: {type(e).__name__}")
        try:
            t0 = time.time()
            hi = compile_policy(CompileInput(url=OFFICIAL_DOCS[3][1], lang="hi"), lambda e: None, store, debug=dbg)
            say(f"- ✅ Hindi PDF “{hi.title}” in {time.time() - t0:.0f} s: {hi.stats.verified} verified, "
                f"{hi.stats.rejected} rejected, {len(hi.rules)} rules")
            for c in hi.claims[:3]:
                say(f"  - [{c.kind}] {c.text}  _(quote: {c.quote[:70]})_")
        except Exception as e:
            say(f"- ❌ Hindi PDF compile: {type(e).__name__}: {e}")
            st = dbg.get("state") or {}
            from app.verify import skeleton
            for c in (st.get("claims") or [])[:5]:
                say(f"  - claim {c.id} [{c.kind}] quote={c.quote[:80]!r} clause={c.clause_id} "
                    f"result={c.verification.method}/{c.verification.reason[:60]}")
            for cl in (st.get("clauses") or [])[:3]:
                say(f"  - clause {cl.id}: {cl.text[:100]!r}")
        say("\n<details><summary>Trace</summary>\n")
        for ev in events:
            if ev.get("type") in ("node", "llm", "guard", "info", "tool"):
                say(f"- {ev.get('type')} {ev.get('node') or ev.get('task') or ev.get('tool') or ''} "
                    f"{ev.get('status', '')} {ev.get('provider', '')} {ev.get('model', '')} {str(ev.get('detail', ''))[:200]}")
        say("</details>")
    say(f"\nLLM router stats: {json.dumps(llm.STATS)}")
    out.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
