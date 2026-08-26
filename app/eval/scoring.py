"""Gold-answer and citation scoring for MARE vs RAG comparisons."""

from __future__ import annotations

import re
from typing import Any


def source_key(collection: str, document_id: str) -> str:
    return f"{collection}:{document_id}"


def evidence_scores(citations: list[dict], gold_sources: list[dict]) -> dict[str, Any]:
    gold = {source_key(s["collection"], s["document_id"]) for s in gold_sources}
    got = {source_key(c.get("collection", ""), c.get("document_id", "")) for c in citations}
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
        "matched_all": matched_all,
        "matched_any": matched_any,
        "forbidden_hits": forbidden_hits,
        "foreign_incident_cites": foreign,
        "group_hits": group_hits,
        "entity_found": entity_found,
        "cause_found": cause_found,
    }
