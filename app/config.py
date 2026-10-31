"""Central configuration.

Everything comes from environment variables so the exact same code runs on a
laptop, inside GitHub Actions and on Hugging Face Spaces.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "AdhikarVani"
VERSION = "1.0.0"

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT / "data")))
POLICY_DIR = DATA_DIR / "policies"
AUDIO_DIR = DATA_DIR / "audio"

# ---- Safety and quota limits (free-tier friendly) --------------------------
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024      # biggest document we will fetch/accept
MAX_PDF_PAGES = 80                          # pages read from one PDF
MAX_OCR_PAGES = 12                          # scanned pages we OCR (CPU time)
MAX_CLAUSES = 3000
MAX_AUDIO_BYTES = 12 * 1024 * 1024
MAX_CONCURRENT_COMPILES = 2
MAX_CLAIMS = 40

# ---- Persistence: compiled cards are mirrored to a Hugging Face dataset ----
HF_TOKEN = os.getenv("HF_TOKEN", "").strip()
SPACE_ID = os.getenv("SPACE_ID", "")                 # set by Hugging Face, "user/space"
SPACE_AUTHOR = os.getenv("SPACE_AUTHOR_NAME", "") or (SPACE_ID.split("/")[0] if "/" in SPACE_ID else "")
HF_DATASET_REPO = os.getenv("HF_DATASET_REPO", "") or (f"{SPACE_AUTHOR}/adhikarvani-store" if SPACE_AUTHOR else "")
STORE_PUBLIC = os.getenv("STORE_PUBLIC", "0") == "1"
ADMIN_KEY = os.getenv("ADMIN_KEY", "").strip()   # enables DELETE /api/policies/{id}

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0 Safari/537.36 AdhikarVani/1.0"
)

# Domains we treat as official government sources (shown as a trust badge).
OFFICIAL_SUFFIXES = ("gov.in", "nic.in", "rbi.org.in", "sebi.gov.in", "india.gov.in")


def is_official_domain(domain: str | None) -> bool:
    if not domain:
        return False
    d = domain.lower().strip(".")
    return any(d == s or d.endswith("." + s) for s in OFFICIAL_SUFFIXES)
