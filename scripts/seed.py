#!/usr/bin/env python3
"""Generate synthetic demo data and write it to mare_demo."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pymongo import ASCENDING, HASHED  # noqa: E402

from app.constants import DEFAULT_TENANT, RAW_COLLECTIONS, RAW_DB  # noqa: E402
from app.datagen.generator import generate, write_gold  # noqa: E402
from app.mongo.client import get_client, ping  # noqa: E402

GOLD_PATH = Path(__file__).resolve().parents[1] / "benchmarks" / "gold.json"


def main() -> None:
    ping()
    bundle = generate(seed=42)
    gold = bundle.pop("gold")
    stories = bundle.pop("stories_meta")
    write_gold(gold, GOLD_PATH)

    client = get_client()
    db = client[RAW_DB]
    for name in RAW_COLLECTIONS:
        db[name].delete_many({"tenant_id": DEFAULT_TENANT})

    for name in RAW_COLLECTIONS:
        docs = bundle[name]
        if not docs:
            continue
        for i in range(0, len(docs), 500):
            db[name].insert_many(docs[i : i + 500], ordered=False)
        print(f"inserted {len(docs)} into {RAW_DB}.{name}")

    _classic_indexes(db)
    print(f"gold queries: {len(gold)} -> {GOLD_PATH}")
    print(f"stories: {len(stories)}")


def _classic_indexes(db) -> None:
    db.customers.create_index([("tenant_id", ASCENDING), ("customer_id", ASCENDING)], unique=True)
    db.tickets.create_index([("tenant_id", ASCENDING), ("customer_id", ASCENDING), ("created_at", ASCENDING)])
    db.deployments.create_index([("tenant_id", ASCENDING), ("customer_id", ASCENDING), ("started_at", ASCENDING)])
    db.migrations.create_index([("tenant_id", ASCENDING), ("customer_id", ASCENDING)])
    db.incidents.create_index([("tenant_id", ASCENDING), ("customer_id", ASCENDING)])
    db.logs.create_index([("tenant_id", ASCENDING), ("customer_id", ASCENDING), ("timestamp", ASCENDING)])
    for name in RAW_COLLECTIONS:
        try:
            db[name].create_index([("tenant_id", HASHED)])
        except Exception:
            pass


if __name__ == "__main__":
    main()
