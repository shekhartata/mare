#!/usr/bin/env python3
"""Ask a question against the generic index saved by scripts/index_generic.py."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm import get_embedding_model
from app.mongo.client import get_client
from app.retrieval.generic_ask import run_saved_generic


def main() -> int:
    parser = argparse.ArgumentParser(description="Query the saved generic MARE index.")
    parser.add_argument("question")
    args = parser.parse_args()
    session, timing = run_saved_generic(get_client(), args.question, get_embedding_model())
    print(session.answer)
    status = timing["index_status"]
    print(f"{timing['request_ms']} ms (load {timing['load_ms']} ms), index {status.get('status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
