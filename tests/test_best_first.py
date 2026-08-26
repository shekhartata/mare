from app.models.schemas import Candidate, NodeType, SourcePointer
from app.retrieval.best_first import apply_priority, score_candidate
from app.retrieval.candidate import CandidateQueue


def test_priority_weights_prefer_relevance_and_gaps():
    a = Candidate(node_id="a", relevance=1, evidence_gap=1, uncertainty_reduction=0, novelty=0, diversity=0, retrieval_cost=0)
    b = Candidate(node_id="b", relevance=0, evidence_gap=0, uncertainty_reduction=0, novelty=0, diversity=0, retrieval_cost=1)
    assert score_candidate(a) > score_candidate(b)


def test_queue_pops_highest_and_marks_visited():
    q = CandidateQueue()
    low = apply_priority(Candidate(node_id="low", name="low", relevance=0.1, novelty=1))
    high = apply_priority(
        Candidate(
            node_id="high",
            name="high",
            relevance=0.9,
            evidence_gap=0.9,
            novelty=1,
            source=SourcePointer(database="mare_demo", collection="logs"),
        )
    )
    q.add(low)
    q.add(high)
    first = q.pop_best()
    assert first is not None
    assert first.node_id == "high"
    second = q.pop_best()
    assert second is not None
    assert second.node_id == "low"
    assert q.pop_best() is None
