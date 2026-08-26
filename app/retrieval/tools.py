"""High-level retrieval tools for the agent loop and MCP.

Each tool does a full deterministic pipeline internally so the model reasons
about what information it needs, not which Mongo primitive to invoke next.
"""

from __future__ import annotations

import json
from typing import Any

from app.config import get_settings
from app.constants import NAV_NODES, RAW_DB
from app.models.schemas import SearchMethod
from app.mongo.client import agent_db
from app.mongo.jsonutil import jsonable
from app.mongo.security import inject_tenant
from app.retrieval.serialize import doc_to_retrieved
from app.search.service import (
    get_children,
    get_node,
    navigation_search,
    query_namespace,
    read_namespace,
    search_within,
)

DOC_TEXT_CHARS = 1400
SUMMARY_CHARS = 480
CHILD_PREVIEW = 6
CHILD_EXPAND_HITS = 4
RELATED_LIMIT = 6
RELATED_ENTITY_CAP = 3
QUERY_RELATED_DOC_CAP = 3

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_information",
            "description": (
                "Find where relevant information lives in MongoDB. Searches the "
                "navigation hierarchy (not raw chunks) and returns matching nodes "
                "with summaries, important fields, a children preview, and related "
                "neighborhoods in other collections. Use this first for open-ended "
                "or multi-hop questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What you need to find."},
                    "scope": {
                        "type": "string",
                        "description": "Optional parent navigation node id to restrict search.",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["auto", "lexical", "semantic", "hybrid", "mongo_query"],
                        "description": (
                            "auto lets the server pick. Use lexical for ids/error codes."
                        ),
                    },
                    "limit": {"type": "integer", "description": "Max navigation hits (default 8)."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retrieve_evidence",
            "description": (
                "Read raw source documents for one or more navigation node ids in a "
                "single call. Prefer this after search_information identifies a "
                "neighborhood. Returns related_nodes in other collections when the "
                "documents belong to a shared entity."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Navigation node ids to expand.",
                    },
                    "query": {
                        "type": "string",
                        "description": (
                            "Optional focus query used to rank documents inside each node."
                        ),
                    },
                    "max_documents": {
                        "type": "integer",
                        "description": "Cap on raw documents returned (default 8, max 20).",
                    },
                },
                "required": ["node_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_documents",
            "description": (
                "Structured Mongo find on database.collection when you already know a "
                "field predicate from navigation nodes or retrieved documents. Use only "
                "field names you have observed. Tenant scope is injected server-side. "
                "Small result sets include related_nodes in other collections."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "namespace": {
                        "type": "string",
                        "description": (
                            "database.collection as reported by a navigation node source."
                        ),
                    },
                    "filter": {
                        "type": "object",
                        "description": "Mongo filter document. Do not include tenant_id.",
                    },
                    "projection": {"type": "object"},
                    "limit": {"type": "integer"},
                },
                "required": ["namespace", "filter"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_answer",
            "description": (
                "Call this once you can answer from retrieved evidence. Do not keep "
                "searching after this. Cite only Mongo documents you actually saw."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "answer": {
                        "type": "string",
                        "description": "Grounded answer with inline Mongo citations.",
                    },
                    "hypothesis": {"type": "string"},
                    "claims": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "claim_id": {"type": "string"},
                                "claim": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": [
                                        "supported",
                                        "partially_supported",
                                        "unsupported",
                                        "contradicted",
                                    ],
                                },
                                "confidence": {"type": "number"},
                            },
                            "required": ["claim"],
                        },
                    },
                    "cited_source_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "database.collection:document_id for evidence you used.",
                    },
                },
                "required": ["answer"],
            },
        },
    },
]


def search_information(
    query: str,
    *,
    tenant_id: str | None = None,
    scope: str | None = None,
    mode: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    tenant_id = tenant_id or settings.tenant_id
    limit = int(limit or settings.default_search_limit)
    method: SearchMethod | None = None
    if mode and mode != "auto":
        method = SearchMethod(mode)
    selected, hits = navigation_search(
        query, method=method, tenant_id=tenant_id, scope=scope, limit=limit
    )
    results: list[dict[str, Any]] = []
    expanded = 0
    for hit in hits:
        ntype = hit.get("node_type")
        children_preview: list[dict[str, Any]] = []
        if ntype in {"database", "collection", "group"} and expanded < CHILD_EXPAND_HITS:
            kids = get_children(str(hit.get("_id")), tenant_id, limit=CHILD_PREVIEW)
            children_preview = [_brief_node(k, include_children=False) for k in kids]
            expanded += 1
        results.append(_brief_node(hit, children_preview=children_preview))
    related = related_nodes_for(tenant_id=tenant_id, nodes=hits)
    return {
        "method": selected.value,
        "count": len(results),
        "results": results,
        "related_nodes": related,
    }


def retrieve_evidence(
    node_ids: list[str],
    *,
    tenant_id: str | None = None,
    query: str | None = None,
    max_documents: int | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    tenant_id = tenant_id or settings.tenant_id
    cap = max(1, min(int(max_documents or 8), 20))
    ids = [str(n) for n in (node_ids or []) if n][:8]
    documents: list[dict[str, Any]] = []
    seen: set[str] = set()
    missing: list[str] = []
    hints: list[dict[str, Any]] = []
    origin_nodes: list[dict[str, Any]] = []
    per_node = max(2, min(6, cap))
    for nid in ids:
        node = get_node(nid, tenant_id)
        if not node:
            missing.append(nid)
            continue
        origin_nodes.append(node)
        batch = _docs_for_node(node, tenant_id, query or "", per_node)
        if not batch:
            kids = get_children(nid, tenant_id, limit=CHILD_PREVIEW)
            if kids:
                hints.append(
                    {
                        "node_id": nid,
                        "hint": "no raw documents; inspect child nodes",
                        "children": [_brief_node(k, include_children=False) for k in kids],
                    }
                )
        for doc in batch:
            key = f"{doc.ref.collection}:{doc.ref.document_id}"
            if key in seen:
                continue
            seen.add(key)
            documents.append(_doc_payload(doc))
            if len(documents) >= cap:
                break
        if len(documents) >= cap:
            break
    related = related_nodes_for(
        tenant_id=tenant_id, nodes=origin_nodes, documents=documents
    )
    return {
        "count": len(documents),
        "documents": documents,
        "missing_nodes": missing,
        "hints": hints,
        "related_nodes": related,
    }


def query_documents_tool(
    namespace: str,
    filter: dict[str, Any] | str | None = None,
    *,
    tenant_id: str | None = None,
    projection: dict[str, Any] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    tenant_id = tenant_id or get_settings().tenant_id
    filt = _as_dict(filter)
    proj = _as_dict(projection) or None
    cap = max(1, min(int(limit or 10), 20))
    if "." not in (namespace or ""):
        return {"error": "namespace must be database.collection"}
    database, collection = namespace.split(".", 1)
    rows = query_namespace(
        namespace, filt, tenant_id=tenant_id, projection=proj, limit=cap
    )
    docs = [_doc_payload(_as_docs_row(r, database, collection)) for r in rows]
    related: list[dict[str, Any]] = []
    if len(docs) <= QUERY_RELATED_DOC_CAP:
        related = related_nodes_for(
            tenant_id=tenant_id,
            documents=docs,
            exclude_collections={collection} if collection else set(),
        )
    return {
        "count": len(docs),
        "namespace": namespace,
        "documents": docs,
        "related_nodes": related,
    }


def default_handlers() -> dict[str, Any]:
    return {
        "search_information": search_information,
        "retrieve_evidence": retrieve_evidence,
        "query_documents": query_documents_tool,
    }


def dispatch_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    tenant_id: str,
    handlers: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fns = handlers or default_handlers()
    handler = fns.get(name)
    if handler is None:
        return {"error": f"unknown tool {name}"}
    if name == "search_information":
        return handler(
            arguments.get("query") or "",
            tenant_id=tenant_id,
            scope=arguments.get("scope"),
            mode=arguments.get("mode"),
            limit=arguments.get("limit"),
        )
    if name == "retrieve_evidence":
        return handler(
            arguments.get("node_ids") or [],
            tenant_id=tenant_id,
            query=arguments.get("query"),
            max_documents=arguments.get("max_documents"),
        )
    if name == "query_documents":
        return handler(
            arguments.get("namespace") or "",
            arguments.get("filter") or {},
            tenant_id=tenant_id,
            projection=arguments.get("projection"),
            limit=arguments.get("limit"),
        )
    return {"error": f"tool {name} is not executable here"}


def _docs_for_node(node: dict[str, Any], tenant_id: str, query: str, limit: int):
    source = node.get("source") or {}
    ntype = node.get("node_type")
    database = source.get("database") or RAW_DB
    collection = source.get("collection")
    node_id = str(node.get("_id"))
    if ntype in {"database", "collection"}:
        if query:
            scoped = search_within(node_id, query, tenant_id=tenant_id, limit=limit)
            if collection:
                return [_as_docs_row(r, database, collection) for r in scoped]
            return []
        if collection:
            raw = query_namespace(
                f"{database}.{collection}",
                source.get("filter") or {},
                tenant_id=tenant_id,
                limit=limit,
            )
            return [_as_docs_row(r, database, collection) for r in raw]
        return []
    if ntype == "group":
        if query:
            scoped = search_within(node_id, query, tenant_id=tenant_id, limit=limit)
            if collection:
                docs = [_as_docs_row(r, database, collection) for r in scoped]
                if docs:
                    return docs
        if collection:
            raw = query_namespace(
                f"{database}.{collection}",
                source.get("filter") or {},
                tenant_id=tenant_id,
                limit=limit,
            )
            return [_as_docs_row(r, database, collection) for r in raw]
        return []
    ids = list(source.get("document_ids") or [])
    if collection and ids:
        raw = read_namespace(f"{database}.{collection}", [str(i) for i in ids], tenant_id=tenant_id)
        return [_as_docs_row(r, database, collection) for r in raw]
    return []


def _as_docs_row(row: dict[str, Any], database: str, collection: str):
    return doc_to_retrieved(row, database, collection, float(row.get("_score") or 0))


def _brief_node(
    node: dict[str, Any],
    *,
    children_preview: list[dict[str, Any]] | None = None,
    include_children: bool = True,
) -> dict[str, Any]:
    source = node.get("source") or {}
    brief_source = {
        "database": source.get("database"),
        "collection": source.get("collection"),
        "filter": source.get("filter") or {},
        "document_ids": (source.get("document_ids") or [])[:8],
    }
    schema_info = node.get("schema") or {}
    fields = list(schema_info.get("important_fields") or [])[:12]
    descriptions = schema_info.get("field_descriptions") or {}
    examples = {str(k): descriptions[k] for k in list(descriptions)[:6]}
    metadata = node.get("metadata") or {}
    out: dict[str, Any] = {
        "node_id": node.get("_id") or node.get("node_id"),
        "name": node.get("name"),
        "node_type": node.get("node_type"),
        "summary": (node.get("summary") or node.get("description") or "")[:SUMMARY_CHARS],
        "source": brief_source,
        "score": node.get("_score") or node.get("score"),
        "document_count": metadata.get("document_count"),
        "important_fields": fields,
    }
    if examples:
        out["field_examples"] = examples
    if metadata.get("time_min") is not None:
        out["time_min"] = metadata.get("time_min")
    if metadata.get("time_max") is not None:
        out["time_max"] = metadata.get("time_max")
    if include_children:
        out["children_preview"] = children_preview or []
    return jsonable(out)


def extract_entity_ids(
    *,
    nodes: list[dict[str, Any]] | None = None,
    documents: list[Any] | None = None,
) -> list[str]:
    """Pull customer-like entity ids from navigation nodes or retrieved docs."""
    found: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if not text.startswith("cust_") or text in seen:
            return
        seen.add(text)
        found.append(text)

    for node in nodes or []:
        source = node.get("source") or {}
        filt = source.get("filter") or {}
        add(filt.get("customer_id"))
        for did in source.get("document_ids") or []:
            add(did)
        for ent in (node.get("metadata") or {}).get("entities") or []:
            add(ent)
        add(node.get("name"))
    for doc in documents or []:
        if isinstance(doc, dict):
            ref = doc.get("ref") or {}
            add(ref.get("document_id"))
            add((doc.get("content") or {}).get("customer_id"))
            text = str(doc.get("text") or "")
            for token in text.replace("\n", " ").split():
                cleaned = token.strip(".,;:()[]\"'")
                add(cleaned)
            continue
        ref = getattr(doc, "ref", None)
        if ref is not None:
            add(getattr(ref, "document_id", None))
        content = getattr(doc, "content", None) or {}
        if isinstance(content, dict):
            add(content.get("customer_id"))
        text = str(getattr(doc, "text", "") or "")
        for token in text.replace("\n", " ").split():
            add(token.strip(".,;:()[]\"'"))
    return found


def node_matches_entities(node: dict[str, Any], entities: set[str]) -> bool:
    if not entities:
        return False
    source = node.get("source") or {}
    filt = source.get("filter") or {}
    values: list[str] = []
    cid = filt.get("customer_id")
    if cid:
        values.append(str(cid))
    values.extend(str(x) for x in (source.get("document_ids") or []) if x)
    values.extend(str(x) for x in ((node.get("metadata") or {}).get("entities") or []) if x)
    return bool(entities.intersection(values))


def select_related_nodes(
    candidates: list[dict[str, Any]],
    *,
    entities: list[str],
    exclude_ids: set[str] | None = None,
    exclude_collections: set[str] | None = None,
    limit: int = RELATED_LIMIT,
) -> list[dict[str, Any]]:
    """Pick sibling nodes in other collections that share an entity id."""
    wanted = set(entities)
    skip_ids = exclude_ids or set()
    skip_colls = exclude_collections or set()
    matched: list[dict[str, Any]] = []
    for node in candidates:
        nid = str(node.get("_id") or node.get("node_id") or "")
        if not nid or nid in skip_ids:
            continue
        collection = (node.get("source") or {}).get("collection")
        if not collection or collection in skip_colls:
            continue
        if node.get("node_type") in {None, "database"}:
            continue
        if not node_matches_entities(node, wanted):
            continue
        matched.append(node)
    rank = {"group": 0, "document": 1, "collection": 2}
    matched.sort(key=lambda n: (rank.get(str(n.get("node_type")), 9), str(n.get("_id"))))
    picked: list[dict[str, Any]] = []
    seen_coll: set[str] = set()
    rest: list[dict[str, Any]] = []
    for node in matched:
        collection = str((node.get("source") or {}).get("collection"))
        if collection in seen_coll:
            rest.append(node)
            continue
        seen_coll.add(collection)
        picked.append(node)
        if len(picked) >= limit:
            return picked
    for node in rest:
        picked.append(node)
        if len(picked) >= limit:
            break
    return picked


def related_nodes_for(
    *,
    tenant_id: str,
    nodes: list[dict[str, Any]] | None = None,
    documents: list[Any] | None = None,
    exclude_collections: set[str] | None = None,
    candidates: list[dict[str, Any]] | None = None,
    limit: int = RELATED_LIMIT,
) -> list[dict[str, Any]]:
    """Cross-collection neighborhoods for entities found in the current result."""
    entities = extract_entity_ids(nodes=nodes, documents=documents)[:RELATED_ENTITY_CAP]
    if not entities:
        return []
    skip_ids = {str(n.get("_id") or n.get("node_id") or "") for n in (nodes or [])}
    skip_colls = set(exclude_collections or [])
    for node in nodes or []:
        collection = (node.get("source") or {}).get("collection")
        if collection:
            skip_colls.add(str(collection))
    for doc in documents or []:
        if isinstance(doc, dict):
            coll = (doc.get("ref") or {}).get("collection")
        else:
            ref = getattr(doc, "ref", None)
            coll = getattr(ref, "collection", None) if ref is not None else None
        if coll:
            skip_colls.add(str(coll))
    pool = candidates
    if pool is None:
        pool = _load_related_candidates(tenant_id, entities, skip_ids)
    picked = select_related_nodes(
        pool,
        entities=entities,
        exclude_ids=skip_ids,
        exclude_collections=skip_colls,
        limit=limit,
    )
    return [_brief_node(n, include_children=False) for n in picked]


def _load_related_candidates(
    tenant_id: str,
    entities: list[str],
    exclude_ids: set[str],
) -> list[dict[str, Any]]:
    query: dict[str, Any] = {
        "$or": [
            {"source.filter.customer_id": {"$in": entities}},
            {"metadata.entities": {"$in": entities}},
            {"source.document_ids": {"$in": entities}},
        ]
    }
    if exclude_ids:
        query["_id"] = {"$nin": [i for i in exclude_ids if i]}
    try:
        return list(
            agent_db()[NAV_NODES].find(inject_tenant(query, tenant_id)).limit(40)
        )
    except Exception:
        return []



def _doc_payload(doc) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ref": doc.ref.model_dump(),
        "text": (doc.text or "")[:DOC_TEXT_CHARS],
        "score": doc.score,
    }
    content = doc.content or {}
    if isinstance(content, dict) and content.get("customer_id"):
        payload["content"] = {"customer_id": content["customer_id"]}
    return jsonable(payload)


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}
