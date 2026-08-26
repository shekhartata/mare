from __future__ import annotations

from app.config import get_settings
from app.models.schemas import Candidate


def score_candidate(c: Candidate) -> float:
    s = get_settings()
    return (
        s.w_relevance * c.relevance
        + s.w_evidence_gap * c.evidence_gap
        + s.w_uncertainty * c.uncertainty_reduction
        + s.w_novelty * c.novelty
        + s.w_diversity * c.diversity
        - s.w_cost * c.retrieval_cost
    )


def apply_priority(c: Candidate) -> Candidate:
    c.priority = score_candidate(c)
    return c
