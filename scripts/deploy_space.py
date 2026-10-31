"""Publish AdhikarVani on Hugging Face (run by GitHub Actions).

Two modes (repository variable HF_SPACE_MODE):
* static (default, free): a static Space that is the public front door to the live app
  hosted on Render (APP_URL / deploy/app_url.txt), embedding it full-page.
* docker (needs Hugging Face PRO since July 2026): the whole app runs in a Docker Space.

Docker mode:
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


FRONT_DOOR = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AdhikarVani: your rights, in your voice</title>
<style>
  html, body { margin: 0; height: 100%; background: #EDF1EA; font-family: system-ui, sans-serif; }
  .bar { display: flex; gap: 12px; justify-content: space-between; align-items: center; padding: 6px 14px;
         background: #2B2A6E; color: #F3EEDF; font-size: 14px; }
  .bar a { color: #E2CF9F; font-weight: 600; }
  iframe { border: 0; width: 100%; height: calc(100% - 34px); display: block; }
</style>
</head>
<body>
<div class="bar"><span>AdhikarVani (अधिकार-वाणी). If the app is waking up, the first load can take about a minute.</span>
<a href="__APP__" target="_blank" rel="noopener">Open full screen</a></div>
<iframe src="__APP__" title="AdhikarVani app" allow="microphone; autoplay; clipboard-write"></iframe>
</body>
</html>
"""
STATIC_FRONT_MATTER = FRONT_MATTER.replace("sdk: docker\napp_port: 7860\n", "sdk: static\n")


def app_url() -> str:
    url = os.getenv("APP_URL", "").strip()
    if not url:
        f = ROOT / "deploy" / "app_url.txt"
        url = f.read_text().strip() if f.exists() else ""
    return url.rstrip("/")


def front_door(api: HfApi, space: str, sha: str, url: str, say) -> None:
    api.create_repo(space, repo_type="space", space_sdk="static", exist_ok=True, private=False)
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        (stage / "index.html").write_text(FRONT_DOOR.replace("__APP__", url), encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8") if (ROOT / "README.md").exists() else "# AdhikarVani\n"
        (stage / "README.md").write_text(STATIC_FRONT_MATTER + f"**Live app:** {url}\n\n" + readme, encoding="utf-8")
        info = api.upload_folder(repo_id=space, repo_type="space", folder_path=str(stage),
                                 commit_message=f"Front door for {sha}")
    say(f"- Static front-door Space updated: {getattr(info, 'commit_url', info)}")
    say(f"- It embeds the live app at {url}")


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


def check_app(url: str, say, tries: int = 6) -> bool:
    """Report the live app's health (the host deploys on its own; a cold start can take a minute)."""
    if not url:
        say("- No APP_URL configured")
        return False
    for _ in range(tries):
        try:
            r = httpx.get(f"{url}/api/health", timeout=90)
            if r.status_code == 200:
                h = r.json()
                say(f"- {url} is up: version {h.get('version')}, providers {h['llm']['configured']}, store {h['store']}")
                for prof, models in h["llm"]["active"].items():
                    say(f"  - {prof}: {', '.join(models) or '(discovering)'}")
                return True
            say(f"- {url} answered HTTP {r.status_code}")
        except Exception as e:
            say(f"- {url} not reachable yet ({type(e).__name__})")
        time.sleep(20)
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
    mode = os.getenv("HF_SPACE_MODE", "static").strip().lower() or "static"
    url = app_url()
    if mode != "docker":
        say(f"## Hugging Face front door https://huggingface.co/spaces/{space} (commit {sha})\n")
        if not args.verify_only:
            try:
                front_door(api, space, sha, url, say)
            except Exception as e:
                say(f"- ❌ Front door update failed: {type(e).__name__}: {str(e)[:400]}")
        ok = True
        if not args.upload_only:
            say("\n## Live app\n")
            ok = check_app(url, say)
        report.close()
        return 0
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
