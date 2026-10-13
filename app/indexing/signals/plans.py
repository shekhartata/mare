"""Declarative plans over an allowlist. Parameters come from the question, not from init."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.indexing.signals.contracts import evidence_receipt
from app.indexing.signals.discovery import collection_names, field_paths

_ID_TOKEN = re.compile(r"[A-Za-z]+_[A-Za-z0-9]+")
_WORD = re.compile(r"[a-z]{3,}")
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_STOP = {
    "what",
    "which",
    "when",
    "where",
    "how",
    "many",
    "were",
    "there",
    "any",
    "the",
    "and",
    "for",
}


def compile_plans(profile: dict[str, Any], routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    for name in sorted(collection_names(profile)):
        paths = field_paths(profile, name)
        if "_id" in paths:
            plans.append(_plan("find", name, field="_id"))
        plans.append(_plan("count", name))
        for field in sorted(paths):
            if field == "_id" or field.endswith("_id") or field.endswith("_at"):
                continue
            if "[]" in field or "." in field:
                continue
            plans.append(_plan("find", name, field=field))
    for route in routes:
        if route.get("status") != "validated" or route.get("op") != "hop":
            continue
        plans.append(
            {
                "plan_id": (
                    f"hop:{route['from_collection']}.{route['from_field']}"
                    f"->{route['to_collection']}"
                ),
                "op": "hop",
                "collection": route["from_collection"],
                "field": route["from_field"],
                "to_collection": route["to_collection"],
                "to_field": route.get("to_field") or "_id",
                "exact": False,
                "status": "validated",
            }
        )
    return plans


def investigate(
    index: Any,
    question: str,
) -> dict[str, Any]:
    documents: dict[str, list[dict[str, Any]]] = index.documents
    mentioned = _mentioned(question, documents)
    tokens = _ID_TOKEN.findall(question)
    month = _month_window(question)
    counting = question.lower().startswith("how many")

    if counting and mentioned:
        collection = _primary(mentioned, question)
        rows = _match(documents[collection], tokens, month)
        return _done(
            index,
            plan_id=f"count:{collection}",
            exact=True,
            collections=[collection],
            document_ids=[str(r.get("_id")) for r in rows],
            count=len(rows),
            absence_scope="collection" if not rows else None,
        )

    id_hits = _id_hits(documents, tokens)
    if len(mentioned) > 1 and id_hits:
        hopped = _hop_toward(index, id_hits, mentioned)
        if hopped is not None:
            collection, rows = hopped
            return _done(
                index,
                plan_id=f"hop:{collection}",
                exact=False,
                collections=sorted({hit[0] for hit in id_hits} | {collection}),
                document_ids=[str(r.get("_id")) for r in rows],
                count=len(rows),
                absence_scope=None,
            )
    if id_hits and (not mentioned or any(name in mentioned for name, _doc in id_hits)):
        hits = [item for item in id_hits if not mentioned or item[0] in mentioned] or id_hits
        collection, doc = hits[0]
        return _done(
            index,
            plan_id=f"find:{collection}._id",
            exact=True,
            collections=[collection],
            document_ids=[str(doc.get("_id"))],
            count=1,
            absence_scope=None,
        )

    field_hits = _field_hits(documents, tokens, mentioned)
    if field_hits and not counting:
        collection, rows = field_hits
        return _done(
            index,
            plan_id=f"find:{collection}",
            exact=True,
            collections=[collection],
            document_ids=[str(r.get("_id")) for r in rows],
            count=len(rows),
            absence_scope="collection" if not rows else None,
        )

    hopped = _search_and_hop(index, question, mentioned)
    if hopped is not None:
        collections, rows, plan_id = hopped
        return _done(
            index,
            plan_id=plan_id,
            exact=False,
            collections=collections,
            document_ids=[str(r.get("_id")) for r in rows],
            count=len(rows),
            absence_scope=None,
        )

    return _done(
        index,
        plan_id=None,
        exact=False,
        collections=[],
        document_ids=[],
        count=None,
        absence_scope=None,
        fallback=True,
        warnings=["no validated plan matched; coverage is incomplete"],
    )


def _plan(op: str, collection: str, field: str | None = None) -> dict[str, Any]:
    suffix = f".{field}" if field else ""
    return {
        "plan_id": f"{op}:{collection}{suffix}",
        "op": op,
        "collection": collection,
        "field": field,
        "exact": True,
        "status": "validated",
    }


def _mentioned(question: str, documents: dict[str, list[dict[str, Any]]]) -> set[str]:
    words = set(_WORD.findall(question.lower()))
    found = set()
    for name in documents:
        stem = name.lower().rstrip("s")
        if name.lower() in words or (len(stem) >= 3 and stem in words):
            found.add(name)
    return found


def _primary(mentioned: set[str], question: str) -> str:
    words = question.lower()
    ranked = sorted(mentioned, key=lambda name: (name.lower() not in words, name))
    return ranked[0]


def _month_window(question: str) -> tuple[datetime, datetime] | None:
    match = re.search(
        r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+(20\d\d)",
        question,
        re.I,
    )
    if not match:
        return None
    month = _MONTHS[match.group(1).lower()]
    year = int(match.group(2))
    start = datetime(year, month, 1)
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    return start, end


def _match(
    docs: list[dict[str, Any]],
    tokens: list[str],
    month: tuple[datetime, datetime] | None,
) -> list[dict[str, Any]]:
    wanted = {token.lower() for token in tokens}
    rows = []
    for doc in docs:
        if wanted and not _doc_has_token(doc, wanted):
            continue
        if month and not _in_month(doc, month):
            continue
        rows.append(doc)
    return rows


def _doc_has_token(doc: dict[str, Any], wanted: set[str]) -> bool:
    if str(doc.get("_id") or "").lower() in wanted:
        return True
    for value in doc.values():
        if isinstance(value, str) and value.lower() in wanted:
            return True
    return False


def _in_month(doc: dict[str, Any], window: tuple[datetime, datetime]) -> bool:
    start, end = window
    dates = [value for value in doc.values() if isinstance(value, datetime)]
    if not dates:
        return False
    return any(start <= value < end for value in dates)


def _id_hits(
    documents: dict[str, list[dict[str, Any]]], tokens: list[str]
) -> list[tuple[str, dict[str, Any]]]:
    wanted = {token.lower() for token in tokens}
    hits = []
    for name, docs in documents.items():
        for doc in docs:
            if str(doc.get("_id") or "").lower() in wanted:
                hits.append((name, doc))
    return hits


def _field_hits(
    documents: dict[str, list[dict[str, Any]]],
    tokens: list[str],
    mentioned: set[str],
) -> tuple[str, list[dict[str, Any]]] | None:
    if not tokens:
        return None
    names = mentioned or set(documents)
    for name in sorted(names):
        rows = _match(documents[name], tokens, None)
        wanted = {token.lower() for token in tokens}
        id_only = [row for row in rows if str(row.get("_id")).lower() in wanted]
        if rows and not (len(id_only) == len(rows) and not mentioned):
            return name, rows
    return None


def _hop_toward(
    index: Any,
    id_hits: list[tuple[str, dict[str, Any]]],
    mentioned: set[str],
) -> tuple[str, list[dict[str, Any]]] | None:
    routes = [plan for plan in index.plans if plan.get("op") == "hop"]
    for source, doc in id_hits:
        for plan in routes:
            if plan["collection"] != source or plan["to_collection"] not in mentioned:
                continue
            value = doc.get(plan["field"])
            rows = [
                row
                for row in index.documents[plan["to_collection"]]
                if str(row.get(plan["to_field"])) == str(value)
            ]
            if rows:
                return plan["to_collection"], rows
    return None


def _search_and_hop(
    index: Any, question: str, mentioned: set[str]
) -> tuple[list[str], list[dict[str, Any]], str] | None:
    words = [w for w in _WORD.findall(question.lower()) if w not in _STOP]
    if not words:
        return None
    best_collection = None
    best_score = 0
    best_docs: list[dict[str, Any]] = []
    for collection, groups in index.groups.items():
        for group in groups:
            ids = {str(i) for i in group.get("document_ids") or []}
            docs = [doc for doc in index.documents[collection] if str(doc.get("_id")) in ids]
            text = " ".join(
                [
                    str(group.get("name") or ""),
                    str(group.get("summary") or ""),
                    " ".join(group.get("distinguishing") or []),
                    " ".join(group.get("extra_terms") or []),
                    " ".join(_blob(doc) for doc in docs),
                ]
            ).lower()
            score = sum(1 for word in words if word in text)
            if score <= best_score:
                continue
            narrowed = [doc for doc in docs if any(word in _blob(doc) for word in words)] or docs
            best_score = score
            best_collection = collection
            best_docs = narrowed
    if not best_collection or best_score == 0:
        return None
    for plan in index.plans:
        if plan.get("op") != "hop" or plan["collection"] != best_collection:
            continue
        if mentioned and plan["to_collection"] not in mentioned:
            continue
        found = []
        for doc in best_docs:
            value = doc.get(plan["field"])
            found.extend(
                row
                for row in index.documents[plan["to_collection"]]
                if str(row.get(plan["to_field"])) == str(value)
            )
        if found:
            return [best_collection, plan["to_collection"]], found, plan["plan_id"]
    return [best_collection], best_docs, f"search_cards:{best_collection}"


def _blob(doc: dict[str, Any]) -> str:
    parts = []
    for value in doc.values():
        if isinstance(value, str):
            parts.append(value.lower())
    return " ".join(parts)


def _done(
    index: Any,
    *,
    plan_id: str | None,
    exact: bool,
    collections: list[str],
    document_ids: list[str],
    count: int | None,
    absence_scope: str | None,
    fallback: bool = False,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    receipt = evidence_receipt(
        generation_id=index.generation_id,
        plan_id=plan_id,
        fallback=fallback,
        exact=exact,
        collections_checked=collections,
        document_ids=document_ids,
        count=count,
        absence_scope=absence_scope,
        warnings=warnings,
    )
    index.traces.append(
        {
            "generation_id": index.generation_id,
            "plan_id": plan_id,
            "collections": collections,
            "document_ids": document_ids,
            "exact": exact,
            "fallback": fallback,
        }
    )
    return {"document_ids": document_ids, "count": count, "evidence_receipt": receipt}
