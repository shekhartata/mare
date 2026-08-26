from app.search.router import recommend_method
from app.models.schemas import SearchMethod


def test_identifier_routes_lexical():
    assert recommend_method("What is AUTH_401 on dep_apex_fail_1?") == SearchMethod.lexical


def test_simple_predicate_routes_mongo_query():
    assert recommend_method("What is customer cust_007's current subscription tier?") in {
        SearchMethod.mongo_query,
        SearchMethod.lexical,
    }


def test_conceptual_routes_semantic_or_hybrid():
    method = recommend_method("Find incidents involving authentication failures.")
    assert method in {SearchMethod.semantic, SearchMethod.hybrid}


def test_multihop_routes_hybrid():
    q = (
        "Why did customer Apex Logistics (cust_007) begin experiencing deployment "
        "failures after migration mig_auth_sso?"
    )
    assert recommend_method(q) == SearchMethod.hybrid
