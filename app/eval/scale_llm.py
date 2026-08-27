"""Deterministic answer/evidence scoring for the scale LLM-on benchmark.

Scoring labels (topic_id, family) are allowed here. Grouping still must not see them.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from app.constants import SCALE_COLLECTION, SCALE_RAW_DB
from app.datagen.scale_corpus import TOPICS
from app.eval.scoring import answer_scores, evidence_scores, retrieval_metrics

_BY_ID = {t.topic_id: t for t in TOPICS}
_TOKEN_RE = re.compile(r"[a-z][a-z0-9_\-]{3,}")
_CUSTOMER_RE = re.compile(r"cust_scale_\d{4}")
_GENERIC = {
    "incident",
    "incidents",
    "records",
    "failed",
    "failure",
    "failures",
    "request",
    "service",
    "during",
    "before",
    "after",
    "which",
    "about",
    "find",
    "retrieve",
    "mention",
    "specifically",
    "other",
    "customer",
    "customers",
    "similar",
    "symptoms",
}


def topic_needles(topic_id: str) -> list[str]:
    topic = _BY_ID[topic_id]
    own = _tokens_for(topic)
    others: set[str] = set()
    for other in TOPICS:
        if other.topic_id == topic.topic_id:
            continue
        others.update(_tokens_for(other))
    unique = [t for t in own if t not in others and t not in _GENERIC]
    return unique[:8] or [t for t in own if t not in _GENERIC][:6]


def sibling_needles(topic_id: str) -> list[str]:
    topic = _BY_ID[topic_id]
    own = set(topic_needles(topic_id))
    out: list[str] = []
    for other in TOPICS:
        if other.family != topic.family or other.topic_id == topic.topic_id:
            continue
        for needle in topic_needles(other.topic_id):
            if needle not in own and needle not in out:
                out.append(needle)
    return out[:12]


def answer_spec_for_query(query: dict[str, Any]) -> dict[str, Any]:
    topic_id = str(query.get("topic_id") or "")
    spec: dict[str, Any] = {
        "must_contain_any": topic_needles(topic_id) if topic_id else [],
        "must_contain_all": [],
        "must_not_contain": [],
    }
    if query.get("category") == "fine_grained":
        spec["must_not_contain"] = sibling_needles(topic_id)
    if query.get("category") == "similar_distractors":
        cid = _customer_id(query.get("question") or "")
        if cid:
            spec["must_contain_all"] = [cid]
    return spec


def gold_sources_for(query: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "database": SCALE_RAW_DB,
            "collection": SCALE_COLLECTION,
            "document_id": str(did),
        }
        for did in (query.get("gold_document_ids") or [])
    ]


def hallucination_scores(
    *,
    answer: str,
    citations: list[dict[str, Any]],
    retrieved: list[dict[str, Any]],
    spec: dict[str, Any],
) -> dict[str, Any]:
    retrieved_ids = {str(r.get("document_id") or "") for r in retrieved if r.get("document_id")}
    cited_ids = [str(c.get("document_id") or "") for c in citations if c.get("document_id")]
    cited_set = {i for i in cited_ids if i}
    unsupported = sorted(cited_set - retrieved_ids)
    invented = sorted(i for i in cited_set if i and not i.startswith("inc_scale_"))
    forbidden = [p.lower() for p in spec.get("must_not_contain") or []]
    text = (answer or "").lower()
    forbidden_hits = [p for p in forbidden if p in text]
    hallucinated = bool(invented or forbidden_hits)
    return {
        "unsupported_citations": unsupported,
        "invented_ids": invented,
        "forbidden_hits": forbidden_hits,
        "cited_not_retrieved": len(unsupported),
        "hallucinated": hallucinated,
    }


def score_llm_blob(blob: dict[str, Any], query: dict[str, Any]) -> dict[str, Any]:
    gold = gold_sources_for(query)
    spec = answer_spec_for_query(query)
    citations = blob.get("citations") or []
    retrieved = blob.get("retrieved_docs") or citations
    blob["evidence"] = evidence_scores(citations, gold)
    blob["retrieval"] = retrieval_metrics(retrieved, gold)
    blob["answer_score"] = answer_scores(blob.get("answer") or "", spec)
    blob["hallucination"] = hallucination_scores(
        answer=blob.get("answer") or "",
        citations=citations,
        retrieved=retrieved,
        spec=spec,
    )
    blob["answer_spec"] = {
        "must_contain_any": spec.get("must_contain_any"),
        "must_contain_all": spec.get("must_contain_all"),
        "must_not_contain": spec.get("must_not_contain"),
    }
    return blob


def stratified_sample(
    queries: list[dict[str, Any]],
    *,
    per_category: int,
    split: str = "heldout",
) -> list[dict[str, Any]]:
    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for q in queries:
        if split and q.get("split") != split:
            continue
        by_cat[str(q.get("category") or "other")].append(q)
    out: list[dict[str, Any]] = []
    for cat in sorted(by_cat):
        rows = sorted(by_cat[cat], key=lambda q: str(q.get("query_id") or ""))
        out.extend(rows[:per_category])
    return out


def summarize_engine(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    blobs = [r[key] for r in rows if key in r]
    n = max(len(blobs), 1)

    def mean(path: str) -> float:
        vals: list[float] = []
        for b in blobs:
            cur: Any = b
            for part in path.split("."):
                cur = (cur or {}).get(part) if isinstance(cur, dict) else None
            if isinstance(cur, (int, float)):
                vals.append(float(cur))
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    correct = sum(1 for b in blobs if (b.get("answer_score") or {}).get("correct") is True)
    halluc = sum(1 for b in blobs if (b.get("hallucination") or {}).get("hallucinated"))
    return {
        "n": len(blobs),
        "correct_rate": round(correct / n, 4),
        "hallucination_rate": round(halluc / n, 4),
        "mean_gold_evidence_recall": mean("retrieval.gold_evidence_recall"),
        "mean_citation_recall": mean("evidence.recall"),
        "mean_elapsed_ms": mean("elapsed_ms"),
        "mean_tokens": mean("tokens_consumed"),
        "mean_tool_calls": mean("tool_calls"),
        "mean_agent_turns": mean("agent_turns"),
        "mean_llm_latency_ms": mean("llm_latency_ms"),
    }


def _tokens_for(topic: Any) -> list[str]:
    blob = " ".join(topic.doc_phrases + topic.query_phrases + (topic.title,)).lower()
    seen: list[str] = []
    for tok in _TOKEN_RE.findall(blob):
        if tok in _GENERIC or tok in seen:
            continue
        seen.append(tok)
    return seen


def _customer_id(question: str) -> str | None:
    match = _CUSTOMER_RE.search(question)
    return match.group(0) if match else None
