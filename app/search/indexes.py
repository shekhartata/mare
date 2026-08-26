from __future__ import annotations

import time
from typing import Any

from pymongo.collection import Collection
from pymongo.operations import SearchIndexModel

from app.constants import (
    AUTO_EMBED_MODEL,
    NAV_LEXICAL_INDEX,
    NAV_VECTOR_INDEX,
    RAG_LEXICAL_INDEX,
    RAG_VECTOR_INDEX,
    RAW_LEXICAL_INDEX,
)
from app.models.schemas import ClusterCapabilities


def create_lexical_index(
    coll: Collection,
    name: str,
    dynamic: bool = True,
    extra_fields: dict[str, Any] | None = None,
) -> str:
    fields = {
        "tenant_id": {"type": "token"},
        **(extra_fields or {}),
    }
    definition = {"mappings": {"dynamic": dynamic, "fields": fields}}
    return _ensure_search_index(coll, name, definition, index_type="search")


def create_auto_embed_index(
    coll: Collection,
    name: str,
    path: str,
    filter_fields: list[str],
    model: str = AUTO_EMBED_MODEL,
) -> str:
    fields: list[dict[str, Any]] = [
        {"type": "autoEmbed", "path": path, "model": model, "modality": "text"}
    ]
    for f in filter_fields:
        fields.append({"type": "filter", "path": f})
    definition = {"fields": fields}
    return _ensure_search_index(coll, name, definition, index_type="vectorSearch")


def create_manual_vector_index(
    coll: Collection,
    name: str,
    path: str,
    dims: int,
    filter_fields: list[str],
) -> str:
    fields: list[dict[str, Any]] = [
        {
            "type": "vector",
            "path": path,
            "numDimensions": dims,
            "similarity": "cosine",
        }
    ]
    for f in filter_fields:
        fields.append({"type": "filter", "path": f})
    return _ensure_search_index(coll, name, {"fields": fields}, index_type="vectorSearch")


def _ensure_search_index(
    coll: Collection, name: str, definition: dict[str, Any], index_type: str
) -> str:
    existing = {idx.get("name") for idx in coll.list_search_indexes()}
    if name in existing:
        return name
    model = SearchIndexModel(definition=definition, name=name, type=index_type)
    coll.create_search_index(model=model)
    return name


def wait_for_indexes(coll: Collection, names: list[str], timeout_s: int = 300) -> dict[str, str]:
    deadline = time.time() + timeout_s
    status: dict[str, str] = {n: "pending" for n in names}
    while time.time() < deadline:
        found = {idx.get("name"): idx for idx in coll.list_search_indexes()}
        all_ready = True
        for n in names:
            idx = found.get(n)
            if not idx:
                status[n] = "missing"
                all_ready = False
                continue
            st = str(idx.get("status") or idx.get("queryable") or "")
            queryable = bool(idx.get("queryable")) or st.lower() in {"ready", "active", "true"}
            status[n] = "ready" if queryable else str(idx.get("status") or "building")
            if not queryable:
                all_ready = False
        if all_ready:
            return status
        time.sleep(5)
    return status


def list_index_stats(coll: Collection) -> list[dict[str, Any]]:
    out = []
    for idx in coll.list_search_indexes():
        out.append(
            {
                "name": idx.get("name"),
                "type": idx.get("type"),
                "status": idx.get("status"),
                "queryable": idx.get("queryable"),
                "latestDefinition": idx.get("latestDefinition") or idx.get("definition"),
            }
        )
    return out


def probe_capabilities(coll: Collection) -> ClusterCapabilities:
    """Try autoEmbed + $rankFusion on a tiny scratch collection."""
    caps = ClusterCapabilities()
    notes: list[str] = []
    try:
        from app.mongo.client import server_version

        caps.mongo_version = server_version()
    except Exception as exc:
        notes.append(f"version lookup failed: {exc}")

    probe_name = "nav_vector_probe"
    try:
        create_auto_embed_index(coll, probe_name, "search_text", ["tenant_id"])
        caps.auto_embed = True
        caps.embedding_path = "atlas_auto"
        caps.embedding_model = AUTO_EMBED_MODEL
        notes.append("autoEmbed index accepted")
        try:
            coll.drop_search_index(probe_name)
        except Exception:
            pass
    except Exception as exc:
        caps.auto_embed = False
        caps.embedding_path = "manual"
        notes.append(f"autoEmbed unavailable: {exc}")

    try:
        list(coll.aggregate([{"$rankFusion": {"input": {"pipelines": {"a": [{"$limit": 1}]}}}}]))
        caps.rank_fusion = True
        notes.append("rankFusion accepted (unexpected empty coll success)")
    except Exception as exc:
        msg = str(exc).lower()
        if "unrecognized" in msg or "unknown" in msg or "not supported" in msg:
            caps.rank_fusion = False
            notes.append(f"$rankFusion unsupported: {exc}")
        else:
            # Stage is recognized but failed on empty/invalid input — treat as available.
            caps.rank_fusion = True
            notes.append(f"$rankFusion recognized ({exc})")

    caps.hybrid_strategy = "rank_fusion" if caps.rank_fusion else "rrf"
    caps.notes = notes
    return caps
