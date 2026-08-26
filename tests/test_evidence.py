from app.llm.heuristic import HeuristicReasoningModel
from app.models.schemas import Claim, ClaimStatus, EvidenceExtraction, HypothesisUpdate
from app.retrieval.evidence import apply_extraction, identify_gaps
from app.models.schemas import EvidenceSession, MongoRef, RetrievedDocument


def test_heuristic_hypothesis_extracts_ids():
    model = HeuristicReasoningModel()
    result = model.structured_generate(
        "Question: Why did cust_007 fail after mig_auth_sso?",
        HypothesisUpdate,
    )
    assert result.value.claims
    blob = result.value.hypothesis + "".join(c.claim for c in result.value.claims)
    assert "cust_007" in blob or "mig_auth_sso" in blob


def test_apply_extraction_promotes_supported_claims():
    session = EvidenceSession(
        _id="s",
        tenant_id="demo",
        question="q",
        claims=[Claim(claim_id="C1", claim="auth failed after migration", status=ClaimStatus.unsupported)],
    )
    extraction = EvidenceExtraction(
        claims_supported=[{"claim_id": "C1", "support_strength": 0.9, "evidence": "AUTH_401"}]
    )
    docs = [
        RetrievedDocument(
            ref=MongoRef(database="mare_demo", collection="logs", document_id="log_1001"),
            content={},
            text="jwt issuer mismatch",
        )
    ]
    apply_extraction(session, extraction, docs)
    assert session.claims[0].status == ClaimStatus.supported
    assert session.claims[0].supporting_sources
    gaps = identify_gaps(session)
    assert isinstance(gaps, list)
