"""Unified PRD §11 tool surface used by the loop, FastAPI, and MCP."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.constants import (
    AGENT_DB,
    NAV_NODES,
    RAG_DB,
    RAW_COLLECTIONS,
    RAW_DB,
    RAW_LEXICAL_INDEX,
)
from app.llm import get_embedding_model
from app.models.schemas import SearchMethod
from app.mongo.client import agent_db, get_client
from app.mongo.security import inject_tenant
from app.search.capabilities import capabilities_or_default
from app.search.hybrid import hybrid_search
from app.search.lexical import lexical_search
from app.search.router import recommend_method
from app.search.structured import query_documents, read_documents
from app.search.vector import semantic_search

ALLOWED_DBS = {RAW_DB, AGENT_DB, RAG_DB}


def list_databases() -> list[str]:
    names = get_client().list_database_names()
    return [n for n in names if n in ALLOWED_DBS or n.startswith("mare")]


def list_collections(database: str) -> list[str]:
    _guard_db(database)
    return get_client()[database].list_collection_names()


def get_node(node_id: str, tenant_id: str | None = None) -> dict[str, Any] | None:
    tenant_id = tenant_id or get_settings().tenant_id
    return agent_db()[NAV_NODES].find_one(inject_tenant({"_id": node_id}, tenant_id))


def get_children(node_id: str, tenant_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    tenant_id = tenant_id or get_settings().tenant_id
    return list(
        agent_db()[NAV_NODES]
        .find(inject_tenant({"parent_id": node_id}, tenant_id))
        .limit(limit)
    )


def navigation_search(
    query: str,
    *,
    method: SearchMethod | str | None = None,
    tenant_id: str | None = None,
    scope: str | None = None,
    filters: dict[str, Any] | None = None,
    limit: int | None = None,
) -> tuple[SearchMethod, list[dict[str, Any]]]:
    settings = get_settings()
    tenant_id = tenant_id or settings.tenant_id
    limit = limit or settings.default_search_limit
    recommended = recommend_method(query)
    selected = SearchMethod(method) if method else recommended
    extra = dict(filters or {})
    if scope:
        extra["parent_id"] = scope
    coll = agent_db()[NAV_NODES]
    caps = capabilities_or_default()
    query_vector = None
    auto_embed = caps.embedding_path == "atlas_auto"
    vector_path = "search_text" if auto_embed else "embedding"
    if not auto_embed and selected in {SearchMethod.semantic, SearchMethod.hybrid}:
        query_vector = get_embedding_model().embed([query])[0]

    if selected == SearchMethod.lexical:
        hits = lexical_search(coll, query, tenant_id=tenant_id, extra_filter=extra, limit=limit)
    elif selected == SearchMethod.semantic:
        hits = semantic_search(
            coll,
            query,
            tenant_id=tenant_id,
            extra_filter=extra,
            limit=limit,
            path=vector_path,
            query_vector=query_vector,
            auto_embed=auto_embed,
        )
    elif selected == SearchMethod.mongo_query:
        hits = query_documents(coll, tenant_id=tenant_id, filter_doc=extra, limit=limit)
    else:
        hits = hybrid_search(
            coll,
            query,
            tenant_id=tenant_id,
            extra_filter=extra,
            limit=limit,
            strategy=caps.hybrid_strategy,
            auto_embed=auto_embed,
            query_vector=query_vector,
            vector_path=vector_path,
        )
    return selected, hits


def search_within(
    node_id: str,
    query: str,
    *,
    tenant_id: str | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    tenant_id = tenant_id or get_settings().tenant_id
    node = get_node(node_id, tenant_id)
    if not node:
        return []
    source = node.get("source") or {}
    database = source.get("database") or RAW_DB
    collection = source.get("collection")
    if not collection:
        _, hits = navigation_search(query, tenant_id=tenant_id, scope=node_id, limit=limit)
        return hits
    _guard_db(database)
    coll = get_client()[database][collection]
    extra = dict(source.get("filter") or {})
    try:
        return lexical_search(
            coll,
            query,
            tenant_id=tenant_id,
            index=RAW_LEXICAL_INDEX,
            path={"wildcard": "*"},
            extra_filter=extra,
            limit=limit,
        )
    except Exception:
        filt = inject_tenant(extra, tenant_id)
        return list(coll.find(filt).limit(limit))


def query_namespace(
    namespace: str,
    filter_doc: dict[str, Any],
    *,
    tenant_id: str | None = None,
    projection: dict[str, Any] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    tenant_id = tenant_id or get_settings().tenant_id
    database, collection = _split_ns(namespace)
    return query_documents(
        get_client()[database][collection],
        tenant_id=tenant_id,
        filter_doc=filter_doc,
        projection=projection,
        limit=limit,
    )


def read_namespace(
    namespace: str,
    ids: list[str],
    *,
    tenant_id: str | None = None,
    projection: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    tenant_id = tenant_id or get_settings().tenant_id
    database, collection = _split_ns(namespace)
    return read_documents(
        get_client()[database][collection],
        ids,
        tenant_id=tenant_id,
        projection=projection,
    )


def _split_ns(namespace: str) -> tuple[str, str]:
    if "." not in namespace:
        raise ValueError("namespace must be database.collection")
    database, collection = namespace.split(".", 1)
    _guard_db(database)
    if database == RAW_DB and collection not in RAW_COLLECTIONS:
        raise ValueError(f"collection {collection} is not in the allowed raw set")
    return database, collection


def _guard_db(database: str) -> None:
    if database not in ALLOWED_DBS:
        raise ValueError(f"database {database} is not reachable from MARE")
