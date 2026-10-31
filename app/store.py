"""Persistent store for compiled Rights Cards.

Cards are JSON documents on disk. On Hugging Face Spaces the folder is mirrored
to a Hugging Face *dataset* repository: restored on startup and committed every
two minutes by huggingface_hub's CommitScheduler, so compiled policies survive
restarts. No citizen data is ever stored: eligibility checks are stateless.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from contextlib import nullcontext
from pathlib import Path
from typing import Optional

from . import config
from .models import PolicyCard

log = logging.getLogger("adhikarvani.store")


class Store:
    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = Path(data_dir or config.DATA_DIR)
        self.policy_dir = self.data_dir / "policies"
        self.audio_dir = self.data_dir / "audio"
        self.policy_dir.mkdir(parents=True, exist_ok=True)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self._index: dict[str, dict] = {}
        self._sha: dict[str, str] = {}
        self._lock = threading.RLock()
        self.scheduler = None
        self.sync_status = "local only"

    # ----------------------------------------------------------- lifecycle --
    def start(self) -> None:
        if config.HF_TOKEN and config.HF_DATASET_REPO:
            try:
                from huggingface_hub import CommitScheduler, create_repo, snapshot_download
                create_repo(config.HF_DATASET_REPO, repo_type="dataset", private=not config.STORE_PUBLIC,
                            exist_ok=True, token=config.HF_TOKEN)
                try:
                    snapshot_download(config.HF_DATASET_REPO, repo_type="dataset", local_dir=str(self.data_dir),
                                      token=config.HF_TOKEN, allow_patterns=["policies/*.json", "audio/*.mp3"])
                except Exception as e:  # empty repo on first run
                    log.info("dataset restore skipped: %s", e)
                self.scheduler = CommitScheduler(repo_id=config.HF_DATASET_REPO, repo_type="dataset",
                                                 folder_path=self.data_dir, every=2, token=config.HF_TOKEN,
                                                 allow_patterns=["policies/*.json", "audio/*.mp3"],
                                                 private=not config.STORE_PUBLIC)
                self.sync_status = f"synced to dataset {config.HF_DATASET_REPO}"
            except Exception as e:
                self.sync_status = f"local only (dataset sync failed: {type(e).__name__})"
                log.warning("dataset sync disabled: %s", e)
        self.reload()

    def reload(self) -> None:
        with self._lock:
            self._index.clear()
            self._sha.clear()
            for f in self.policy_dir.glob("*.json"):
                try:
                    card = PolicyCard.model_validate_json(f.read_text(encoding="utf-8"))
                except Exception as e:
                    log.warning("skipping unreadable card %s: %s", f.name, e)
                    continue
                self._index[card.id] = card.summary_row()
                self._sha[card.source.sha256] = card.id

    def _writer(self):
        return self.scheduler.lock if self.scheduler else nullcontext()

    # ---------------------------------------------------------------- api --
    def save(self, card: PolicyCard) -> None:
        path = self.policy_dir / f"{card.id}.json"
        tmp = path.with_suffix(".json.tmp")
        with self._lock, self._writer():
            tmp.write_text(card.model_dump_json(indent=1), encoding="utf-8")
            os.replace(tmp, path)
            self._index[card.id] = card.summary_row()
            self._sha[card.source.sha256] = card.id

    def get(self, policy_id: str) -> Optional[PolicyCard]:
        path = self.policy_dir / f"{policy_id}.json"
        if not path.exists():
            return None
        return PolicyCard.model_validate_json(path.read_text(encoding="utf-8"))

    def find_by_sha(self, sha: str) -> Optional[PolicyCard]:
        pid = self._sha.get(sha)
        return self.get(pid) if pid else None

    def list(self) -> list[dict]:
        with self._lock:
            return sorted(self._index.values(), key=lambda r: r.get("created_at", ""), reverse=True)

    def all_cards(self) -> list[PolicyCard]:
        out = []
        for row in self.list():
            card = self.get(row["id"])
            if card:
                out.append(card)
        return out

    def delete(self, policy_id: str) -> bool:
        path = self.policy_dir / f"{policy_id}.json"
        if not path.exists():
            return False
        with self._lock, self._writer():
            card = self.get(policy_id)
            path.unlink()
            for f in self.audio_dir.glob(f"{policy_id}_*.mp3"):
                f.unlink(missing_ok=True)
            self._index.pop(policy_id, None)
            if card:
                self._sha.pop(card.source.sha256, None)
        return True

    def status(self) -> dict:
        return {"policies": len(self._index), "persistence": self.sync_status}

    def write_audio_lock(self):
        return self._writer()

    def dump(self) -> str:
        return json.dumps(self.list(), indent=1)
