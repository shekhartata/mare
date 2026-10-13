#!/usr/bin/env python3
"""Index one MongoDB database and save the navigation cards for later asks.

Source documents stay in place. Cards and hops are written to _agent_retrieval.
A later process loads them with scripts/ask_generic.py, POST /ask, or MCP.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.indexing.signals import build_generic_index
from app.indexing.signals.store import read_source, save_generic_index
from app.mongo.client import get_client


def main() -> int:
    parser = argparse.ArgumentParser(description="Save a generic MARE index for one database.")
    parser.add_argument("--database", required=True)
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max documents per collection. 0 reads the whole collection.",
    )
    parser.add_argument(
        "--collection",
        action="append",
        default=None,
        help="Index only this collection. Repeat to name more than one.",
    )
    args = parser.parse_args()
    client = get_client()
    database = client[args.database]
    names = args.collection or [
        name
        for name in sorted(database.list_collection_names())
        if not name.startswith("system.")
    ]
    documents, scope = read_source(database, names, args.limit or None)
    index = build_generic_index(
        documents,
        database=args.database,
        sample_size=get_settings().generic_sample_size,
        use_cache=False,
    )
    save_generic_index(client, index, scope)
    count = sum(len(rows) for rows in documents.values())
    partial = [name for name, entry in scope.items() if not entry.get("complete")]
    print(
        f"saved {args.database}: {count} documents, {len(index.cards)} cards, "
        f"{len(index.plans)} plans"
    )
    if partial:
        print("partial collections (counts cover the saved ids only): " + ", ".join(partial))
    print("Ask with scripts/ask_generic.py, or set MARE_GENERIC_INDEX=true and use POST /ask.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
