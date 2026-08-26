from __future__ import annotations

from app.config import get_settings
from app.config.budgets import budgets_from_settings
from app.models.schemas import (
    Accounting,
    Budgets,
    Claim,
    ClaimStatus,
    EvidenceSession,
    SessionStatus,
)


def coverage(claims: list[Claim]) -> float:
    material = [c for c in claims if c.material]
    if not material:
        return 0.0
    covered = [
        c
        for c in material
        if c.status in {ClaimStatus.supported, ClaimStatus.partially_supported, ClaimStatus.contradicted}
    ]
    return len(covered) / len(material)


def mean_confidence(claims: list[Claim]) -> float:
    material = [c for c in claims if c.material]
    if not material:
        return 0.0
    return sum(c.confidence for c in material) / len(material)


def unresolved_critical_contradictions(claims: list[Claim]) -> bool:
    return any(c.material and c.status == ClaimStatus.contradicted and c.confidence >= 0.5 for c in claims)


def hypothesis_delta(prev: str, current: str) -> float:
    if not prev:
        return 1.0
    if prev.strip() == current.strip():
        return 0.0
    a, b = set(prev.lower().split()), set(current.lower().split())
    if not a or not b:
        return 1.0
    inter = len(a & b)
    union = len(a | b)
    return 1.0 - (inter / union)


def should_stop(
    *,
    session: EvidenceSession,
    accounting: Accounting,
    budgets: Budgets | None = None,
    highest_priority: float,
    consecutive_low_gain: int,
    last_gain: float,
    stable_rounds: int,
    round_index: int,
) -> tuple[bool, str, SessionStatus]:
    settings = get_settings()
    budgets = budgets or budgets_from_settings()

    if accounting.retrieval_count >= budgets.max_retrieval_operations:
        return True, "max_retrieval_operations", SessionStatus.budget_exhausted
    if accounting.search_count >= budgets.max_search_operations:
        return True, "max_search_operations", SessionStatus.budget_exhausted
    if accounting.documents_read >= budgets.max_documents_read:
        return True, "max_documents_read", SessionStatus.budget_exhausted
    if accounting.tokens_consumed >= budgets.max_llm_tokens:
        return True, "max_llm_tokens", SessionStatus.budget_exhausted
    if accounting.elapsed_ms >= budgets.max_elapsed_ms:
        return True, "max_elapsed_ms", SessionStatus.budget_exhausted
    if round_index >= budgets.max_loop_rounds:
        return True, "max_loop_rounds", SessionStatus.budget_exhausted

    if unresolved_critical_contradictions(session.claims):
        return False, "unresolved_contradictions", SessionStatus.running

    cov = coverage(session.claims)
    if cov >= settings.coverage_threshold and stable_rounds >= settings.answer_stability_rounds:
        return True, "coverage_and_stability", SessionStatus.complete

    if last_gain < settings.min_gain and consecutive_low_gain >= settings.consecutive_low_gain_rounds:
        status = SessionStatus.partial if cov > 0 else SessionStatus.insufficient_evidence
        return True, "marginal_information_gain", status

    if highest_priority < settings.min_priority:
        status = SessionStatus.partial if cov > 0 else SessionStatus.insufficient_evidence
        return True, "frontier_exhausted", status

    return False, "", SessionStatus.running
