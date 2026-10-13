"""Persist a generic index beside the source data, then read it from any process.

Cards and hops go in `_agent_retrieval`. Source documents stay in the user's
database. A later ask loads the cards and finds those documents live.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId

from app.constants import AGENT_DB
from app.indexing.signals.orchestrator import GenericIndex
from app.retrieval.generic_tools import _matches, generic_handlers

CATALOG = "generic_catalog"
CARDS = "generic_cards"
ACTIVE_ID = "active"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


class MissingGenericIndex(LookupError):
    """No saved generic index is available to query."""


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
    save_generic_index(client, index, scope)
    return {
        "database": database_name,
        "documents": sum(len(rows) for rows in documents.values()),
        "cards": len(index.cards),
        "plans": len(index.plans),
        "partial": [name for name, entry in scope.items() if not entry.get("complete")],
    }


def save_generic_index(
    client: Any,
    index: GenericIndex,
    scope: dict[str, dict[str, Any]],
) -> None:
    """Replace the active generic index. `scope` records which ids were indexed."""
    agent = client[AGENT_DB]
    catalog = {
        "_id": ACTIVE_ID,
        "database": index.database,
        "generation_id": index.generation_id,
        "profile": index.profile,
        "plans": index.plans,
        "text_fields": {name: list(fields) for name, fields in index.text_fields.items()},
        "scope": scope,
    }
    agent[CATALOG].replace_one({"_id": ACTIVE_ID}, catalog, upsert=True)
    cards = agent[CARDS]
    cards.delete_many({})
    rows = []
    for card in index.cards:
        rows.append({"_id": f"{card['collection']}:{card['key']}", **card})
    if rows:
        cards.insert_many(rows)


def load_generic_index(client: Any) -> tuple[GenericIndex, dict[str, dict[str, Any]]]:
    agent = client[AGENT_DB]
    catalog = agent[CATALOG].find_one({"_id": ACTIVE_ID})
    if not catalog:
        raise MissingGenericIndex(
            "No generic index is saved. Run scripts/index_generic.py --database <name>."
        )
    cards = []
    for row in agent[CARDS].find({}):
        cards.append(
            {
                "key": row.get("key"),
                "collection": row.get("collection"),
                "document_ids": list(row.get("document_ids") or []),
                "filter": row.get("filter") or {},
                "search_text": row.get("search_text") or "",
            }
        )
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
    return index, dict(catalog.get("scope") or {})


def load_generic_handlers(client: Any, embedder: Any | None = None) -> dict[str, Any]:
    index, scope = load_generic_index(client)
    reader = MongoReader(client[index.database], scope)
    return generic_handlers(index, embedder, reader)


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
