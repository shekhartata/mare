from __future__ import annotations

import json

from app.llm.base import ReasoningModel
from app.models.schemas import Claim, ClaimStatus, EvidenceSession, HypothesisUpdate, RetrievedDocument
from app.retrieval.stopping import mean_confidence


def generate_hypothesis(
    model: ReasoningModel,
    question: str,
    seed_docs: list[RetrievedDocument] | None = None,
) -> HypothesisUpdate:
    snippets = ""
    if seed_docs:
        snippets = "\n\n".join(
            f"{d.ref.collection}/{d.ref.document_id}: {d.text[:500]}" for d in seed_docs[:6]
        )
    prompt = (
        f"Question: {question}\n\n"
        f"Initial navigation snippets:\n{snippets or '(none yet)'}\n\n"
        "Produce a tentative hypothesis and decompose it into material claims "
        "that can be confirmed or contradicted by MongoDB records. "
        "Claims should be specific (ids, timestamps, config keys) when possible."
    )
    result = model.structured_generate(
        prompt,
        HypothesisUpdate,
        system=(
            "You are the hypothesis stage of an adaptive retrieval engine. "
            "Do not answer the user yet. Identify what must be true for a grounded answer."
        ),
    )
    return result.value


def update_hypothesis(
    model: ReasoningModel,
    session: EvidenceSession,
    latest_text: str,
) -> tuple[HypothesisUpdate, int]:
    claims_blob = json.dumps([c.model_dump() for c in session.claims], default=str)
    prompt = (
        f"Question: {session.question}\n"
        f"Current hypothesis: {session.hypothesis}\n"
        f"Claims JSON: {claims_blob}\n"
        f"Latest evidence:\n{latest_text[:4000]}\n\n"
        "Update the hypothesis and claims. Set status/confidence from the evidence. "
        "Preserve claim_ids when the claim is the same idea."
    )
    result = model.structured_generate(
        prompt,
        HypothesisUpdate,
        system="Revise claims conservatively. Prefer Mongo source facts over speculation.",
    )
    updated = result.value
    updated.changed = updated.hypothesis.strip() != session.hypothesis.strip()
    return updated, result.usage.total_tokens


def merge_claims(existing: list[Claim], incoming: list[Claim]) -> list[Claim]:
    by_id = {c.claim_id: c for c in existing}
    for claim in incoming:
        prior = by_id.get(claim.claim_id)
        if prior:
            claim.supporting_sources = list(
                {s.document_id: s for s in [*prior.supporting_sources, *claim.supporting_sources]}.values()
            )
            claim.contradicting_sources = list(
                {
                    s.document_id: s
                    for s in [*prior.contradicting_sources, *claim.contradicting_sources]
                }.values()
            )
            claim.confidence = max(prior.confidence, claim.confidence)
            claim.status = _stronger_status(prior.status, claim.status)
            if not claim.claim:
                claim.claim = prior.claim
        by_id[claim.claim_id] = claim
    merged = list(by_id.values())
    _ = mean_confidence(merged)
    return merged


_STATUS_RANK = {
    ClaimStatus.unsupported: 0,
    ClaimStatus.partially_supported: 1,
    ClaimStatus.supported: 2,
    ClaimStatus.contradicted: 3,
}


def _stronger_status(a: ClaimStatus, b: ClaimStatus) -> ClaimStatus:
    return a if _STATUS_RANK[a] >= _STATUS_RANK[b] else b
