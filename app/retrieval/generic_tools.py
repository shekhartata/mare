"""Same MARE tool names over a generic index. No tenant injection.

Pass a reader to fetch live Mongo documents. Without one, the index's
in-memory documents are used.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
from datetime import datetime
from typing import Any

from app.indexing.signals.nav_nodes import build_nav_nodes
from app.retrieval.serialize import doc_to_retrieved, doc_to_text
from app.retrieval.tool_policy import (
    ToolHandlers,
    ToolPolicy,
    validate_query,
    validate_retrieve,
    validate_search,
)

_TOKEN = re.compile(r"[a-z0-9_]+")
_NAMED_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{3,}")
_SUMMARY = 480
_DOC_CHARS = 1400
MEMBER_PREFETCH_LIMIT = 200


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
        self.last_timing: dict[str, int] = {}
        self._fetch_ms = 0.0
        self._fetch_docs = 0
        self._fetch_ids = 0
        self._embed_ms = 0.0
        self.question = ""
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
        self._begin_timing()
        cap = max(1, min(int(limit or 8), 8))
        pool = self._scoped(scope)
        ranked = self._rank(query, pool)
        hits = ranked[:cap]
        if not hits:
            hits = [node for node in pool if node["node_type"] == "collection"][:cap]
        results = [_brief(node) for node in hits]
        documents = self._documents_named_in(self._focus(query), cap)
        related = self._related([*hits, *_origins_for(documents)], query)
        self._finish_timing()
        payload: dict[str, Any] = {
            "method": mode or "hybrid",
            "count": len(results),
        }
        if documents:
            payload["documents"] = documents
        payload["results"] = results
        payload["related_nodes"] = related
        payload["index_status"] = dict(self.semantic)
        return payload

    def retrieve_evidence(
        self,
        node_ids: list[str],
        *,
        tenant_id: str | None = None,
        query: str | None = None,
        max_documents: int | None = None,
    ) -> dict[str, Any]:
        del tenant_id
        self._begin_timing()
        cap = max(1, min(int(max_documents or 8), 20))
        documents: list[dict[str, Any]] = []
        missing: list[str] = []
        hints: list[dict[str, Any]] = []
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
            id_list = list((node.get("source") or {}).get("document_ids") or [])
            named = _member_ids_named(id_list, self._focus(query or ""))
            if len(id_list) > MEMBER_PREFETCH_LIMIT and named:
                self._collect_named(
                    node, named[:cap], documents, seen, origins, self._focus(query or ""), cap
                )
                if len(documents) >= cap:
                    break
                continue
            if len(id_list) > MEMBER_PREFETCH_LIMIT:
                hints.append(
                    {
                        "node_id": node_id,
                        "document_count": len(id_list),
                        "hint": (
                            f"card has {len(id_list)} documents; "
                            "use query_documents with a filter"
                        ),
                    }
                )
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
        related = self._related(origins, query or "")
        self._finish_timing()
        return {
            "count": len(documents),
            "documents": documents,
            "missing_nodes": missing,
            "hints": hints,
            "related_nodes": related,
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
        self._begin_timing()
        filt = _as_dict(filter)
        if _forbidden(filt):
            self._finish_timing()
            return {"error": "operator not allowlisted"}
        if "." not in (namespace or ""):
            self._finish_timing()
            return {"error": "namespace must be database.collection"}
        database, collection = namespace.split(".", 1)
        if database != self.index.database or not self._known(collection):
            self._finish_timing()
            return {"error": f"unknown namespace {namespace}"}
        cap = max(1, min(int(limit or 10), 20))
        matched = self._rows(collection, filt=filt, limit=cap)
        docs = [_payload(doc, database, collection, focus=self._focus()) for doc in matched]
        related = (
            self._related(
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
            else []
        )
        self._finish_timing()
        return {
            "count": len(docs),
            "namespace": namespace,
            "documents": docs,
            "related_nodes": related,
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
        if not document_ids or len(document_ids) > MEMBER_PREFETCH_LIMIT:
            return []
        return self._rows(collection, ids=document_ids)

    def _documents_named_in(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Point-read ids the question names, from every collection that contains them."""
        named = _ids_named_in_query(query)
        if not named or limit < 1:
            return []
        picks: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str]] = set()
        for node in self.nodes:
            source = node.get("source") or {}
            collection = str(source.get("collection") or "")
            database = str(source.get("database") or self.index.database)
            if not collection:
                continue
            for doc_id in source.get("document_ids") or []:
                text = str(doc_id)
                key = (collection, text)
                if text.lower() not in named or key in seen:
                    continue
                seen.add(key)
                picks.append((database, collection, text))
                if len(picks) >= limit:
                    break
            if len(picks) >= limit:
                break
        grouped: dict[tuple[str, str], list[str]] = {}
        for database, collection, text in picks:
            grouped.setdefault((database, collection), []).append(text)
        documents: list[dict[str, Any]] = []
        for (database, collection), ids in grouped.items():
            for doc in self._rows(collection, ids=ids):
                documents.append(_payload(doc, database, collection, focus=self._focus(query)))
                if len(documents) >= limit:
                    return documents
        return documents

    def _collect_named(
        self,
        node: dict[str, Any],
        ids: list[Any],
        documents: list[dict[str, Any]],
        seen: set[str],
        origins: list[dict[str, Any]],
        focus: str,
        cap: int,
    ) -> None:
        source = node.get("source") or {}
        collection = str(source.get("collection") or "")
        database = str(source.get("database") or self.index.database)
        if not collection or not ids:
            return
        added: list[str] = []
        for doc in self._rows(collection, ids=list(ids)):
            payload = _payload(doc, database, collection, focus=focus)
            key = f"{payload['ref']['collection']}:{payload['ref']['document_id']}"
            if key in seen:
                continue
            seen.add(key)
            documents.append(payload)
            added.append(str(payload["ref"]["document_id"]))
            if len(documents) >= cap:
                break
        if added:
            origins.append({"source": {"collection": collection, "document_ids": added}})

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

    def _focus(self, query: str = "") -> str:
        parts = [str(self.question or ""), str(query or "")]
        return "\n".join(part for part in parts if part)

    def _begin_timing(self) -> None:
        self._fetch_ms = 0.0
        self._fetch_docs = 0
        self._fetch_ids = 0
        self._embed_ms = 0.0
        self.last_timing = {}

    def _finish_timing(self) -> None:
        self.last_timing = {
            "embed_ms": round(self._embed_ms),
            "fetch_ms": round(self._fetch_ms),
            "fetch_docs": self._fetch_docs,
            "fetch_ids": self._fetch_ids,
        }

    def _rows(
        self,
        collection: str,
        *,
        ids: list[Any] | None = None,
        filt: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if self._reader is not None:
            started = time.perf_counter()
            rows = self._reader.fetch(collection, ids=ids, filt=filt, limit=limit)
        else:
            started = time.perf_counter()
            rows = list(self.index.documents.get(collection) or [])
            if ids:
                wanted = {str(i) for i in ids}
                rows = [doc for doc in rows if str(doc.get("_id")) in wanted]
            if filt:
                rows = [doc for doc in rows if _matches(doc, filt)]
            if limit is not None:
                rows = rows[: int(limit)]
        self._fetch_ms += (time.perf_counter() - started) * 1000
        self._fetch_docs += len(rows)
        self._fetch_ids += len(ids or [])
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
                started = time.perf_counter()
                try:
                    embedded = self._embedder.embed([query])
                except Exception:
                    embedded = []
                else:
                    self.embed_calls["queries"] += 1
                self._embed_ms += (time.perf_counter() - started) * 1000
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
        if len(id_list) > MEMBER_PREFETCH_LIMIT:
            return []
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
        focused = self._focus(query)
        return [_payload(doc, database, collection, focus=focused) for doc in rows[:limit]]


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
            "document_ids": list(source.get("document_ids") or [])[:8],
        },
        "document_count": (node.get("metadata") or {}).get("document_count"),
        "important_fields": list((node.get("schema") or {}).get("important_fields") or [])[:12],
        "children_preview": [],
    }


def _payload(
    doc: dict[str, Any], database: str, collection: str, *, focus: str = ""
) -> dict[str, Any]:
    retrieved = doc_to_retrieved(doc, database, collection)
    return {
        "ref": retrieved.ref.model_dump(),
        "text": doc_to_text(doc, max_chars=_DOC_CHARS, focus=focus),
        "score": retrieved.score,
    }


def _origins_for(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[str]] = {}
    for doc in documents:
        ref = doc.get("ref") or {}
        collection = str(ref.get("collection") or "")
        doc_id = str(ref.get("document_id") or "")
        if collection and doc_id:
            grouped.setdefault(collection, []).append(doc_id)
    return [
        {"source": {"collection": collection, "document_ids": ids}}
        for collection, ids in grouped.items()
    ]


def _ids_named_in_query(query: str) -> set[str]:
    named: set[str] = set()
    for match in _NAMED_ID.finditer(query or ""):
        token = match.group(0)
        if any(character.isdigit() for character in token):
            named.add(token.lower())
    return named


def _member_ids_named(document_ids: list[Any], query: str) -> list[Any]:
    named = _ids_named_in_query(query)
    if not named:
        return []
    return [doc_id for doc_id in document_ids if str(doc_id).lower() in named]


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
