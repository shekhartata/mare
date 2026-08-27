import json

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

    dist = gold_by_id["dist_northstar_identity"]
    assert dist["class"] == "distributed"
    q = dist["question"].lower()
    assert "northstar" in q
    for leak in (
        "cust_012",
        "issuer",
        "jwt",
        "oidc",
        "auth_401",
        "mig_ns",
        "identity",
        "migration",
    ):
        assert leak not in q, leak
    dist_ids = {s["document_id"] for s in dist["gold_sources"]}
    assert dist_ids == {"tkt_ns_login", "mig_ns_identity", "dep_ns_stale", "log_ns_jwt"}
    by_id = {d["_id"]: d for d in bundle["tickets"] + bundle["migrations"] + bundle["deployments"] + bundle["logs"]}
    ticket_blob = json.dumps(by_id["tkt_ns_login"], default=str).lower()
    mig_blob = json.dumps(by_id["mig_ns_identity"], default=str).lower()
    dep_blob = json.dumps(by_id["dep_ns_stale"], default=str).lower()
    log_blob = json.dumps(by_id["log_ns_jwt"], default=str).lower()
    assert "login" in ticket_blob and "issuer" not in ticket_blob and "jwt" not in ticket_blob
    assert "oidc" in mig_blob and "login" not in mig_blob and "jwt" not in mig_blob
    assert "previous" in dep_blob and "jwt" not in dep_blob
    assert "issuer" in log_blob and "mig_ns" not in log_blob
    # No single record contains the full cause (login + oidc/issuer + previous/stale).
    for blob in (ticket_blob, mig_blob, dep_blob, log_blob):
        has_login = "login" in blob
        has_oidc = "oidc" in blob or "issuer" in blob
        has_stale = "previous" in blob or "stale" in blob
        assert not (has_login and has_oidc and has_stale), blob[:200]

    small = gold_by_id["vk_apex_small"]
    medium = gold_by_id["vk_apex_medium"]
    deep = gold_by_id["vk_apex_deep"]
    assert small["class"] == medium["class"] == deep["class"] == "variable_k"
    s_ids = {s["document_id"] for s in small["gold_sources"]}
    m_ids = {s["document_id"] for s in medium["gold_sources"]}
    d_ids = {s["document_id"] for s in deep["gold_sources"]}
    assert len(s_ids) == 2
    assert 6 <= len(m_ids) <= 8
    assert 15 <= len(d_ids) <= 25
    assert s_ids <= m_ids <= d_ids
    assert "inc_apex_mar" in d_ids and "inc_apex_apr" in d_ids
    assert "inc_apex_mar" not in m_ids


def test_tenant_injection_cannot_be_overridden_by_model_filter():
    scoped = inject_tenant({"tenant_id": "evil", "customer_id": "cust_007"}, "demo")
    assert scoped["tenant_id"] == "demo"
    assert scoped["customer_id"] == "cust_007"
