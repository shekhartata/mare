"""Equal-budget retrieval pipelines. No LLM calls."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from pymongo.collection import Collection

from app.constants import (
    NAV_LEXICAL_INDEX,
    NAV_VECTOR_INDEX,
    RAG_LEXICAL_INDEX,
    RAG_VECTOR_INDEX,
    RAW_LEXICAL_INDEX,
)
from app.search.hybrid import hybrid_search
from app.search.lexical import lexical_search
from app.search.vector import semantic_search


def rag_retrieve(
    question: str,
    *,
    chunks: Collection,
    tenant_id: str,
    budget: int,
    method: str = "hybrid",
    extra_filter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = perf_counter()
    if method == "vector":
        hits = semantic_search(
            chunks,
            question,
            tenant_id=tenant_id,
            index=RAG_VECTOR_INDEX,
            path="text",
            extra_filter=extra_filter,
            limit=budget,
        )
    elif method == "lexical":
        hits = lexical_search(
            chunks,
            question,
            tenant_id=tenant_id,
            index=RAG_LEXICAL_INDEX,
            path="text",
            extra_filter=extra_filter,
            limit=budget,
        )
    else:
        hits = hybrid_search(
            chunks,
            question,
            tenant_id=tenant_id,
            extra_filter=extra_filter,
            limit=budget,
            strategy="rrf",
            lexical_index=RAG_LEXICAL_INDEX,
            vector_index=RAG_VECTOR_INDEX,
            vector_path="text",
            lexical_path="text",
        )
    ranked: list[str] = []
    seen: set[str] = set()
    for hit in hits:
        sid = str(hit.get("source_id") or hit.get("_id") or "")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        ranked.append(sid)
        if len(ranked) >= budget:
            break
    return {
        "engine": "rag",
        "method": method,
        "ranked_ids": ranked,
        "elapsed_ms": (perf_counter() - started) * 1000,
        "hits": len(hits),
    }


def mare_retrieve(
    question: str,
    *,
    nodes: Collection,
    source: Collection,
    tenant_id: str,
    budget: int,
    extra_filter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Navigate to groups, then lexical-rank documents inside them."""
    started = perf_counter()
    nav_limit = min(24, max(4, budget))
    nav_filter = {"node_type": "group", **(extra_filter or {})}
    groups = hybrid_search(
        nodes,
        question,
        tenant_id=tenant_id,
        extra_filter=nav_filter,
        limit=nav_limit,
        strategy="rrf",
        lexical_index=NAV_LEXICAL_INDEX,
        vector_index=NAV_VECTOR_INDEX,
        vector_path="search_text",
        lexical_path="search_text",
    )
    ranked: list[str] = []
    seen: set[str] = set()
    groups_used = 0
    for group in groups:
        source_meta = group.get("source") or {}
        remaining = budget - len(ranked)
        if remaining <= 0:
            break
        ids = [str(x) for x in (source_meta.get("document_ids") or [])]
        filt = dict(source_meta.get("filter") or {})
        hits: list[dict[str, Any]] = []
        if filt:
            try:
                hits = lexical_search(
                    source,
                    question,
                    tenant_id=tenant_id,
                    index=RAW_LEXICAL_INDEX,
                    path={"wildcard": "*"},
                    extra_filter=filt,
                    limit=remaining,
                )
            except Exception:
                hits = []
        if not hits and ids:
            cursor = source.find({"_id": {"$in": ids[: max(remaining * 4, remaining)]}})
            hits = list(cursor.limit(remaining) if hasattr(cursor, "limit") else cursor)
        groups_used += 1
        for hit in hits:
            did = str(hit.get("_id") or "")
            if not did or did in seen:
                continue
            seen.add(did)
            ranked.append(did)
            if len(ranked) >= budget:
                break
        if len(ranked) >= budget:
            break
        # If lexical missed, append unread group ids in stored order.
        for did in ids:
            if did in seen:
                continue
            seen.add(did)
            ranked.append(did)
            if len(ranked) >= budget:
                break
        if len(ranked) >= budget:
            break
    return {
        "engine": "mare",
        "ranked_ids": ranked[:budget],
        "elapsed_ms": (perf_counter() - started) * 1000,
        "nav_groups": len(groups),
        "groups_expanded": groups_used,
    }
