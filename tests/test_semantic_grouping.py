from collections import defaultdict

from app.datagen.scale_corpus import generate_scale_corpus
from app.indexing.semantic_grouping import semantic_groups_from_docs
from app.indexing.topical_grouping import document_text


def _groups(n: int = 400, target: int = 20):
    bundle = generate_scale_corpus(n, seed=7, gold_prefix=n)
    groups = semantic_groups_from_docs(
        bundle["documents"],
        tenant_id="scale",
        collection="incidents",
        target_docs_per_group=target,
    )
    return bundle, groups


def test_semantic_groups_ignore_topic_id():
    bundle, groups = _groups(240, 25)
    assert groups
    docs = bundle["documents"]
    stripped = [{k: v for k, v in d.items() if k != "topic_id"} for d in docs]
    scrambled = [dict(d, topic_id="zzz") for d in docs]
    g2 = semantic_groups_from_docs(
        stripped, tenant_id="scale", collection="incidents", target_docs_per_group=25
    )
    g3 = semantic_groups_from_docs(
        scrambled, tenant_id="scale", collection="incidents", target_docs_per_group=25
    )
    assert [g["key"] for g in groups] == [g["key"] for g in g2] == [g["key"] for g in g3]
    assert "zzz" not in " ".join(document_text(d) for d in stripped[:8])
    for g in groups:
        assert "topic_id" not in g["summary"]
        assert g["examples"]
        assert "Distinguishing attributes" in g["summary"]
        assert "Representative examples" in g["summary"]
        assert "Entities:" in g["summary"]


def test_semantic_groups_stay_within_vector_budget():
    _, groups = _groups(400, 20)
    n_groups = len(groups)
    assert 8 <= n_groups <= 150
    sizes = [g["document_count"] for g in groups]
    assert max(sizes) <= 80
    assert sum(sizes) == 400


def test_semantic_split_separates_auth_siblings():
    bundle, groups = _groups(800, 20)
    id_to_topic = {str(d["_id"]): d["topic_id"] for d in bundle["documents"]}
    id_to_group: dict[str, str] = {}
    for g in groups:
        for did in g["document_ids"]:
            id_to_group[did] = g["key"]
    def majority(topic: str) -> str:
        counts: dict[str, int] = defaultdict(int)
        for did, t in id_to_topic.items():
            if t == topic:
                counts[id_to_group[did]] += 1
        return max(counts, key=counts.get)

    issuer = majority("invalid_issuer")
    cert = majority("certificate_expiry")
    expired = majority("expired_token")
    assert issuer != cert
    assert issuer != expired or cert != expired
    # Summaries for the issuer-majority group should mention issuer-like terms.
    issuer_group = next(g for g in groups if g["key"] == issuer)
    blob = (issuer_group["summary"] + " " + " ".join(issuer_group["topics"])).lower()
    assert "issuer" in blob or "iss" in blob or "oidc" in blob
