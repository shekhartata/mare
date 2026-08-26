from __future__ import annotations

import json

from app.llm.base import ReasoningModel
from app.models.schemas import (
    Claim,
    ClaimStatus,
    EvidenceExtraction,
    EvidenceSession,
    MongoRef,
    RetrievedDocument,
)


def extract_evidence(
    model: ReasoningModel,
    question: str,
    hypothesis: str,
    claims: list[Claim],
    documents: list[RetrievedDocument],
) -> tuple[EvidenceExtraction, int]:
    claim_blob = "\n".join(f"{c.claim_id}: {c.claim} (status={c.status})" for c in claims)
    docs_blob = "\n\n".join(
        f"[{d.ref.database}.{d.ref.collection} {d.ref.document_id}]\n{d.text}" for d in documents
    )
    prompt = (
        f"Question: {question}\nHypothesis: {hypothesis}\nClaims:\n{claim_blob}\n\n"
        f"Retrieved Mongo documents:\n{docs_blob}\n\n"
        "Decide which claims are supported or contradicted. Quote short evidence."
    )
    result = model.structured_generate(
        prompt,
        EvidenceExtraction,
        system="Only use the provided documents. Never invent Mongo document ids.",
    )
    return result.value, result.usage.total_tokens


def apply_extraction(
    session: EvidenceSession,
    extraction: EvidenceExtraction,
    documents: list[RetrievedDocument],
) -> list[str]:
    refs = [d.ref for d in documents]
    by_id = {c.claim_id: c for c in session.claims}
    for obs in extraction.claims_supported:
        claim = by_id.get(obs.claim_id)
        if not claim:
            continue
        claim.confidence = max(claim.confidence, obs.support_strength)
        claim.supporting_sources = _merge_refs(claim.supporting_sources, refs)
        if obs.support_strength >= 0.75:
            claim.status = ClaimStatus.supported
        elif obs.support_strength >= 0.4:
            claim.status = ClaimStatus.partially_supported
    for obs in extraction.claims_contradicted:
        claim = by_id.get(obs.claim_id)
        if not claim:
            continue
        claim.confidence = max(claim.confidence, obs.support_strength)
        claim.contradicting_sources = _merge_refs(claim.contradicting_sources, refs)
        claim.status = ClaimStatus.contradicted
    for text in extraction.new_claims:
        cid = f"N{len(by_id)+1}"
        if cid not in by_id:
            by_id[cid] = Claim(claim_id=cid, claim=text, status=ClaimStatus.unsupported)
    for q in extraction.new_questions:
        if q not in session.open_questions:
            session.open_questions.append(q)
    session.claims = list(by_id.values())
    return identify_gaps(session)


def identify_gaps(session: EvidenceSession) -> list[str]:
    gaps: list[str] = []
    for claim in session.claims:
        if claim.status in {ClaimStatus.unsupported, ClaimStatus.partially_supported}:
            gaps.append(claim.claim)
            gaps.extend(claim.missing_information)
    gaps.extend(session.open_questions)
    return [g for g in gaps if g]


def generate_answer(
    model: ReasoningModel,
    session: EvidenceSession,
    documents: list[RetrievedDocument],
) -> tuple[str, list[MongoRef], int]:
    docs_blob = "\n\n".join(
        f"[{d.ref.database}.{d.ref.collection} {d.ref.document_id}]\n{d.text}" for d in documents[:20]
    )
    claims_blob = json.dumps([c.model_dump() for c in session.claims], default=str)
    prompt = (
        f"Question: {session.question}\n"
        f"Hypothesis: {session.hypothesis}\n"
        f"Claims: {claims_blob}\n\n"
        f"Evidence documents:\n{docs_blob}\n\n"
        "Write a grounded answer. Cite Mongo sources as database.collection:id. "
        "If evidence is incomplete, say so."
    )
    result = model.generate(
        prompt,
        system="Answer only from provided Mongo evidence. Include source ids inline.",
    )
    citations: list[MongoRef] = []
    seen: set[str] = set()
    preferred = [d for d in documents if d.ref.database == "mare_demo"] or documents
    for d in preferred:
        key = f"{d.ref.collection}:{d.ref.document_id}"
        if key not in seen:
            seen.add(key)
            citations.append(d.ref)
    for claim in session.claims:
        for ref in claim.supporting_sources + claim.contradicting_sources:
            if ref.database == "_agent_retrieval":
                continue
            key = f"{ref.collection}:{ref.document_id}"
            if key not in seen:
                seen.add(key)
                citations.append(ref)
    return result.text.strip(), citations, result.usage.total_tokens


def _merge_refs(existing: list[MongoRef], incoming: list[MongoRef]) -> list[MongoRef]:
    out = {f"{r.collection}:{r.document_id}": r for r in existing}
    for r in incoming:
        out[f"{r.collection}:{r.document_id}"] = r
    return list(out.values())
