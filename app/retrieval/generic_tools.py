"""Same MARE tool names, backed by an in-memory generic index. No tenant injection."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from typing import Any

from app.retrieval.serialize import doc_to_retrieved

_TOKEN = re.compile(r"[a-z0-9_]+")
_SUMMARY = 480
_DOC_CHARS = 1400


class GenericSurface:
    def __init__(self, index: Any, embedder: Any | None = None) -> None:
        self.index = index
        self.nodes = _nodes(index)
        self._by_id = {str(node["_id"]): node for node in self.nodes}
        self._embedder = embedder
        self._vector_by_id: dict[str, list[float]] = {}
        if embedder is not None and self.nodes:
            vectors = embedder.embed([str(node.get("search_text") or "") for node in self.nodes])
            self._vector_by_id = {
                str(node["_id"]): vector for node, vector in zip(self.nodes, vectors, strict=True)
            }

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
        if database != self.index.database or collection not in self.index.documents:
            return {"error": f"unknown namespace {namespace}"}
        cap = max(1, min(int(limit or 10), 20))
        matched = [
            doc
            for doc in self.index.documents[collection]
            if _matches(doc, filt)
        ][:cap]
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
                                    for row in self.index.documents.get(target) or []
                                    if _eq(row.get(to_field), value)
                                ][:8],
                            },
                            "children_preview": [],
                        }
                    )
                    if len(out) >= 6:
                        return out
        return out

    def _members(self, collection: str, document_ids: list[Any]) -> list[dict[str, Any]]:
        wanted = {str(i) for i in document_ids}
        if not wanted:
            return []
        rows = list(self.index.documents.get(collection) or [])
        return [doc for doc in rows if str(doc.get("_id")) in wanted]

    def _hop_docs(self, node_id: str, limit: int) -> list[dict[str, Any]]:
        _prefix, collection, field, value = node_id.split(":", 3)
        rows = [
            doc
            for doc in self.index.documents.get(collection) or []
            if _eq(doc.get(field), value)
        ]
        return [_payload(doc, self.index.database, collection) for doc in rows[:limit]]

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
            query_vec = self._embedder.embed([query])[0]
            order = sorted(
                pool,
                key=lambda node: (
                    -_cosine(query_vec, self._vector_by_id[str(node["_id"])]),
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
        rows = list(self.index.documents.get(collection) or [])
        ids = {str(i) for i in (source.get("document_ids") or [])}
        if ids:
            rows = [doc for doc in rows if str(doc.get("_id")) in ids]
        filt = source.get("filter") or {}
        if filt and filt != {"_id": {"$in": list(source.get("document_ids") or [])}}:
            rows = [doc for doc in rows if _matches(doc, filt)]
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


def generic_handlers(index: Any, embedder: Any | None = None) -> dict[str, Any]:
    return GenericSurface(index, embedder).handlers()


def _nodes(index: Any) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    fields_by_col = {
        str(coll["name"]): [
            str(field["path"])
            for field in coll.get("fields") or []
            if "." not in str(field["path"]) and "[]" not in str(field["path"])
        ]
        for coll in index.profile.get("collections") or []
    }
    for card in index.cards:
        collection = str(card["collection"])
        nodes.append(
            {
                "_id": f"card:{collection}:{card['key']}",
                "name": str(card.get("key")),
                "node_type": "group",
                "summary": str(card.get("search_text") or "")[:_SUMMARY],
                "search_text": str(card.get("search_text") or ""),
                "source": {
                    "database": index.database,
                    "collection": collection,
                    "filter": card.get("filter") or {},
                    "document_ids": list(card.get("document_ids") or []),
                },
                "schema": {"important_fields": fields_by_col.get(collection, [])[:12]},
                "metadata": {"document_count": len(card.get("document_ids") or [])},
            }
        )
    for coll in index.profile.get("collections") or []:
        name = str(coll["name"])
        fields = fields_by_col.get(name, [])
        nodes.append(
            {
                "_id": f"col:{name}",
                "name": name,
                "node_type": "collection",
                "summary": f"Collection {name}. Fields: {', '.join(fields[:12])}.",
                "search_text": " ".join([name, *fields]),
                "source": {
                    "database": index.database,
                    "collection": name,
                    "filter": {},
                    "document_ids": [],
                },
                "schema": {"important_fields": fields[:12]},
                "metadata": {
                    "document_count": coll.get("population") or coll.get("inspected") or 0
                },
            }
        )
    return nodes


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
