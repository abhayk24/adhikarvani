"""Speech in and out.

ASR: Whisper large-v3 on Groq (free tier), falling back to Gemini audio input.
TTS: Microsoft neural voices through edge-tts (free), falling back to Google
Translate TTS (gTTS). Audio is normalised with ffmpeg first, so any browser
recording format (webm/ogg/m4a/wav) works.
"""
from __future__ import annotations

import asyncio
import base64
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

import regex

from . import llm
from .languages import LANGS

Trace = Optional[Callable[[dict], None]]


class VoiceError(RuntimeError):
    pass


def _emit(trace: Trace, **e) -> None:
    if trace:
        trace({"type": "tool", **e})


def to_mp3(data: bytes, suffix: str = ".webm") -> bytes:
    """Convert any audio container to 16 kHz mono MP3."""
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / f"in{suffix if suffix.startswith('.') else '.' + suffix}"
        dst = Path(d) / "out.mp3"
        src.write_bytes(data)
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-ac", "1", "-ar", "16000",
             "-b:a", "32k", str(dst)], capture_output=True, timeout=60)
        if proc.returncode != 0 or not dst.exists() or dst.stat().st_size < 200:
            raise VoiceError("Could not read the recording. Please try recording again.")
        return dst.read_bytes()


def _groq_whisper(mp3: bytes, lang: Optional[str]) -> tuple[str, str]:
    p = llm.PROVIDER_BY_NAME["groq"]
    if not p.key():
        raise VoiceError("Groq key not configured")
    available = llm.list_models(p) or set()
    models = [m for m in ("whisper-large-v3", "whisper-large-v3-turbo") if not available or m in available] \
        or sorted(m for m in available if "whisper" in m)
    last = "no whisper model"
    for model in models:
        data = {"model": model, "temperature": "0", "response_format": "json"}
        if lang:
            data["language"] = lang
        try:
            r = llm._client.post(f"{p.base_url}/audio/transcriptions", headers={"Authorization": f"Bearer {p.key()}"},
                                 data=data, files={"file": ("speech.mp3", mp3, "audio/mpeg")}, timeout=60)
        except Exception as e:
            last = type(e).__name__
            continue
        if r.status_code == 200:
            return (r.json().get("text") or "").strip(), model
        last = f"HTTP {r.status_code}"
    raise VoiceError(f"Whisper failed ({last})")


def _gemini_transcribe(mp3: bytes, lang: Optional[str]) -> tuple[str, str]:
    p = llm.PROVIDER_BY_NAME["gemini"]
    if not p.key():
        raise VoiceError("Gemini key not configured")
    models = llm.resolve_models(p, "fast") + llm.resolve_models(p, "heavy")
    hint = f" The speaker most likely uses {LANGS[lang]['name']}." if lang in LANGS else ""
    last = "no model"
    for model in models[:3]:
        body = {"model": model, "messages": [{"role": "user", "content": [
            {"type": "text", "text": "Transcribe this speech exactly, in the original language and its native "
                                     f"script. Reply with only the transcript.{hint}"},
            {"type": "input_audio", "input_audio": {"data": base64.b64encode(mp3).decode(), "format": "mp3"}},
        ]}]}
        try:
            r = llm._client.post(f"{p.base_url}/chat/completions", headers=llm._headers(p), json=body, timeout=60)
        except Exception as e:
            last = type(e).__name__
            continue
        if r.status_code == 200:
            txt = ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            if txt.strip():
                return txt.strip(), model
        last = f"HTTP {r.status_code}"
    raise VoiceError(f"Gemini transcription failed ({last})")


def transcribe(data: bytes, filename: str = "speech.webm", lang: Optional[str] = None,
               trace: Trace = None) -> dict:
    t0 = time.time()
    suffix = os.path.splitext(filename or "")[1] or ".webm"
    mp3 = to_mp3(data, suffix)
    hint = LANGS.get(lang or "", {}).get("whisper")
    errors = []
    for name, fn in (("Groq Whisper", _groq_whisper), ("Gemini", _gemini_transcribe)):
        try:
            text, model = fn(mp3, hint)
            ms = int((time.time() - t0) * 1000)
            _emit(trace, tool="asr", status="ok", detail=f"{name} · {model} · {ms} ms")
            return {"text": text, "provider": name, "model": model, "ms": ms}
        except VoiceError as e:
            errors.append(f"{name}: {e}")
            _emit(trace, tool="asr", status="failover", detail=str(e))
    raise VoiceError("Speech recognition is unavailable right now. You can type instead. (" + "; ".join(errors) + ")")


# -------------------------------------------------------------------- TTS --
def tts_clean(text: str, limit: int = 2400) -> str:
    t = regex.sub(r"https?://\S+", "", text or "")
    t = regex.sub(r"[\[(]\s*(?:K|C|R)\d+(?:\s*,\s*(?:K|C|R)\d+)*\s*[\])]", "", t)  # citation ids
    t = regex.sub(r"[*#_`>|]+", " ", t)
    t = regex.sub(r"^\s*[-•●]\s*", "", t, flags=regex.M)
    t = " ".join(t.split())
    return t[:limit]


async def _edge(text: str, voice: str, out: Path) -> None:
    import edge_tts
    await edge_tts.Communicate(text, voice, rate="-4%").save(str(out))


def synthesize(text: str, lang: str, out_path: Path, trace: Trace = None) -> str:
    """Write an MP3 to out_path; returns the provider used."""
    text = tts_clean(text)
    if not text:
        raise VoiceError("Nothing to speak")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.name + ".part")
    cfg = LANGS.get(lang, LANGS["en"])
    t0 = time.time()
    for voice in cfg["edge"]:
        try:
            asyncio.run(asyncio.wait_for(_edge(text, voice, tmp), timeout=45))
            if tmp.exists() and tmp.stat().st_size > 1500:
                tmp.replace(out_path)
                _emit(trace, tool="tts", status="ok", detail=f"Edge neural voice {voice} · {int((time.time()-t0)*1000)} ms")
                return f"edge:{voice}"
        except Exception as e:
            _emit(trace, tool="tts", status="failover", detail=f"{voice}: {type(e).__name__}")
    try:
        from gtts import gTTS
        gTTS(text=text, lang=cfg["gtts"]).save(str(tmp))
        if tmp.exists() and tmp.stat().st_size > 1500:
            tmp.replace(out_path)
            _emit(trace, tool="tts", status="ok", detail=f"Google TTS ({cfg['gtts']}) · {int((time.time()-t0)*1000)} ms")
            return f"gtts:{cfg['gtts']}"
    except Exception as e:
        _emit(trace, tool="tts", status="failover", detail=f"gTTS: {type(e).__name__}")
    if tmp.exists():
        tmp.unlink(missing_ok=True)
    raise VoiceError("Voice generation is unavailable right now; the text explanation is still shown.")
