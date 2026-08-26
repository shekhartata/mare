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
from app.constants import AGENT_DB, EVIDENCE_SESSIONS, RAW_DB
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
from app.retrieval.evidence import generate_answer
from app.retrieval.loop import run_adaptive
from app.retrieval.tools import TOOL_DEFINITIONS, default_handlers, dispatch_tool
from app.search.router import recommend_method

SUBMIT_TOOL = "submit_answer"
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
) -> EvidenceSession:
    settings = get_settings()
    tenant_id = tenant_id or settings.tenant_id
    if client is None and not settings.openai_api_key:
        return run_adaptive(question, tenant_id=tenant_id)

    agent_model = agent_model or settings.openai_model_agent or settings.openai_model
    answer_model = answer_model or settings.openai_model
    effort = reasoning_effort if reasoning_effort is not None else settings.openai_reasoning_effort
    max_turns = settings.max_agent_turns if max_turns is None else int(max_turns)
    informed = settings.schema_in_prompt if schema_in_prompt is None else bool(schema_in_prompt)
    handlers = handlers or default_handlers()
    openai_client = client or OpenAI(api_key=settings.openai_api_key)

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
        {"role": "system", "content": system_prompt(schema_in_prompt=informed)},
        {"role": "user", "content": question},
    ]
    gathered: list[RetrievedDocument] = []
    submitted: dict[str, Any] | None = None
    forced = False
    step = 0
    status = SessionStatus.complete
    stop_reason = "completed"

    while True:
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

        params: dict[str, Any] = {
            "model": agent_model,
            "messages": messages,
            "tools": TOOL_DEFINITIONS,
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

        message = resp.choices[0].message
        assistant_dict = _assistant_dict(message)
        messages.append(assistant_dict)
        tool_calls = list(assistant_dict.get("tool_calls") or [])
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
            break

        turn_submit: dict[str, Any] | None = None
        for tc in tool_calls:
            session.tool_calls += 1
            name = (tc.get("function") or {}).get("name") or ""
            args = _parse_arguments((tc.get("function") or {}).get("arguments"))
            if name == SUBMIT_TOOL:
                turn_submit = args
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id"),
                        "content": json.dumps({"ok": True}),
                    }
                )
                step = _trace(session_id, step, SUBMIT_TOOL, persist, reason="agent_decided")
                continue
            t_mongo = time.perf_counter()
            try:
                result = dispatch_tool(name, args, tenant_id=tenant_id, handlers=handlers)
            except Exception as exc:
                result = {"error": str(exc)}
            mongo_ms = (time.perf_counter() - t_mongo) * 1000
            session.mongo_latency_ms += mongo_ms
            if name in {"retrieve_evidence", "query_documents"}:
                session.retrieval_count += 1
            gathered.extend(_docs_from_tool_result(result))
            payload = json.dumps(result, default=str)
            if len(payload) > 24_000:
                payload = payload[:24_000] + "…(truncated)"
            messages.append({"role": "tool", "tool_call_id": tc.get("id"), "content": payload})
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
        if turn_submit is not None:
            submitted = turn_submit
            status = SessionStatus.complete
            stop_reason = "completed"
            break

    gathered = _dedupe_docs(gathered)
    draft = submitted or {}
    session.hypothesis = str(draft.get("hypothesis") or session.hypothesis or "")
    session.claims = _claims_from_payload(draft.get("claims") or [])
    if session.hypothesis:
        session.hypothesis_versions.append(session.hypothesis)

    answer = str(draft.get("answer") or "").strip()
    citations = _citations_from_docs(gathered)
    needs_synthesis = agent_model != answer_model and bool(gathered or answer)
    reasoner = answer_reasoner
    if needs_synthesis and reasoner is None and settings.openai_api_key:
        reasoner = OpenAIReasoningModel(
            settings.openai_api_key, answer_model, reasoning_effort="medium"
        )
    if needs_synthesis and reasoner is not None:
        t_syn = time.perf_counter()
        synth_docs = gathered or [
            RetrievedDocument(
                ref=MongoRef(database=RAW_DB, collection="unknown", document_id="draft"),
                content={},
                text=answer,
            )
        ]
        answer, synth_cites, tokens = generate_answer(reasoner, session, synth_docs)
        session.llm_latency_ms += (time.perf_counter() - t_syn) * 1000
        session.tokens_consumed += tokens
        session.agent_turns += 1
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


def _docs_from_tool_result(result: dict[str, Any]) -> list[RetrievedDocument]:
    out: list[RetrievedDocument] = []
    for d in result.get("documents") or []:
        if not isinstance(d, dict):
            continue
        ref = d.get("ref") or {}
        doc_id = str(ref.get("document_id") or "")
        database = str(ref.get("database") or RAW_DB)
        collection = str(ref.get("collection") or "")
        if not doc_id or database == AGENT_DB:
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
        if d.ref.database == AGENT_DB:
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
        if ref.database == AGENT_DB:
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
