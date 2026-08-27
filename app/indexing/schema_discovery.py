from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from pymongo.collection import Collection

from app.config import get_settings

SKIP_FIELDS = {"_id", "tenant_id", "embedding", "topic_id", "tier", "family", "query_lexicon"}


def discover_schema(coll: Collection, sample_size: int | None = None) -> dict[str, Any]:
    settings = get_settings()
    n = sample_size or settings.schema_sample_size
    sample = list(coll.aggregate([{"$sample": {"size": n}}]))
    if not sample:
        sample = list(coll.find({}, limit=n))
    field_types: dict[str, Counter] = defaultdict(Counter)
    field_examples: dict[str, Any] = {}
    timestamps: list[datetime] = []
    entities: set[str] = set()

    for doc in sample:
        _walk(doc, "", field_types, field_examples, timestamps, entities)

    fields = []
    for name, types in sorted(field_types.items(), key=lambda kv: (-sum(kv[1].values()), kv[0])):
        if name.split(".")[0] in SKIP_FIELDS:
            continue
        fields.append(
            {
                "name": name,
                "types": dict(types),
                "example": _stringify(field_examples.get(name)),
            }
        )

    important = [f["name"] for f in fields[:18] if f["name"].count(".") == 0]
    time_min = min(timestamps) if timestamps else None
    time_max = max(timestamps) if timestamps else None
    count = coll.estimated_document_count()
    indexes = [idx.get("name") for idx in coll.list_indexes()]
    grouping_keys = [
        f
        for f in ("customer_id", "region", "severity", "status", "service", "category")
        if any(x["name"] == f for x in fields)
    ]
    representative_terms = _top_terms(sample)

    return {
        "collection": coll.name,
        "database": coll.database.name,
        "document_count": count,
        "sampled": len(sample),
        "fields": fields,
        "important_fields": important,
        "indexes": indexes,
        "time_min": time_min,
        "time_max": time_max,
        "grouping_keys": grouping_keys,
        "representative_terms": representative_terms,
        "entities": sorted(entities)[:40],
    }


def _walk(
    value: Any,
    prefix: str,
    field_types: dict[str, Counter],
    field_examples: dict[str, Any],
    timestamps: list[datetime],
    entities: set[str],
    depth: int = 0,
) -> None:
    if depth > 4 or value is None:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            path = f"{prefix}.{k}" if prefix else k
            field_types[path][type(v).__name__] += 1
            field_examples.setdefault(path, v)
            if isinstance(v, datetime):
                timestamps.append(v)
            if k.endswith("_id") and isinstance(v, str):
                entities.add(v)
            _walk(v, path, field_types, field_examples, timestamps, entities, depth + 1)
    elif isinstance(value, list) and value and depth < 3:
        _walk(value[0], prefix + "[]", field_types, field_examples, timestamps, entities, depth + 1)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value)
    return text[:120]


def _top_terms(docs: list[dict[str, Any]], k: int = 24) -> list[str]:
    counts: Counter[str] = Counter()
    stop = {
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
        "cust",
        "tenant",
    }
    for doc in docs:
        blob = _flatten_text(doc)
        for tok in blob.lower().replace("/", " ").replace("_", " ").split():
            tok = "".join(ch for ch in tok if ch.isalnum())
            if len(tok) < 4 or tok in stop or tok.isdigit():
                continue
            counts[tok] += 1
    return [t for t, _ in counts.most_common(k)]


def _flatten_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten_text(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_text(v) for v in value[:8])
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
