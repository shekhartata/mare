#!/usr/bin/env python3
"""Run gold queries through adaptive retrieval and conventional RAG; write a comparison report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.baseline.rag import run_rag, vector_counts  # noqa: E402
from app.mongo.client import ping  # noqa: E402
from app.retrieval.agent_loop import run_agent  # noqa: E402
from app.search.indexes import list_index_stats  # noqa: E402
from app.constants import NAV_NODES, RAG_CHUNKS  # noqa: E402
from app.mongo.client import agent_db, rag_db  # noqa: E402

GOLD = Path(__file__).resolve().parents[1] / "benchmarks" / "gold.json"
OUT_DIR = Path(__file__).resolve().parents[1] / "benchmarks" / "results"


def _source_key(database: str, collection: str, document_id: str) -> str:
    return f"{collection}:{document_id}"


def evidence_scores(citations: list[dict], gold_sources: list[dict]) -> dict[str, float]:
    gold = {_source_key(s["database"], s["collection"], s["document_id"]) for s in gold_sources}
    got = {_source_key("", c.get("collection", ""), c.get("document_id", "")) for c in citations}
    got |= {_source_key("", c.get("collection", ""), c.get("document_id", "")) for c in citations}
    if not gold:
        return {"recall": 0.0, "precision": 0.0, "hit": 0}
    hit = gold & got
    recall = len(hit) / len(gold)
    precision = len(hit) / len(got) if got else 0.0
    return {"recall": round(recall, 3), "precision": round(precision, 3), "hit": len(hit), "gold": len(gold)}


def estimate_index_bytes(vector_count: int, dims: int = 1024) -> int:
    return vector_count * dims * 4


def main() -> None:
    ping()
    only = None
    if "--class" in sys.argv:
        only = sys.argv[sys.argv.index("--class") + 1]
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    gold = json.loads(GOLD.read_text())["queries"]
    if only:
        gold = [q for q in gold if q["class"] == only]
    if limit:
        gold = gold[:limit]

    rows = []
    for q in gold:
        print(f"adaptive: {q['id']}")
        adaptive = run_agent(q["question"])
        print(f"rag: {q['id']}")
        rag = run_rag(q["question"])
        a_cites = [c.model_dump() for c in adaptive.citations]
        r_cites = [c.model_dump() for c in rag.citations]
        rows.append(
            {
                "id": q["id"],
                "class": q["class"],
                "question": q["question"],
                "gold_answer": q["gold_answer"],
                "adaptive": {
                    "answer": adaptive.answer,
                    "status": adaptive.status.value,
                    "stop_reason": adaptive.stop_reason,
                    "hypothesis": adaptive.hypothesis,
                    "elapsed_ms": adaptive.elapsed_ms,
                    "tokens": adaptive.tokens_consumed,
                    "retrievals": adaptive.retrieval_count,
                    "agent_turns": adaptive.agent_turns,
                    "tool_calls": adaptive.tool_calls,
                    "llm_latency_ms": adaptive.llm_latency_ms,
                    "mongo_latency_ms": adaptive.mongo_latency_ms,
                    "citations": a_cites,
                    "evidence": evidence_scores(a_cites, q["gold_sources"]),
                },
                "rag": {
                    "answer": rag.answer,
                    "elapsed_ms": rag.elapsed_ms,
                    "tokens": rag.tokens_consumed,
                    "retrievals": rag.retrieval_count,
                    "citations": r_cites,
                    "evidence": evidence_scores(r_cites, q["gold_sources"]),
                },
            }
        )

    footprint = vector_counts()
    dims = 1024
    footprint["adaptive_index_size_bytes_est"] = estimate_index_bytes(footprint["adaptive_vector_count"], dims)
    footprint["rag_index_size_bytes_est"] = estimate_index_bytes(footprint["rag_vector_count"], dims)
    footprint["adaptive_index_over_rag"] = (
        round(footprint["adaptive_index_size_bytes_est"] / footprint["rag_index_size_bytes_est"], 4)
        if footprint["rag_index_size_bytes_est"]
        else 0
    )
    footprint["nav_indexes"] = list_index_stats(agent_db()[NAV_NODES])
    footprint["rag_indexes"] = list_index_stats(rag_db()[RAG_CHUNKS])

    summary = {
        "n": len(rows),
        "adaptive_mean_recall": _mean(rows, "adaptive"),
        "rag_mean_recall": _mean(rows, "rag"),
        "adaptive_mean_latency_ms": _mean_num(rows, "adaptive", "elapsed_ms"),
        "rag_mean_latency_ms": _mean_num(rows, "rag", "elapsed_ms"),
        "adaptive_mean_tokens": _mean_num(rows, "adaptive", "tokens"),
        "rag_mean_tokens": _mean_num(rows, "rag", "tokens"),
        "vector_footprint": footprint,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"summary": summary, "queries": rows}
    (OUT_DIR / "latest.json").write_text(json.dumps(payload, indent=2, default=str) + "\n")
    (OUT_DIR / "latest.md").write_text(_markdown(summary, rows), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))
    print(f"wrote {OUT_DIR / 'latest.md'}")


def _mean(rows, engine: str) -> float:
    vals = [r[engine]["evidence"]["recall"] for r in rows]
    return round(sum(vals) / len(vals), 3) if vals else 0.0


def _mean_num(rows, engine: str, field: str) -> float:
    vals = [float(r[engine][field] or 0) for r in rows]
    return round(sum(vals) / len(vals), 1) if vals else 0.0


def _markdown(summary: dict, rows: list[dict]) -> str:
    fp = summary["vector_footprint"]
    lines = [
        "# MARE vs conventional RAG",
        "",
        "MongoDB stays the system of record, navigation index, search system, and evidence store.",
        "",
        "## Vector footprint (primary product metric)",
        "",
        f"- adaptive_vector_count: **{fp['adaptive_vector_count']}**",
        f"- rag_vector_count: **{fp['rag_vector_count']}**",
        f"- adaptive / rag vectors: **{fp['adaptive_over_rag']}**",
        f"- estimated adaptive index bytes: {fp['adaptive_index_size_bytes_est']}",
        f"- estimated rag index bytes: {fp['rag_index_size_bytes_est']}",
        f"- adaptive / rag index size: **{fp['adaptive_index_over_rag']}**",
        "",
        "## Quality / cost",
        "",
        f"- mean evidence recall (adaptive): {summary['adaptive_mean_recall']}",
        f"- mean evidence recall (rag): {summary['rag_mean_recall']}",
        f"- mean latency ms (adaptive): {summary['adaptive_mean_latency_ms']}",
        f"- mean latency ms (rag): {summary['rag_mean_latency_ms']}",
        f"- mean tokens (adaptive): {summary['adaptive_mean_tokens']}",
        f"- mean tokens (rag): {summary['rag_mean_tokens']}",
        "",
        "## Per query",
        "",
        "| id | class | adaptive recall | rag recall | adaptive ms | rag ms |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['class']} | {r['adaptive']['evidence']['recall']} | "
            f"{r['rag']['evidence']['recall']} | {round(r['adaptive']['elapsed_ms'])} | "
            f"{round(r['rag']['elapsed_ms'])} |"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
