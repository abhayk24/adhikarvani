"""Background compile jobs whose events stream to the browser (Server-Sent Events).

Every node, tool call, LLM call, failover and guardrail decision is an event, so
the UI shows the agent's work live and a dropped connection can resume from the
last event id.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from . import config

_pool = ThreadPoolExecutor(max_workers=config.MAX_CONCURRENT_COMPILES, thread_name_prefix="compile")


class Job:
    def __init__(self, kind: str):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.status = "queued"
        self.events: list[dict] = []
        self.result: Any = None
        self.error: str | None = None
        self.created = time.time()
        self._cond = threading.Condition()

    def emit(self, event: dict) -> None:
        with self._cond:
            event = {"seq": len(self.events) + 1, "t": round(time.time() - self.created, 2), **event}
            self.events.append(event)
            self._cond.notify_all()

    def finish(self, status: str, result: Any = None, error: str | None = None) -> None:
        with self._cond:
            self.status, self.result, self.error = status, result, error
            self._cond.notify_all()
        self.emit({"type": "end", "status": status, "result": result, "error": error})

    def snapshot(self, after: int = 0) -> dict:
        return {"id": self.id, "status": self.status, "events": self.events[after:], "result": self.result,
                "error": self.error}


JOBS: dict[str, Job] = {}


def start(kind: str, work: Callable[[Job], Any]) -> Job:
    job = Job(kind)
    JOBS[job.id] = job
    _gc()

    def run() -> None:
        job.status = "running"
        job.emit({"type": "start", "kind": kind})
        try:
            result = work(job)
            job.finish("done", result=result)
        except Exception as e:  # surfaced to the UI as a readable message
            job.finish("error", error=str(e)[:500] or type(e).__name__)

    _pool.submit(run)
    return job


def _gc(max_age: int = 3 * 3600) -> None:
    now = time.time()
    for jid in [j for j, job in JOBS.items() if now - job.created > max_age]:
        JOBS.pop(jid, None)


async def sse(job: Job, last_seq: int = 0):
    """Yield SSE frames until the job ends; heartbeats keep proxies from closing the stream."""
    sent = last_seq
    idle = 0.0
    while True:
        batch = job.events[sent:]
        for ev in batch:
            sent = ev["seq"]
            yield f"id: {ev['seq']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
            if ev.get("type") == "end":
                return
        if not batch:
            await asyncio.sleep(0.25)
            idle += 0.25
            if idle >= 12:
                idle = 0.0
                yield ": keep-alive\n\n"
        else:
            idle = 0.0
