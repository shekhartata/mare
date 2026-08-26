from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

from app.config import get_settings
from app.constants import AGENT_DB, EVIDENCE_SESSIONS, NAV_NODES, RAW_DB
from app.llm import get_reasoning_model
from app.llm.base import ReasoningModel
from app.models.schemas import (
    Accounting,
    Candidate,
    EvidenceSession,
    RetrievedDocument,
    SearchMethod,
    SessionStatus,
    TraceEvent,
)
from app.mongo.client import agent_db, get_client
from app.observability.traces import write_trace
from app.retrieval.candidate import CandidateQueue
from app.retrieval.evidence import apply_extraction, extract_evidence, generate_answer, identify_gaps
from app.retrieval.hypothesis import generate_hypothesis, merge_claims, update_hypothesis
from app.retrieval.serialize import doc_to_retrieved
from app.retrieval.stopping import coverage, hypothesis_delta, should_stop
from app.search.router import recommend_method
from app.search.service import get_children, get_node, navigation_search, query_namespace, search_within


def run_adaptive(
    question: str,
    *,
    tenant_id: str | None = None,
    model: ReasoningModel | None = None,
) -> EvidenceSession:
    settings = get_settings()
    tenant_id = tenant_id or settings.tenant_id
    model = model or get_reasoning_model()
    started = time.perf_counter()
    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    accounting = Accounting()
    step = 0

    session = EvidenceSession(
        _id=session_id,
        tenant_id=tenant_id,
        question=question,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    _persist(session)

    recommended = recommend_method(question)
    session.router_recommendation = recommended
    selected, nav_hits = navigation_search(
        question, method=recommended, tenant_id=tenant_id, limit=settings.default_search_limit
    )
    session.agent_selected_method = selected
    accounting.search_count += 1
    step = _trace(
        session_id,
        step,
        "navigate",
        reason=f"router={recommended.value} selected={selected.value}",
        query=question,
        results=_brief(nav_hits),
        extra={"router_recommendation": recommended.value, "agent_selected_method": selected.value},
    )

    queue = CandidateQueue()
    queue.extend(
        CandidateQueue.from_nodes(
            nav_hits, query=question, method=selected, reason="initial navigation"
        )
    )

    seed_docs = _nodes_as_docs(nav_hits)
    hypo = generate_hypothesis(model, question, seed_docs)
    accounting.tokens_consumed += 400
    accounting.llm_calls += 1
    session.hypothesis = hypo.hypothesis
    session.claims = hypo.claims
    session.open_questions = hypo.open_questions
    session.hypothesis_versions.append(hypo.hypothesis)
    _persist(session)
    step = _trace(session_id, step, "initialize", reason="hypothesis+claims", extra={"hypothesis": hypo.hypothesis})

    gathered: list[RetrievedDocument] = list(seed_docs)
    consecutive_low_gain = 0
    stable_rounds = 0
    last_gain = 1.0
    round_index = 0
    prev_hypo = session.hypothesis

    stop, reason, status = should_stop(
        session=session,
        accounting=accounting,
        highest_priority=queue.highest_priority(),
        consecutive_low_gain=consecutive_low_gain,
        last_gain=last_gain,
        stable_rounds=stable_rounds,
        round_index=round_index,
    )

    while not stop:
        round_index += 1
        candidate = queue.pop_best()
        if candidate is None:
            reason, status = "frontier_exhausted", SessionStatus.insufficient_evidence
            break

        docs, child_nodes, step = _retrieve(candidate, tenant_id, session_id, step, question)
        accounting.retrieval_count += 1
        raw_docs = [d for d in docs if d.ref.database == RAW_DB]
        accounting.documents_read += len(raw_docs)
        gathered.extend(raw_docs or docs)
        if child_nodes:
            queue.extend(
                CandidateQueue.from_nodes(
                    child_nodes,
                    query=candidate.query or question,
                    method=candidate.search_method,
                    reason=f"children of {candidate.node_id}",
                )
            )

        extraction, tokens = extract_evidence(
            model, question, session.hypothesis, session.claims, raw_docs or docs[:3]
        )
        accounting.tokens_consumed += tokens
        accounting.llm_calls += 1
        gaps = apply_extraction(session, extraction, raw_docs or docs)
        step = _trace(
            session_id,
            step,
            "extract_evidence",
            reason=candidate.reason,
            selected_result=candidate.node_id,
            extra={"extraction": extraction.model_dump(), "gaps": gaps[:8]},
            tokens=tokens,
        )

        latest_text = "\n\n".join(d.text for d in (raw_docs or docs)[:8])
        updated, tokens = update_hypothesis(model, session, latest_text)
        accounting.tokens_consumed += tokens
        accounting.llm_calls += 1
        session.hypothesis = updated.hypothesis
        session.claims = merge_claims(session.claims, updated.claims)
        for q in updated.open_questions:
            if q not in session.open_questions:
                session.open_questions.append(q)
        session.hypothesis_versions.append(updated.hypothesis)
        delta = hypothesis_delta(prev_hypo, session.hypothesis)
        if delta < 0.08:
            stable_rounds += 1
        else:
            stable_rounds = 0
        last_gain = max(delta, 0.05 if extraction.claims_supported else 0.0)
        if last_gain < settings.min_gain:
            consecutive_low_gain += 1
        else:
            consecutive_low_gain = 0
        prev_hypo = session.hypothesis
        step = _trace(
            session_id,
            step,
            "update_hypothesis",
            reason="revise claims from evidence",
            extra={"delta": delta, "coverage": coverage(session.claims)},
            tokens=tokens,
        )

        if gaps:
            gap_query = gaps[0]
            method, gap_hits = navigation_search(
                gap_query, method=SearchMethod.hybrid, tenant_id=tenant_id, limit=6
            )
            accounting.search_count += 1
            queue.extend(
                CandidateQueue.from_nodes(
                    gap_hits, query=gap_query, method=method, reason=f"gap: {gap_query[:180]}"
                )
            )
            queue.rerank_for_gaps(gaps)
            step = _trace(
                session_id,
                step,
                "gap_search",
                reason="search for missing evidence",
                query=gap_query,
                results=_brief(gap_hits),
            )

        accounting.elapsed_ms = (time.perf_counter() - started) * 1000
        session.retrieval_count = accounting.retrieval_count
        session.tokens_consumed = accounting.tokens_consumed
        session.elapsed_ms = accounting.elapsed_ms
        _persist(session)

        stop, reason, status = should_stop(
            session=session,
            accounting=accounting,
            highest_priority=queue.highest_priority(),
            consecutive_low_gain=consecutive_low_gain,
            last_gain=last_gain,
            stable_rounds=stable_rounds,
            round_index=round_index,
        )

    answer, citations, tokens = generate_answer(model, session, _dedupe_docs(gathered))
    accounting.tokens_consumed += tokens
    accounting.llm_calls += 1
    session.answer = answer
    session.citations = citations
    session.status = status if stop else SessionStatus.complete
    session.stop_reason = reason or "completed"
    session.tokens_consumed = accounting.tokens_consumed
    session.retrieval_count = accounting.retrieval_count
    session.elapsed_ms = (time.perf_counter() - started) * 1000
    session.updated_at = datetime.now(UTC)
    _persist(session)
    _trace(
        session_id,
        step + 1,
        "stop",
        reason=session.stop_reason,
        extra={"status": session.status.value, "coverage": coverage(session.claims)},
        tokens=tokens,
    )
    return session


def _retrieve(
    candidate: Candidate,
    tenant_id: str,
    session_id: str,
    step: int,
    question: str,
) -> tuple[list[RetrievedDocument], list[dict], int]:
    docs: list[RetrievedDocument] = []
    child_nodes: list[dict] = []
    node = get_node(candidate.node_id, tenant_id)
    if not node:
        return [], [], step
    source = node.get("source") or {}
    ntype = node.get("node_type")
    database = source.get("database") or RAW_DB
    collection = source.get("collection")

    if ntype in {"database", "collection"}:
        child_nodes = get_children(candidate.node_id, tenant_id, limit=12)
        scoped = search_within(
            candidate.node_id, candidate.query or question, tenant_id=tenant_id, limit=5
        )
        if collection:
            docs = _raw_as_docs(scoped, database, collection)
    elif ntype == "group":
        scoped = search_within(
            candidate.node_id, candidate.query or question, tenant_id=tenant_id, limit=6
        )
        if collection:
            docs = _raw_as_docs(scoped, database, collection)
        if not docs and collection:
            filt = source.get("filter") or {}
            raw = query_namespace(f"{database}.{collection}", filt, tenant_id=tenant_id, limit=5)
            docs = _raw_as_docs(raw, database, collection)
    else:
        ids = source.get("document_ids") or []
        if collection and ids:
            raw = list(
                get_client()[database][collection].find(
                    {"tenant_id": tenant_id, "_id": {"$in": ids}}
                )
            )
            docs = _raw_as_docs(raw, database, collection)

    step = _trace(
        session_id,
        step,
        "retrieve",
        reason=candidate.reason or f"expand {candidate.node_id}",
        scope=candidate.node_id,
        query=candidate.query,
        selected_result=candidate.node_id,
        results=[{"id": d.ref.document_id, "collection": d.ref.collection} for d in docs],
        candidate_scores={"priority": candidate.priority, "relevance": candidate.relevance},
    )
    return docs, child_nodes, step


def _nodes_as_docs(nodes: list[dict]) -> list[RetrievedDocument]:
    return [
        doc_to_retrieved(n, AGENT_DB, NAV_NODES, float(n.get("_score") or 0))
        for n in nodes
    ]


def _raw_as_docs(rows: list[dict], database: str, collection: str) -> list[RetrievedDocument]:
    return [doc_to_retrieved(r, database, collection, float(r.get("_score") or 0)) for r in rows]


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


def _brief(hits: list[dict]) -> list[dict]:
    return [{"_id": h.get("_id"), "name": h.get("name"), "score": h.get("_score")} for h in hits[:12]]


def _trace(session_id: str, step: int, operation: str, **kwargs) -> int:
    step += 1
    write_trace(TraceEvent(session_id=session_id, step=step, operation=operation, **kwargs))
    return step


def _persist(session: EvidenceSession) -> None:
    doc = session.model_dump(by_alias=True)
    agent_db()[EVIDENCE_SESSIONS].replace_one({"_id": session.id}, doc, upsert=True)


