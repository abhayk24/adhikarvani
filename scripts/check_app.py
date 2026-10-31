"""Drive the deployed app through its public API, the way a user would, and report.

Compiles real official documents on the live app (instant if already compiled),
opens the Rights Card, asks the eligibility agent in Hindi, generates a Tamil
explainer and runs the Benefit Radar.

    python scripts/check_app.py --url https://adhikarvani.onrender.com --report report.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DOCS = [
    # Reachable from the app's cloud region; other official documents are compiled by
    # scripts/ingest.py from CI and reach the app through the dataset.
    ("Atal Pension Yojana brochure (PFRDA, scanned)",
     "https://www.pfrda.org.in/documents/33652/307349/APY%20Subscriber%20Information%20Brochure%20English"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.getenv("APP_URL", "").strip() or (ROOT / "deploy" / "app_url.txt").read_text().strip())
    ap.add_argument("--report", default="report.md")
    ap.add_argument("--docs", type=int, default=len(DOCS))
    args = ap.parse_args()
    base = args.url.rstrip("/")
    out = open(args.report, "a", encoding="utf-8")

    def say(line: str = "") -> None:
        print(line, flush=True)
        out.write(line + "\n")

    c = httpx.Client(base_url=base, timeout=httpx.Timeout(120, connect=90))
    say(f"\n## Live app walkthrough ({base})\n")
    try:
        h = c.get("/api/health").json()
    except Exception as e:
        say(f"- ❌ app not reachable: {type(e).__name__}")
        return 1
    say(f"- Health: v{h['version']}, AI {h['llm']['configured']}, store: {h['store']}")
    for prof, models in h["llm"]["active"].items():
        say(f"  - {prof}: {', '.join(models) or '(discovering)'}")
    try:
        feed = c.get("/api/pulse?lang=en").json()
        say(f"- PIB feed on the app: {len(feed.get('items', []))} English items {feed.get('note') or ''}")
    except Exception as e:
        say(f"- PIB feed on the app: ❌ {type(e).__name__}")

    first_id = None
    for name, url in DOCS[: args.docs]:
        t0 = time.time()
        try:
            job = c.post("/api/compile", data={"url": url, "lang": "hi"}).json()["job_id"]
            seq, snap = 0, {}
            nodes = []
            while time.time() - t0 < 420:
                snap = c.get(f"/api/jobs/{job}", params={"after": seq}).json()
                for ev in snap["events"]:
                    seq = max(seq, ev.get("seq", 0))
                    if ev.get("type") == "node" and ev.get("status") in ("done", "error"):
                        nodes.append(f"{ev['node']} {ev.get('ms', 0) / 1000:.1f}s: {str(ev.get('detail', ''))[:110]}")
                    if ev.get("type") == "llm" and ev.get("status") != "ok":
                        nodes.append(f"  ↳ {ev.get('task')}: {ev.get('provider')} {ev.get('model')} {ev.get('status')} ({ev.get('detail', '')})")
                if snap["status"] in ("done", "error"):
                    break
                time.sleep(3)
            if snap.get("status") != "done":
                say(f"- ❌ {name}: {snap.get('error') or 'timed out'} after {time.time() - t0:.0f}s")
                say("<details><summary>trace</summary>\n\n" + "\n".join(f"- {n}" for n in nodes) + "\n</details>")
                continue
            pid = snap["result"]["policy_id"]
            first_id = first_id or pid
            card = c.get(f"/api/policies/{pid}").json()
            st = card["stats"]
            say(f"- ✅ {name} → “{card['title']}” in {time.time() - t0:.0f}s: **{st['verified']} verified, "
                f"{st['corrected']} repaired, {st['rejected']} rejected, {len(card['rules'])} rules**; "
                f"models: {', '.join(card.get('models_used', []))}")
            for cl in card["claims"][:4]:
                say(f"  - [{cl['kind']}] {cl['text']} _(quote {cl['verification']['method']}, {cl['clause_id']})_")
            for r in card["rules"][:5]:
                say(f"  - {r['id']} {r['kind']}: `{json.dumps(r['condition'], ensure_ascii=False)}`")
            for rj in card["rejected"][:3]:
                say(f"  - rejected: {rj['text']} ({rj['reason']})")
            ex = card["explainers"].get("hi")
            if ex:
                say(f"  - Hindi explainer, audio={ex.get('audio_provider')}: {ex['script'][:160]}…")
            if nodes:
                say("<details><summary>trace</summary>\n\n" + "\n".join(f"- {n}" for n in nodes) + "\n</details>")
        except Exception as e:
            say(f"- ❌ {name}: {type(e).__name__}: {str(e)[:200]}")

    try:  # prefer the scheme with the most rules for the agent walkthrough
        rows = c.get("/api/policies").json()["policies"]
        say(f"- Register on the live app: {len(rows)} card(s): " + "; ".join(f"{r['title'][:40]} ({r['rules']} rules)" for r in rows))
        ruled = sorted([r for r in rows if r["rules"]], key=lambda r: -r["rules"])
        if ruled:
            first_id = ruled[0]["id"]
    except Exception:
        pass
    if first_id:
        try:
            state = "{}"
            for text in ("नमस्ते", "मैं उत्तर प्रदेश का किसान हूँ, मेरे पास 2 एकड़ जमीन है और मैं आयकर नहीं भरता"):
                t0 = time.time()
                t = c.post("/api/agent/turn", data={"mode": "policy", "policy_id": first_id, "lang": "hi",
                                                    "text": text, "state": state}).json()
                state = json.dumps(t["state"], ensure_ascii=False)
                ev = t["evaluations"][0]
                say(f"- Agent turn “{text[:40]}” ({time.time() - t0:.1f}s): facts {[(f['var'], f['value']) for f in t['facts']]}, "
                    f"verdict **{ev['status']}**, next question: {t.get('next_var')}; says: {t['say'][:140]}; audio: {bool(t.get('audio_url'))}")
            t0 = time.time()
            r = c.post(f"/api/policies/{first_id}/explain", data={"lang": "ta"}).json()
            ex = r["explainer"]
            say(f"- Tamil explainer ({time.time() - t0:.1f}s, audio {ex.get('audio_provider')}): {ex['script'][:120]}…")
            if ex.get("audio"):
                a = c.get(f"/audio/{ex['audio']}")
                say(f"  - audio file: HTTP {a.status_code}, {len(a.content) // 1024} KB")
            rad = c.post("/api/agent/turn", data={"mode": "radar", "lang": "hi", "state": state, "text": ""}).json()
            say("- Benefit Radar: " + "; ".join(f"{e['title'][:40]} → {e['status']}" for e in rad["evaluations"]))
        except Exception as e:
            say(f"- ❌ agent/explain/radar: {type(e).__name__}: {str(e)[:200]}")
    out.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
