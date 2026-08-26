#!/usr/bin/env python3
"""Probe Atlas for Automated Embedding and $rankFusion; persist capabilities."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.constants import AGENT_DB, NAV_NODES  # noqa: E402
from app.mongo.client import agent_db, ping, server_version  # noqa: E402
from app.search.capabilities import save_capabilities  # noqa: E402
from app.search.indexes import probe_capabilities  # noqa: E402


def main() -> None:
    ping()
    print(f"mongo version: {server_version()}")
    coll = agent_db()[NAV_NODES]
    # Ensure collection exists
    agent_db()[NAV_NODES].insert_one({"_id": "__probe__", "search_text": "probe", "tenant_id": "demo"})
    try:
        caps = probe_capabilities(coll)
    finally:
        agent_db()[NAV_NODES].delete_one({"_id": "__probe__"})
    save_capabilities(caps)
    print(json.dumps(caps.model_dump(), indent=2))
    print(f"saved to {AGENT_DB}.config")


if __name__ == "__main__":
    main()
