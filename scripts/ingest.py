"""Compile official documents and publish the Rights Cards to the Hugging Face dataset.

The live app pulls new cards from the dataset every few minutes. This lets the
pipeline reach government sites that block the app's cloud region: the compile is
the same code, run from CI, on the live official documents in deploy/sources.txt.

    python scripts/ingest.py --report report.md
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default="report.md")
    ap.add_argument("--sources", default=str(ROOT / "deploy" / "sources.txt"))
    ap.add_argument("--lang", default="hi")
    args = ap.parse_args()
    out = open(args.report, "a", encoding="utf-8")

    def say(line: str = "") -> None:
        print(line, flush=True)
        out.write(line + "\n")

    token = os.getenv("HF_TOKEN", "").strip()
    if not token:
        say("## Ingestion skipped: no HF_TOKEN")
        return 0
    from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download
    from app.compiler import CompileInput, compile_policy
    from app.models import COMPILER_VERSION
    from app.store import Store

    api = HfApi(token=token)
    repo = os.getenv("HF_DATASET_REPO", "").strip() or f"{api.whoami()['name']}/adhikarvani-store"
    api.create_repo(repo, repo_type="dataset", private=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="av-ingest-"))
    remote = set(api.list_repo_files(repo, repo_type="dataset"))
    for name in remote:  # existing cards, so already-compiled documents are skipped (no AI calls)
        if name.startswith("policies/") and name.endswith(".json"):
            hf_hub_download(repo, name, repo_type="dataset", local_dir=str(work), token=token)
    store = Store(work)
    store.reload()
    os.environ["DATA_DIR"] = str(work)
    import app.config as config
    config.AUDIO_DIR = work / "audio"

    say(f"\n## Ingestion of official documents into {repo}\n")
    urls = [l.strip() for l in Path(args.sources).read_text().splitlines() if l.strip() and not l.startswith("#")]
    ops = []
    for url in urls:
        t0 = time.time()
        before = {r["id"] for r in store.list()}
        try:
            card = compile_policy(CompileInput(url=url, lang=args.lang), lambda e: None, store)
        except Exception as e:
            say(f"- ❌ {url[:90]}: {str(e)[:160]}")
            continue
        if card.id in before and card.compiler_version >= COMPILER_VERSION:
            say(f"- already in the dataset: {card.title} ({card.stats.verified} facts, {len(card.rules)} rules)")
            continue
        if card.id in before:  # compiled by an older compiler: recompile once, same id
            old = (card.stats.verified, len(card.rules))
            try:
                card = compile_policy(CompileInput(url=url, lang=args.lang, force=True), lambda e: None, store)
            except Exception as e:
                say(f"- ❌ recompile {url[:80]}: {str(e)[:160]}")
                continue
            say(f"- recompiled with compiler v{COMPILER_VERSION}: was {old[0]} facts / {old[1]} rules")
        st = card.stats
        conds = [c for c in card.claims if c.kind in ("eligibility", "exclusion")]
        say(f"- ✅ {card.title} in {time.time() - t0:.0f}s: {st.verified} verified, {st.corrected} repaired, "
            f"{st.rejected} rejected, {len(conds)} conditions → {len(card.rules)} rules "
            f"(source OCR: {card.source.ocr_used}; models: {', '.join(card.models_used)})")
        for nc in card.not_compilable[:4]:
            say(f"  - not compilable {nc.get('claim_id')}: {str(nc.get('reason'))[:120]}")
        for issue in card.rule_issues[:6]:
            say(f"  - rule issue: {issue[:140]}")
        ops.append(CommitOperationAdd(f"policies/{card.id}.json", str(work / "policies" / f"{card.id}.json")))
        for ex in card.explainers.values():
            if ex.audio and (work / "audio" / ex.audio).exists():
                ops.append(CommitOperationAdd(f"audio/{ex.audio}", str(work / "audio" / ex.audio)))
    if ops:
        api.create_commit(repo, repo_type="dataset", operations=ops,
                          commit_message=f"Ingest {len([o for o in ops if o.path_in_repo.startswith('policies/')])} card(s)")
        say(f"- Published {len(ops)} file(s); the live app picks them up within 5 minutes.")
    out.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
