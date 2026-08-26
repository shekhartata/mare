from __future__ import annotations

from typing import Any

from bson import ObjectId
from pymongo.collection import Collection

from app.mongo.security import inject_tenant, sanitize_projection


def query_documents(
    coll: Collection,
    *,
    tenant_id: str,
    filter_doc: dict[str, Any] | None = None,
    projection: dict[str, Any] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    scoped = inject_tenant(filter_doc, tenant_id)
    proj = sanitize_projection(projection)
    cursor = coll.find(scoped, proj).limit(limit)
    return list(cursor)


def read_documents(
    coll: Collection,
    ids: list[str],
    *,
    tenant_id: str,
    projection: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    object_ids: list[Any] = []
    raw_ids: list[Any] = []
    for i in ids:
        raw_ids.append(i)
        try:
            object_ids.append(ObjectId(i))
        except Exception:
            pass
    id_filter: dict[str, Any] = {"_id": {"$in": raw_ids + object_ids}}
    scoped = inject_tenant(id_filter, tenant_id)
    proj = sanitize_projection(projection)
    return list(coll.find(scoped, proj))
