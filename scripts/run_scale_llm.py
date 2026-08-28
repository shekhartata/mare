#!/usr/bin/env python3
"""End-to-end LLM-on MARE vs RAG on the scale corpus. Does not replace LLM-off IR."""

from __future__ import annotations

import json
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.baseline.rag import run_rag  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.constants import (  # noqa: E402
    SCALE_RAW_DB,
    SCALE_TENANT,
    scale_agent_db_name,
    scale_rag_db_name,
)
from app.eval.accounting import footprint_report  # noqa: E402
from app.eval.scale_llm import score_llm_blob, stratified_sample, summarize_engine  # noqa: E402
from app.eval.scale_runner import load_gold  # noqa: E402
from app.mongo.client import get_client, override_namespaces, ping  # noqa: E402
from app.retrieval.agent_loop import run_agent  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "benchmarks" / "scale" / "gold_queries.json"
OUT_DIR = ROOT / "reports" / "scale"


def _session_blob(session) -> dict:
    citations = [c.model_dump(mode="json") for c in (session.citations or [])]
    retrieved = list(getattr(session, "retrieved_docs", None) or [])
    if retrieved and hasattr(retrieved[0], "model_dump"):
        retrieved = [d.model_dump(mode="json") for d in retrieved]
    normalized = []
    for item in retrieved:
        if not isinstance(item, dict):
            continue
        ref = item.get("ref") or {}
        normalized.append(
            {
                "database": item.get("database") or ref.get("database"),
                "collection": item.get("collection") or ref.get("collection"),
                "document_id": item.get("document_id") or ref.get("document_id"),
                "text": item.get("text") or "",
            }
        )
        if not normalized[-1]["document_id"] and item.get("document_id"):
            normalized[-1]["document_id"] = item["document_id"]
    return {
        "session_id": session.id if hasattr(session, "id") else getattr(session, "_id", None),
        "answer": session.answer,
        "status": session.status.value if hasattr(session.status, "value") else str(session.status),
        "stop_reason": session.stop_reason,
        "elapsed_ms": session.elapsed_ms,
        "tokens_consumed": session.tokens_consumed,
        "retrieval_count": session.retrieval_count,
        "agent_turns": getattr(session, "agent_turns", 0) or 0,
        "tool_calls": getattr(session, "tool_calls", 0) or 0,
        "llm_latency_ms": getattr(session, "llm_latency_ms", 0) or 0,
        "mongo_latency_ms": getattr(session, "mongo_latency_ms", 0) or 0,
        "citations": citations,
        "retrieved_docs": normalized or retrieved,
        "acgc_stats": getattr(session, "acgc_stats", None) or {},
    }


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n")


def main() -> None:
    n = 10_000
    density = 20
    strategy = "semantic"
    per_category = 4
    split = "heldout"
    engine = "both"
    use_acgc = False
    if "--n" in sys.argv:
        n = int(sys.argv[sys.argv.index("--n") + 1])
    if "--density" in sys.argv:
        density = int(sys.argv[sys.argv.index("--density") + 1])
    if "--strategy" in sys.argv:
        strategy = sys.argv[sys.argv.index("--strategy") + 1]
    if "--per-category" in sys.argv:
        per_category = int(sys.argv[sys.argv.index("--per-category") + 1])
    if "--split" in sys.argv:
        split = sys.argv[sys.argv.index("--split") + 1]
    if "--engine" in sys.argv:
        engine = sys.argv[sys.argv.index("--engine") + 1]
    if "--acgc" in sys.argv:
        use_acgc = True

    ping()
    settings = get_settings()
    agent_db_name = scale_agent_db_name(n, density, strategy)
    rag_db_name = scale_rag_db_name(n)
    queries = stratified_sample(load_gold(GOLD, split=None), per_category=per_category, split=split)
    out = OUT_DIR / (
        f"llm_on_{n}_{strategy}_d{density}_{split}_acgc.json"
        if use_acgc
        else f"llm_on_{n}_{strategy}_d{density}_{split}.json"
    )
    rows: list[dict] = []
    if out.exists() and "--resume" in sys.argv:
        prev = json.loads(out.read_text())
        rows = list(prev.get("queries") or [])
        done = {r.get("query_id") for r in rows}
        queries = [q for q in queries if q.get("query_id") not in done]
        print(f"resuming with {len(rows)} done, {len(queries)} remaining")

    payload: dict = {
        "generated_at": datetime.now(UTC).isoformat(),
        "n": n,
        "strategy": strategy,
        "density": density,
        "split": split,
        "per_category": per_category,
        "n_queries": len(rows) + len(queries),
        "tenant_id": SCALE_TENANT,
        "agent_db": agent_db_name,
        "rag_db": rag_db_name,
        "answer_model": settings.openai_model,
        "agent_model": settings.openai_model_agent,
        "reasoning_effort": settings.openai_reasoning_effort,
        "max_agent_turns": settings.max_agent_turns,
        "schema_in_prompt": False,
        "acgc": use_acgc,
        "acgc_grpc_addr": settings.acgc_grpc_addr if use_acgc else None,
        "acgc_token_budget": settings.acgc_token_budget if use_acgc else None,
        "note": "LLM-on end-to-end. Does not replace LLM-off retrieval reports.",
        "queries": rows,
    }

    print(
        f"LLM-on scale: {len(rows) + len(queries)} queries "
        f"agent={settings.openai_model_agent} answer={settings.openai_model} "
        f"nav={agent_db_name} rag={rag_db_name} acgc={use_acgc}"
    )
    if use_acgc:
        from app.retrieval.acgc_sidecar import connect_sidecar

        probe = connect_sidecar(settings.acgc_grpc_addr, "mare_acgc_probe")
        probe.close()
        print(f"ACGC sidecar ok at {settings.acgc_grpc_addr}")
    with override_namespaces(agent=agent_db_name, rag=rag_db_name):
        for i, q in enumerate(queries, start=1):
            print(f"[{i}/{len(queries)}] {q.get('query_id')} {q.get('category')}")
            row: dict = {
                "query_id": q.get("query_id"),
                "category": q.get("category"),
                "tier": q.get("tier"),
                "topic_id": q.get("topic_id"),
                "question": q.get("question"),
                "gold_document_ids": q.get("gold_document_ids"),
            }
            if engine in {"mare", "both"}:
                try:
                    session = run_agent(
                        q["question"],
                        tenant_id=SCALE_TENANT,
                        persist=False,
                        schema_in_prompt=False,
                        use_acgc=use_acgc,
                    )
                    row["mare"] = score_llm_blob(_session_blob(session), q)
                    print(
                        f"  MARE correct={row['mare']['answer_score']['correct']} "
                        f"recall={row['mare']['retrieval'].get('gold_evidence_recall')} "
                        f"ms={round(row['mare']['elapsed_ms'] or 0)} "
                        f"tok={row['mare']['tokens_consumed']}"
                    )
                except Exception as exc:
                    row["mare"] = {"error": str(exc), "traceback": traceback.format_exc()}
                    print(f"  MARE error: {exc}")
            if engine in {"rag", "both"}:
                try:
                    rag = run_rag(
                        q["question"],
                        tenant_id=SCALE_TENANT,
                        source_database=SCALE_RAW_DB,
                    )
                    row["rag"] = score_llm_blob(_session_blob(rag), q)
                    print(
                        f"  RAG  correct={row['rag']['answer_score']['correct']} "
                        f"recall={row['rag']['retrieval'].get('gold_evidence_recall')} "
                        f"ms={round(row['rag']['elapsed_ms'] or 0)} "
                        f"tok={row['rag']['tokens_consumed']}"
                    )
                except Exception as exc:
                    row["rag"] = {"error": str(exc), "traceback": traceback.format_exc()}
                    print(f"  RAG error: {exc}")
            rows.append(row)
            payload["queries"] = rows
            payload["mare"] = summarize_engine(rows, "mare")
            payload["rag"] = summarize_engine(rows, "rag")
            payload["footprint"] = footprint_report(
                agent_db=get_client()[agent_db_name],
                rag_db=get_client()[rag_db_name],
            )
            payload["generated_at"] = datetime.now(UTC).isoformat()
            _write(out, payload)

    print(json.dumps({"mare": payload.get("mare"), "rag": payload.get("rag")}, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
