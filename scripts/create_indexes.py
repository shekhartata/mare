#!/usr/bin/env python3
"""Create Atlas Search / Vector Search indexes for MARE and the RAG baseline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.constants import (  # noqa: E402
    AUTO_EMBED_MODEL,
    NAV_LEXICAL_INDEX,
    NAV_NODES,
    NAV_VECTOR_INDEX,
    RAG_CHUNKS,
    RAG_LEXICAL_INDEX,
    RAG_VECTOR_INDEX,
    RAW_COLLECTIONS,
    RAW_LEXICAL_INDEX,
)
from app.llm import get_embedding_model  # noqa: E402
from app.mongo.client import agent_db, ping, rag_db, raw_db  # noqa: E402
from app.search.capabilities import capabilities_or_default, save_capabilities  # noqa: E402
from app.search.indexes import (  # noqa: E402
    create_auto_embed_index,
    create_lexical_index,
    create_manual_vector_index,
    list_index_stats,
    wait_for_indexes,
)


def main() -> None:
    ping()
    settings = get_settings()
    caps = capabilities_or_default()
    nav = agent_db()[NAV_NODES]
    chunks = rag_db()[RAG_CHUNKS]

    create_lexical_index(
        nav,
        NAV_LEXICAL_INDEX,
        extra_fields={
            "node_type": {"type": "token"},
            "parent_id": {"type": "token"},
            "search_text": {"type": "string"},
        },
    )
    create_lexical_index(chunks, RAG_LEXICAL_INDEX, extra_fields={"text": {"type": "string"}})
    for name in RAW_COLLECTIONS:
        create_lexical_index(raw_db()[name], RAW_LEXICAL_INDEX)

    vector_ok = False
    if caps.embedding_path == "atlas_auto" or caps.auto_embed:
        try:
            create_auto_embed_index(nav, NAV_VECTOR_INDEX, "search_text", ["tenant_id", "node_type"])
            create_auto_embed_index(chunks, RAG_VECTOR_INDEX, "text", ["tenant_id", "collection"])
            vector_ok = True
            caps.auto_embed = True
            caps.embedding_path = "atlas_auto"
            caps.embedding_model = AUTO_EMBED_MODEL
        except Exception as exc:
            print(f"autoEmbed failed, falling back to manual vectors: {exc}")
            caps.auto_embed = False
            caps.embedding_path = "manual"

    if not vector_ok:
        embedder = get_embedding_model()
        create_manual_vector_index(
            nav, NAV_VECTOR_INDEX, "embedding", embedder.dimensions, ["tenant_id", "node_type"]
        )
        create_manual_vector_index(
            chunks, RAG_VECTOR_INDEX, "embedding", embedder.dimensions, ["tenant_id", "collection"]
        )
        _backfill_embeddings(nav, "search_text", embedder)
        _backfill_embeddings(chunks, "text", embedder)
        caps.vector_dims = embedder.dimensions

    save_capabilities(caps)

    print("waiting for navigation indexes...")
    print(wait_for_indexes(nav, [NAV_LEXICAL_INDEX, NAV_VECTOR_INDEX], timeout_s=420))
    print("waiting for rag indexes...")
    print(wait_for_indexes(chunks, [RAG_LEXICAL_INDEX, RAG_VECTOR_INDEX], timeout_s=420))
    print(json.dumps({"nav": list_index_stats(nav), "rag": list_index_stats(chunks), "caps": caps.model_dump()}, indent=2, default=str))
    print(f"tenant={settings.tenant_id}")


def _backfill_embeddings(coll, field: str, embedder) -> None:
    docs = list(coll.find({field: {"$exists": True}}, {field: 1}))
    if not docs:
        return
    texts = [d.get(field) or "" for d in docs]
    vectors = embedder.embed(texts)
    for doc, vec in zip(docs, vectors, strict=False):
        coll.update_one({"_id": doc["_id"]}, {"$set": {"embedding": vec}})
    print(f"backfilled {len(docs)} embeddings on {coll.full_name}")


if __name__ == "__main__":
    main()
