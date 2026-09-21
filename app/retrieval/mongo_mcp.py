"""Schema-blind Mongo primitives: the control vs MARE's navigation tools.

No navigation_nodes, no related_nodes. Source-of-record find/count only.
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.constants import RAW_COLLECTIONS, RAW_DB
from app.indexing.schema_discovery import discover_schema
from app.mongo.client import get_client
from app.retrieval.serialize import doc_to_retrieved
from app.retrieval.tools import TOOL_DEFINITIONS as MARE_TOOLS, _as_dict, _doc_payload
from app.search.service import count_namespace, query_namespace

SYSTEM_PROMPT = (
    "You are a MongoDB assistant with standard database tools.\n\n"
    "You do not know the databases, collections, or field names in advance. "
    "Discover them with list_databases, list_collections, and collection_schema. "
    "Then find or count on database.collection using only field names you observed.\n\n"
    "Rules:\n"
    "- Never invent Mongo document ids, collections, or field names.\n"
    "- Cite sources as database.collection:document_id from documents you actually read.\n"
    "- Tenant scope is injected server-side. Never send tenant_id.\n"
    "- submit_answer as soon as the evidence is sufficient.\n"
)

_SUBMIT = next(t for t in MARE_TOOLS if t["function"]["name"] == "submit_answer")

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_databases",
            "description": "List databases you may query.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_collections",
            "description": "List collections in a database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "database": {"type": "string"},
                },
                "required": ["database"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "collection_schema",
            "description": (
                "Sample field names, types, and examples for database.collection. "
                "Call this before find/count if you do not yet know the fields."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "namespace": {
                        "type": "string",
                        "description": "database.collection",
                    },
                },
                "required": ["namespace"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find",
            "description": (
                "Mongo find on database.collection. Use only field names you have "
                "observed. Tenant scope is injected server-side."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "namespace": {"type": "string", "description": "database.collection"},
                    "filter": {"type": "object", "description": "Mongo filter. No tenant_id."},
                    "projection": {"type": "object"},
                    "limit": {"type": "integer"},
                },
                "required": ["namespace"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "count",
            "description": "Mongo countDocuments on database.collection. Tenant scope is injected.",
            "parameters": {
                "type": "object",
                "properties": {
                    "namespace": {"type": "string", "description": "database.collection"},
                    "filter": {"type": "object", "description": "Mongo filter. No tenant_id."},
                },
                "required": ["namespace"],
            },
        },
    },
    _SUBMIT,
]


def list_databases_tool(**_kwargs: Any) -> dict[str, Any]:
    return {"databases": [RAW_DB]}


def list_collections_tool(database: str, **_kwargs: Any) -> dict[str, Any]:
    if database != RAW_DB:
        return {"error": f"database {database} is not reachable"}
    names = set(get_client()[database].list_collection_names())
    return {"database": database, "collections": [c for c in RAW_COLLECTIONS if c in names]}


def collection_schema_tool(namespace: str, **_kwargs: Any) -> dict[str, Any]:
    if "." not in (namespace or ""):
        return {"error": "namespace must be database.collection"}
    database, collection = namespace.split(".", 1)
    if database != RAW_DB or collection not in RAW_COLLECTIONS:
        return {"error": f"{namespace} is not reachable"}
    schema = discover_schema(get_client()[database][collection])
    fields = [
        {"name": f.get("name"), "example": f.get("example")}
        for f in (schema.get("fields") or [])[:18]
    ]
    return {
        "namespace": namespace,
        "document_count": schema.get("document_count"),
        "important_fields": schema.get("important_fields") or [],
        "fields": fields,
    }


def find_tool(
    namespace: str,
    filter: dict[str, Any] | str | None = None,
    *,
    tenant_id: str | None = None,
    projection: dict[str, Any] | None = None,
    limit: int | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    tenant_id = tenant_id or get_settings().tenant_id
    filt = _as_dict(filter)
    proj = _as_dict(projection) or None
    cap = max(1, min(int(limit or 10), 20))
    if "." not in (namespace or ""):
        return {"error": "namespace must be database.collection"}
    database, collection = namespace.split(".", 1)
    if database != RAW_DB or collection not in RAW_COLLECTIONS:
        return {"error": f"{namespace} is not reachable"}
    rows = query_namespace(
        namespace, filt, tenant_id=tenant_id, projection=proj, limit=cap
    )
    docs = [_doc_payload(doc_to_retrieved(r, database, collection)) for r in rows]
    return {"count": len(docs), "namespace": namespace, "documents": docs}


def count_tool(
    namespace: str,
    filter: dict[str, Any] | str | None = None,
    *,
    tenant_id: str | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    tenant_id = tenant_id or get_settings().tenant_id
    if "." not in (namespace or ""):
        return {"error": "namespace must be database.collection"}
    database, collection = namespace.split(".", 1)
    if database != RAW_DB or collection not in RAW_COLLECTIONS:
        return {"error": f"{namespace} is not reachable"}
    n = count_namespace(namespace, _as_dict(filter), tenant_id=tenant_id)
    return {"count": n, "namespace": namespace}


def default_handlers() -> dict[str, Any]:
    return {
        "list_databases": list_databases_tool,
        "list_collections": list_collections_tool,
        "collection_schema": collection_schema_tool,
        "find": find_tool,
        "count": count_tool,
    }
