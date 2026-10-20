"""Persist a generic index beside the source data, then read it from any process.

Cards and hops go in `_agent_retrieval`. Source documents stay in the user's
database. A later ask loads the cards and finds those documents live.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId

from app.constants import AGENT_DB
from app.indexing.signals.nav_nodes import NODE_BUILDER_VERSION, build_nav_nodes
from app.indexing.signals.nav_vectors import (
    contract_for,
    embed_nav_nodes,
    same_contract,
    usable_embedder,
)
from app.indexing.signals.orchestrator import GenericIndex
from app.retrieval.generic_tools import GenericSurface, _matches, _policies
from app.retrieval.tool_policy import ToolHandlers

CATALOG = "generic_catalog"
CARDS = "generic_cards"
NAV_VECTORS = "generic_nav_vectors"
ACTIVE_ID = "active"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


class MissingGenericIndex(LookupError):
    """No saved generic index is available to query."""


class SemanticIndexError(RuntimeError):
    """Saved vectors cannot be used and semantic search was required."""


def read_source(
    database: Any,
    names: list[str],
    limit: int | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    """Load source collections. A short read is marked incomplete so later counts stay inside it."""
    documents: dict[str, list[dict[str, Any]]] = {}
    scope: dict[str, dict[str, Any]] = {}
    for name in names:
        collection = database[name]
        cursor = collection.find({})
        if limit:
            cursor = cursor.limit(int(limit))
        docs = [plain_document(doc) for doc in cursor]
        total = int(collection.count_documents({}))
        entry: dict[str, Any] = {"complete": len(docs) == total}
        if not entry["complete"]:
            entry["ids"] = [str(doc.get("_id")) for doc in docs]
        documents[name] = docs
        scope[name] = entry
    return documents, scope


def index_database(
    client: Any,
    database_name: str,
    *,
    limit: int | None = None,
    collections: list[str] | None = None,
    embedder: Any | None = None,
) -> dict[str, Any]:
    """Read one database, build neighborhoods, and save the cards on that cluster."""
    from app.config import get_settings
    from app.indexing.signals.orchestrator import build_generic_index

    database = client[database_name]
    names = collections or [
        name
        for name in sorted(database.list_collection_names())
        if not name.startswith("system.")
    ]
    documents, scope = read_source(database, names, limit)
    index = build_generic_index(
        documents,
        database=database_name,
        sample_size=get_settings().generic_sample_size,
        use_cache=False,
    )
    saved = save_generic_index(client, index, scope, embedder=embedder)
    return {
        "database": database_name,
        "documents": sum(len(rows) for rows in documents.values()),
        "cards": len(index.cards),
        "plans": len(index.plans),
        "partial": [name for name, entry in scope.items() if not entry.get("complete")],
        "semantic": saved["semantic"],
        "embedded": saved["embedded"],
        "reused": saved["reused"],
    }


def save_generic_index(
    client: Any,
    index: GenericIndex,
    scope: dict[str, dict[str, Any]],
    embedder: Any | None = None,
) -> dict[str, Any]:
    """Publish one build. A failed build leaves the previous active catalog in place."""
    agent = client[AGENT_DB]
    build_id = uuid.uuid4().hex
    try:
        saved = _stage_build(agent, index, scope, build_id, embedder)
    except Exception:
        _drop_build(agent, build_id)
        raise
    _drop_other_builds(agent, build_id)
    return saved


def upgrade_vectors(client: Any, embedder: Any) -> dict[str, Any]:
    """Embed saved cards without reading the source collections again."""
    provider = usable_embedder(embedder)
    if provider is None:
        raise SemanticIndexError("An embedding provider is required to upgrade vectors.")
    index, scope, _bundle = load_generic_bundle(client)
    saved = save_generic_index(client, index, scope, embedder=provider)
    saved["database"] = index.database
    return saved


def saved_index_summary(client: Any) -> dict[str, Any] | None:
    """Read the active catalog only. None when this cluster has no saved index."""
    catalog = client[AGENT_DB][CATALOG].find_one({"_id": ACTIVE_ID})
    if not catalog or not catalog.get("database"):
        return None
    collections = (catalog.get("profile") or {}).get("collections") or []
    documents = sum(
        int(item.get("population") or item.get("inspected") or 0) for item in collections
    )
    build_id = str(catalog.get("build_id") or "")
    cards = (
        int(client[AGENT_DB][CARDS].count_documents({"build_id": build_id})) if build_id else 0
    )
    scope = catalog.get("scope") or {}
    return {
        "database": str(catalog["database"]),
        "documents": documents,
        "cards": cards,
        "plans": len(catalog.get("plans") or []),
        "partial": [name for name, entry in scope.items() if not (entry or {}).get("complete")],
        "semantic": catalog.get("semantic") or "",
        "embedded": 0,
        "reused": cards,
        "already": True,
    }


def load_generic_index(client: Any) -> tuple[GenericIndex, dict[str, dict[str, Any]]]:
    index, scope, _bundle = load_generic_bundle(client)
    return index, scope


def load_generic_bundle(
    client: Any,
) -> tuple[GenericIndex, dict[str, dict[str, Any]], dict[str, Any]]:
    agent = client[AGENT_DB]
    catalog = agent[CATALOG].find_one({"_id": ACTIVE_ID})
    if not catalog:
        raise MissingGenericIndex(
            "No generic index is saved. Run scripts/index_generic.py --database <name>."
        )
    build_id = str(catalog.get("build_id") or "")
    cards = [_card(row) for row in _rows(agent[CARDS], build_id)]
    vector_rows = _rows(agent[NAV_VECTORS], build_id) if build_id else []
    index = GenericIndex(
        database=str(catalog["database"]),
        profile=catalog.get("profile") or {},
        text_fields={
            name: tuple(fields) for name, fields in (catalog.get("text_fields") or {}).items()
        },
        groups={},
        cards=cards,
        signals=[],
        validation={},
        plans=list(catalog.get("plans") or []),
        documents={},
        generation_id=str(catalog.get("generation_id") or ""),
    )
    bundle = {
        "build_id": build_id,
        "legacy": not build_id,
        "semantic": catalog.get("semantic") or "",
        "embedding": catalog.get("embedding") or {},
        "vectors": {str(row.get("node_id")): row for row in vector_rows},
    }
    return index, dict(catalog.get("scope") or {}), bundle


def load_generic_handlers(client: Any, embedder: Any | None = None) -> ToolHandlers:
    from app.config import get_settings

    index, scope, bundle = load_generic_bundle(client)
    status, vectors, query_embedder = _resolve_semantic(index, bundle, embedder)
    if status.get("error") and get_settings().generic_semantic_required:
        raise SemanticIndexError(str(status.get("reason") or "semantic index is unavailable"))
    reader = MongoReader(client[index.database], scope)
    surface = GenericSurface(
        index,
        reader=reader,
        vectors=vectors or None,
        query_embedder=query_embedder,
    )
    surface.semantic = status
    handlers = ToolHandlers(surface.handlers())
    handlers.policies = _policies(surface)
    handlers.semantic = status
    handlers.surface = surface
    return handlers


def _stage_build(
    agent: Any,
    index: GenericIndex,
    scope: dict[str, dict[str, Any]],
    build_id: str,
    embedder: Any | None,
) -> dict[str, Any]:
    provider = usable_embedder(embedder)
    nodes = build_nav_nodes(index)
    embedded = 0
    reused = 0
    contract = None
    semantic = "lexical_only"
    if provider is not None:
        previous = _reusable_vectors(agent, provider)
        records, stats = embed_nav_nodes(nodes, provider, previous)
        if len(records) != len(nodes):
            raise RuntimeError("navigation vectors are incomplete")
        embedded = int(stats["embedded"])
        reused = int(stats["reused"])
        contract = contract_for(provider)
        semantic = "ready"
        vector_rows = [
            {"_id": f"{build_id}:{record['node_id']}", "build_id": build_id, **record}
            for record in records
        ]
        if vector_rows:
            agent[NAV_VECTORS].insert_many(vector_rows)
        stored = _rows(agent[NAV_VECTORS], build_id)
        if len(stored) != len(nodes):
            raise RuntimeError("navigation vectors were not stored")
    card_rows = [
        {
            "_id": f"{build_id}:{card['collection']}:{card['key']}",
            "build_id": build_id,
            **card,
        }
        for card in index.cards
    ]
    if card_rows:
        agent[CARDS].insert_many(card_rows)
    if len(_rows(agent[CARDS], build_id)) != len(index.cards):
        raise RuntimeError("navigation cards were not stored")
    agent[CATALOG].replace_one(
        {"_id": ACTIVE_ID},
        {
            "_id": ACTIVE_ID,
            "database": index.database,
            "generation_id": index.generation_id,
            "build_id": build_id,
            "profile": index.profile,
            "plans": index.plans,
            "text_fields": {name: list(fields) for name, fields in index.text_fields.items()},
            "scope": scope,
            "semantic": semantic,
            "embedding": contract,
            "node_builder_version": NODE_BUILDER_VERSION,
        },
        upsert=True,
    )
    return {
        "build_id": build_id,
        "semantic": semantic,
        "embedded": embedded,
        "reused": reused,
        "nodes": len(nodes),
    }


def _reusable_vectors(agent: Any, embedder: Any) -> dict[str, dict[str, Any]]:
    catalog = agent[CATALOG].find_one({"_id": ACTIVE_ID}) or {}
    if not same_contract(catalog.get("embedding") or {}, embedder):
        return {}
    build_id = str(catalog.get("build_id") or "")
    if not build_id:
        return {}
    return {
        str(row.get("node_id")): row
        for row in _rows(agent[NAV_VECTORS], build_id)
        if row.get("node_id")
    }


def _resolve_semantic(
    index: GenericIndex,
    bundle: dict[str, Any],
    embedder: Any | None,
) -> tuple[dict[str, Any], dict[str, list[float]], Any | None]:
    provider = usable_embedder(embedder)
    contract = bundle.get("embedding") or {}
    if bundle.get("legacy") or not contract:
        reason = (
            "legacy index has no saved vectors"
            if bundle.get("legacy")
            else "index is lexical-only"
        )
        return {
            "status": "unavailable" if bundle.get("legacy") else "lexical_only",
            "reason": reason,
            "error": True,
        }, {}, None
    if provider is None or not same_contract(contract, provider):
        reason = (
            "no embedding provider matches the saved index"
            if provider is None
            else "embedding model does not match the saved index"
        )
        return {"status": "unavailable", "reason": reason, "error": True}, {}, None
    vectors: dict[str, list[float]] = {}
    expected = int(contract.get("dimensions") or 0)
    for node in build_nav_nodes(index):
        row = (bundle.get("vectors") or {}).get(str(node["_id"])) or {}
        vector = list(row.get("vector") or [])
        if len(vector) != expected:
            return {
                "status": "unavailable",
                "reason": "saved navigation vectors are incomplete",
                "error": True,
            }, {}, None
        vectors[str(node["_id"])] = vector
    return {"status": "ready", "reason": ""}, vectors, provider


def _rows(collection: Any, build_id: str) -> list[dict[str, Any]]:
    if not build_id:
        return [row for row in collection.find({}) if not row.get("build_id")]
    found = collection.find({"build_id": build_id})
    return [row for row in found if row.get("build_id") == build_id]


def _card(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": row.get("key"),
        "collection": row.get("collection"),
        "document_ids": list(row.get("document_ids") or []),
        "filter": row.get("filter") or {},
        "search_text": row.get("search_text") or "",
    }


def _drop_build(agent: Any, build_id: str) -> None:
    agent[CARDS].delete_many({"build_id": build_id})
    agent[NAV_VECTORS].delete_many({"build_id": build_id})


def _drop_other_builds(agent: Any, build_id: str) -> None:
    agent[CARDS].delete_many({"build_id": {"$ne": build_id}})
    agent[NAV_VECTORS].delete_many({"build_id": {"$ne": build_id}})


class MongoReader:
    """Live finds against the indexed database. Results are plain dicts."""

    def __init__(self, database: Any, scope: dict[str, dict[str, Any]] | None = None) -> None:
        self.database = database
        self.scope = scope or {}

    def fetch(
        self,
        collection: str,
        *,
        ids: list[Any] | None = None,
        filt: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        allowed = _allowed_ids(self.scope.get(collection))
        query = _mongo_query(ids, filt, allowed)
        cursor = self.database[collection].find(query)
        if limit is not None:
            cursor = cursor.limit(int(limit))
        docs = [plain_document(doc) for doc in cursor]
        if ids:
            wanted = {str(i) for i in ids}
            docs = [doc for doc in docs if str(doc.get("_id")) in wanted]
        if filt:
            docs = [doc for doc in docs if _matches(doc, filt)]
        if allowed is not None:
            docs = [doc for doc in docs if str(doc.get("_id")) in allowed]
        return docs


def plain_document(doc: dict[str, Any]) -> dict[str, Any]:
    return {key: _plain(value) for key, value in doc.items()}


def _plain(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _allowed_ids(entry: dict[str, Any] | None) -> set[str] | None:
    if not entry or entry.get("complete", True):
        return None
    return {str(i) for i in (entry.get("ids") or [])}


def _mongo_query(
    ids: list[Any] | None,
    filt: dict[str, Any] | None,
    allowed: set[str] | None,
) -> dict[str, Any]:
    parts: list[dict[str, Any]] = []
    if allowed is not None:
        parts.append({"_id": {"$in": _id_variants(list(allowed))}})
    if ids:
        parts.append({"_id": {"$in": _id_variants(ids)}})
    if filt:
        clause = _filt_query(filt)
        if clause:
            parts.append(clause)
    if not parts:
        return {}
    if len(parts) == 1:
        return parts[0]
    return {"$and": parts}


def _filt_query(filt: dict[str, Any]) -> dict[str, Any]:
    clauses: list[dict[str, Any]] = []
    for key, expected in filt.items():
        if key == "$and" and isinstance(expected, list):
            for item in expected:
                if isinstance(item, dict):
                    clause = _filt_query(item)
                    if clause:
                        clauses.append(clause)
            continue
        if str(key).startswith("$"):
            continue
        clause = _field_clause(str(key), expected)
        if clause:
            clauses.append(clause)
    if not clauses:
        return {}
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _field_clause(field: str, expected: Any) -> dict[str, Any]:
    primary = _field_ops(field, expected, coerce=False)
    if primary is None:
        return {}
    twin = _field_ops(field, expected, coerce=True)
    if twin is not None and twin != primary:
        return {"$or": [primary, twin]}
    return primary


def _field_ops(field: str, expected: Any, *, coerce: bool) -> dict[str, Any] | None:
    if isinstance(expected, dict):
        ops: dict[str, Any] = {}
        changed = False
        for op, raw in expected.items():
            if op not in {"$in", "$eq", "$gte", "$gt", "$lte", "$lt"}:
                continue
            if op == "$in":
                values = list(raw or [])
                coerced = [_coerce_date(item) for item in values]
                if coerce:
                    if coerced == values or any(item is None for item in coerced):
                        return None
                    ops[op] = coerced
                    changed = True
                else:
                    ops[op] = values
                continue
            coerced = _coerce_date(raw)
            if coerce:
                if coerced is None or coerced == raw:
                    return None
                ops[op] = coerced
                changed = True
            else:
                ops[op] = raw
        if coerce and not changed:
            return None
        return {field: ops} if ops else None
    values = _id_variants([expected]) if field == "_id" else [expected]
    if coerce:
        coerced = [_coerce_date(item) for item in values]
        if any(item is None for item in coerced) or coerced == values:
            return None
        values = coerced
    if len(values) == 1:
        return {field: values[0]}
    return {field: {"$in": values}}


def _id_variants(values: list[Any]) -> list[Any]:
    found: list[Any] = []
    seen: set[str] = set()
    for value in values:
        for item in (value, _object_id(value)):
            if item is None:
                continue
            key = f"{type(item).__name__}:{item}"
            if key in seen:
                continue
            seen.add(key)
            found.append(item)
    return found


def _object_id(value: Any) -> ObjectId | None:
    if isinstance(value, ObjectId):
        return value
    text = str(value)
    if len(text) != 24:
        return None
    try:
        return ObjectId(text)
    except InvalidId:
        return None


def _coerce_date(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and _DATE.match(value):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None
