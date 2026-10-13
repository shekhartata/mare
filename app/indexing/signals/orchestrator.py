"""Build a generic index. The lexical grouper is called unchanged."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.datagen.scale_corpus import TEXT_FIELDS
from app.indexing.search_text import compose_search_text
from app.indexing.semantic_grouping import semantic_groups_from_docs
from app.indexing.signals.contracts import SignalContext
from app.indexing.signals.discovery import fingerprint_profile, profile_from_documents
from app.indexing.signals.generations import ActivationError, GenerationBook
from app.indexing.signals.plans import compile_plans, investigate
from app.indexing.signals.providers import builtin_providers
from app.indexing.signals.registry import clear, register, run_enabled
from app.indexing.signals.text_fields import select_text_fields
from app.indexing.signals.validate import validate_signals

DEFAULT_PROVIDERS = ("schema_profile", "schema_llm", "lexical", "relationship_probe")

_CACHE: dict[str, GenericIndex] = {}
_BOOK = GenerationBook()


@dataclass
class GenericIndex:
    database: str
    profile: dict[str, Any]
    text_fields: dict[str, tuple[str, ...]]
    groups: dict[str, list[dict[str, Any]]]
    cards: list[dict[str, Any]]
    signals: list[dict[str, Any]]
    validation: dict[str, Any]
    plans: list[dict[str, Any]]
    documents: dict[str, list[dict[str, Any]]]
    generation_id: str
    traces: list[dict[str, Any]] = field(default_factory=list)

    def investigate(self, question: str) -> dict[str, Any]:
        return investigate(self, question)


def build_generic_index(
    documents: dict[str, list[dict[str, Any]]],
    *,
    database: str,
    sample_size: int = 1000,
    text_field_overrides: dict[str, tuple[str, ...]] | None = None,
    providers: list[str] | None = None,
    llm: Any | None = None,
    judge: Any | None = None,
    policy: dict[str, Any] | None = None,
    tenant_id: str = "generic",
    use_cache: bool = True,
) -> GenericIndex:
    """Index documents without domain constants.

    `semantic_groups_from_docs` is called as-is. Providers only wrap its group ids.
    """
    policy = dict(policy or {})
    enabled = list(providers or DEFAULT_PROVIDERS)
    profile = profile_from_documents(database, documents, sample_size=sample_size)
    text_fields = select_text_fields(profile, overrides=text_field_overrides)
    cache_key = _cache_key(profile, enabled, text_fields, llm, policy)
    if use_cache and cache_key in _CACHE and not policy.get("force_fail"):
        return _CACHE[cache_key]

    groups: dict[str, list[dict[str, Any]]] = {}
    for name, docs in documents.items():
        fields = text_fields.get(name) or ()
        if not docs or not fields:
            groups[name] = []
            continue
        grouped_docs, grouped_fields = _project_text(docs, fields)
        groups[name] = semantic_groups_from_docs(
            grouped_docs,
            tenant_id=tenant_id,
            collection=name,
            text_fields=grouped_fields,
        )

    _install(enabled)
    context = SignalContext(
        database=database,
        documents=documents,
        profile=profile,
        text_fields=text_fields,
        groups=groups,
        llm=llm,
        judge=judge,
        policy=policy,
    )
    signals = run_enabled(enabled, context)
    validation = validate_signals(profile, signals, judge=judge)
    cards = _cards(database, groups, documents, text_fields)
    plans = compile_plans(profile, validation["routes"])
    valid = not policy.get("force_fail")
    generation_id = _BOOK.stage(fingerprint_profile(profile), valid=valid)
    try:
        _BOOK.activate(generation_id)
    except ActivationError:
        generation_id = _BOOK.active or generation_id
    index = GenericIndex(
        database=database,
        profile=profile,
        text_fields=text_fields,
        groups=groups,
        cards=cards,
        signals=signals,
        validation=validation,
        plans=plans,
        documents=documents,
        generation_id=_BOOK.active or generation_id,
    )
    if valid and use_cache:
        _CACHE[cache_key] = index
    return index


def active_generation() -> str | None:
    return _BOOK.active


def rollback_generation() -> str | None:
    return _BOOK.rollback()


def reset_index_state() -> None:
    _CACHE.clear()
    _BOOK.records.clear()
    _BOOK.active = None
    _BOOK.previous = None
    _BOOK._seq = 0
    clear()


def _project_text(
    docs: list[dict[str, Any]], fields: tuple[str, ...]
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    """Map selected strings onto the fields the existing grouper is allowed to read.

    The TF-IDF function is unchanged. When the selected fields are already in its
    text list, the documents are passed through.
    """
    if set(fields) <= set(TEXT_FIELDS):
        return docs, fields
    projected: list[dict[str, Any]] = []
    for doc in docs:
        shadow = dict(doc)
        chunks = [
            str(doc[field_name])
            for field_name in fields
            if isinstance(doc.get(field_name), str) and doc[field_name]
        ]
        shadow["title"] = chunks[0][:120] if chunks else str(doc.get("title") or "")
        shadow["description"] = " ".join(chunks)
        shadow["resolution"] = str(doc.get("resolution") or "")
        projected.append(shadow)
    return projected, TEXT_FIELDS


def _install(enabled: list[str]) -> None:
    """Register built-ins without dropping providers a caller already registered."""
    known = {provider.name: provider for provider in builtin_providers()}
    for name in enabled:
        if name in known:
            register(known[name])


def _cards(
    database: str,
    groups: dict[str, list[dict[str, Any]]],
    documents: dict[str, list[dict[str, Any]]],
    text_fields: dict[str, tuple[str, ...]],
) -> list[dict[str, Any]]:
    by_id = {
        collection: {str(doc.get("_id")): doc for doc in docs}
        for collection, docs in documents.items()
    }
    cards = []
    for collection, rows in groups.items():
        fields = text_fields.get(collection) or ()
        for group in rows:
            terms = list(group.get("distinguishing") or []) + list(group.get("extra_terms") or [])
            snippets: list[str] = []
            for doc_id in group.get("document_ids") or []:
                doc = by_id.get(collection, {}).get(str(doc_id)) or {}
                for field_name in fields:
                    value = doc.get(field_name)
                    if isinstance(value, str) and value:
                        snippets.append(value)
            cards.append(
                {
                    "key": group.get("key"),
                    "collection": collection,
                    "document_ids": list(group.get("document_ids") or []),
                    "filter": {"_id": {"$in": list(group.get("document_ids") or [])}},
                    "search_text": compose_search_text(
                        name=str(group.get("name") or group.get("key")),
                        database=database,
                        collection=collection,
                        description=" ".join(snippets)[:500],
                        summary=str(group.get("summary") or ""),
                        important_fields=list(fields),
                        entities=list(group.get("entities") or []),
                        topics=terms[:8],
                        representative_terms=terms[:12],
                    ),
                }
            )
    return cards


def _cache_key(
    profile: dict[str, Any],
    enabled: list[str],
    text_fields: dict[str, tuple[str, ...]],
    llm: Any | None,
    policy: dict[str, Any],
) -> str:
    body = {
        "fingerprint": fingerprint_profile(profile),
        "providers": enabled,
        "text_fields": {name: list(fields) for name, fields in text_fields.items()},
        "llm": id(llm) if llm is not None else None,
        "policy": {key: policy[key] for key in sorted(policy) if key != "force_fail"},
    }
    return json.dumps(body, sort_keys=True, default=str)
