#!/usr/bin/env python3
"""Time a fixed question set against the saved generic index on the configured cluster.

Each question lists values the answer must contain. The script prints one line per
question and can write the full rows to JSON for before/after comparisons.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm import get_embedding_model
from app.mongo.client import get_client
from app.retrieval.generic_ask import run_saved_generic

QUESTIONS: list[dict] = [
    {
        "id": "loan_purpose",
        "question": (
            "What loan purpose is on the loan instance that the automated underwriting "
            "system response message points to?"
        ),
        "expect": ["Purchase"],
    },
    {
        "id": "underwriter",
        "question": (
            "What was the desktop underwriter recommendation on loan instance "
            "415c5349-d293-5e99-9e29-34949c4b8c54, and what purchase price and combined "
            "loan amount are on it?"
        ),
        "expect": ["APPROVE", "325", "305"],
    },
    {
        "id": "quote_payload",
        "question": (
            "Which raw payload did quote 5ce9fcf5-f832-43c0-9c2a-238858e3cbbe send, and "
            "which loan does that quote belong to?"
        ),
        "expect": ["6a7324183bb27cbb2f124d63", "00025c69-cda4-4fc3-bcba-86070a183376"],
    },
    {
        "id": "order_loan",
        "question": "Which loan does order 74546ada-e44f-4a47-9d71-eb9cab75f6a5 point to?",
        "expect": ["00030289-54c4-4d6d-bd44-f5de34ab5984"],
    },
    {
        "id": "event_loan",
        "question": (
            "What is the event type on event transaction 6ac3f1d8b66fb1d370c18719, and "
            "which loan does its loan instance point to?"
        ),
        "expect": ["Received", "5cb913ab-9991-48b2-95e4-5142bd86a9bd"],
    },
    {
        "id": "partner",
        "question": "What is the status and MISMO version of trading partner A0000094?",
        "expect": ["Active", "3.5"],
    },
]


def _found(answer: str, expect: list[str]) -> list[bool]:
    low = answer.lower().replace(",", "")
    return [value.lower().replace(",", "") in low for value in expect]


def _row(case: dict, session, timing: dict, wall_ms: float) -> dict:
    stats = getattr(session, "tool_stats", None) or {}
    steps = list(stats.get("steps") or [])
    tools = [step for step in steps if step.get("kind") == "tool"]
    models = [step for step in steps if step.get("kind") == "model"]
    found = _found(session.answer or "", case["expect"])
    return {
        "id": case["id"],
        "ok": all(found),
        "found": found,
        "total_ms": round(wall_ms),
        "load_ms": timing.get("load_ms"),
        "llm_ms": round(session.llm_latency_ms),
        "mongo_ms": round(session.mongo_latency_ms),
        "turns": session.agent_turns,
        "tool_calls": session.tool_calls,
        "fetch_calls": sum(int(step.get("fetch_calls") or 0) for step in tools),
        "fetch_docs": sum(int(step.get("fetch_docs") or 0) for step in tools),
        "embed_ms": sum(int(step.get("embed_ms") or 0) for step in tools),
        "synthesized": any("synthesize" in (step.get("tools") or []) for step in models),
        "tokens": session.tokens_consumed,
        "status": getattr(session.status, "value", str(session.status)),
        "stop_reason": session.stop_reason,
        "tools": [step.get("name") for step in tools],
        "answer": session.answer,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="*", help="question ids to run")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--out", help="write rows to this JSON file")
    args = parser.parse_args()

    cases = [c for c in QUESTIONS if not args.only or c["id"] in args.only]
    client = get_client()
    embedder = get_embedding_model()
    rows: list[dict] = []
    for round_no in range(args.repeat):
        for case in cases:
            started = time.perf_counter()
            session, timing = run_saved_generic(client, case["question"], embedder)
            row = _row(case, session, timing, (time.perf_counter() - started) * 1000)
            row["round"] = round_no
            rows.append(row)
            print(
                f"{row['id']:<14} {'ok ' if row['ok'] else 'BAD'} {row['total_ms']:>7} ms "
                f"load {row['load_ms']:>6} llm {row['llm_ms']:>6} mongo {row['mongo_ms']:>6} "
                f"turns {row['turns']:>2} fetches {row['fetch_calls']:>3} "
                f"synth {'y' if row['synthesized'] else 'n'} stop {row['stop_reason']}",
                flush=True,
            )
    passed = sum(1 for row in rows if row["ok"])
    mean = sum(row["total_ms"] for row in rows) / max(1, len(rows))
    print(f"passed {passed}/{len(rows)}, mean {round(mean)} ms")
    if args.out:
        Path(args.out).write_text(json.dumps(rows, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
