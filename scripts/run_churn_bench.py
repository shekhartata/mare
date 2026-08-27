#!/usr/bin/env python3
"""Churn / update-amplification benchmark for one scale slice."""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.constants import (  # noqa: E402
    NAV_NODES,
    RAG_CHUNKS,
    SCALE_COLLECTION,
    SCALE_RAW_DB,
    SCALE_TENANT,
    scale_agent_db_name,
    scale_rag_db_name,
)
from app.indexing.incremental import (  # noqa: E402
    groups_touching_ids,
    rebuild_rag_chunks_for_ids,
)
from app.mongo.client import get_client, ping  # noqa: E402


def _pick_ids(source, n_docs: int, pct: float, pattern: str, seed: int) -> list[str]:
    rng = random.Random(seed)
    match = {"tenant_id": SCALE_TENANT, "seq": {"$lt": n_docs}}
    if pattern == "clustered":
        # Change every document for a handful of customers.
        customers = source.distinct("customer_id", match)
        rng.shuffle(customers)
        want = max(1, int(n_docs * pct / 100))
        ids: list[str] = []
        for cid in customers:
            batch = [str(d["_id"]) for d in source.find({**match, "customer_id": cid}, {"_id": 1})]
            ids.extend(batch)
            if len(ids) >= want:
                return ids[:want]
        return ids[:want]
    ids = [str(d["_id"]) for d in source.find(match, {"_id": 1})]
    rng.shuffle(ids)
    want = max(1, int(len(ids) * pct / 100))
    return ids[:want]


def main() -> None:
    n = 10_000
    pct = 5.0
    pattern = "scattered"
    density = 100
    if "--n" in sys.argv:
        n = int(sys.argv[sys.argv.index("--n") + 1])
    if "--pct" in sys.argv:
        pct = float(sys.argv[sys.argv.index("--pct") + 1])
    if "--pattern" in sys.argv:
        pattern = sys.argv[sys.argv.index("--pattern") + 1]
    if "--density" in sys.argv:
        density = int(sys.argv[sys.argv.index("--density") + 1])
    ping()
    settings = get_settings()
    client = get_client()
    source = client[SCALE_RAW_DB][SCALE_COLLECTION]
    nodes = client[scale_agent_db_name(n)][NAV_NODES]
    chunks = client[scale_rag_db_name(n)][RAG_CHUNKS]
    changed = _pick_ids(source, n, pct, pattern, seed=11)
    dirty = groups_touching_ids(nodes, SCALE_TENANT, changed)
    rag = rebuild_rag_chunks_for_ids(
        source=source,
        chunks=chunks,
        tenant_id=SCALE_TENANT,
        changed_ids=changed,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        collection_name=SCALE_COLLECTION,
    )
    mare_amp = (len(dirty) / len(changed)) if changed else 0.0
    report = {
        "n": n,
        "pct": pct,
        "pattern": pattern,
        "density": density,
        "docs_changed": len(changed),
        "mare": {
            "vectors_invalidated": len(dirty),
            "vectors_regenerated": len(dirty),
            "update_amplification": round(mare_amp, 4),
            "note": "Incremental rewrite of dirty group nodes; not a full hierarchy rebuild.",
        },
        "rag": {
            "vectors_invalidated": rag["chunks_deleted"],
            "vectors_regenerated": rag["chunks_inserted"],
            "update_amplification": round(rag["update_amplification"], 4),
            "elapsed_ms": rag["elapsed_ms"],
        },
    }
    out = (
        Path(__file__).resolve().parents[1]
        / "reports"
        / "scale"
        / f"churn_{n}_{pattern}_{int(pct)}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(json.dumps(report, indent=2, default=str))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
