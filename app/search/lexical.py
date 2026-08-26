from __future__ import annotations

from typing import Any

from pymongo.collection import Collection

from app.constants import NAV_LEXICAL_INDEX, RAW_LEXICAL_INDEX
from app.mongo.security import inject_tenant


def lexical_search(
    coll: Collection,
    query: str,
    *,
    tenant_id: str,
    index: str = NAV_LEXICAL_INDEX,
    path: Any = "search_text",
    extra_filter: dict[str, Any] | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    scoped = inject_tenant(extra_filter, tenant_id)
    tenant = scoped.pop("tenant_id")
    remaining = {k: v for k, v in scoped.items() if not str(k).startswith("$")}
    must = [{"text": {"query": query, "path": path}}]
    search_stage: dict[str, Any] = {
        "index": index,
        "compound": {
            "must": must,
            "filter": [{"equals": {"path": "tenant_id", "value": tenant}}],
        },
    }
    pipeline: list[dict[str, Any]] = [{"$search": search_stage}]
    if remaining:
        pipeline.append({"$match": remaining})
    pipeline.extend(
        [
            {"$limit": limit},
            {"$addFields": {"_score": {"$meta": "searchScore"}}},
        ]
    )
    return list(coll.aggregate(pipeline))


def lexical_search_raw(
    coll: Collection,
    query: str,
    *,
    tenant_id: str,
    extra_filter: dict[str, Any] | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    return lexical_search(
        coll,
        query,
        tenant_id=tenant_id,
        index=RAW_LEXICAL_INDEX,
        path={"wildcard": "*"},
        extra_filter=extra_filter,
        limit=limit,
    )
