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

from app.indexing.signals.store import index_database
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
    summary = index_database(
        client,
        args.database,
        limit=args.limit or None,
        collections=args.collection,
    )
    print(
        f"saved {summary['database']}: {summary['documents']} documents, "
        f"{summary['cards']} cards, {summary['plans']} plans"
    )
    if summary["partial"]:
        print(
            "partial collections (counts cover the saved ids only): "
            + ", ".join(summary["partial"])
        )
    print("Ask with scripts/ask_generic.py, or set MARE_GENERIC_INDEX=true and use POST /ask.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
