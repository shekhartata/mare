"""Load a saved generic index and time the ask, including vector load."""

from __future__ import annotations

import time
from typing import Any

from app.indexing.signals.store import load_generic_handlers
from app.retrieval.agent_loop import run_agent


def run_saved_generic(
    client: Any,
    question: str,
    embedder: Any | None = None,
    **agent_kwargs: Any,
) -> tuple[Any, dict[str, Any]]:
    started = time.perf_counter()
    handlers = load_generic_handlers(client, embedder)
    load_ms = (time.perf_counter() - started) * 1000
    session = run_agent(
        question,
        handlers=handlers,
        persist=agent_kwargs.pop("persist", False),
        schema_in_prompt=agent_kwargs.pop("schema_in_prompt", False),
        **agent_kwargs,
    )
    request_ms = (time.perf_counter() - started) * 1000
    surface = getattr(handlers, "surface", None)
    return session, {
        "load_ms": round(load_ms),
        "request_ms": round(request_ms),
        "index_status": dict(getattr(handlers, "semantic", {}) or {}),
        "embed_calls": dict(getattr(surface, "embed_calls", {}) or {}),
    }
