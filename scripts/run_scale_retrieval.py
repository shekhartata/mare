#!/usr/bin/env python3
"""Equal-budget retrieval eval for one scale slice. No LLM."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.constants import (  # noqa: E402
    NAV_NODES,
    RAG_CHUNKS,
    SCALE_COLLECTION,
    SCALE_RAW_DB,
    SCALE_TENANT,
    scale_agent_db_name,
    scale_rag_db_name,
)
from app.eval.scale_runner import evaluate_queries, load_gold  # noqa: E402
from app.mongo.client import get_client, ping  # noqa: E402

GOLD = Path(__file__).resolve().parents[1] / "benchmarks" / "scale" / "gold_queries.json"


def main() -> None:
    n = 10_000
    budget = 10
    split = "heldout"
    engine = "both"
    if "--n" in sys.argv:
        n = int(sys.argv[sys.argv.index("--n") + 1])
    if "--budget" in sys.argv:
        budget = int(sys.argv[sys.argv.index("--budget") + 1])
    if "--split" in sys.argv:
        split = sys.argv[sys.argv.index("--split") + 1]
    if "--engine" in sys.argv:
        engine = sys.argv[sys.argv.index("--engine") + 1]
    ping()
    queries = load_gold(GOLD, split=None if split == "all" else split)
    client = get_client()
    source = client[SCALE_RAW_DB][SCALE_COLLECTION]
    nodes = client[scale_agent_db_name(n)][NAV_NODES]
    chunks = client[scale_rag_db_name(n)][RAG_CHUNKS]
    payload: dict = {"n": n, "budget": budget, "split": split, "n_queries": len(queries)}
    if engine in {"mare", "both"}:
        payload["mare"] = evaluate_queries(
            queries,
            engine="mare",
            budget=budget,
            tenant_id=SCALE_TENANT,
            nodes=nodes,
            source=source,
        )
    if engine in {"rag", "both"}:
        payload["rag"] = evaluate_queries(
            queries,
            engine="rag",
            budget=budget,
            tenant_id=SCALE_TENANT,
            chunks=chunks,
        )
    out = Path(__file__).resolve().parents[1] / "reports" / "scale" / f"retrieval_{n}_k{budget}_{split}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    # Keep the markdown-friendly summary without per-query dump unless --full.
    summary = {k: v for k, v in payload.items() if k not in {"mare", "rag"}}
    for key in ("mare", "rag"):
        if key in payload:
            blob = dict(payload[key])
            if "--full" not in sys.argv:
                blob.pop("queries", None)
            summary[key] = blob
    out.write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps(summary, indent=2, default=str))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
