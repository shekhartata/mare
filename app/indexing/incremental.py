"""Rebuild only navigation groups (or RAG chunks) touched by changed documents."""

from __future__ import annotations

from collections.abc import Iterable
from time import perf_counter
from typing import Any

from pymongo.collection import Collection
from pymongo.database import Database

from app.baseline.chunker import document_to_chunks
from app.constants import NAV_NODES, RAG_CHUNKS
from app.indexing.hierarchy_builder import build_hierarchy
from app.indexing.topical_grouping import topical_groups_from_docs


def groups_touching_ids(
    nodes: Collection, tenant_id: str, doc_ids: Iterable[str]
) -> list[dict[str, Any]]:
    wanted = list({str(i) for i in doc_ids})
    if not wanted:
        return []
    return list(
        nodes.find(
            {
                "tenant_id": tenant_id,
                "node_type": "group",
                "source.document_ids": {"$in": wanted},
            }
        )
    )


def rebuild_dirty_groups(
    *,
    source: Collection,
    nodes: Collection,
    tenant_id: str,
    changed_ids: list[str],
    target_docs_per_group: int,
    collection_name: str,
) -> dict[str, Any]:
    started = perf_counter()
    dirty = groups_touching_ids(nodes, tenant_id, changed_ids)
    member_ids: set[str] = set(changed_ids)
    for node in dirty:
        member_ids.update(str(x) for x in ((node.get("source") or {}).get("document_ids") or []))
    docs = list(source.find({"_id": {"$in": list(member_ids)}}))
    fresh = topical_groups_from_docs(
        docs,
        tenant_id=tenant_id,
        collection=collection_name,
        target_docs_per_group=target_docs_per_group,
    )
    deleted = 0
    for node in dirty:
        nodes.delete_one({"_id": node["_id"]})
        deleted += 1
    # Full rebuild of just these documents' groups is approximate: we delete dirty
    # nodes and rely on the caller to insert replacement nodes via build_hierarchy
    # on a slice, or we insert fresh group dicts as incomplete nodes.
    elapsed = (perf_counter() - started) * 1000
    return {
        "dirty_groups": len(dirty),
        "docs_considered": len(docs),
        "fresh_groups": len(fresh),
        "nodes_deleted": deleted,
        "elapsed_ms": elapsed,
        "fresh": fresh,
    }


def rebuild_rag_chunks_for_ids(
    *,
    source: Collection,
    chunks: Collection,
    tenant_id: str,
    changed_ids: list[str],
    chunk_size: int,
    chunk_overlap: int,
    collection_name: str,
) -> dict[str, Any]:
    started = perf_counter()
    deleted = chunks.delete_many(
        {"tenant_id": tenant_id, "source_id": {"$in": changed_ids}}
    ).deleted_count
    docs = list(source.find({"_id": {"$in": changed_ids}}))
    batch: list[dict[str, Any]] = []
    for doc in docs:
        batch.extend(document_to_chunks(doc, collection_name, chunk_size, chunk_overlap))
    inserted = 0
    if batch:
        chunks.insert_many(batch)
        inserted = len(batch)
    return {
        "docs_changed": len(changed_ids),
        "chunks_deleted": deleted,
        "chunks_inserted": inserted,
        "elapsed_ms": (perf_counter() - started) * 1000,
        "update_amplification": (inserted / len(changed_ids)) if changed_ids else 0.0,
    }


def full_nav_rebuild(
    *,
    tenant_id: str,
    source_db: str,
    agent_database: str,
    collections: tuple[str, ...],
    grouping_strategy: str,
    target_docs_per_group: int | None,
    extra_match: dict[str, Any] | None,
) -> dict[str, Any]:
    started = perf_counter()
    stats = build_hierarchy(
        tenant_id,
        source_db=source_db,
        collections=collections,
        agent_database=agent_database,
        grouping_strategy=grouping_strategy,
        target_docs_per_group=target_docs_per_group,
        extra_match=extra_match,
    )
    stats["elapsed_ms"] = (perf_counter() - started) * 1000
    return stats


def nav_node_count(db: Database, tenant_id: str) -> int:
    return db[NAV_NODES].count_documents({"tenant_id": tenant_id})


def rag_chunk_count(db: Database, tenant_id: str) -> int:
    return db[RAG_CHUNKS].count_documents({"tenant_id": tenant_id})
