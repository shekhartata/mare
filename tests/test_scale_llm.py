from app.eval.scale_llm import answer_spec_for_query, sibling_needles, stratified_sample, topic_needles
from app.mongo.client import override_namespaces
from app.constants import AGENT_DB, RAG_DB, is_nav_database


def test_fine_grained_spec_forbids_sibling_needles():
    spec = answer_spec_for_query(
        {
            "category": "fine_grained",
            "topic_id": "invalid_issuer",
            "question": "Find incidents whose cause is specifically assertion host mismatch",
        }
    )
    assert spec["must_contain_any"]
    assert "issuer" in spec["must_contain_any"] or "iss" in " ".join(spec["must_contain_any"])
    forbidden = set(spec["must_not_contain"])
    assert forbidden
    assert not set(spec["must_contain_any"]) & forbidden
    cert = set(topic_needles("certificate_expiry"))
    assert cert & forbidden or sibling_needles("invalid_issuer")


def test_similar_distractors_require_customer_id():
    spec = answer_spec_for_query(
        {
            "category": "similar_distractors",
            "topic_id": "expired_token",
            "question": "Find expired token incidents for cust_scale_0007 only",
        }
    )
    assert spec["must_contain_all"] == ["cust_scale_0007"]


def test_stratified_sample_is_deterministic():
    queries = [
        {"query_id": f"Q{i:03d}", "category": cat, "split": "heldout"}
        for i, cat in enumerate(
            ["direct_semantic", "paraphrase", "fine_grained", "rare", "similar_distractors"] * 3,
            start=1,
        )
    ]
    a = stratified_sample(queries, per_category=2)
    b = stratified_sample(queries, per_category=2)
    assert a == b
    assert len(a) == 10


def test_nav_database_helper_and_namespace_override_restores():
    assert is_nav_database("_agent_retrieval")
    assert is_nav_database("_agent_scale_10000_semantic_d20")
    assert not is_nav_database("mare_scale")
    # override without a live Mongo call: ContextVar round-trip
    from app.mongo import client as mongo_client

    assert mongo_client._agent_db_override.get() is None
    with override_namespaces(agent="_agent_scale_10000_semantic_d20", rag="_rag_scale_10000"):
        assert mongo_client._agent_db_override.get() == "_agent_scale_10000_semantic_d20"
        assert mongo_client._rag_db_override.get() == "_rag_scale_10000"
    assert mongo_client._agent_db_override.get() is None
    assert mongo_client._rag_db_override.get() is None
    assert AGENT_DB == "_agent_retrieval"
    assert RAG_DB == "_rag_baseline"
