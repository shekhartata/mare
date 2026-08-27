"""Run held-out / dev retrieval eval without an LLM."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from pymongo.collection import Collection

from app.eval.ir_metrics import mean_scores, score_ranking
from app.eval.pipelines import mare_retrieve, rag_retrieve


def evaluate_queries(
    queries: list[dict[str, Any]],
    *,
    engine: str,
    budget: int,
    tenant_id: str,
    chunks: Collection | None = None,
    nodes: Collection | None = None,
    source: Collection | None = None,
    rag_method: str = "hybrid",
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    by_cat: dict[str, list[dict[str, float]]] = defaultdict(list)
    by_tier: dict[str, list[dict[str, float]]] = defaultdict(list)
    latencies: list[float] = []
    for q in queries:
        gold = [str(x) for x in q.get("gold_document_ids") or []]
        if engine == "rag":
            if chunks is None:
                raise ValueError("rag eval needs chunks")
            result = rag_retrieve(
                q["question"], chunks=chunks, tenant_id=tenant_id, budget=budget, method=rag_method
            )
        else:
            if nodes is None or source is None:
                raise ValueError("mare eval needs nodes and source")
            result = mare_retrieve(
                q["question"],
                nodes=nodes,
                source=source,
                tenant_id=tenant_id,
                budget=budget,
            )
        metrics = score_ranking(result["ranked_ids"], gold, budget)
        latencies.append(float(result.get("elapsed_ms") or 0))
        row = {
            "query_id": q.get("query_id"),
            "category": q.get("category"),
            "tier": q.get("tier"),
            "split": q.get("split"),
            **metrics,
            "elapsed_ms": result.get("elapsed_ms"),
        }
        rows.append(row)
        by_cat[str(q.get("category"))].append(metrics)
        by_tier[str(q.get("tier"))].append(metrics)
    latencies.sort()
    p50 = latencies[len(latencies) // 2] if latencies else 0.0
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0.0
    return {
        "engine": engine,
        "budget": budget,
        "n": len(rows),
        "overall": mean_scores(rows),
        "by_category": {k: mean_scores(v) for k, v in sorted(by_cat.items())},
        "by_tier": {k: mean_scores(v) for k, v in sorted(by_tier.items())},
        "latency_ms": {"p50": round(p50, 1), "p95": round(p95, 1)},
        "queries": rows,
    }


def load_gold(path: Path, *, split: str | None = None) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text())
    queries = payload.get("queries") or []
    if split:
        queries = [q for q in queries if q.get("split") == split]
    return queries
