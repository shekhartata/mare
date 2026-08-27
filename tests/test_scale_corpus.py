from app.datagen.scale_corpus import (
    FORBIDDEN_GROUPING_FIELDS,
    TEXT_FIELDS,
    TOPICS,
    generate_scale_corpus,
    grouping_projection,
)
from app.indexing.topical_grouping import document_text, topical_groups_from_docs


def test_scale_corpus_nested_prefix_and_text_length():
    small = generate_scale_corpus(400, seed=7, gold_prefix=400)
    assert small["gold_prefix"] == 400
    assert len(small["documents"]) == 400
    for doc in small["documents"][:20]:
        blob = f"{doc['title']} {doc['description']} {doc['resolution']}"
        assert len(blob) >= 1200
        assert "topic_id" in doc
    queries = small["queries"]
    assert len(queries) >= 80
    gold_ids = {d["_id"] for d in small["documents"]}
    for q in queries:
        assert q["split"] in {"dev", "heldout"}
        assert q["gold_document_ids"]
        assert set(q["gold_document_ids"]) <= gold_ids
        assert q["category"] in {
            "direct_semantic",
            "paraphrase",
            "fine_grained",
            "rare",
            "similar_distractors",
        }
    # Paraphrase questions must not copy document-only phrases.
    doc_lexicon = set()
    for topic in TOPICS:
        doc_lexicon.update(p.lower() for p in topic.doc_phrases)
    for q in queries:
        if q["category"] != "paraphrase":
            continue
        question = q["question"].lower()
        for phrase in doc_lexicon:
            assert phrase not in question, phrase


def test_larger_n_keeps_same_prefix_ids():
    a = generate_scale_corpus(200, seed=7, gold_prefix=200)
    b = generate_scale_corpus(500, seed=7, gold_prefix=200)
    assert [d["_id"] for d in a["documents"]] == [d["_id"] for d in b["documents"][:200]]
    assert [d["topic_id"] for d in a["documents"]] == [d["topic_id"] for d in b["documents"][:200]]


def test_grouping_projection_hides_scoring_labels():
    keys = set(grouping_projection())
    assert keys.isdisjoint(FORBIDDEN_GROUPING_FIELDS)
    assert "topic_id" not in keys
    assert set(TEXT_FIELDS) <= keys


def test_topical_groups_ignore_topic_id_and_respect_density():
    bundle = generate_scale_corpus(240, seed=7, gold_prefix=240)
    docs = bundle["documents"]
    groups = topical_groups_from_docs(
        docs, tenant_id="scale", collection="incidents", target_docs_per_group=30
    )
    assert groups
    sizes = [g["document_count"] for g in groups]
    assert max(sizes) <= 60  # time/hash split keeps groups near the knob
    # Same grouping if topic_id is stripped or scrambled.
    stripped = [{k: v for k, v in d.items() if k != "topic_id"} for d in docs]
    scrambled = [dict(d, topic_id="zzz") for d in docs]
    g2 = topical_groups_from_docs(
        stripped, tenant_id="scale", collection="incidents", target_docs_per_group=30
    )
    g3 = topical_groups_from_docs(
        scrambled, tenant_id="scale", collection="incidents", target_docs_per_group=30
    )
    keys = [g["key"] for g in groups]
    assert keys == [g["key"] for g in g2] == [g["key"] for g in g3]
    blob = " ".join(document_text(d) for d in stripped[:5])
    assert "zzz" not in blob
