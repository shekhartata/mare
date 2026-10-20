"""Plan one model response. Execution stays serial unless the caller opts in."""

from __future__ import annotations

import contextvars
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings
from app.retrieval.tool_policy import ToolPolicy

_POOL: ThreadPoolExecutor | None = None
_SEM: threading.BoundedSemaphore | None = None
_GUARD = threading.Lock()


@dataclass
class PlannedCall:
    index: int
    call_id: str
    name: str
    args: dict[str, Any]
    raw: dict[str, Any]
    decision: str
    reason: str


@dataclass
class Segment:
    parallel: bool
    calls: list[PlannedCall] = field(default_factory=list)


def plan_calls(
    tool_calls: list[dict[str, Any]],
    handlers: dict[str, Any],
    ledger: Any,
    *,
    cap: int,
) -> list[PlannedCall]:
    del cap
    policies = getattr(handlers, "policies", None) or {}
    planned: list[PlannedCall] = []
    for index, raw in enumerate(tool_calls):
        function = raw.get("function") or {}
        name = str(function.get("name") or "")
        args = _parse(function.get("arguments"))
        decision, reason = _decide(name, args, handlers, policies, ledger)
        planned.append(
            PlannedCall(
                index=index,
                call_id=str(raw.get("id") or ""),
                name=name,
                args=args,
                raw=raw,
                decision=decision,
                reason=reason,
            )
        )
    return planned


def segments(planned: list[PlannedCall], cap: int) -> list[Segment]:
    out: list[Segment] = []
    batch: list[PlannedCall] = []

    def flush() -> None:
        nonlocal batch
        if batch:
            out.append(Segment(parallel=True, calls=batch))
            batch = []

    for call in planned:
        if call.decision == "parallel_eligible":
            batch.append(call)
            if len(batch) >= max(1, cap):
                flush()
            continue
        flush()
        out.append(Segment(parallel=False, calls=[call]))
    flush()
    return out


def summarize(
    planned: list[PlannedCall],
    *,
    executed_parallel: bool,
    max_concurrency: int,
    batch_wall_ms: float | None,
    sum_call_ms: float | None,
) -> dict[str, Any]:
    reasons: dict[str, int] = {}
    eligible = 0
    for call in planned:
        if call.decision == "parallel_eligible":
            eligible += 1
        else:
            reasons[call.reason] = reasons.get(call.reason, 0) + 1
    return {
        "eligible": eligible,
        "ineligible": len(planned) - eligible,
        "reasons": reasons,
        "parallel_batches": 1 if executed_parallel else 0,
        "max_concurrency": max_concurrency if executed_parallel else 1,
        "batch_wall_ms": batch_wall_ms,
        "sum_call_ms": sum_call_ms,
    }


def run_bounded(
    calls: list[PlannedCall],
    worker: Any,
    *,
    deadline: float,
    semaphore: threading.BoundedSemaphore | None = None,
) -> list[tuple[float, Any]]:
    """Run calls together. Results stay in request order. Workers do not touch the session."""
    pool, default_sem = _executor()
    sem = semaphore or default_sem
    results: list[tuple[float, Any] | None] = [None] * len(calls)

    def guarded(call: PlannedCall) -> tuple[float, Any]:
        sem.acquire()
        try:
            if time.perf_counter() >= deadline:
                return 0.0, {"error": "deadline"}
            started = time.perf_counter()
            try:
                value = worker(call)
            except Exception as exc:
                value = {"error": str(exc)}
            return (time.perf_counter() - started) * 1000, value
        finally:
            sem.release()

    futures = []
    for index, call in enumerate(calls):
        ctx = contextvars.copy_context()
        futures.append((index, pool.submit(ctx.run, guarded, call)))
    for index, future in futures:
        remaining = deadline - time.perf_counter()
        try:
            if remaining <= 0:
                results[index] = (0.0, {"error": "deadline"})
                continue
            results[index] = future.result(timeout=remaining)
        except FuturesTimeout:
            results[index] = (max(remaining, 0) * 1000, {"error": "deadline"})
        except Exception as exc:
            results[index] = (0.0, {"error": str(exc)})
    return [item if item is not None else (0.0, {"error": "deadline"}) for item in results]


def _executor() -> tuple[ThreadPoolExecutor, threading.BoundedSemaphore]:
    global _POOL, _SEM
    with _GUARD:
        if _POOL is None or _SEM is None:
            workers = max(1, int(get_settings().parallel_tools_global))
            _POOL = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mare-tool")
            _SEM = threading.BoundedSemaphore(workers)
        return _POOL, _SEM


def _decide(
    name: str,
    args: dict[str, Any],
    handlers: dict[str, Any],
    policies: dict[str, ToolPolicy],
    ledger: Any,
) -> tuple[str, str]:
    if name == "submit_answer":
        return "sequential_reason", "finalization"
    policy = policies.get(name)
    registered = handlers.get(name)
    if policy is None or registered is None or policy.handler is not registered:
        return "sequential_reason", "no approved policy for this handler"
    if policy.barrier or not policy.read_only or not policy.concurrent_safe:
        return "sequential_reason", "handler is not approved for concurrent reads"
    reason = policy.validate(args, ledger)
    if reason:
        return "invalid_input_reason", reason
    return "parallel_eligible", ""


def _parse(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
