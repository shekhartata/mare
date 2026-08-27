"""Index footprint and embedding-cost estimates."""

from __future__ import annotations

from typing import Any

from pymongo.database import Database

from app.constants import DEFAULT_VECTOR_DIMS, NAV_NODES, RAG_CHUNKS


def estimate_embedding_tokens(texts: list[str]) -> int:
    return sum(max(len(t), 0) for t in texts) // 4


def vector_index_bytes_est(n_vectors: int, dims: int = DEFAULT_VECTOR_DIMS) -> int:
    return int(n_vectors) * int(dims) * 4


def collection_storage(db: Database, name: str) -> dict[str, Any]:
    try:
        stats = db.command("collstats", name)
    except Exception as exc:
        return {"error": str(exc), "name": name}
    return {
        "name": name,
        "count": stats.get("count"),
        "size": stats.get("size"),
        "storageSize": stats.get("storageSize"),
        "totalIndexSize": stats.get("totalIndexSize"),
        "avgObjSize": stats.get("avgObjSize"),
    }


def footprint_report(
    *,
    agent_db: Database,
    rag_db: Database,
    dims: int = DEFAULT_VECTOR_DIMS,
) -> dict[str, Any]:
    nav = agent_db[NAV_NODES]
    chunks = rag_db[RAG_CHUNKS]
    nav_n = nav.estimated_document_count()
    rag_n = chunks.estimated_document_count()
    return {
        "mare_persistent_vectors": nav_n,
        "rag_persistent_vectors": rag_n,
        "vector_ratio": round((nav_n / rag_n), 4) if rag_n else None,
        "mare_index_bytes_est": vector_index_bytes_est(nav_n, dims),
        "rag_index_bytes_est": vector_index_bytes_est(rag_n, dims),
        "index_bytes_ratio_est": round(
            vector_index_bytes_est(nav_n, dims) / vector_index_bytes_est(rag_n, dims), 4
        )
        if rag_n
        else None,
        "nav_storage": collection_storage(agent_db, NAV_NODES),
        "rag_storage": collection_storage(rag_db, RAG_CHUNKS),
        "note": (
            "index_bytes_est is vectors × dims × 4 bytes (unquantized). "
            "storageSize is measured collection bytes, not Atlas vector-index bytes."
        ),
    }
