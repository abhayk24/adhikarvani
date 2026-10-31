"""Deploy this repository to a Hugging Face Docker Space (run by GitHub Actions).

* Creates the Space on first run (public, Docker SDK) under the token owner's account.
* Copies the API keys from GitHub secrets into Space secrets, so they live in one place.
* Uploads the code with a Space README (YAML front matter) generated from README.md.
* Waits for the build, prints build/run logs on failure, then checks /api/health.

    python scripts/deploy_space.py --upload-only   # phase 1
    python scripts/deploy_space.py --verify-only   # phase 2 (after other CI work)
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import httpx
from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parent.parent
SECRET_KEYS = ["GROQ_API_KEY", "GEMINI_API_KEY", "CEREBRAS_API_KEY", "MISTRAL_API_KEY", "OPENROUTER_API_KEY",
               "ADMIN_KEY"]
FRONT_MATTER = """---
title: AdhikarVani
emoji: 📜
colorFrom: indigo
colorTo: yellow
sdk: docker
app_port: 7860
pinned: true
license: mit
short_description: Government notices into verified rights you can hear
---

"""
INCLUDE = ["app", "static", "scripts", "tests", "docs", "Dockerfile", ".dockerignore", "requirements.txt",
           "requirements-dev.txt", "LICENSE"]


def log_tail(token: str, space: str, kind: str, seconds: float = 12.0, lines: int = 60) -> list[str]:
    """Read the tail of a Space's build/run log stream."""
    out: list[str] = []
    try:
        with httpx.stream("GET", f"https://huggingface.co/api/spaces/{space}/logs/{kind}",
                          headers={"Authorization": f"Bearer {token}"}, timeout=seconds + 5) as r:
            t0 = time.time()
            for line in r.iter_lines():
                if line.startswith("data:"):
                    out.append(line[5:].strip()[:300])
                if time.time() - t0 > seconds:
                    break
    except Exception as e:
        out.append(f"(could not read {kind} logs: {type(e).__name__})")
    return out[-lines:]


def upload(api: HfApi, space: str, token: str, sha: str, say) -> None:
    api.create_repo(space, repo_type="space", space_sdk="docker", exist_ok=True, private=False)
    set_keys = []
    for key in SECRET_KEYS:
        val = os.getenv(key, "").strip()
        if val:
            api.add_space_secret(space, key, val)
            set_keys.append(key)
    api.add_space_secret(space, "HF_TOKEN", token)  # lets the app persist compiled cards to a dataset
    say(f"- Space secrets set: {', '.join(set_keys + ['HF_TOKEN'])}")
    missing = [k for k in ("GROQ_API_KEY", "GEMINI_API_KEY") if k not in set_keys]
    if missing:
        say(f"- ⚠️ Missing recommended secrets: {', '.join(missing)}")
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        for name in INCLUDE:
            src = ROOT / name
            if src.is_dir():
                shutil.copytree(src, stage / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            elif src.exists():
                shutil.copy2(src, stage / name)
        readme = (ROOT / "README.md").read_text(encoding="utf-8") if (ROOT / "README.md").exists() else "# AdhikarVani\n"
        (stage / "README.md").write_text(FRONT_MATTER + readme, encoding="utf-8")
        info = api.upload_folder(repo_id=space, repo_type="space", folder_path=str(stage),
                                 commit_message=f"Deploy {sha} from GitHub",
                                 delete_patterns=["app/**", "static/**", "scripts/**", "tests/**", "docs/**"])
    say(f"- Uploaded: {getattr(info, 'commit_url', info)}")


def verify(api: HfApi, space: str, token: str, host: str, wait: int, say) -> bool:
    t0, stage = time.time(), "UNKNOWN"
    while time.time() - t0 < wait:
        try:
            stage = str(api.get_space_runtime(space).stage)
        except Exception as e:
            stage = f"UNKNOWN ({type(e).__name__})"
        if stage in ("RUNNING", "BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR", "NO_APP_FILE"):
            break
        time.sleep(15)
    say(f"- Space stage after {int(time.time() - t0)} s: **{stage}**")
    if stage != "RUNNING":
        kind = "run" if "RUNTIME" in stage else "build"
        say(f"\n<details><summary>{kind} log tail</summary>\n\n```")
        for line in log_tail(token, space, kind):
            say(line)
        say("```\n</details>")
        return False
    for _ in range(24):  # the container may still be starting up
        try:
            r = httpx.get(f"{host}/api/health", timeout=20)
            if r.status_code == 200:
                h = r.json()
                say(f"- Health: providers={h['llm']['configured']} store={h['store']}")
                for prof, models in h["llm"]["active"].items():
                    say(f"  - {prof}: {', '.join(models) or 'none'}")
                return True
        except Exception:
            pass
        time.sleep(10)
    say("- ⚠️ /api/health did not answer\n\n```")
    for line in log_tail(token, space, "run"):
        say(line)
    say("```")
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default="report.md")
    ap.add_argument("--wait", type=int, default=1200, help="seconds to wait for the build")
    ap.add_argument("--upload-only", action="store_true")
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()
    report = open(args.report, "a", encoding="utf-8")

    def say(line: str = "") -> None:
        print(line, flush=True)
        report.write(line + "\n")

    token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        say("## Deploy\n\n**HF_TOKEN secret is missing.** Add it in GitHub → Settings → Secrets and variables → Actions.")
        return 1
    api = HfApi(token=token)
    me = api.whoami()
    user = me["name"]
    role = ((me.get("auth") or {}).get("accessToken") or {}).get("role")
    say(f"- Token owner: {user}; token type: {role or 'unknown'}")
    space = os.getenv("HF_SPACE", "").strip() or f"{user}/adhikarvani"
    host = f"https://{space.replace('/', '-').replace('_', '-').replace('.', '-').lower()}.hf.space"
    sha = os.getenv("GITHUB_SHA", "local")[:7]
    ok = True
    if not args.verify_only:
        say(f"## Deploy to https://huggingface.co/spaces/{space} (commit {sha})\n")
        try:
            upload(api, space, token, sha, say)
        except Exception as e:
            import traceback
            say(f"- ❌ Upload failed: {type(e).__name__}: {str(e)[:600]}")
            if "403" in str(e) or "401" in str(e) or "rights" in str(e).lower() or "permission" in str(e).lower():
                say("- The HF_TOKEN probably has read-only access. Create a token with **Write** permission at "
                    "https://huggingface.co/settings/tokens and update the HF_TOKEN repository secret.")
            say("\n```\n" + traceback.format_exc()[-2000:] + "\n```")
            report.close()
            return 1
        say(f"- App URL: {host}")
    if not args.upload_only:
        say("\n## Space status\n")
        ok = verify(api, space, token, host, args.wait, say)
    report.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
