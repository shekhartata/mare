"""Bounded schema profile from in-memory documents or a Mongo collection."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from app.indexing.signals.masking import normalize_key, type_marker


def profile_from_documents(
    database: str,
    documents: dict[str, list[dict[str, Any]]],
    *,
    sample_size: int = 1000,
) -> dict[str, Any]:
    if sample_size < 1:
        raise ValueError("sample_size must be >= 1")
    collections = []
    for name in sorted(documents):
        rows = list(documents[name])
        sample = rows[:sample_size]
        collections.append(_collection_profile(name, sample, population=len(rows)))
    profile = {
        "version": "1",
        "database": database,
        "sample_size": sample_size,
        "sampling": "prefix",
        "collections": collections,
    }
    profile["fingerprint"] = fingerprint_profile(profile)
    return profile


def fingerprint_profile(profile: dict[str, Any]) -> str:
    body = {
        "database": profile.get("database"),
        "collections": [
            {
                "name": coll.get("name"),
                "fields": [
                    {"path": f.get("path"), "types": list(f.get("types") or [])}
                    for f in (coll.get("fields") or [])
                ],
            }
            for coll in profile.get("collections") or []
        ],
    }
    raw = json.dumps(body, sort_keys=True)
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def field_paths(profile: dict[str, Any], collection: str) -> set[str]:
    for coll in profile.get("collections") or []:
        if coll.get("name") == collection:
            return {str(f.get("path")) for f in coll.get("fields") or []}
    return set()


def collection_names(profile: dict[str, Any]) -> set[str]:
    return {str(c.get("name")) for c in profile.get("collections") or []}


def _collection_profile(
    name: str, sample: list[dict[str, Any]], *, population: int
) -> dict[str, Any]:
    stats: dict[str, dict[str, Any]] = {}
    for doc in sample:
        _walk(doc, "", stats, documents=1)
    fields = []
    for path in sorted(stats):
        item = stats[path]
        fields.append(
            {
                "path": path,
                "types": sorted(item["types"]),
                "presence": round(item["docs"] / len(sample), 4) if sample else 0,
                "denominator": "documents",
                "docs": item["docs"],
            }
        )
    return {
        "name": name,
        "inspected": len(sample),
        "population": population,
        "complete": len(sample) >= population,
        "fields": fields,
    }


def _walk(value: Any, prefix: str, stats: dict[str, dict[str, Any]], *, documents: int) -> None:
    if not isinstance(value, dict):
        return
    for key, item in value.items():
        if key == "_id":
            path = "_id"
        else:
            path = f"{prefix}.{normalize_key(str(key))}" if prefix else normalize_key(str(key))
        bucket = stats.setdefault(path, {"types": set(), "docs": 0})
        bucket["types"].add(type_marker(item) if not isinstance(item, datetime) else "date")
        bucket["docs"] += documents
        if isinstance(item, dict):
            _walk(item, path, stats, documents=documents)
        elif isinstance(item, list) and item and isinstance(item[0], dict):
            _walk(item[0], path + "[]", stats, documents=documents)
