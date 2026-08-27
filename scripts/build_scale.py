#!/usr/bin/env python3
"""Build MARE navigation + RAG chunks for one scale slice and density."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.baseline.chunker import document_to_chunks  # noqa: E402
from app.constants import (  # noqa: E402
    NAV_LEXICAL_INDEX,
    NAV_NODES,
    NAV_VECTOR_INDEX,
    RAG_CHUNKS,
    RAG_LEXICAL_INDEX,
    RAG_VECTOR_INDEX,
    RAW_LEXICAL_INDEX,
    SCALE_COLLECTION,
    SCALE_RAW_DB,
    SCALE_TENANT,
    scale_agent_db_name,
    scale_rag_db_name,
)
from app.eval.accounting import estimate_embedding_tokens, footprint_report  # noqa: E402
from app.indexing.hierarchy_builder import build_hierarchy  # noqa: E402
from app.mongo.client import get_client, ping  # noqa: E402
from app.search.capabilities import capabilities_or_default  # noqa: E402
from app.search.indexes import (  # noqa: E402
    create_lexical_index,
    ensure_nav_and_rag_indexes,
    wait_for_indexes,
)


def main() -> None:
    n = 10_000
    density = 100
    strategy = "topical"
    chunk_size = 512
    if "--n" in sys.argv:
        n = int(sys.argv[sys.argv.index("--n") + 1])
    if "--density" in sys.argv:
        density = int(sys.argv[sys.argv.index("--density") + 1])
    if "--strategy" in sys.argv:
        strategy = sys.argv[sys.argv.index("--strategy") + 1]
    if "--chunk-size" in sys.argv:
        chunk_size = int(sys.argv[sys.argv.index("--chunk-size") + 1])
    overlap = max(int(chunk_size * 0.10), 0)

    ping()
    client = get_client()
    extra_match = {"seq": {"$lt": n}}
    agent_db_name = scale_agent_db_name(n)
    rag_db_name = scale_rag_db_name(n)
    source = client[SCALE_RAW_DB][SCALE_COLLECTION]

    t0 = time.perf_counter()
    nav_stats = build_hierarchy(
        SCALE_TENANT,
        source_db=SCALE_RAW_DB,
        collections=(SCALE_COLLECTION,),
        agent_database=agent_db_name,
        grouping_strategy=strategy,
        target_docs_per_group=density if strategy == "topical" else None,
        extra_match=extra_match,
    )
    nav_ms = (time.perf_counter() - t0) * 1000

    chunks_coll = client[rag_db_name][RAG_CHUNKS]
    chunks_coll.delete_many({"tenant_id": SCALE_TENANT})
    t1 = time.perf_counter()
    batch: list[dict] = []
    total = 0
    texts: list[str] = []
    for doc in source.find({"tenant_id": SCALE_TENANT, **extra_match}):
        pieces = document_to_chunks(doc, SCALE_COLLECTION, chunk_size, overlap)
        batch.extend(pieces)
        texts.extend(p["text"] for p in pieces)
        if len(batch) >= 400:
            chunks_coll.insert_many(batch)
            total += len(batch)
            batch = []
    if batch:
        chunks_coll.insert_many(batch)
        total += len(batch)
    rag_ms = (time.perf_counter() - t1) * 1000

    create_lexical_index(source, RAW_LEXICAL_INDEX)
    caps = capabilities_or_default()
    nav = client[agent_db_name][NAV_NODES]
    idx = ensure_nav_and_rag_indexes(nav, chunks_coll, auto_embed=caps.auto_embed)
    t2 = time.perf_counter()
    nav_ready = wait_for_indexes(nav, [NAV_LEXICAL_INDEX, NAV_VECTOR_INDEX], timeout_s=900)
    rag_ready = wait_for_indexes(chunks_coll, [RAG_LEXICAL_INDEX, RAG_VECTOR_INDEX], timeout_s=900)
    wait_ms = (time.perf_counter() - t2) * 1000

    nav_texts = [d.get("search_text") or "" for d in nav.find({"tenant_id": SCALE_TENANT}, {"search_text": 1})]
    report = {
        "n": n,
        "strategy": strategy,
        "density": density,
        "chunk_size": chunk_size,
        "chunk_overlap": overlap,
        "nav_build": nav_stats,
        "nav_build_ms": round(nav_ms, 1),
        "rag_chunks": total,
        "rag_build_ms": round(rag_ms, 1),
        "index_wait_ms": round(wait_ms, 1),
        "indexes": {"nav": nav_ready, "rag": rag_ready, **idx},
        "embedding_tokens_est": {
            "mare_nav": estimate_embedding_tokens(nav_texts),
            "rag_chunks": estimate_embedding_tokens(texts),
        },
        "footprint": footprint_report(
            agent_db=client[agent_db_name],
            rag_db=client[rag_db_name],
        ),
    }
    out = Path(__file__).resolve().parents[1] / "reports" / "scale" / f"build_{n}_{strategy}_{density}_{chunk_size}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(json.dumps(report, indent=2, default=str))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
