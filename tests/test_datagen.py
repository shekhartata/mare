from app.datagen.generator import generate
from app.mongo.security import inject_tenant


def test_generate_has_story_evidence_split_across_collections():
    bundle = generate(seed=42)
    ids = {d["_id"] for d in bundle["migrations"]}
    assert "mig_auth_sso" in ids
    logs = [d for d in bundle["logs"] if d["_id"] == "log_1001"]
    assert logs and "auth-v3.apex.io" in logs[0]["message"]
    gold_by_id = {q["id"]: q for q in bundle["gold"]}
    assert "mh_auth_sso" in gold_by_id
    assert any(q["class"] == "simple_lookup" for q in bundle["gold"])
    assert any(q["class"] == "semantic" for q in bundle["gold"])
    assert any(q["class"] == "complex_multihop" for q in bundle["gold"])
    assert "bridge_elena_may_deploys" in gold_by_id
    assert gold_by_id["bridge_elena_may_deploys"]["class"] == "bridge"
    assert "cust_007" not in gold_by_id["bridge_elena_may_deploys"]["question"]
    groups = gold_by_id["bridge_elena_may_deploys"]["must_contain_groups"]
    assert groups[0] == ["cust_007", "apex"]
    assert "auth_401" in groups[1]
    assert gold_by_id["agg_enterprise_count"]["class"] == "aggregation"
    assert gold_by_id["neg_cedar_april_incidents"]["class"] == "negative"
    assert gold_by_id["agg_enterprise_count"]["gold_answer"].startswith("18 ")
    assert len(bundle["customers"]) == 50
    assert len(bundle["logs"]) >= 3000


def test_tenant_injection_cannot_be_overridden_by_model_filter():
    scoped = inject_tenant({"tenant_id": "evil", "customer_id": "cust_007"}, "demo")
    assert scoped["tenant_id"] == "demo"
    assert scoped["customer_id"] == "cust_007"
