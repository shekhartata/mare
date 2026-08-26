from __future__ import annotations

from typing import Any

from pymongo.collection import Collection

from app.config import get_settings
from app.constants import AUTO_EMBED_MODEL, NAV_LEXICAL_INDEX, NAV_VECTOR_INDEX
from app.mongo.security import inject_tenant
from app.search.lexical import lexical_search
from app.search.vector import semantic_search


def hybrid_search(
    coll: Collection,
    query: str,
    *,
    tenant_id: str,
    extra_filter: dict[str, Any] | None = None,
    limit: int = 8,
    strategy: str = "rrf",
    auto_embed: bool = True,
    query_vector: list[float] | None = None,
    lexical_index: str = NAV_LEXICAL_INDEX,
    vector_index: str = NAV_VECTOR_INDEX,
    vector_path: str = "search_text",
    lexical_path: str | list[str] | dict[str, str] = "search_text",
) -> list[dict[str, Any]]:
    if strategy == "rank_fusion":
        try:
            return _rank_fusion(
                coll,
                query,
                tenant_id=tenant_id,
                extra_filter=extra_filter,
                limit=limit,
                auto_embed=auto_embed,
                query_vector=query_vector,
                lexical_index=lexical_index,
                vector_index=vector_index,
                vector_path=vector_path,
            )
        except Exception:
            pass
    return reciprocal_rank_fusion(
        coll,
        query,
        tenant_id=tenant_id,
        extra_filter=extra_filter,
        limit=limit,
        auto_embed=auto_embed,
        query_vector=query_vector,
        lexical_index=lexical_index,
        vector_index=vector_index,
        vector_path=vector_path,
        lexical_path=lexical_path,
    )


def reciprocal_rank_fusion(
    coll: Collection,
    query: str,
    *,
    tenant_id: str,
    extra_filter: dict[str, Any] | None = None,
    limit: int = 8,
    auto_embed: bool = True,
    query_vector: list[float] | None = None,
    lexical_index: str = NAV_LEXICAL_INDEX,
    vector_index: str = NAV_VECTOR_INDEX,
    vector_path: str = "search_text",
    lexical_path: str | list[str] | dict[str, str] = "search_text",
) -> list[dict[str, Any]]:
    settings = get_settings()
    k = settings.rrf_k
    lex = lexical_search(
        coll,
        query,
        tenant_id=tenant_id,
        index=lexical_index,
        path=lexical_path,
        extra_filter=extra_filter,
        limit=limit * 2,
    )
    try:
        sem = semantic_search(
            coll,
            query,
            tenant_id=tenant_id,
            index=vector_index,
            path=vector_path,
            extra_filter=extra_filter,
            limit=limit * 2,
            query_vector=query_vector,
            auto_embed=auto_embed,
        )
    except Exception:
        sem = []

    scores: dict[str, float] = {}
    docs: dict[str, dict[str, Any]] = {}
    for rank, doc in enumerate(lex, start=1):
        key = str(doc.get("_id"))
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
        docs[key] = doc
    for rank, doc in enumerate(sem, start=1):
        key = str(doc.get("_id"))
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
        docs.setdefault(key, doc)
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    out = []
    for key, score in ordered:
        doc = dict(docs[key])
        doc["_score"] = score
        out.append(doc)
    return out


def _rank_fusion(
    coll: Collection,
    query: str,
    *,
    tenant_id: str,
    extra_filter: dict[str, Any] | None,
    limit: int,
    auto_embed: bool,
    query_vector: list[float] | None,
    lexical_index: str,
    vector_index: str,
    vector_path: str,
) -> list[dict[str, Any]]:
    settings = get_settings()
    scoped = inject_tenant(extra_filter, tenant_id)
    vs: dict[str, Any] = {
        "index": vector_index,
        "path": vector_path,
        "limit": limit,
        "numCandidates": max(limit * 8, settings.vector_num_candidates),
        "filter": scoped,
    }
    if query_vector is not None:
        vs["queryVector"] = query_vector
    else:
        vs["query"] = {"text": query}
        vs["model"] = AUTO_EMBED_MODEL
        if not auto_embed:
            raise ValueError("rankFusion vector branch needs a query vector")

    pipeline = [
        {
            "$rankFusion": {
                "input": {
                    "pipelines": {
                        "vector": [{"$vectorSearch": vs}],
                        "lexical": [
                            {
                                "$search": {
                                    "index": lexical_index,
                                    "compound": {
                                        "must": [{"text": {"query": query, "path": "search_text"}}],
                                        "filter": [{"equals": {"path": "tenant_id", "value": tenant_id}}],
                                    },
                                }
                            },
                            {"$limit": limit},
                        ],
                    }
                }
            }
        },
        {"$limit": limit},
        {"$addFields": {"_score": {"$meta": "score"}}},
    ]
    return list(coll.aggregate(pipeline))
