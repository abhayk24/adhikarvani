"""The LLM router under simulated failures (no network): a provider that stalls,
a rate limit with Retry-After, streamed output, and a reply that is not JSON."""
import json

import httpx
import pytest

from app import llm


def sse(*chunks: str) -> bytes:
    out = []
    for c in chunks:
        out.append("data: " + json.dumps({"choices": [{"delta": {"content": c}}]}))
    out.append("data: [DONE]")
    return ("\n\n".join(out) + "\n\n").encode()


@pytest.fixture()
def router(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    monkeypatch.setenv("GROQ_API_KEY", "q-test")
    for k in ("CEREBRAS_API_KEY", "MISTRAL_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    llm._models_cache.clear()
    llm._cooldown.clear()
    llm._disabled.clear()
    state = {"handler": None, "calls": []}

    def transport(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if request.url.path.endswith("/models"):
            ids = ["gemini-3.5-flash", "gemini-2.5-flash"] if "googleapis" in host else ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
            return httpx.Response(200, json={"data": [{"id": i} for i in ids]})
        body = json.loads(request.content)
        state["calls"].append((host, body["model"]))
        return state["handler"](request, host, body)

    monkeypatch.setattr(llm, "_client", httpx.Client(transport=httpx.MockTransport(transport)))
    yield state
    llm._models_cache.clear()
    llm._cooldown.clear()
    llm._disabled.clear()


def test_stalled_provider_fails_over_to_next(router):
    def handler(req, host, body):
        if "googleapis" in host:
            raise httpx.ReadTimeout("silent", request=req)
        return httpx.Response(200, content=sse('{"ok":', ' true}'), headers={"content-type": "text/event-stream"})
    router["handler"] = handler
    events = []
    data, meta = llm.chat_json(task="t", profile="heavy", system="s", user="u", trace=events.append)
    assert data == {"ok": True} and meta["provider"] == "Groq"
    # the whole Gemini provider is rested after one stall, so its second model is not tried
    assert [h for h, _ in router["calls"]].count("generativelanguage.googleapis.com") == 1
    assert any(e["status"] == "failover" and "stalled" in e["detail"] for e in events)


def test_rate_limit_sets_cooldown_and_fails_over(router):
    def handler(req, host, body):
        if body["model"] == "gemini-3.5-flash":
            return httpx.Response(429, headers={"retry-after": "30"}, json={"error": {"message": "quota"}})
        return httpx.Response(200, content=sse('{"v": 2}'), headers={"content-type": "text/event-stream"})
    router["handler"] = handler
    data, meta = llm.chat_json(task="t", profile="heavy", system="s", user="u")
    assert data == {"v": 2} and meta["model"] == "gemini-2.5-flash"
    assert llm._cooling(llm.PROVIDER_BY_NAME["gemini"], "gemini-3.5-flash") > 20


def test_invalid_json_is_repaired_by_the_model(router):
    replies = iter(["Sure! here you go", '{"fixed": true}'])

    def handler(req, host, body):
        return httpx.Response(200, content=sse(next(replies)), headers={"content-type": "text/event-stream"})
    router["handler"] = handler
    data, _ = llm.chat_json(task="t", profile="fast", system="s", user="u")
    assert data == {"fixed": True}


def test_unsupported_json_mode_is_dropped(router):
    def handler(req, host, body):
        if "response_format" in body:
            return httpx.Response(400, json={"error": {"message": "response_format is not supported"}})
        return httpx.Response(200, content=sse('{"plain": 1}'), headers={"content-type": "text/event-stream"})
    router["handler"] = handler
    data, _ = llm.chat_json(task="t", profile="fast", system="s", user="u")
    assert data == {"plain": 1}


def test_parse_json_loose_handles_fences_and_think_blocks():
    assert llm.parse_json_loose('<think>hmm</think>```json\n{"a": 1,}\n```') == {"a": 1}
    assert llm.parse_json_loose('Here: {"b": [1, 2]} done') == {"b": [1, 2]}
