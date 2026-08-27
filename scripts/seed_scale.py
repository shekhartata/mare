#!/usr/bin/env python3
"""Generate and insert the scale corpus. Nested prefixes share one collection (seq)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pymongo import ASCENDING  # noqa: E402

from app.constants import (  # noqa: E402
    SCALE_COLLECTION,
    SCALE_RAW_DB,
    SCALE_TENANT,
)
from app.datagen.scale_corpus import generate_scale_corpus, write_scale_gold  # noqa: E402
from app.mongo.client import get_client, ping  # noqa: E402

GOLD = Path(__file__).resolve().parents[1] / "benchmarks" / "scale" / "gold_queries.json"


def main() -> None:
    n = 10_000
    if "--n" in sys.argv:
        n = int(sys.argv[sys.argv.index("--n") + 1])
    seed = 7
    if "--seed" in sys.argv:
        seed = int(sys.argv[sys.argv.index("--seed") + 1])
    ping()
    bundle = generate_scale_corpus(n, seed=seed, tenant_id=SCALE_TENANT)
    write_scale_gold(bundle["queries"], GOLD)
    client = get_client()
    coll = client[SCALE_RAW_DB][SCALE_COLLECTION]
    if "--replace" in sys.argv:
        coll.delete_many({"tenant_id": SCALE_TENANT})
    else:
        coll.delete_many({"tenant_id": SCALE_TENANT, "seq": {"$lt": n}})
    docs = bundle["documents"]
    for i in range(0, len(docs), 500):
        coll.insert_many(docs[i : i + 500], ordered=False)
        print(f"inserted {min(i + 500, len(docs))}/{len(docs)}")
    coll.create_index([("tenant_id", ASCENDING), ("seq", ASCENDING)])
    coll.create_index([("tenant_id", ASCENDING), ("customer_id", ASCENDING)])
    print(
        json.dumps(
            {
                "n": n,
                "gold_prefix": bundle["gold_prefix"],
                "queries": len(bundle["queries"]),
                "customers": bundle["n_customers"],
                "gold_path": str(GOLD),
                "db": SCALE_RAW_DB,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
