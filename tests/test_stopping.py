from app.config.budgets import budgets_from_settings
from app.models.schemas import Accounting, Claim, ClaimStatus, EvidenceSession, SessionStatus
from app.retrieval.stopping import coverage, should_stop


def _session(claims: list[Claim]) -> EvidenceSession:
    return EvidenceSession(_id="s1", tenant_id="demo", question="q", claims=claims)


def test_coverage():
    claims = [
        Claim(claim_id="C1", claim="a", status=ClaimStatus.supported, material=True),
        Claim(claim_id="C2", claim="b", status=ClaimStatus.unsupported, material=True),
    ]
    assert coverage(claims) == 0.5


def test_budget_stop():
    budgets = budgets_from_settings()
    acc = Accounting(retrieval_count=budgets.max_retrieval_operations)
    stop, reason, status = should_stop(
        session=_session([]),
        accounting=acc,
        budgets=budgets,
        highest_priority=1.0,
        consecutive_low_gain=0,
        last_gain=1.0,
        stable_rounds=0,
        round_index=1,
    )
    assert stop is True
    assert status == SessionStatus.budget_exhausted
    assert reason == "max_retrieval_operations"


def test_frontier_stop():
    stop, reason, status = should_stop(
        session=_session([]),
        accounting=Accounting(),
        highest_priority=0.01,
        consecutive_low_gain=0,
        last_gain=1.0,
        stable_rounds=0,
        round_index=1,
    )
    assert stop is True
    assert reason == "frontier_exhausted"
