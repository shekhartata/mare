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

from app.indexing.signals.nav_vectors import usable_embedder
from app.indexing.signals.store import index_database, upgrade_vectors
from app.llm import get_embedding_model
from app.mongo.client import get_client


def main() -> int:
    parser = argparse.ArgumentParser(description="Save a generic MARE index for one database.")
    parser.add_argument("--database", default="")
    parser.add_argument(
        "--upgrade-vectors",
        action="store_true",
        help="Embed the saved cards without reading the source collections again.",
    )
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
    embedder = usable_embedder(get_embedding_model())
    if args.upgrade_vectors:
        summary = upgrade_vectors(client, embedder)
        if args.database and summary.get("database") != args.database:
            print(f"active index is {summary.get('database')}, not {args.database}")
            return 1
        print(
            f"upgraded {summary['database']}: semantic {summary['semantic']}, "
            f"embedded {summary['embedded']}, reused {summary['reused']}"
        )
        print("Ask with scripts/ask_generic.py, or set MARE_GENERIC_INDEX=true and use POST /ask.")
        return 0
    else:
        if not args.database:
            parser.error("--database is required")
        summary = index_database(
            client,
            args.database,
            limit=args.limit or None,
            collections=args.collection,
            embedder=embedder,
        )
    print(
        f"saved {summary['database']}: {summary['documents']} documents, "
        f"{summary['cards']} cards, {summary.get('plans', 0)} plans, "
        f"semantic {summary.get('semantic', 'unknown')}"
    )
    if "embedded" in summary:
        print(f"navigation vectors embedded {summary['embedded']}, reused {summary['reused']}")
    if summary["partial"]:
        print(
            "partial collections (counts cover the saved ids only): "
            + ", ".join(summary["partial"])
        )
    print("Ask with scripts/ask_generic.py, or set MARE_GENERIC_INDEX=true and use POST /ask.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
