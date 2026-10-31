"""AdhikarVani web server (FastAPI).

Pages:  /               single-page app
API:    /api/health     providers, models, voice, storage status
        /api/pulse      live PIB press-release feed
        /api/compile    start compiling a URL or uploaded file -> job id
        /api/jobs/{id}/events   live agent trace (Server-Sent Events)
        /api/policies[/{id}]    compiled Rights Cards
        /api/policies/{id}/explain   spoken explainer in another language
        /api/agent/turn         one voice/text turn of the eligibility agent
        /api/graph              the compiler's state graph (Mermaid)
"""
from __future__ import annotations

import json
import logging
import re
import threading
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import agent, config, jobs, llm, sources, voice
from .compiler import GRAPH, CompileError, CompileInput, compile_policy, generate_explainer, speak_explainer
from .languages import LANGS, lang_or_default
from .store import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("adhikarvani")
store = Store()
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,120}$")
AUDIO_RE = re.compile(r"^[a-z0-9-]{3,140}_[a-z]{2}\.mp3$")
REPLY_RE = re.compile(r"^[a-f0-9]{32}\.mp3$")
_explain_locks: dict[str, threading.Lock] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.start()
    threading.Thread(target=llm.warm_up, daemon=True).start()
    log.info("AdhikarVani %s ready: %s", config.VERSION, store.status())
    yield


app = FastAPI(title="AdhikarVani API", version=config.VERSION, lifespan=lifespan,
              description="Compiles government documents into verified, executable Rights Cards.")
app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse({"error": "Something went wrong on our side. Please try again."}, status_code=500)


def _need_id(policy_id: str) -> None:
    if not ID_RE.match(policy_id or ""):
        raise HTTPException(400, "Invalid policy id")


# ------------------------------------------------------------------ pages --
@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(config.STATIC_DIR / "index.html")


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/api/health")
def health():
    return {
        "status": "ok", "app": config.APP_NAME, "version": config.VERSION,
        "llm": {"configured": llm.configured_providers(), "active": llm.active_models(),
                "stats": {k: v for k, v in llm.STATS.items()}},
        "voice": {"asr": "Groq Whisper large-v3 → Gemini audio fallback",
                  "tts": "Edge neural voices → Google TTS fallback"},
        "languages": {k: {"name": v["name"], "native": v["native"]} for k, v in LANGS.items()},
        "store": store.status(),
    }


@app.get("/api/graph")
def graph():
    return {"mermaid": GRAPH.to_mermaid()}


# ------------------------------------------------------------------ pulse --
@app.get("/api/pulse")
def pulse(lang: str = "en"):
    try:
        return sources.pib_feed(lang)
    except sources.SourceError as e:
        raise HTTPException(502, f"The PIB feed is unreachable right now: {e}") from e


# ---------------------------------------------------------------- compile --
@app.post("/api/compile")
async def compile_endpoint(url: Optional[str] = Form(None), lang: str = Form("hi"), force: bool = Form(False),
                           file: Optional[UploadFile] = File(None)):
    data, name = None, None
    if file is not None and file.filename:
        data = await file.read(config.MAX_DOWNLOAD_BYTES + 1)
        if len(data) > config.MAX_DOWNLOAD_BYTES:
            raise HTTPException(413, "File is larger than 25 MB.")
        if not data:
            raise HTTPException(400, "The uploaded file is empty.")
        name = file.filename[:120]
    elif not (url or "").strip():
        raise HTTPException(400, "Paste a link to a government document or upload a file.")
    inp = CompileInput(url=(url or "").strip() or None, file_bytes=data, filename=name, lang=lang_or_default(lang),
                       force=bool(force))

    def work(job: jobs.Job):
        try:
            card = compile_policy(inp, job.emit, store)
        except CompileError as e:
            raise RuntimeError(str(e)) from e
        return {"policy_id": card.id, "title": card.title}

    job = jobs.start("compile", work)
    return {"job_id": job.id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str, after: int = 0):
    job = jobs.JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found (it may have expired).")
    return job.snapshot(after)


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request):
    job = jobs.JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found (it may have expired).")
    last = int(request.headers.get("last-event-id") or 0)
    return StreamingResponse(jobs.sse(job, last), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --------------------------------------------------------------- policies --
@app.get("/api/policies")
def list_policies():
    return {"policies": store.list()}


@app.get("/api/policies/{policy_id}")
def get_policy(policy_id: str):
    _need_id(policy_id)
    card = store.get(policy_id)
    if not card:
        raise HTTPException(404, "Policy not found")
    return json.loads(card.model_dump_json())


@app.post("/api/policies/{policy_id}/explain")
def explain(policy_id: str, lang: str = Form("hi")):
    _need_id(policy_id)
    lang = lang_or_default(lang)
    lock = _explain_locks.setdefault(f"{policy_id}:{lang}", threading.Lock())
    with lock:
        card = store.get(policy_id)
        if not card:
            raise HTTPException(404, "Policy not found")
        ex = card.explainers.get(lang)
        events: list[dict] = []
        if not ex:
            try:
                ex = generate_explainer(card, lang, events.append)
            except llm.LLMError as e:
                raise HTTPException(503, f"The AI service is busy; please retry in a few seconds. ({str(e)[:120]})")
        if not ex.audio or not (config.AUDIO_DIR / ex.audio).exists():
            try:
                speak_explainer(card, ex, events.append)
            except voice.VoiceError as e:
                ex.warnings = list(dict.fromkeys(ex.warnings + [str(e)]))
        card.explainers[lang] = ex
        store.save(card)
    return {"explainer": json.loads(ex.model_dump_json()), "events": events}


@app.delete("/api/policies/{policy_id}")
def delete_policy(policy_id: str, request: Request):
    _need_id(policy_id)
    if not config.ADMIN_KEY or request.headers.get("x-admin-key") != config.ADMIN_KEY:
        raise HTTPException(403, "Deleting requires the admin key.")
    if not store.delete(policy_id):
        raise HTTPException(404, "Policy not found")
    return {"deleted": policy_id}


# ------------------------------------------------------------------ agent --
@app.post("/api/agent/turn")
def agent_turn(mode: str = Form("policy"), policy_id: Optional[str] = Form(None), lang: str = Form("hi"),
               text: Optional[str] = Form(None), state: str = Form("{}"), audio: Optional[UploadFile] = File(None)):
    if mode not in ("policy", "radar"):
        raise HTTPException(400, "mode must be policy or radar")
    if mode == "policy":
        _need_id(policy_id or "")
    try:
        st = json.loads(state or "{}")
        if not isinstance(st, dict):
            raise ValueError
    except ValueError:
        st = {}
    audio_bytes, audio_name = None, None
    if audio is not None and audio.filename:
        audio_bytes = audio.file.read(config.MAX_AUDIO_BYTES + 1)
        if len(audio_bytes) > config.MAX_AUDIO_BYTES:
            raise HTTPException(413, "Recording is too long; keep it under a minute.")
        audio_name = audio.filename
    events: list[dict] = []
    try:
        out = agent.run_turn(agent.TurnInput(mode=mode, policy_id=policy_id, lang=lang, text=(text or "")[:2000],
                                             audio=audio_bytes or None, audio_name=audio_name, state=st),
                             store, events.append)
    except (agent.AgentError, voice.VoiceError) as e:
        raise HTTPException(422, str(e)) from e
    out["events"] = events
    return out


# ------------------------------------------------------------------ audio --
@app.get("/audio/r/{name}")
def reply_audio(name: str):
    if not REPLY_RE.match(name):
        raise HTTPException(400, "bad name")
    path = agent.REPLY_AUDIO_DIR / name
    if not path.exists():
        raise HTTPException(404, "expired")
    return FileResponse(path, media_type="audio/mpeg")


@app.get("/audio/{name}")
def card_audio(name: str):
    if not AUDIO_RE.match(name):
        raise HTTPException(400, "bad name")
    path = config.AUDIO_DIR / name
    if not path.exists():
        raise HTTPException(404, "not found")
    return FileResponse(path, media_type="audio/mpeg", headers={"Cache-Control": "public, max-age=86400"})
