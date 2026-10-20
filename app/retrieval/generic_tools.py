"""Same MARE tool names over a generic index. No tenant injection.

Pass a reader to fetch live Mongo documents. Without one, the index's
in-memory documents are used.
"""

from __future__ import annotations

import json
import math
import re
import threading
from datetime import datetime
from typing import Any

from app.indexing.signals.nav_nodes import build_nav_nodes
from app.retrieval.serialize import doc_to_retrieved
from app.retrieval.tool_policy import (
    ToolHandlers,
    ToolPolicy,
    validate_query,
    validate_retrieve,
    validate_search,
)

_TOKEN = re.compile(r"[a-z0-9_]+")
_SUMMARY = 480
_DOC_CHARS = 1400


class GenericSurface:
    def __init__(
        self,
        index: Any,
        embedder: Any | None = None,
        reader: Any | None = None,
        *,
        vectors: dict[str, list[float]] | None = None,
        query_embedder: Any | None = None,
    ) -> None:
        self.index = index
        self._reader = reader
        self.nodes = build_nav_nodes(index)
        self._by_id = {str(node["_id"]): node for node in self.nodes}
        self._embed_lock = threading.Lock()
        self.embed_calls = {"nodes": 0, "queries": 0}
        chosen = query_embedder if query_embedder is not None else embedder
        self._vector_by_id = {}
        if vectors and chosen is not None:
            for node_id, vector in vectors.items():
                if vector:
                    self._vector_by_id[str(node_id)] = list(vector)
        self._embedder = chosen if self._vector_by_id else None
        if self._vector_by_id:
            self.semantic = {"status": "ready", "reason": ""}
        elif chosen is not None:
            self.semantic = {
                "status": "unavailable",
                "reason": "navigation vectors are not loaded",
            }
        else:
            self.semantic = {"status": "lexical_only", "reason": "no embedding provider"}

    def handlers(self) -> dict[str, Any]:
        return {
            "search_information": self.search_information,
            "retrieve_evidence": self.retrieve_evidence,
            "query_documents": self.query_documents,
        }

    def search_information(
        self,
        query: str,
        *,
        tenant_id: str | None = None,
        scope: str | None = None,
        mode: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        del tenant_id
        cap = max(1, min(int(limit or 8), 8))
        pool = self._scoped(scope)
        ranked = self._rank(query, pool)
        hits = ranked[:cap]
        if not hits:
            hits = [node for node in pool if node["node_type"] == "collection"][:cap]
        results = [_brief(node) for node in hits]
        return {
            "method": mode or "hybrid",
            "count": len(results),
            "results": results,
            "related_nodes": self._related(hits, query),
            "index_status": dict(self.semantic),
        }

    def retrieve_evidence(
        self,
        node_ids: list[str],
        *,
        tenant_id: str | None = None,
        query: str | None = None,
        max_documents: int | None = None,
    ) -> dict[str, Any]:
        del tenant_id
        cap = max(1, min(int(max_documents or 8), 20))
        documents: list[dict[str, Any]] = []
        missing: list[str] = []
        origins: list[dict[str, Any]] = []
        seen: set[str] = set()
        for node_id in [str(n) for n in (node_ids or []) if n][:8]:
            if node_id.startswith("hop:"):
                hopped = self._hop_docs(node_id, cap)
                if not hopped:
                    missing.append(node_id)
                    continue
                for doc in hopped:
                    key = f"{doc['ref']['collection']}:{doc['ref']['document_id']}"
                    if key in seen:
                        continue
                    seen.add(key)
                    documents.append(doc)
                    if len(documents) >= cap:
                        break
                if len(documents) >= cap:
                    break
                continue
            node = self._by_id.get(node_id)
            if node is None:
                missing.append(node_id)
                continue
            origins.append(node)
            for doc in self._docs_for(node, query or "", cap):
                key = f"{doc['ref']['collection']}:{doc['ref']['document_id']}"
                if key in seen:
                    continue
                seen.add(key)
                documents.append(doc)
                if len(documents) >= cap:
                    break
            if len(documents) >= cap:
                break
        return {
            "count": len(documents),
            "documents": documents,
            "missing_nodes": missing,
            "hints": [],
            "related_nodes": self._related(origins, query or ""),
        }

    def query_documents(
        self,
        namespace: str,
        filter: dict[str, Any] | str | None = None,
        *,
        tenant_id: str | None = None,
        projection: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        del tenant_id, projection
        filt = _as_dict(filter)
        if _forbidden(filt):
            return {"error": "operator not allowlisted"}
        if "." not in (namespace or ""):
            return {"error": "namespace must be database.collection"}
        database, collection = namespace.split(".", 1)
        if database != self.index.database or not self._known(collection):
            return {"error": f"unknown namespace {namespace}"}
        cap = max(1, min(int(limit or 10), 20))
        matched = self._rows(collection, filt=filt, limit=cap)
        docs = [_payload(doc, database, collection) for doc in matched]
        return {
            "count": len(docs),
            "namespace": namespace,
            "documents": docs,
            "related_nodes": self._related(
                [
                    {
                        "source": {
                            "collection": collection,
                            "document_ids": [d["ref"]["document_id"] for d in docs],
                        }
                    }
                ],
                "",
            )
            if len(docs) <= 3
            else [],
        }

    def _related(self, nodes: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
        """Bind a validated hop to the key on the documents that matched the query."""
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for node in nodes:
            source = node.get("source") or {}
            collection = str(source.get("collection") or "")
            if not collection:
                continue
            members = self._members(collection, source.get("document_ids") or [])
            if query:
                ranked = sorted(
                    members,
                    key=lambda doc: -_overlap(query, {"search_text": _text(doc)}),
                )
                focused = [
                    doc for doc in ranked if _overlap(query, {"search_text": _text(doc)}) > 0
                ]
                members = (focused or ranked)[:2]
            else:
                members = members[:3]
            for plan in self.index.plans:
                if plan.get("op") != "hop" or plan.get("collection") != collection:
                    continue
                target = str(plan["to_collection"])
                to_field = str(plan.get("to_field") or "_id")
                for doc in members:
                    value = doc.get(plan["field"])
                    if value is None:
                        continue
                    node_id = f"hop:{target}:{to_field}:{value}"
                    if node_id in seen:
                        continue
                    seen.add(node_id)
                    out.append(
                        {
                            "node_id": node_id,
                            "name": f"{target} {value}",
                            "node_type": "group",
                            "summary": (
                                f"Hop {collection}.{plan['field']} -> {target}.{to_field} = {value}"
                            )[:_SUMMARY],
                            "source": {
                                "database": self.index.database,
                                "collection": target,
                                "filter": {to_field: value},
                                "document_ids": [
                                    str(row.get("_id"))
                                    for row in self._rows(
                                        target, filt={to_field: value}, limit=8
                                    )
                                ],
                            },
                            "children_preview": [],
                        }
                    )
                    if len(out) >= 6:
                        return out
        return out

    def _members(self, collection: str, document_ids: list[Any]) -> list[dict[str, Any]]:
        if not document_ids:
            return []
        return self._rows(collection, ids=document_ids)

    def _hop_docs(self, node_id: str, limit: int) -> list[dict[str, Any]]:
        _prefix, collection, field, value = node_id.split(":", 3)
        rows = self._rows(collection, filt={field: value}, limit=limit)
        return [_payload(doc, self.index.database, collection) for doc in rows]

    def _known(self, collection: str) -> bool:
        if collection in (self.index.documents or {}):
            return True
        names = {
            str(coll.get("name"))
            for coll in (self.index.profile.get("collections") or [])
        }
        return collection in names

    def _rows(
        self,
        collection: str,
        *,
        ids: list[Any] | None = None,
        filt: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if self._reader is not None:
            return self._reader.fetch(collection, ids=ids, filt=filt, limit=limit)
        rows = list(self.index.documents.get(collection) or [])
        if ids:
            wanted = {str(i) for i in ids}
            rows = [doc for doc in rows if str(doc.get("_id")) in wanted]
        if filt:
            rows = [doc for doc in rows if _matches(doc, filt)]
        if limit is not None:
            rows = rows[: int(limit)]
        return rows

    def _scoped(self, scope: str | None) -> list[dict[str, Any]]:
        if not scope:
            return list(self.nodes)
        node = self._by_id.get(str(scope))
        if node is None:
            return list(self.nodes)
        collection = (node.get("source") or {}).get("collection")
        return [
            item
            for item in self.nodes
            if (item.get("source") or {}).get("collection") == collection
        ]

    def _rank(self, query: str, pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not pool:
            return []
        scores = {id(node): 0.0 for node in pool}
        lexical = sorted(pool, key=lambda node: (-_overlap(query, node), str(node["_id"])))
        for rank, node in enumerate(lexical):
            scores[id(node)] += 1.0 / (60 + rank + 1)
        if self._vector_by_id and self._embedder is not None:
            embedded: list[list[float]] = []
            with self._embed_lock:
                try:
                    embedded = self._embedder.embed([query])
                except Exception:
                    embedded = []
                else:
                    self.embed_calls["queries"] += 1
            query_vec = list(embedded[0]) if embedded else []
            stored = next(iter(self._vector_by_id.values()), [])
            if query_vec and stored and len(query_vec) != len(stored):
                query_vec = []
            if query_vec:
                order = sorted(
                    pool,
                    key=lambda node: (
                        -_cosine(query_vec, self._vector_by_id.get(str(node["_id"])) or []),
                        str(node["_id"]),
                    ),
                )
                for rank, node in enumerate(order):
                    scores[id(node)] += 1.0 / (60 + rank + 1)
        return sorted(pool, key=lambda node: (-scores[id(node)], str(node["_id"])))

    def _docs_for(self, node: dict[str, Any], query: str, limit: int) -> list[dict[str, Any]]:
        source = node.get("source") or {}
        collection = str(source.get("collection") or "")
        database = str(source.get("database") or self.index.database)
        id_list = list(source.get("document_ids") or [])
        filt = source.get("filter") or {}
        applied = None
        if filt and filt != {"_id": {"$in": id_list}}:
            applied = filt
        fetch_limit = None
        if self._reader is not None and not id_list and applied is None:
            fetch_limit = max(limit, 20)
        rows = self._rows(
            collection,
            ids=id_list or None,
            filt=applied,
            limit=fetch_limit,
        )
        if query:
            ranked = sorted(
                rows,
                key=lambda doc: (
                    -_overlap(query, {"search_text": _text(doc)}),
                    str(doc.get("_id")),
                ),
            )
            matched = [
                doc for doc in ranked if _overlap(query, {"search_text": _text(doc)}) > 0
            ]
            rows = matched or ranked
        return [_payload(doc, database, collection) for doc in rows[:limit]]


def generic_handlers(
    index: Any,
    embedder: Any | None = None,
    reader: Any | None = None,
    *,
    vectors: dict[str, list[float]] | None = None,
) -> ToolHandlers:
    """Ask-time handlers. `embedder` ranks queries and is not applied to navigation cards."""
    surface = GenericSurface(
        index,
        reader=reader,
        vectors=vectors,
        query_embedder=embedder if vectors else None,
    )
    handlers = ToolHandlers(surface.handlers())
    handlers.policies = _policies(surface)
    handlers.semantic = surface.semantic
    handlers.surface = surface
    return handlers


def generic_handlers_with_vectors(
    index: Any,
    embedder: Any | None = None,
    reader: Any | None = None,
) -> ToolHandlers:
    """Embed navigation nodes once for an in-memory index."""
    from app.indexing.signals.nav_vectors import embed_nav_nodes, usable_embedder

    embedder = usable_embedder(embedder)
    vectors = None
    if embedder is not None:
        records, _stats = embed_nav_nodes(build_nav_nodes(index), embedder, {})
        vectors = {row["node_id"]: row["vector"] for row in records}
    return generic_handlers(index, embedder, reader, vectors=vectors)


def _policies(surface: GenericSurface) -> dict[str, ToolPolicy]:
    return {
        "search_information": ToolPolicy(
            True, True, False, validate_search, surface.search_information
        ),
        "retrieve_evidence": ToolPolicy(
            True, True, False, validate_retrieve, surface.retrieve_evidence
        ),
        "query_documents": ToolPolicy(
            True, True, False, validate_query, surface.query_documents
        ),
    }


def _brief(node: dict[str, Any]) -> dict[str, Any]:
    source = node.get("source") or {}
    return {
        "node_id": node.get("_id"),
        "name": node.get("name"),
        "node_type": node.get("node_type"),
        "summary": str(node.get("summary") or "")[:_SUMMARY],
        "source": {
            "database": source.get("database"),
            "collection": source.get("collection"),
            "filter": source.get("filter") or {},
            "document_ids": list(source.get("document_ids") or [])[:8],
        },
        "document_count": (node.get("metadata") or {}).get("document_count"),
        "important_fields": list((node.get("schema") or {}).get("important_fields") or [])[:12],
        "children_preview": [],
    }


def _payload(doc: dict[str, Any], database: str, collection: str) -> dict[str, Any]:
    retrieved = doc_to_retrieved(doc, database, collection)
    return {
        "ref": retrieved.ref.model_dump(),
        "text": (retrieved.text or "")[:_DOC_CHARS],
        "score": retrieved.score,
    }


def _text(doc: dict[str, Any]) -> str:
    parts = []
    for key, value in doc.items():
        if isinstance(value, datetime):
            value = value.strftime("%Y-%m-%d")
        elif isinstance(value, (dict, list)):
            value = json.dumps(value, default=str)
        parts.append(f"{key} {value}")
    return " ".join(parts)


def _overlap(query: str, node: dict[str, Any]) -> int:
    blob = " ".join(
        [
            str(node.get("name") or ""),
            str(node.get("summary") or ""),
            str(node.get("search_text") or ""),
            " ".join(str(i) for i in ((node.get("source") or {}).get("document_ids") or [])),
        ]
    ).lower()
    return sum(1 for token in _tokens(query) if token in blob)


def _tokens(text: str) -> list[str]:
    return [token for token in _TOKEN.findall(text.lower()) if len(token) >= 2]


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_n = math.sqrt(sum(a * a for a in left))
    right_n = math.sqrt(sum(b * b for b in right))
    if left_n == 0 or right_n == 0:
        return 0.0
    return dot / (left_n * right_n)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _forbidden(filt: dict[str, Any]) -> bool:
    blob = json.dumps(filt)
    return "$where" in blob or "$expr" in blob or "$function" in blob


def _matches(doc: dict[str, Any], filt: dict[str, Any]) -> bool:
    for key, expected in filt.items():
        if key == "$and" and isinstance(expected, list):
            if not all(_matches(doc, item) for item in expected if isinstance(item, dict)):
                return False
            continue
        if key.startswith("$"):
            return False
        if not _value_matches(doc.get(key), expected):
            return False
    return True


def _value_matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        for op, raw in expected.items():
            if op == "$in":
                if not any(_eq(actual, item) for item in raw or []):
                    return False
            elif op == "$eq":
                if not _eq(actual, raw):
                    return False
            elif op in {"$gte", "$gt", "$lte", "$lt"}:
                if not _cmp(actual, raw, op):
                    return False
            else:
                return False
        return True
    return _eq(actual, expected)


def _eq(actual: Any, expected: Any) -> bool:
    if isinstance(actual, datetime):
        return _stamp(actual).startswith(str(expected)[:10]) or _stamp(actual) == _stamp(expected)
    return str(actual) == str(expected)


def _cmp(actual: Any, expected: Any, op: str) -> bool:
    left = _stamp(actual)
    right = _stamp(expected)
    if op == "$gte":
        return left >= right
    if op == "$gt":
        return left > right
    if op == "$lte":
        return left <= right
    return left < right


def _stamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    return str(value)
