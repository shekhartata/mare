#!/usr/bin/env python3
"""Build the navigation hierarchy over mare_demo without copying raw documents."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.indexing.hierarchy_builder import build_hierarchy  # noqa: E402
from app.mongo.client import ping  # noqa: E402


def main() -> None:
    ping()
    use_llm = "--llm" in sys.argv
    stats = build_hierarchy(use_llm=use_llm)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
