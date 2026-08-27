"""Gold-answer and citation scoring for MARE vs RAG comparisons."""

from __future__ import annotations

import re
from typing import Any


def source_key(collection: str, document_id: str) -> str:
    return f"{collection}:{document_id}"


def _ref_key(item: dict) -> str:
    return source_key(str(item.get("collection") or ""), str(item.get("document_id") or ""))


def _token_count(text: str) -> int:
    return len((text or "").split())


def evidence_scores(citations: list[dict], gold_sources: list[dict]) -> dict[str, Any]:
    gold = {source_key(s["collection"], s["document_id"]) for s in gold_sources}
    got = {_ref_key(c) for c in citations if c.get("document_id")}
    hit = gold & got
    return {
        "recall": round(len(hit) / len(gold), 3) if gold else None,
        "precision": round(len(hit) / len(got), 3) if got else (1.0 if not gold else 0.0),
        "hit": sorted(hit),
        "missed": sorted(gold - got),
        "extra": sorted(got - gold),
        "gold_count": len(gold),
        "cited_count": len(got),
    }


def retrieval_metrics(
    retrieved: list[dict],
    gold_sources: list[dict],
    *,
    required_evidence_count: int | None = None,
) -> dict[str, Any]:
    """Score discovery against gold using retrieved document ids, not answer citations."""
    gold = {source_key(s["collection"], s["document_id"]) for s in gold_sources}
    got = {_ref_key(r) for r in retrieved if r.get("document_id")}
    hit = gold & got
    by_key = {_ref_key(r): r for r in retrieved if r.get("document_id")}
    useful_tokens = sum(_token_count(str(by_key[k].get("text") or "")) for k in hit if k in by_key)
    all_tokens = sum(_token_count(str(r.get("text") or "")) for r in retrieved)
    required = required_evidence_count if required_evidence_count is not None else (len(gold) or None)
    return {
        "gold_evidence_recall": round(len(hit) / len(gold), 3) if gold else None,
        "critical_evidence_missing": sorted(gold - got),
        "documents_retrieved": len(got),
        "useful_documents": len(hit),
        "irrelevant_documents": len(got - gold),
        "retrieved_token_count": all_tokens,
        "useful_evidence_tokens": useful_tokens,
        "context_efficiency": round(useful_tokens / all_tokens, 3) if all_tokens else None,
        "required_evidence_count": required,
        "hit": sorted(hit),
    }


def has_needle(text: str, needle: str) -> bool:
    if needle.isdigit():
        return re.search(rf"\b{re.escape(needle)}\b", text) is not None
    return needle in text


def answer_scores(answer: str, spec: dict) -> dict[str, Any]:
    text = (answer or "").lower()
    must_all = [p.lower() for p in spec.get("must_contain_all") or []]
    must_any = [p.lower() for p in spec.get("must_contain_any") or []]
    forbidden = [p.lower() for p in spec.get("must_not_contain") or []]
    groups = [[p.lower() for p in g] for g in (spec.get("must_contain_groups") or [])]
    matched_all = [p for p in must_all if has_needle(text, p)]
    matched_any = [p for p in must_any if has_needle(text, p)]
    forbidden_hits = [p for p in forbidden if has_needle(text, p)]
    group_hits = []
    for needles in groups:
        matched = [p for p in needles if has_needle(text, p)]
        group_hits.append({"needles": needles, "matched": matched, "ok": bool(matched)})
    ok_all = len(matched_all) == len(must_all)
    ok_any = (not must_any) or bool(matched_any)
    ok_not = not forbidden_hits
    ok_groups = all(g["ok"] for g in group_hits) if group_hits else True
    foreign = []
    if spec.get("no_foreign_incident_cites"):
        cites = spec.get("_citations") or []
        allowed = {str(x) for x in (spec.get("allowed_incident_cites") or [])}
        foreign = [
            f"{c.get('collection')}:{c.get('document_id')}"
            for c in cites
            if c.get("collection") == "incidents"
            and str(c.get("document_id") or "") not in allowed
        ]
    ok_grounded = not foreign
    entity_found = group_hits[0]["ok"] if len(group_hits) > 0 else None
    cause_found = group_hits[1]["ok"] if len(group_hits) > 1 else None
    return {
        "correct": ok_all and ok_any and ok_not and ok_groups and ok_grounded,
        "completeness": ok_groups,
        "matched_all": matched_all,
        "matched_any": matched_any,
        "forbidden_hits": forbidden_hits,
        "foreign_incident_cites": foreign,
        "group_hits": group_hits,
        "entity_found": entity_found,
        "cause_found": cause_found,
        "groups_hit": sum(1 for g in group_hits if g["ok"]),
        "groups_total": len(group_hits),
    }
