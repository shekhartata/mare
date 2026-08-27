"""Topical navigation groups from document text (never from scoring labels)."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from app.datagen.scale_corpus import FORBIDDEN_GROUPING_FIELDS, TEXT_FIELDS, grouping_projection

TOKEN_RE = re.compile(r"[a-z][a-z0-9]{2,}")
STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "this",
    "that",
    "none",
    "true",
    "false",
    "were",
    "was",
    "are",
    "been",
    "being",
    "have",
    "has",
    "had",
    "not",
    "but",
    "they",
    "their",
    "them",
    "into",
    "onto",
    "over",
    "under",
    "after",
    "before",
    "during",
    "while",
    "also",
    "only",
    "more",
    "than",
    "then",
    "when",
    "what",
    "which",
    "about",
    "record",
    "records",
    "incident",
    "incidents",
    "customer",
    "operators",
    "dashboard",
    "attached",
    "existing",
    "intentionally",
    "narrative",
    "identifiers",
    "metadata",
    "follow",
    "tracked",
    "linked",
    "ticket",
    "queue",
    "enough",
    "natural",
    "language",
    "rather",
    "error",
    "code",
    "noted",
    "overlapping",
    "alerts",
    "backlog",
    "similar",
    "pages",
    "region",
    "shift",
    "secondary",
    "checks",
    "included",
    "recent",
    "config",
    "feature",
    "whether",
    "deploy",
    "landed",
    "hour",
    "symptoms",
    "those",
    "replace",
    "specific",
    "cause",
    "named",
    "resolution",
    "opened",
    "window",
    "confirm",
    "longer",
    "reproduces",
    "confuse",
    "neighboring",
    "failures",
    "mitigation",
    "focused",
    "product",
    "area",
    "related",
    "note",
    "on-call",
    "engineer",
    "captured",
    "timestamps",
    "console",
    "later",
    "reviews",
    "reconstruct",
    "watchers",
    "paged",
    "according",
    "escalation",
    "policy",
    "short",
    "bridge",
    "account",
    "team",
    "identifying",
    "payload",
    "copied",
    "fields",
    "work",
    "write",
    "below",
    "retrieval",
    "rank",
    "against",
    "line",
}


def strip_scoring_fields(doc: dict[str, Any]) -> dict[str, Any]:
    allowed = grouping_projection()
    return {k: v for k, v in doc.items() if k in allowed}


def document_text(doc: dict[str, Any], fields: tuple[str, ...] = TEXT_FIELDS) -> str:
    for forbidden in FORBIDDEN_GROUPING_FIELDS:
        if forbidden in fields:
            raise ValueError(f"grouping cannot read {forbidden}")
    return " ".join(str(doc.get(f) or "") for f in fields)


def tokenize(text: str) -> list[str]:
    return [tok for tok in TOKEN_RE.findall(text.lower()) if tok not in STOPWORDS]


def topical_groups_from_docs(
    docs: Iterable[dict[str, Any]],
    *,
    tenant_id: str,
    collection: str,
    target_docs_per_group: int,
    text_fields: tuple[str, ...] = TEXT_FIELDS,
) -> list[dict[str, Any]]:
    """Cluster documents by TF-IDF signature, then split oversized groups by time."""
    if target_docs_per_group < 1:
        raise ValueError("target_docs_per_group must be >= 1")
    cleaned = [strip_scoring_fields(d) for d in docs]
    tokenized = [tokenize(document_text(d, text_fields)) for d in cleaned]
    idf = _idf(tokenized)
    signatures: list[str] = []
    term_lists: list[list[str]] = []
    for toks in tokenized:
        terms = _top_terms(toks, idf, k=4)
        term_lists.append(terms)
        signatures.append("|".join(terms[:2]) if terms else "misc")

    buckets: dict[str, list[int]] = defaultdict(list)
    for i, sig in enumerate(signatures):
        buckets[sig].append(i)

    groups: list[dict[str, Any]] = []
    for sig, indexes in buckets.items():
        chunks = _split_by_time(
            [cleaned[i] for i in indexes],
            [term_lists[i] for i in indexes],
            target_docs_per_group,
        )
        for part_docs, part_terms, month in chunks:
            groups.append(
                _group_payload(
                    tenant_id=tenant_id,
                    collection=collection,
                    signature=sig,
                    month=month,
                    docs=part_docs,
                    term_lists=part_terms,
                )
            )
    groups.sort(key=lambda g: g["key"])
    return groups


def summarize_topical_group(
    name: str,
    terms: list[str],
    entities: list[str],
    count: int,
    time_min: datetime | None,
    time_max: datetime | None,
) -> str:
    term_s = ", ".join(terms[:12]) or "mixed operational language"
    entity_s = ", ".join(entities[:8]) or "no dominant entity"
    tmin = time_min.isoformat() if isinstance(time_min, datetime) else "unknown"
    tmax = time_max.isoformat() if isinstance(time_max, datetime) else "unknown"
    return (
        f"Neighborhood of {count} incident records about {term_s}. "
        f"Entities: {entity_s}. Time range {tmin} to {tmax}."
    )


def _idf(tokenized: list[list[str]]) -> dict[str, float]:
    df: Counter[str] = Counter()
    for toks in tokenized:
        df.update(set(toks))
    n = max(len(tokenized), 1)
    return {term: math.log((n + 1) / (count + 1)) + 1.0 for term, count in df.items()}


def _top_terms(tokens: list[str], idf: dict[str, float], k: int) -> list[str]:
    if not tokens:
        return []
    tf: Counter[str] = Counter(tokens)
    length = len(tokens)
    scored = [(tf[t] / length) * idf.get(t, 0.0) for t in tf]
    ranked = sorted(tf.keys(), key=lambda t: -(tf[t] / length) * idf.get(t, 0.0))
    _ = scored
    return ranked[:k]


def _split_by_time(
    docs: list[dict[str, Any]],
    term_lists: list[list[str]],
    target: int,
) -> list[tuple[list[dict[str, Any]], list[list[str]], str | None]]:
    if len(docs) <= target:
        return [(docs, term_lists, _month(docs[0].get("timestamp") if docs else None))]
    by_month: dict[str, list[int]] = defaultdict(list)
    for i, doc in enumerate(docs):
        by_month[_month(doc.get("timestamp")) or "unknown"].append(i)
    out: list[tuple[list[dict[str, Any]], list[list[str]], str | None]] = []
    for month, idxs in sorted(by_month.items()):
        part_docs = [docs[i] for i in idxs]
        part_terms = [term_lists[i] for i in idxs]
        if len(part_docs) <= target:
            out.append((part_docs, part_terms, month))
            continue
        # Hash-split leftovers so density stays near the knob.
        shards = max(2, math.ceil(len(part_docs) / target))
        buckets: list[list[int]] = [[] for _ in range(shards)]
        for j, doc in enumerate(part_docs):
            digest = hashlib.md5(str(doc.get("_id")).encode(), usedforsecurity=False)
            buckets[int(digest.hexdigest(), 16) % shards].append(j)
        for shard, members in enumerate(buckets):
            if not members:
                continue
            out.append(
                (
                    [part_docs[i] for i in members],
                    [part_terms[i] for i in members],
                    f"{month}:s{shard}",
                )
            )
    return out


def _month(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m")
    return None


def _group_payload(
    *,
    tenant_id: str,
    collection: str,
    signature: str,
    month: str | None,
    docs: list[dict[str, Any]],
    term_lists: list[list[str]],
) -> dict[str, Any]:
    ids = [str(d["_id"]) for d in docs]
    entities = sorted({str(d.get("customer_id")) for d in docs if d.get("customer_id")})
    times = [d.get("timestamp") for d in docs if isinstance(d.get("timestamp"), datetime)]
    term_counts: Counter[str] = Counter()
    for terms in term_lists:
        term_counts.update(terms)
    representative = [t for t, _ in term_counts.most_common(12)]
    key = f"topic:{signature}"
    if month:
        key = f"{key}:month:{month}"
    filt: dict[str, Any] = {"tenant_id": tenant_id, "_id": {"$in": ids}}
    tmin = min(times) if times else None
    tmax = max(times) if times else None
    name = f"{collection} {signature.replace('|', ' ')}"
    if month:
        name = f"{name} {month}"
    return {
        "key": key,
        "name": name,
        "filter": filt,
        "document_ids": ids,
        "document_count": len(ids),
        "time_min": tmin,
        "time_max": tmax,
        "entities": entities[:20],
        "topics": representative,
        "extra_terms": representative,
        "summary": summarize_topical_group(name, representative, entities, len(ids), tmin, tmax),
    }
