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
    for lang in ("en", "hi"):
        try:
            feed = sources.pib_feed(lang)
            first = feed["items"][0]
            say(f"- PIB feed {lang}: ✅ {len(feed['items'])} items; latest: {first['title'][:90]}")
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
        url = os.getenv("E2E_URL", OFFICIAL_DOCS[0][1])
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
