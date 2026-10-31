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
    from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi, hf_hub_download
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
    lines = [l.strip() for l in Path(args.sources).read_text().splitlines() if l.strip() and not l.startswith("#")]
    force_urls = {l.rstrip("!").strip() for l in lines if l.endswith("!")}  # "url !" = recompile this run
    urls = [l.rstrip("!").strip() for l in lines]
    ops = []
    # One card per source URL: keep the best (direct source first, then most verified facts).
    by_url: dict[str, list] = {}
    for card in store.all_cards():
        if card.source.url:
            by_url.setdefault(card.source.url, []).append(card)
    for url_, cards in by_url.items():
        if len(cards) > 1:
            cards.sort(key=lambda c: (c.source.via is None, c.compiler_version, c.stats.verified), reverse=True)
            for dup in cards[1:]:
                ops.append(CommitOperationDelete(f"policies/{dup.id}.json"))
                (work / "policies" / f"{dup.id}.json").unlink(missing_ok=True)
                say(f"- removing duplicate card {dup.id} (kept {cards[0].id})")
    store.reload()
    current = {c.source.url: c for c in store.all_cards() if c.source.url}
    from app.ingest import fetch_url
    for url in urls:
        t0 = time.time()
        have = current.get(url)
        if have and have.compiler_version >= COMPILER_VERSION and url not in force_urls:
            say(f"- already in the dataset: {have.title} ({have.stats.verified} facts, {len(have.rules)} rules)")
            continue
        try:
            doc = fetch_url(url)
        except Exception as e:
            say(f"- ❌ could not fetch {url[:80]}: {str(e)[:140]}")
            continue
        if have and have.source.via is None and doc.via:
            say(f"- kept {have.title}: the site is only reachable through a relay right now, and the earlier "
                f"card was read directly from the official file")
            continue
        before = {r["id"] for r in store.list()}
        try:
            card = compile_policy(CompileInput(url=url, lang=args.lang, force=have is not None, prefetched=doc),
                                  lambda e: None, store)
        except Exception as e:
            say(f"- ❌ {url[:90]}: {str(e)[:160]}")
            continue
        if card.id in before and not have:
            say(f"- already in the dataset (same file under another link): {card.title}")
            continue
        if have and have.id != card.id:
            ops.append(CommitOperationDelete(f"policies/{have.id}.json"))
        st = card.stats
        conds = [c for c in card.claims if c.kind in ("eligibility", "exclusion")]
        say(f"- ✅ {'re' if have else ''}compiled {card.title} in {time.time() - t0:.0f}s: {st.verified} verified, "
            f"{st.corrected} repaired, {st.rejected} rejected, {len(conds)} conditions → {len(card.rules)} rules "
            f"(OCR: {card.source.ocr_used}; via: {card.source.via or 'direct'}; models: {', '.join(card.models_used)})")
        for nc in card.not_compilable[:4]:
            say(f"  - not compilable {nc.get('claim_id')}: {str(nc.get('reason'))[:120]}")
        for issue in card.rule_issues[:6]:
            say(f"  - rule issue: {issue[:140]}")
        ops.append(CommitOperationAdd(f"policies/{card.id}.json", str(work / "policies" / f"{card.id}.json")))
        for ex in card.explainers.values():
            if ex.audio and (work / "audio" / ex.audio).exists():
                ops.append(CommitOperationAdd(f"audio/{ex.audio}", str(work / "audio" / ex.audio)))
    remote_now = set(api.list_repo_files(repo, repo_type="dataset"))
    ops = [o for o in ops if not (isinstance(o, CommitOperationDelete) and o.path_in_repo not in remote_now)]
    if ops:
        api.create_commit(repo, repo_type="dataset", operations=ops,
                          commit_message=f"Ingest: {len(ops)} change(s)")
        say(f"- Published {len(ops)} file(s); the live app picks them up within 5 minutes.")
    out.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
