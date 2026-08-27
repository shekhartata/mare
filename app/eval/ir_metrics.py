"""Deterministic IR metrics over ranked document ids."""

from __future__ import annotations

import math
from collections.abc import Sequence


def recall_at_k(ranked: Sequence[str], gold: Sequence[str], k: int) -> float:
    if not gold:
        return 0.0
    hit = set(ranked[:k]).intersection(gold)
    return len(hit) / len(set(gold))


def precision_at_k(ranked: Sequence[str], gold: Sequence[str], k: int) -> float:
    top = ranked[:k]
    if not top:
        return 0.0
    gold_set = set(gold)
    return sum(1 for i in top if i in gold_set) / len(top)


def mrr(ranked: Sequence[str], gold: Sequence[str]) -> float:
    gold_set = set(gold)
    for i, doc_id in enumerate(ranked, start=1):
        if doc_id in gold_set:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: Sequence[str], gold: Sequence[str], k: int) -> float:
    gold_set = set(gold)
    dcg = 0.0
    for i, doc_id in enumerate(ranked[:k], start=1):
        rel = 1.0 if doc_id in gold_set else 0.0
        if rel:
            dcg += rel / math.log2(i + 1)
    ideal_hits = min(k, len(gold_set))
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    return (dcg / idcg) if idcg else 0.0


def score_ranking(ranked: Sequence[str], gold: Sequence[str], k: int) -> dict[str, float]:
    return {
        "recall": round(recall_at_k(ranked, gold, k), 4),
        "precision": round(precision_at_k(ranked, gold, k), 4),
        "mrr": round(mrr(ranked, gold), 4),
        "ndcg": round(ndcg_at_k(ranked, gold, k), 4),
        "retrieved": len(ranked[:k]),
        "gold": len(set(gold)),
        "hits": len(set(ranked[:k]).intersection(gold)),
    }


def mean_scores(rows: list[dict[str, float]]) -> dict[str, float]:
    if not rows:
        return {"recall": 0.0, "precision": 0.0, "mrr": 0.0, "ndcg": 0.0}
    keys = ("recall", "precision", "mrr", "ndcg")
    return {k: round(sum(r[k] for r in rows) / len(rows), 4) for k in keys}
