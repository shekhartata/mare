from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

from app.config import get_settings
from app.constants import RAG_CHUNKS, RAG_DB, RAG_LEXICAL_INDEX, RAG_VECTOR_INDEX, RAW_DB
from app.llm import get_embedding_model, get_reasoning_model
from app.models.schemas import EvidenceSession, MongoRef, SessionStatus
from app.search.capabilities import capabilities_or_default
from app.search.hybrid import hybrid_search
from app.search.vector import semantic_search
from app.mongo.client import rag_db


def run_rag(
    question: str,
    *,
    tenant_id: str | None = None,
    top_k: int | None = None,
    method: str = "hybrid",
    source_database: str | None = None,
) -> EvidenceSession:
    settings = get_settings()
    tenant_id = tenant_id or settings.tenant_id
    top_k = top_k or settings.rag_top_k
    source_database = source_database or RAW_DB
    started = time.perf_counter()
    session_id = f"rag_{uuid.uuid4().hex[:12]}"
    coll = rag_db()[RAG_CHUNKS]
    caps = capabilities_or_default()
    auto_embed = caps.embedding_path == "atlas_auto"
    vector_path = "text" if auto_embed else "embedding"
    query_vector = None
    if not auto_embed:
        query_vector = get_embedding_model().embed([question])[0]

    if method == "vector":
        hits = semantic_search(
            coll,
            question,
            tenant_id=tenant_id,
            index=RAG_VECTOR_INDEX,
            path=vector_path,
            limit=top_k,
            query_vector=query_vector,
            auto_embed=auto_embed,
        )
    else:
        hits = hybrid_search(
            coll,
            question,
            tenant_id=tenant_id,
            limit=top_k,
            strategy=caps.hybrid_strategy,
            auto_embed=auto_embed,
            query_vector=query_vector,
            lexical_index=RAG_LEXICAL_INDEX,
            vector_index=RAG_VECTOR_INDEX,
            vector_path=vector_path,
            lexical_path="text",
        )

    context = "\n\n".join(
        f"[{h.get('collection')} {h.get('source_id')}]\n{h.get('text')}" for h in hits
    )
    model = get_reasoning_model()
    result = model.generate(
        f"Question: {question}\n\nTop-K chunks:\n{context}\n\nAnswer using only these chunks. Cite source ids.",
        system="You are a conventional RAG answering model.",
    )
    citations = [
        MongoRef(
            database=source_database,
            collection=str(h.get("collection") or ""),
            document_id=str(h.get("source_id") or ""),
        )
        for h in hits
        if h.get("source_id")
    ]
    retrieved_docs = []
    seen: set[str] = set()
    for h in hits:
        sid = str(h.get("source_id") or "")
        coll = str(h.get("collection") or "")
        key = f"{coll}:{sid}"
        if not sid or key in seen:
            continue
        seen.add(key)
        retrieved_docs.append(
            {
                "database": source_database,
                "collection": coll,
                "document_id": sid,
                "text": str(h.get("text") or ""),
            }
        )
    elapsed = (time.perf_counter() - started) * 1000
    return EvidenceSession(
        _id=session_id,
        tenant_id=tenant_id,
        question=question,
        hypothesis="conventional RAG top-k",
        answer=result.text.strip(),
        citations=citations,
        retrieved_docs=retrieved_docs,
        status=SessionStatus.complete,
        stop_reason="rag_topk",
        retrieval_count=1,
        tokens_consumed=result.usage.total_tokens,
        elapsed_ms=elapsed,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def vector_counts() -> dict[str, int]:
    from app.constants import NAV_NODES
    from app.mongo.client import agent_db

    nav = agent_db()[NAV_NODES].estimated_document_count()
    rag = rag_db()[RAG_CHUNKS].estimated_document_count()
    ratio = (nav / rag) if rag else 0.0
    return {
        "adaptive_vector_count": nav,
        "rag_vector_count": rag,
        "adaptive_over_rag": round(ratio, 4),
    }
