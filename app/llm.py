"""Provider-agnostic LLM router with automatic failover.

Groq, Google Gemini, Cerebras, OpenRouter and Mistral all speak the OpenAI
chat-completions dialect, so one small HTTP client covers all of them.

What the router does on every call:
  1. Discovers which models each API key can really use (GET /models, cached).
  2. Builds a ranked candidate list for the call's *profile*:
       heavy = long-document reasoning, write = multilingual writing, fast = short JSON.
  3. Packs as much document text as the chosen provider can take
     (``build_user(char_budget)``), so a big-context model gets more evidence.
  4. On rate limits, outages, oversized requests or broken JSON it moves to the
     next candidate, remembering Retry-After cool-downs.
  5. Repairs invalid JSON once by showing the model its own error (self-correction).
  6. Reports every attempt to the live trace shown in the UI.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import httpx

Trace = Optional[Callable[[dict], None]]


class LLMError(RuntimeError):
    pass


@dataclass
class Provider:
    name: str
    label: str
    base_url: str
    key_env: str
    prefs: dict[str, list[str]]
    char_budget: int  # document characters a heavy prompt may carry for this provider
    extra_headers: dict[str, str] = field(default_factory=dict)
    max_output: int = 16000  # output cap so prompt + output fits the free tier's tokens-per-minute

    def key(self) -> str:
        return os.getenv(self.key_env, "").strip()


def _env_list(name: str, default: list[str]) -> list[str]:
    """Model preference list, overridable with a comma-separated environment variable."""
    raw = os.getenv(name, "").strip()
    return [m.strip() for m in raw.split(",") if m.strip()] or default


_GEMINI_FLASH = r"re:^gemini-\d+(?:\.\d+)?-flash(?:-preview(?:-\d{2}-\d{4})?)?$"
_GEMINI_LITE = r"re:^gemini-\d+(?:\.\d+)?-flash-lite(?:-preview(?:-\d{2}-\d{4})?)?$"

PROVIDERS: list[Provider] = [
    Provider(
        "gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY",
        {
            # Measured from CI (Oct 2026): 3.5-flash ~2 s, 2.5-flash ~0.6 s to first token;
            # 3.8-flash and the *-latest aliases stalled on the free tier, so they are not used.
            "heavy": _env_list("GEMINI_MODELS", ["gemini-3.5-flash", "gemini-2.5-flash", "gemini-3.5-flash-lite",
                                                 "gemini-3.1-flash-lite"]),
            "write": _env_list("GEMINI_MODELS", ["gemini-3.5-flash", "gemini-2.5-flash", "gemini-3.5-flash-lite",
                                                 "gemini-3.1-flash-lite"]),
            "fast": _env_list("GEMINI_FAST_MODELS", ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]),
            "logic": _env_list("GEMINI_MODELS", ["gemini-3.5-flash", "gemini-2.5-flash", "gemini-3.5-flash-lite"]),
            "chat": _env_list("GEMINI_CHAT_MODELS", ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-2.5-flash"]),
        },
        char_budget=120_000,
    ),
    Provider(
        "groq", "Groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY",
        {
            "heavy": _env_list("GROQ_MODELS", ["openai/gpt-oss-120b", "llama-3.3-70b-versatile",
                                               "moonshotai/kimi-k2-instruct-0905", r"re:^qwen/qwen3", "openai/gpt-oss-20b"]),
            "write": _env_list("GROQ_MODELS", ["openai/gpt-oss-120b", "moonshotai/kimi-k2-instruct-0905",
                                               "llama-3.3-70b-versatile", r"re:^qwen/qwen3"]),
            "fast": _env_list("GROQ_FAST_MODELS", ["openai/gpt-oss-20b", "llama-3.3-70b-versatile",
                                                   "openai/gpt-oss-120b", "llama-3.1-8b-instant"]),
            "logic": _env_list("GROQ_MODELS", ["openai/gpt-oss-120b", r"re:^qwen/qwen3", "openai/gpt-oss-20b"]),
            "chat": _env_list("GROQ_MODELS", ["openai/gpt-oss-120b", "openai/gpt-oss-20b", r"re:^qwen/qwen3"]),
        },
        char_budget=9_000,
        max_output=4200,
    ),
    Provider(
        "cerebras", "Cerebras", "https://api.cerebras.ai/v1", "CEREBRAS_API_KEY",
        {p: ["gpt-oss-120b", "llama-3.3-70b", r"re:^qwen-3", "llama3.1-8b"] for p in ("heavy", "write", "fast", "logic", "chat")},
        char_budget=24_000,
    ),
    Provider(
        "mistral", "Mistral", "https://api.mistral.ai/v1", "MISTRAL_API_KEY",
        {p: ["mistral-medium-latest", "mistral-small-latest"] for p in ("heavy", "write", "fast", "logic", "chat")},
        char_budget=60_000,
    ),
    Provider(
        "openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY",
        {p: ["openai/gpt-oss-120b:free", r"re:^meta-llama/llama-3\.3-70b-instruct:free$",
             r"re:^deepseek/deepseek-chat.*:free$", r"re:^qwen/qwen3.*:free$"] for p in ("heavy", "write", "fast", "logic", "chat")},
        char_budget=30_000,
        extra_headers={"HTTP-Referer": "https://huggingface.co/spaces", "X-Title": "AdhikarVani"},
    ),
]
PROVIDER_BY_NAME = {p.name: p for p in PROVIDERS}

# Gemini Flash's free daily quota is small, so it is used where quality matters most (reading
# documents, compiling rules, Indian-language explainers); repairs go to Groq first and voice
# replies to Gemini Flash-Lite, whose free quota is much larger.
PROFILE_ORDER = {
    "heavy": ["gemini", "groq", "cerebras", "mistral", "openrouter"],   # read long documents
    "write": ["gemini", "groq", "cerebras", "mistral", "openrouter"],   # explainers in 11 languages
    "logic": ["groq", "cerebras", "gemini", "mistral", "openrouter"],   # rules, repairs
    "chat": ["gemini", "groq", "cerebras", "mistral", "openrouter"],    # voice replies (Flash-Lite: high quota, good Hindi)
    "fast": ["groq", "gemini", "cerebras", "mistral", "openrouter"],    # short checks
}
PROFILE_TIMEOUT = {"heavy": 150.0, "write": 90.0, "logic": 120.0, "chat": 45.0, "fast": 45.0}   # total per attempt while streaming

_client = httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0))
_models_cache: dict[str, tuple[float, Optional[set[str]]]] = {}
_cooldown: dict[str, float] = {}
_disabled: set[str] = set()
_lock = threading.Lock()
STATS: dict[str, Any] = {"calls": 0, "ok": 0, "failovers": 0, "repairs": 0, "by_provider": {}}


# ----------------------------------------------------------------- helpers --
def _headers(p: Provider) -> dict[str, str]:
    return {"Authorization": f"Bearer {p.key()}", "Content-Type": "application/json", **p.extra_headers}


def list_models(p: Provider, force: bool = False) -> Optional[set[str]]:
    """Model ids this key can use; None if discovery itself failed (network)."""
    now = time.time()
    cached = _models_cache.get(p.name)
    if cached and not force and now - cached[0] < 900:
        return cached[1]
    ids: Optional[set[str]]
    try:
        r = _client.get(f"{p.base_url}/models", headers=_headers(p), timeout=15)
        if r.status_code in (401, 403):
            _disabled.add(f"{p.name}:*")
            ids = set()
        else:
            r.raise_for_status()
            data = r.json().get("data", [])
            ids = {str(m.get("id", "")).removeprefix("models/") for m in data if m.get("id")}
    except Exception:
        ids = None
    _models_cache[p.name] = (now, ids)
    return ids


_VERSION = re.compile(r"(\d+(?:\.\d+)?)")


def _version_key(model_id: str) -> tuple[float, int]:
    m = _VERSION.search(model_id.split("/")[-1])
    v = float(m.group(1)) if m else 0.0
    unstable = 1 if ("preview" in model_id or "exp" in model_id) else 0
    return (v, -unstable)


def resolve_models(p: Provider, profile: str) -> list[str]:
    available = list_models(p)
    out: list[str] = []
    for pref in p.prefs.get(profile, []):
        if pref.startswith("re:"):
            if not available:
                continue
            rx = re.compile(pref[3:])
            for m in sorted((m for m in available if rx.search(m)), key=_version_key, reverse=True):
                if m not in out:
                    out.append(m)
        elif (available is None or pref in available) and pref not in out:
            out.append(pref)
    return [m for m in out if f"{p.name}:{m}" not in _disabled][:4]


def candidates(profile: str) -> list[tuple[Provider, str]]:
    res: list[tuple[Provider, str]] = []
    for name in PROFILE_ORDER[profile]:
        p = PROVIDER_BY_NAME[name]
        if not p.key() or f"{p.name}:*" in _disabled:
            continue
        res.extend((p, m) for m in resolve_models(p, profile))
    return res


def configured_providers() -> list[str]:
    return [p.name for p in PROVIDERS if p.key()]


def active_models() -> dict[str, Any]:
    """What the router would use right now (cached discovery only, never blocks on the network)."""
    out: dict[str, Any] = {}
    for profile in ("heavy", "write", "logic", "chat", "fast"):
        rows = []
        for name in PROFILE_ORDER[profile]:
            p = PROVIDER_BY_NAME[name]
            if not p.key() or f"{p.name}:*" in _disabled or p.name not in _models_cache:
                continue
            rows += [f"{p.label} · {m}" for m in resolve_models(p, profile)]
        out[profile] = rows[:3]
    return out


def parse_json_loose(text: Optional[str]) -> Any:
    """Parse JSON from a model reply that may contain fences, <think> blocks or chatter."""
    if not text or not text.strip():
        raise ValueError("empty reply")
    t = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.I)
    t = re.sub(r"\s*```\s*$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end > start:
        frag = t[start:end + 1]
        try:
            return json.loads(frag)
        except json.JSONDecodeError:
            return json.loads(re.sub(r",\s*([}\]])", r"\1", frag))
    raise ValueError("no JSON object in reply")


def _retry_after(resp: httpx.Response) -> float:
    h = resp.headers.get("retry-after")
    if h:
        try:
            return min(float(h), 3600.0)
        except ValueError:
            pass
    body = resp.text[:4000]
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", body)
    if m:
        return float(m.group(1) or 0) * 60 + float(m.group(2))
    m = re.search(r'"retryDelay"\s*:\s*"([\d.]+)s"', body)
    if m:
        return float(m.group(1))
    return 20.0


def _is_gemini3(p: Provider, model: str) -> bool:
    return p.name == "gemini" and _version_key(model)[0] >= 3 or (p.name == "gemini" and "latest" in model)


def _payload(p: Provider, model: str, messages: list, max_tokens: int, temperature: float,
             json_mode: bool, effort: Optional[str]) -> dict:
    max_tokens = min(max_tokens, p.max_output)
    body: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if not _is_gemini3(p, model):  # Gemini 3 is tuned for its default temperature
        body["temperature"] = temperature
    if p.name == "gemini":
        body["max_tokens"] = max_tokens + 3000  # thinking tokens share this budget
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if effort:
        if p.name in ("groq", "cerebras") and "gpt-oss" in model:
            body["reasoning_effort"] = effort
        elif p.name == "gemini":
            body["reasoning_effort"] = effort
    if p.name == "groq" and "qwen3" in model:
        body["reasoning_format"] = "hidden"
    return body


class _Skip(Exception):
    """Candidate unusable for this call; move on."""


STALL_S = {"heavy": 45.0, "write": 40.0, "logic": 45.0, "chat": 25.0, "fast": 25.0}   # max silence between streamed chunks


def _handle_error(p: Provider, model: str, code: int, text: str, json_mode: bool, effort: Optional[str],
                  retry_after: float) -> tuple[bool, Optional[str]]:
    """Classify an HTTP error. Returns new (json_mode, effort) to retry with, or raises _Skip."""
    low = text.lower()
    too_large = code == 413 or any(s in low for s in (
        "request too large", "context length", "context_length", "too many tokens", "reduce your message"))
    if code == 429 and not too_large:
        if "limit: 0" in low or ("free tier" in low and "not available" in low):
            _disabled.add(f"{p.name}:{model}")
            raise _Skip("not available on free tier")
        wait = retry_after
        if "per day" in low or "perday" in low or "daily" in low:
            wait = max(wait, 1800)
        _cooldown[f"{p.name}:{model}"] = time.time() + wait
        raise _Skip(f"rate limited ({wait:.0f}s)")
    if too_large:
        raise _Skip("request too large for this model's limits")
    if code in (401, 403):
        _disabled.add(f"{p.name}:*")
        raise _Skip(f"auth failed ({code})")
    if code == 404 or (code == 400 and ("model_not_found" in low or "does not exist" in low
                                        or "decommissioned" in low or "not found" in low)):
        _disabled.add(f"{p.name}:{model}")
        raise _Skip("model unavailable")
    if code == 400 and json_mode and ("response_format" in low or "json_validate_failed" in low
                                      or ("json" in low and "support" in low)):
        return False, effort
    if code == 400 and effort and "reasoning" in low:
        return json_mode, None
    if code >= 500:
        _cooldown[f"{p.name}:{model}"] = time.time() + 20
        raise _Skip(f"provider error {code}")
    raise _Skip(f"HTTP {code}: {text[:160]}")


def _post(p: Provider, model: str, messages: list, max_tokens: int, temperature: float,
          json_mode: bool, effort: Optional[str], timeout: float, stall: float = 40.0) -> tuple[str, dict]:
    """One streamed call. A model that goes silent for `stall` seconds is abandoned (and its whole
    provider rested for a minute), while a long answer that keeps streaming is never cut off early."""
    for _ in range(3):
        body = _payload(p, model, messages, max_tokens, temperature, json_mode, effort)
        body["stream"] = True
        t0 = time.time()
        try:
            with _client.stream("POST", f"{p.base_url}/chat/completions", headers=_headers(p), json=body,
                                timeout=httpx.Timeout(connect=15.0, read=stall, write=30.0, pool=15.0)) as r:
                if r.status_code != 200:
                    r.read()
                    json_mode, effort = _handle_error(p, model, r.status_code, r.text[:1500], json_mode, effort,
                                                      _retry_after(r))
                    continue
                parts: list[str] = []
                usage: dict = {}
                finish = None
                for line in r.iter_lines():
                    if time.time() - t0 > timeout:
                        raise _Skip(f"too slow (>{timeout:.0f}s)")
                    if not line.startswith("data:"):
                        continue  # blank lines and ": keep-alive" comments
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("error"):
                        err = obj["error"]
                        raise _Skip(f"stream error: {str(err.get('message', err) if isinstance(err, dict) else err)[:140]}")
                    if obj.get("usage"):
                        usage = obj["usage"]
                    elif (obj.get("x_groq") or {}).get("usage"):
                        usage = obj["x_groq"]["usage"]
                    for ch in obj.get("choices") or []:
                        piece = (ch.get("delta") or {}).get("content")
                        if piece:
                            parts.append(piece)
                        finish = ch.get("finish_reason") or finish
                content = "".join(parts)
                if not content.strip():
                    raise _Skip(f"empty reply (finish={finish})")
                return content, usage
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as e:
            _cooldown[f"{p.name}:{model}"] = time.time() + 120
            _cooldown[f"{p.name}:*"] = time.time() + 60
            raise _Skip(f"stalled ({type(e).__name__} after {time.time() - t0:.0f}s)") from e
    raise _Skip("unsupported request options")


def _cooling(p: Provider, model: str) -> float:
    """Seconds until this model may be tried again (0 = available)."""
    now = time.time()
    return max(_cooldown.get(f"{p.name}:{model}", 0), _cooldown.get(f"{p.name}:*", 0)) - now


def chat_json(*, task: str, profile: str, system: str, user: Optional[str] = None,
              build_user: Optional[Callable[[int], str]] = None, max_tokens: int = 2048,
              temperature: float = 0.1, effort: Optional[str] = "low",
              validate: Optional[Callable[[Any], Any]] = None, trace: Trace = None,
              deadline_s: float = 170.0) -> tuple[Any, dict]:
    """Run a JSON-returning task with failover. Returns (result, meta)."""
    if user is None and build_user is None:
        raise ValueError("user or build_user required")
    t_end = time.time() + deadline_s
    cands = candidates(profile)
    if not cands:
        raise LLMError("No AI provider is configured. Add GEMINI_API_KEY or GROQ_API_KEY as a secret.")
    errors: list[str] = []
    timeout = PROFILE_TIMEOUT.get(profile, 90.0)

    for round_no in range(3):
        tried_any = False
        for p, model in cands:
            ckey = f"{p.name}:{model}"
            if ckey in _disabled or f"{p.name}:*" in _disabled or _cooling(p, model) > 0:
                continue
            if time.time() > t_end:
                break
            tried_any = True
            u = user if user is not None else build_user(p.char_budget)  # type: ignore[misc]
            messages = [{"role": "system", "content": system}, {"role": "user", "content": u}]
            t0 = time.time()
            STATS["calls"] += 1
            try:
                content, usage = _post(p, model, messages, max_tokens, temperature, True, effort,
                                       min(timeout, max(10.0, t_end - time.time())), STALL_S.get(profile, 40.0))
                result = None
                for repair in range(2):
                    try:
                        data = parse_json_loose(content)
                        result = validate(data) if validate else data
                        break
                    except Exception as e:  # invalid JSON or schema -> show the model its error
                        if repair == 1:
                            raise _Skip(f"invalid output after repair: {str(e)[:120]}")
                        STATS["repairs"] += 1
                        _emit(trace, {"type": "llm", "task": task, "provider": p.label, "model": model,
                                      "status": "repair", "detail": f"self-correcting output: {str(e)[:120]}"})
                        messages = messages + [
                            {"role": "assistant", "content": content[:8000]},
                            {"role": "user", "content": f"That reply could not be used ({str(e)[:300]}). "
                                                        "Reply again with ONLY the corrected JSON object."},
                        ]
                        content, usage = _post(p, model, messages, max_tokens, temperature, True, effort, timeout,
                                               STALL_S.get(profile, 40.0))
                ms = int((time.time() - t0) * 1000)
                STATS["ok"] += 1
                bp = STATS["by_provider"].setdefault(p.label, 0)
                STATS["by_provider"][p.label] = bp + 1
                _emit(trace, {"type": "llm", "task": task, "provider": p.label, "model": model, "status": "ok",
                              "ms": ms, "tokens": usage.get("total_tokens")})
                return result, {"provider": p.label, "model": model, "ms": ms, "usage": usage}
            except _Skip as e:
                STATS["failovers"] += 1
                errors.append(f"{p.label}/{model}: {e}")
                _emit(trace, {"type": "llm", "task": task, "provider": p.label, "model": model,
                              "status": "failover", "detail": str(e), "ms": int((time.time() - t0) * 1000)})
            except Exception as e:  # unexpected (bad JSON from HTTP layer etc.)
                errors.append(f"{p.label}/{model}: {type(e).__name__}: {str(e)[:120]}")
                _emit(trace, {"type": "llm", "task": task, "provider": p.label, "model": model,
                              "status": "failover", "detail": f"{type(e).__name__}"})
        # Everyone is cooling down: wait for the soonest one if the deadline allows.
        now = time.time()
        waits = [_cooling(p, m) for p, m in cands
                 if f"{p.name}:{m}" not in _disabled and f"{p.name}:*" not in _disabled]
        waits = [w for w in waits if w > 0]
        if not waits and tried_any:
            break
        if waits:
            w = min(waits)
            if w <= 30 and now + w < t_end:
                _emit(trace, {"type": "info", "detail": f"All AI providers are rate-limited; waiting {w:.0f}s"})
                time.sleep(w + 0.5)
                continue
        break
    raise LLMError("AI providers unavailable right now: " + " | ".join(errors[-4:] or ["no usable model"]))


def _emit(trace: Trace, event: dict) -> None:
    if trace:
        try:
            trace(event)
        except Exception:
            pass


def warm_up() -> dict[str, Any]:
    """Discover models for every configured provider (run in a background thread)."""
    for p in PROVIDERS:
        if p.key():
            list_models(p, force=True)
    return active_models()
