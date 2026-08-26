#!/usr/bin/env python3
"""Chunk raw mare_demo documents into _rag_baseline.chunks for the conventional RAG path."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.baseline.chunker import document_to_chunks  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.constants import DEFAULT_TENANT, RAG_CHUNKS, RAW_COLLECTIONS  # noqa: E402
from app.mongo.client import ping, rag_db, raw_db  # noqa: E402


def main() -> None:
    ping()
    settings = get_settings()
    chunks_coll = rag_db()[RAG_CHUNKS]
    chunks_coll.delete_many({"tenant_id": DEFAULT_TENANT})
    total = 0
    for name in RAW_COLLECTIONS:
        batch: list[dict] = []
        for doc in raw_db()[name].find({"tenant_id": DEFAULT_TENANT}):
            batch.extend(
                document_to_chunks(doc, name, settings.chunk_size, settings.chunk_overlap)
            )
            if len(batch) >= 400:
                chunks_coll.insert_many(batch)
                total += len(batch)
                batch = []
        if batch:
            chunks_coll.insert_many(batch)
            total += len(batch)
        print(f"chunked {name}")
    print(json.dumps({"chunks": total, "chunk_size": settings.chunk_size}, indent=2))


if __name__ == "__main__":
    main()
