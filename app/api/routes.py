from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.baseline.rag import run_rag, vector_counts
from app.config import get_settings
from app.constants import EVIDENCE_SESSIONS
from app.models.schemas import AskRequest, AskResponse
from app.mongo.client import agent_db
from app.mongo.jsonutil import jsonable
from app.observability.traces import traces_for
from app.retrieval.agent_loop import run_agent
from app.retrieval.loop import run_adaptive
from app.search.service import get_children, get_node, list_collections, list_databases

router = APIRouter()


@router.get("/health")
def health() -> dict:
    from app.mongo.client import ping

    try:
        ping()
        mongo = "ok"
    except Exception as exc:
        mongo = f"error: {exc}"
    return {"status": "ok", "mongo": mongo}


@router.post("/ask", response_model=AskResponse)
def ask(body: AskRequest) -> AskResponse:
    tenant = body.tenant_id or get_settings().tenant_id
    if body.method == "rag":
        session = run_rag(body.question, tenant_id=tenant)
        return _to_response(session, engine="rag")
    if body.method == "legacy":
        session = run_adaptive(body.question, tenant_id=tenant)
        return _to_response(session, engine="legacy")
    session = run_agent(body.question, tenant_id=tenant)
    return _to_response(session, engine="adaptive")


@router.post("/ask/rag", response_model=AskResponse)
def ask_rag(body: AskRequest) -> AskResponse:
    tenant = body.tenant_id or get_settings().tenant_id
    session = run_rag(body.question, tenant_id=tenant)
    return _to_response(session, engine="rag")


@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    doc = agent_db()[EVIDENCE_SESSIONS].find_one({"_id": session_id})
    if not doc:
        raise HTTPException(404, "session not found")
    doc["session_id"] = str(doc.get("_id"))
    return jsonable(doc)


@router.get("/sessions/{session_id}/traces")
def get_traces(session_id: str) -> dict:
    return {"session_id": session_id, "traces": jsonable(traces_for(session_id))}


@router.get("/navigation/databases")
def nav_databases() -> dict:
    return {"databases": list_databases()}


@router.get("/navigation/collections")
def nav_collections(database: str = Query(...)) -> dict:
    return {"database": database, "collections": list_collections(database)}


@router.get("/navigation/nodes/{node_id}")
def nav_node(node_id: str) -> dict:
    node = get_node(node_id)
    if not node:
        raise HTTPException(404, "node not found")
    return jsonable(node)


@router.get("/navigation/nodes/{node_id}/children")
def nav_children(node_id: str) -> dict:
    return {"parent": node_id, "children": jsonable(get_children(node_id))}


@router.get("/metrics/vectors")
def metrics_vectors() -> dict:
    return vector_counts()


def _to_response(session, engine: str) -> AskResponse:
    return AskResponse(
        session_id=session.id,
        question=session.question,
        answer=session.answer,
        status=session.status,
        stop_reason=session.stop_reason,
        hypothesis=session.hypothesis,
        claims=session.claims,
        citations=session.citations,
        retrieval_count=session.retrieval_count,
        tokens_consumed=session.tokens_consumed,
        elapsed_ms=session.elapsed_ms,
        agent_turns=session.agent_turns,
        tool_calls=session.tool_calls,
        llm_latency_ms=session.llm_latency_ms,
        mongo_latency_ms=session.mongo_latency_ms,
        router_recommendation=session.router_recommendation.value
        if session.router_recommendation
        else None,
        engine=engine,
    )
