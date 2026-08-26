from __future__ import annotations

from typing import Any

from pymongo.collection import Collection

from app.config import get_settings
from app.constants import AUTO_EMBED_MODEL, NAV_VECTOR_INDEX
from app.mongo.security import inject_tenant


def semantic_search(
    coll: Collection,
    query: str,
    *,
    tenant_id: str,
    index: str = NAV_VECTOR_INDEX,
    path: str = "search_text",
    extra_filter: dict[str, Any] | None = None,
    limit: int = 8,
    query_vector: list[float] | None = None,
    auto_embed: bool = True,
    model: str = AUTO_EMBED_MODEL,
) -> list[dict[str, Any]]:
    settings = get_settings()
    scoped = inject_tenant(extra_filter, tenant_id)
    vs: dict[str, Any] = {
        "index": index,
        "path": path,
        "limit": limit,
        "numCandidates": max(limit * 8, settings.vector_num_candidates),
        "filter": scoped,
    }
    if query_vector is not None:
        vs["queryVector"] = query_vector
    elif auto_embed:
        vs["query"] = {"text": query}
        vs["model"] = model
    else:
        raise ValueError("semantic_search requires query_vector when auto_embed is false")

    pipeline = [
        {"$vectorSearch": vs},
        {"$addFields": {"_score": {"$meta": "vectorSearchScore"}}},
    ]
    return list(coll.aggregate(pipeline))
