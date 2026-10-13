#!/usr/bin/env python3
"""Ask a question against the generic index saved by scripts/index_generic.py."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.indexing.signals.store import load_generic_handlers
from app.llm import get_embedding_model
from app.mongo.client import get_client
from app.retrieval.agent_loop import run_agent


def main() -> int:
    parser = argparse.ArgumentParser(description="Query the saved generic MARE index.")
    parser.add_argument("question")
    args = parser.parse_args()
    session = run_agent(
        args.question,
        handlers=load_generic_handlers(get_client(), get_embedding_model()),
        persist=False,
        schema_in_prompt=False,
    )
    print(session.answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
