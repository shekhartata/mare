"""OpenAI tool-calling retrieval loop.

The model decides which Mongo tools to call and when to answer. Python only
enforces budgets, tenant injection (inside tools), traces, and citation harvest.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from openai import OpenAI

from app.config import get_settings
from app.constants import EVIDENCE_SESSIONS, RAW_DB, is_nav_database
from app.llm.base import ReasoningModel
from app.llm.openai_model import OpenAIReasoningModel, chat_complete, usage_from_response
from app.models.schemas import (
    Claim,
    ClaimStatus,
    EvidenceSession,
    MongoRef,
    RetrievedDocument,
    SessionStatus,
    TraceEvent,
)
from app.mongo.client import agent_db
from app.observability.traces import write_trace
from app.retrieval.context_compact import compact_messages, estimate_tokens, receipt_payload
from app.retrieval.evidence import generate_answer
from app.retrieval.loop import run_adaptive
from app.retrieval.tool_policy import Ledger, absorb
from app.retrieval.tool_scheduler import plan_calls, run_bounded, segments, summarize
from app.retrieval.tools import TOOL_DEFINITIONS, default_handlers, dispatch_tool
from app.search.router import recommend_method

SUBMIT_TOOL = "submit_answer"
_READ_TOOLS = frozenset({"retrieve_evidence", "query_documents", "find", "count"})
FORCE_SUBMIT = (
    "You have reached the retrieval budget. Call submit_answer now using only "
    "evidence already retrieved. Do not call any other tool. If evidence is "
    "incomplete, say so in the answer."
)
BLIND_SYSTEM_PROMPT = (
    "You are MARE, a MongoDB adaptive retrieval agent.\n\n"
    "You do not know the databases, collections, or field names in advance. "
    "Discover them from tool results. Navigation nodes return database.collection, "
    "reusable filters, important fields, field examples, and related neighborhoods. "
    "Nodes point at raw documents; they do not copy payloads.\n\n"
    "How to retrieve:\n"
    "1. search_information to locate neighborhoods "
    "(ids/error codes → lexical; why/root-cause → hybrid/semantic).\n"
    "2. retrieve_evidence on promising node_ids to read raw Mongo documents.\n"
    "3. query_documents only with database.collection and field names you observed "
    "in navigation nodes or retrieved documents.\n"
    "4. When a result includes related_nodes, retrieve those neighborhoods next "
    "instead of stopping after the first entity.\n"
    "5. submit_answer as soon as the evidence is sufficient.\n\n"
    "Rules:\n"
    "- Never invent Mongo document ids, collections, or field names.\n"
    "- Cite sources as database.collection:document_id from retrieved docs.\n"
    "- Multi-hop questions need evidence from more than one collection.\n"
    "- Tenant scope is injected server-side. Never send tenant_id.\n"
    "- Stop once you can answer the user's question from retrieved documents.\n"
)
INFORMED_SYSTEM_PROMPT = (
    "You are MARE, a MongoDB adaptive retrieval agent.\n\n"
    "Environment:\n"
    "- mare_demo is the system of record: customers, tickets, deployments, "
    "migrations, incidents, logs.\n"
    "- navigation_nodes hierarchy: database → collection → customer groups. "
    "Nodes point at raw documents; they do not copy payloads.\n"
    "- Tenant scope is injected server-side. Never send tenant_id.\n\n"
    "How to retrieve:\n"
    "1. search_information to locate neighborhoods "
    "(ids/error codes → lexical; why/root-cause → hybrid/semantic).\n"
    "2. retrieve_evidence on promising node_ids to read raw Mongo documents.\n"
    "3. query_documents when you know a field predicate "
    "(customer_id, error_code, subscription_tier, migration id).\n"
    "4. When a result includes related_nodes, retrieve those neighborhoods next.\n"
    "5. submit_answer as soon as the evidence is sufficient.\n\n"
    "Rules:\n"
    "- Never invent Mongo document ids or collections.\n"
    "- Cite sources as database.collection:document_id from retrieved docs.\n"
    "- Multi-hop questions need evidence from more than one collection.\n"
    "- Stop once you can answer the user's question from retrieved documents.\n"
)
SYSTEM_PROMPT = BLIND_SYSTEM_PROMPT


def system_prompt(*, schema_in_prompt: bool = False) -> str:
    return INFORMED_SYSTEM_PROMPT if schema_in_prompt else BLIND_SYSTEM_PROMPT



def run_agent(
    question: str,
    *,
    tenant_id: str | None = None,
    client: Any | None = None,
    handlers: dict[str, Callable] | None = None,
    persist: bool = True,
    max_turns: int | None = None,
    agent_model: str | None = None,
    answer_model: str | None = None,
    reasoning_effort: str | None = None,
    answer_reasoner: ReasoningModel | None = None,
    schema_in_prompt: bool | None = None,
    use_acgc: bool | None = None,
    compact_context: bool | None = None,
    acgc_client: Any | None = None,
    tool_surface: str | None = None,
    parallel_tools: str | None = None,
) -> EvidenceSession:
    """Run the tool loop. Receipts compact by default; ACGC sidecar only if use_acgc / MARE_ACGC."""
    settings = get_settings()
    tenant_id = tenant_id or settings.tenant_id
    if client is None and not settings.openai_api_key:
        return run_adaptive(question, tenant_id=tenant_id)

    agent_model = agent_model or settings.openai_model_agent or settings.openai_model
    answer_model = answer_model or settings.openai_model
    effort = reasoning_effort if reasoning_effort is not None else settings.openai_reasoning_effort
    max_turns = settings.max_agent_turns if max_turns is None else int(max_turns)
    informed = settings.schema_in_prompt if schema_in_prompt is None else bool(schema_in_prompt)
    surface = (tool_surface or "mare").strip().lower()
    tool_defs = TOOL_DEFINITIONS
    prompt = system_prompt(schema_in_prompt=informed)
    if surface == "mongo_mcp":
        from app.retrieval.mongo_mcp import SYSTEM_PROMPT as MCP_PROMPT
        from app.retrieval.mongo_mcp import TOOL_DEFINITIONS as MCP_TOOLS
        from app.retrieval.mongo_mcp import default_handlers as mcp_handlers

        tool_defs = MCP_TOOLS
        prompt = MCP_PROMPT
        handlers = handlers or mcp_handlers()
    else:
        handlers = handlers or default_handlers()
    openai_client = client or OpenAI(api_key=settings.openai_api_key)
    acgc_on = settings.acgc_enabled if use_acgc is None else bool(use_acgc)
    compact_on = (
        bool(compact_context) if compact_context is not None else settings.compact_context
    )

    started = time.perf_counter()
    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    session = EvidenceSession(
        _id=session_id,
        tenant_id=tenant_id,
        question=question,
        router_recommendation=recommend_method(question),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    _persist(session, persist)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": question},
    ]
    sidecar = acgc_client
    own_sidecar = False
    if acgc_on and sidecar is None:
        from app.retrieval.acgc_sidecar import connect_sidecar

        sidecar = connect_sidecar(settings.acgc_grpc_addr, session_id)
        own_sidecar = True
    if compact_on:
        session.acgc_stats = {
            "enabled": True,
            "mode": "sidecar" if sidecar is not None else "compact",
            "token_budget": settings.acgc_token_budget,
            "prompt_tokens": [],
            "pre_compact_est": [],
            "post_compact_est": [],
        }
    if sidecar is not None:
        sidecar.capture("user_prompt", question, {"tenant_id": tenant_id})

    try:
        return _tool_loop(
            session=session,
            session_id=session_id,
            messages=messages,
            openai_client=openai_client,
            handlers=handlers,
            tenant_id=tenant_id,
            persist=persist,
            max_turns=max_turns,
            agent_model=agent_model,
            answer_model=answer_model,
            effort=effort,
            answer_reasoner=answer_reasoner,
            started=started,
            sidecar=sidecar,
            compact_on=compact_on,
            token_budget=settings.acgc_token_budget,
            tool_defs=tool_defs,
            parallel_tools=parallel_tools,
        )
    finally:
        if sidecar is not None:
            try:
                session.acgc_stats["sidecar"] = sidecar.metrics()
            except Exception as exc:
                session.acgc_stats["sidecar_error"] = str(exc)
            if own_sidecar:
                sidecar.close()


def _tool_loop(
    *,
    session: EvidenceSession,
    session_id: str,
    messages: list[dict[str, Any]],
    openai_client: Any,
    handlers: dict[str, Callable],
    tenant_id: str,
    persist: bool,
    max_turns: int,
    agent_model: str,
    answer_model: str,
    effort: str | None,
    answer_reasoner: ReasoningModel | None,
    started: float,
    sidecar: Any | None,
    compact_on: bool,
    token_budget: int,
    tool_defs: list[dict[str, Any]],
    parallel_tools: str | None = None,
) -> EvidenceSession:
    settings = get_settings()
    gathered: list[RetrievedDocument] = []
    submitted: dict[str, Any] | None = None
    ledger = Ledger()
    reads = [0]
    gate = {"pending": False, "bounced": False}
    mode = _parallel_mode(parallel_tools, settings.parallel_tools)
    session.tool_stats = {"mode": mode, "turns": []}
    forced = False
    step = 0
    status = SessionStatus.complete
    stop_reason = "completed"

    while True:
        if gate["pending"]:
            gate["bounced"] = True
            gate["pending"] = False
        elapsed_ms = (time.perf_counter() - started) * 1000
        over_budget = session.agent_turns >= max_turns or elapsed_ms >= settings.max_elapsed_ms
        if over_budget and submitted is None:
            if forced:
                status = SessionStatus.budget_exhausted
                stop_reason = _budget_reason(session.agent_turns, max_turns)
                break
            messages.append({"role": "user", "content": FORCE_SUBMIT})
            forced = True
            status = SessionStatus.budget_exhausted
            stop_reason = _budget_reason(session.agent_turns, max_turns)

        if compact_on and any(m.get("role") == "tool" for m in messages):
            pre = estimate_tokens(messages)
            messages = compact_messages(messages, token_budget=token_budget)
            session.acgc_stats.setdefault("pre_compact_est", []).append(pre)
            session.acgc_stats.setdefault("post_compact_est", []).append(estimate_tokens(messages))

        params: dict[str, Any] = {
            "model": agent_model,
            "messages": messages,
            "tools": tool_defs,
            "tool_choice": (
                {"type": "function", "function": {"name": SUBMIT_TOOL}} if forced else "auto"
            ),
        }
        if effort:
            params["reasoning_effort"] = effort

        t_llm = time.perf_counter()
        resp = chat_complete(openai_client, **params)
        llm_ms = (time.perf_counter() - t_llm) * 1000
        session.agent_turns += 1
        session.llm_latency_ms += llm_ms
        usage = usage_from_response(resp)
        session.tokens_consumed += usage.total_tokens
        if compact_on:
            session.acgc_stats.setdefault("prompt_tokens", []).append(usage.prompt_tokens)

        message = resp.choices[0].message
        assistant_dict = _assistant_dict(message)
        messages.append(assistant_dict)
        if sidecar is not None:
            sidecar.capture(
                "llm_response",
                json.dumps(
                    {
                        "content": assistant_dict.get("content") or "",
                        "tool_names": [
                            (tc.get("function") or {}).get("name")
                            for tc in (assistant_dict.get("tool_calls") or [])
                        ],
                    },
                    default=str,
                ),
            )
        tool_calls = list(assistant_dict.get("tool_calls") or [])
        _record_step(
            session,
            kind="model",
            name=agent_model,
            ms=round(llm_ms),
            tools=[
                (tc.get("function") or {}).get("name") or "reply" for tc in tool_calls
            ]
            or ["reply"],
        )
        step = _trace(
            session_id,
            step,
            "agent_turn",
            persist,
            reason="forced_submit" if forced else "tool_loop",
            latency_ms=llm_ms,
            tokens=usage.total_tokens,
            extra={
                "tool_names": [tc.get("function", {}).get("name") for tc in tool_calls],
                "has_content": bool(assistant_dict.get("content")),
            },
        )

        if not tool_calls:
            text = (assistant_dict.get("content") or "").strip()
            if text:
                block = None if forced else _submit_block(ledger, reads, gate)
                if block:
                    messages.append({"role": "user", "content": block})
                    continue
                submitted = submitted or {
                    "answer": text,
                    "hypothesis": "",
                    "claims": [],
                    "cited_source_ids": [],
                }
                if not forced:
                    status = SessionStatus.complete
                    stop_reason = "completed"
                break
            if forced:
                break
            messages.append(
                {
                    "role": "user",
                    "content": "Call a tool or submit_answer. Do not reply empty.",
                }
            )
            continue

        if forced:
            submit_call = next(
                (tc for tc in tool_calls if (tc.get("function") or {}).get("name") == SUBMIT_TOOL),
                None,
            )
            for tc in tool_calls:
                session.tool_calls += 1
                if submit_call is None or tc is submit_call:
                    continue
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id"),
                        "content": json.dumps(
                            {"error": "Budget exhausted. Only submit_answer is allowed."}
                        ),
                    }
                )
            if submit_call is not None:
                submitted = _parse_arguments((submit_call.get("function") or {}).get("arguments"))
                step = _trace(
                    session_id,
                    step,
                    SUBMIT_TOOL,
                    persist,
                    reason="forced",
                    extra={"draft": True},
                )
                _record_step(session, kind="tool", name=SUBMIT_TOOL, ms=0, reason="forced")
            break

        if mode == "on":
            turn_submit, step = _run_parallel_turn(
                tool_calls=tool_calls,
                handlers=handlers,
                ledger=ledger,
                session=session,
                session_id=session_id,
                messages=messages,
                gathered=gathered,
                tenant_id=tenant_id,
                persist=persist,
                step=step,
                sidecar=sidecar,
                started=started,
                cap=max(1, int(settings.parallel_tools_cap)),
                reads=reads,
                gate=gate,
            )
        else:
            if mode == "shadow":
                planned = plan_calls(
                    tool_calls,
                    handlers,
                    ledger,
                    cap=max(1, int(settings.parallel_tools_cap)),
                )
                _append_tool_stats(
                    session,
                    summarize(
                        planned,
                        executed_parallel=False,
                        max_concurrency=1,
                        batch_wall_ms=None,
                        sum_call_ms=None,
                    ),
                )
            turn_submit = None
            for tc in tool_calls:
                session.tool_calls += 1
                name = (tc.get("function") or {}).get("name") or ""
                args = _parse_arguments((tc.get("function") or {}).get("arguments"))
                if name == SUBMIT_TOOL:
                    block = _submit_block(ledger, reads, gate)
                    if block:
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.get("id"),
                                "content": json.dumps({"error": block}),
                            }
                        )
                        step = _trace(session_id, step, SUBMIT_TOOL, persist, reason="unread")
                        _record_step(
                            session, kind="tool", name=SUBMIT_TOOL, ms=0, reason="unread"
                        )
                        continue
                    turn_submit = args
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id"),
                            "content": json.dumps({"ok": True}),
                        }
                    )
                    step = _trace(session_id, step, SUBMIT_TOOL, persist, reason="agent_decided")
                    _record_step(
                        session, kind="tool", name=SUBMIT_TOOL, ms=0, reason="agent_decided"
                    )
                    continue
                step, _mongo_ms = _execute_and_record(
                    name=name,
                    args=args,
                    call_id=str(tc.get("id") or ""),
                    result=None,
                    handlers=handlers,
                    ledger=ledger,
                    session=session,
                    session_id=session_id,
                    messages=messages,
                    gathered=gathered,
                    tenant_id=tenant_id,
                    persist=persist,
                    step=step,
                    sidecar=sidecar,
                    reads=reads,
                )
        if turn_submit is not None:
            submitted = turn_submit
            status = SessionStatus.complete
            stop_reason = "completed"
            break

    gathered = _dedupe_docs(gathered)
    session.retrieved_docs = [
        {
            "database": d.ref.database,
            "collection": d.ref.collection,
            "document_id": d.ref.document_id,
            "text": d.text or "",
        }
        for d in gathered
        if d.ref.document_id and d.ref.collection != "unknown"
    ]
    draft = submitted or {}
    session.hypothesis = str(draft.get("hypothesis") or session.hypothesis or "")
    session.claims = _claims_from_payload(draft.get("claims") or [])
    if session.hypothesis:
        session.hypothesis_versions.append(session.hypothesis)

    answer = str(draft.get("answer") or "").strip()
    citations = _citations_from_docs(gathered)
    needs_synthesis = agent_model != answer_model and bool(gathered)
    reasoner = answer_reasoner
    if needs_synthesis and reasoner is None and settings.openai_api_key:
        reasoner = OpenAIReasoningModel(
            settings.openai_api_key, answer_model, reasoning_effort="medium"
        )
    if needs_synthesis and reasoner is not None:
        t_syn = time.perf_counter()
        answer, synth_cites, tokens = generate_answer(reasoner, session, gathered)
        synth_ms = (time.perf_counter() - t_syn) * 1000
        session.llm_latency_ms += synth_ms
        session.tokens_consumed += tokens
        session.agent_turns += 1
        _record_step(
            session,
            kind="model",
            name=answer_model,
            ms=round(synth_ms),
            tools=["synthesize"],
        )
        if synth_cites:
            citations = _merge_citations(synth_cites, citations)
        step = _trace(
            session_id,
            step,
            "synthesize",
            persist,
            reason=f"{agent_model} → {answer_model}",
            tokens=tokens,
        )

    if not answer:
        answer = "Insufficient evidence was retrieved to answer the question."
        if status == SessionStatus.complete:
            status = SessionStatus.insufficient_evidence
            stop_reason = "no_answer"

    cited_ids = [str(x) for x in (draft.get("cited_source_ids") or []) if x]
    if cited_ids:
        citations = _prefer_cited(citations, cited_ids) or citations

    session.answer = answer
    session.citations = citations
    session.status = status
    session.stop_reason = stop_reason
    session.elapsed_ms = (time.perf_counter() - started) * 1000
    session.updated_at = datetime.now(UTC)
    _persist(session, persist)
    _trace(
        session_id,
        step,
        "stop",
        persist,
        reason=session.stop_reason,
        extra={
            "status": session.status.value,
            "agent_turns": session.agent_turns,
            "tool_calls": session.tool_calls,
            "llm_latency_ms": session.llm_latency_ms,
            "mongo_latency_ms": session.mongo_latency_ms,
        },
    )
    return session


def _budget_reason(agent_turns: int, max_turns: int) -> str:
    return "max_agent_turns" if agent_turns >= max_turns else "max_elapsed_ms"


def _assistant_dict(message: Any) -> dict[str, Any]:
    content = _message_content(getattr(message, "content", None))
    out: dict[str, Any] = {"role": "assistant", "content": content}
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        serialized: list[dict[str, Any]] = []
        for tc in tool_calls:
            if isinstance(tc, dict):
                serialized.append(tc)
                continue
            fn = getattr(tc, "function", None)
            serialized.append(
                {
                    "id": getattr(tc, "id", "") or "",
                    "type": getattr(tc, "type", "function") or "function",
                    "function": {
                        "name": getattr(fn, "name", "") if fn is not None else "",
                        "arguments": getattr(fn, "arguments", "{}") if fn is not None else "{}",
                    },
                }
            )
        out["tool_calls"] = serialized
    return out


def _message_content(content: Any) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(str(part.get("text") or ""))
            else:
                parts.append(str(getattr(part, "text", None) or ""))
        return "".join(parts) or None
    return str(content)


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _parallel_mode(override: str | None, configured: str) -> str:
    mode = (override if override is not None else configured or "off").strip().lower()
    return mode if mode in {"off", "shadow", "on"} else "off"


def _append_tool_stats(session: EvidenceSession, summary: dict[str, Any]) -> None:
    stats = dict(session.tool_stats or {})
    turns = list(stats.get("turns") or [])
    turns.append(summary)
    stats["turns"] = turns
    session.tool_stats = stats


def _record_step(session: EvidenceSession, **step: Any) -> None:
    stats = dict(session.tool_stats or {})
    steps = list(stats.get("steps") or [])
    steps.append(step)
    stats["steps"] = steps
    session.tool_stats = stats


def _step_detail(handlers: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    surface = getattr(handlers, "surface", None)
    timing = dict(getattr(surface, "last_timing", {}) or {})
    if surface is not None:
        surface.last_timing = {}
    detail = {
        key: timing[key]
        for key in ("embed_ms", "fetch_ms", "fetch_docs", "fetch_ids")
        if key in timing
    }
    error = result.get("error")
    if error:
        detail["error"] = str(error)[:160]
    nodes = [
        str(row.get("node_id"))
        for row in (result.get("results") or [])
        if isinstance(row, dict) and row.get("node_id")
    ]
    if nodes:
        detail["nodes"] = nodes[:8]
    docs = []
    for doc in (result.get("documents") or [])[:8]:
        if not isinstance(doc, dict):
            continue
        ref = doc.get("ref") or {}
        docs.append(f"{ref.get('collection')}:{ref.get('document_id')}")
    if docs:
        detail["docs"] = docs
    return detail


def _submit_block(ledger: Ledger, reads: list[int], gate: dict[str, bool]) -> str | None:
    """Ask for a document read once. The next submit is accepted."""
    if reads[0] or gate["bounced"]:
        return None
    gate["pending"] = True
    ids = sorted(ledger.node_ids)
    if ids:
        shown = ", ".join(ids[:8])
        return (
            "No documents have been read yet. Call retrieve_evidence on a node_id "
            f"already returned by search ({shown}), or query_documents on a namespace "
            "you already saw, before submit_answer."
        )
    return (
        "No documents have been read yet. Search, then retrieve_evidence or "
        "query_documents, before submit_answer."
    )


def _execute_and_record(
    *,
    name: str,
    args: dict[str, Any],
    call_id: str,
    result: dict[str, Any] | None,
    handlers: dict[str, Any],
    ledger: Ledger,
    session: EvidenceSession,
    session_id: str,
    messages: list[dict[str, Any]],
    gathered: list[RetrievedDocument],
    tenant_id: str,
    persist: bool,
    step: int,
    sidecar: Any | None,
    mongo_ms: float | None = None,
    reads: list[int] | None = None,
    count_read: bool | None = None,
) -> tuple[int, float]:
    dispatched = result is None
    if result is None:
        started = time.perf_counter()
        try:
            result = dispatch_tool(name, args, tenant_id=tenant_id, handlers=handlers)
        except Exception as exc:
            result = {"error": str(exc)}
        mongo_ms = (time.perf_counter() - started) * 1000
    else:
        mongo_ms = float(mongo_ms or 0)
    if not isinstance(result, dict):
        result = {"error": "tool returned an unexpected result"}
    if name in _READ_TOOLS and (dispatched if count_read is None else count_read):
        if reads is not None:
            reads[0] += 1
    session.mongo_latency_ms += mongo_ms
    _record_step(
        session,
        kind="tool",
        name=name or "tool",
        ms=round(mongo_ms),
        **_step_detail(handlers, result),
    )
    if name in {"retrieve_evidence", "query_documents", "find", "count"}:
        session.retrieval_count += 1
    gathered.extend(_docs_from_tool_result(result))
    absorb(ledger, result)
    payload = json.dumps(result, default=str)
    if len(payload) > 24_000:
        payload = payload[:24_000] + "…(truncated)"
    messages.append({"role": "tool", "tool_call_id": call_id, "content": payload})
    if sidecar is not None:
        sidecar.capture("tool_result", receipt_payload(result), {"tool": name})
        sidecar.trigger_gc()
    step = _trace(
        session_id,
        step,
        name or "tool",
        persist,
        query=str(args.get("query") or args.get("namespace") or ""),
        scope=str(args.get("scope") or ""),
        results=_brief_tool_result(result),
        latency_ms=mongo_ms,
        extra={"args_keys": sorted(args.keys())},
    )
    return step, mongo_ms


def _run_parallel_turn(
    *,
    tool_calls: list[dict[str, Any]],
    handlers: dict[str, Any],
    ledger: Ledger,
    session: EvidenceSession,
    session_id: str,
    messages: list[dict[str, Any]],
    gathered: list[RetrievedDocument],
    tenant_id: str,
    persist: bool,
    step: int,
    sidecar: Any | None,
    started: float,
    cap: int,
    reads: list[int],
    gate: dict[str, bool],
) -> tuple[dict[str, Any] | None, int]:
    planned = plan_calls(tool_calls, handlers, ledger, cap=cap)
    has_read = any(call.name != SUBMIT_TOOL for call in planned)
    turn_submit: dict[str, Any] | None = None
    executed_parallel = False
    max_concurrency = 1
    walls: list[float] = []
    summed = 0.0
    deadline = started + get_settings().max_elapsed_ms / 1000
    for segment in segments(planned, cap):
        if len(segment.calls) == 1 and segment.calls[0].name == SUBMIT_TOOL:
            call = segment.calls[0]
            session.tool_calls += 1
            if has_read:
                body: dict[str, Any] = {
                    "deferred": True,
                    "reason": "Submit again after the retrieval in this turn.",
                }
                reason = "deferred"
            else:
                block = _submit_block(ledger, reads, gate)
                if block:
                    body = {"error": block}
                    reason = "unread"
                else:
                    turn_submit = call.args
                    body = {"ok": True}
                    reason = "agent_decided"
            messages.append(
                {"role": "tool", "tool_call_id": call.call_id, "content": json.dumps(body)}
            )
            step = _trace(session_id, step, SUBMIT_TOOL, persist, reason=reason)
            _record_step(session, kind="tool", name=SUBMIT_TOOL, ms=0, reason=reason)
            continue
        runnable = []
        for call in segment.calls:
            if call.decision != "invalid_input_reason":
                runnable.append(call)
                continue
            session.tool_calls += 1
            step, elapsed = _execute_and_record(
                name=call.name,
                args=call.args,
                call_id=call.call_id,
                result={"error": call.reason},
                handlers=handlers,
                ledger=ledger,
                session=session,
                session_id=session_id,
                messages=messages,
                gathered=gathered,
                tenant_id=tenant_id,
                persist=persist,
                step=step,
                sidecar=sidecar,
                mongo_ms=0,
                reads=reads,
                count_read=False,
            )
            summed += elapsed
        if not runnable:
            continue
        if segment.parallel and len(runnable) > 1:
            executed_parallel = True
            max_concurrency = max(max_concurrency, len(runnable))
            batch_started = time.perf_counter()
            pairs = run_bounded(
                runnable,
                lambda call: dispatch_tool(
                    call.name, call.args, tenant_id=tenant_id, handlers=handlers
                ),
                deadline=deadline,
            )
            walls.append((time.perf_counter() - batch_started) * 1000)
            for call, (elapsed, result) in zip(runnable, pairs, strict=True):
                session.tool_calls += 1
                recorded = result if isinstance(result, dict) else {"error": str(result)}
                step, elapsed = _execute_and_record(
                    name=call.name,
                    args=call.args,
                    call_id=call.call_id,
                    result=recorded,
                    handlers=handlers,
                    ledger=ledger,
                    session=session,
                    session_id=session_id,
                    messages=messages,
                    gathered=gathered,
                    tenant_id=tenant_id,
                    persist=persist,
                    step=step,
                    sidecar=sidecar,
                    mongo_ms=elapsed,
                    reads=reads,
                    count_read=True,
                )
                summed += elapsed
            continue
        for call in runnable:
            session.tool_calls += 1
            step, elapsed = _execute_and_record(
                name=call.name,
                args=call.args,
                call_id=call.call_id,
                result=None,
                handlers=handlers,
                ledger=ledger,
                session=session,
                session_id=session_id,
                messages=messages,
                gathered=gathered,
                tenant_id=tenant_id,
                persist=persist,
                step=step,
                sidecar=sidecar,
                reads=reads,
            )
            summed += elapsed
    _append_tool_stats(
        session,
        summarize(
            planned,
            executed_parallel=executed_parallel,
            max_concurrency=max_concurrency,
            batch_wall_ms=sum(walls) if walls else None,
            sum_call_ms=summed,
        ),
    )
    return turn_submit, step


def _docs_from_tool_result(result: dict[str, Any]) -> list[RetrievedDocument]:
    out: list[RetrievedDocument] = []
    for d in result.get("documents") or []:
        if not isinstance(d, dict):
            continue
        ref = d.get("ref") or {}
        doc_id = str(ref.get("document_id") or "")
        database = str(ref.get("database") or RAW_DB)
        collection = str(ref.get("collection") or "")
        if not doc_id or is_nav_database(database):
            continue
        out.append(
            RetrievedDocument(
                ref=MongoRef(
                    database=database,
                    collection=collection,
                    document_id=doc_id,
                    fields=list(ref.get("fields") or []),
                ),
                content=d.get("content") or {},
                text=str(d.get("text") or ""),
                score=float(d.get("score") or 0),
            )
        )
    return out


def _claims_from_payload(raw: list[Any]) -> list[Claim]:
    out: list[Claim] = []
    for i, item in enumerate(raw):
        if isinstance(item, str):
            out.append(Claim(claim_id=f"C{i+1}", claim=item))
            continue
        if not isinstance(item, dict):
            continue
        status_raw = item.get("status") or "unsupported"
        try:
            status = ClaimStatus(status_raw)
        except ValueError:
            status = ClaimStatus.unsupported
        out.append(
            Claim(
                claim_id=str(item.get("claim_id") or f"C{i+1}"),
                claim=str(item.get("claim") or item.get("text") or ""),
                status=status,
                confidence=float(item.get("confidence") or 0),
            )
        )
    return out


def _citations_from_docs(docs: list[RetrievedDocument]) -> list[MongoRef]:
    seen: set[str] = set()
    out: list[MongoRef] = []
    preferred = [d for d in docs if d.ref.database == RAW_DB] or docs
    for d in preferred:
        if is_nav_database(d.ref.database):
            continue
        if d.ref.collection == "unknown" or d.ref.document_id == "draft":
            continue
        key = f"{d.ref.collection}:{d.ref.document_id}"
        if key in seen:
            continue
        seen.add(key)
        out.append(d.ref)
    return out


def _prefer_cited(citations: list[MongoRef], cited_ids: list[str]) -> list[MongoRef]:
    wanted = {c.lower() for c in cited_ids}
    matched: list[MongoRef] = []
    rest: list[MongoRef] = []
    for ref in citations:
        keys = {
            f"{ref.database}.{ref.collection}:{ref.document_id}".lower(),
            f"{ref.collection}:{ref.document_id}".lower(),
            str(ref.document_id).lower(),
        }
        if keys & wanted:
            matched.append(ref)
        else:
            rest.append(ref)
    return matched + rest


def _merge_citations(primary: list[MongoRef], extra: list[MongoRef]) -> list[MongoRef]:
    seen: set[str] = set()
    out: list[MongoRef] = []
    for ref in primary + extra:
        if is_nav_database(ref.database):
            continue
        key = f"{ref.collection}:{ref.document_id}"
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


def _dedupe_docs(docs: list[RetrievedDocument]) -> list[RetrievedDocument]:
    seen: set[str] = set()
    out: list[RetrievedDocument] = []
    for d in docs:
        key = f"{d.ref.collection}:{d.ref.document_id}"
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def _brief_tool_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    if "results" in result:
        return [
            {"node_id": r.get("node_id"), "name": r.get("name"), "score": r.get("score")}
            for r in (result.get("results") or [])[:12]
            if isinstance(r, dict)
        ]
    if "documents" in result:
        return [
            (d.get("ref") or {})
            for d in (result.get("documents") or [])[:12]
            if isinstance(d, dict)
        ]
    if result.get("error"):
        return [{"error": result["error"]}]
    return []


def _trace(
    session_id: str,
    step: int,
    operation: str,
    persist: bool,
    **kwargs: Any,
) -> int:
    step += 1
    if persist:
        write_trace(TraceEvent(session_id=session_id, step=step, operation=operation, **kwargs))
    return step


def _persist(session: EvidenceSession, persist: bool) -> None:
    if not persist:
        return
    doc = session.model_dump(by_alias=True)
    agent_db()[EVIDENCE_SESSIONS].replace_one({"_id": session.id}, doc, upsert=True)
