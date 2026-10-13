"""Generic MARE vs in-memory RAG harness. No network."""

from app.baseline.memory_rag import MemoryRag
from app.datagen.shop_fixture import GOLD as SHOP_GOLD
from app.datagen.shop_fixture import documents as shop_documents
from app.datagen.warehouse_fixture import GOLD as WAREHOUSE_GOLD
from app.datagen.warehouse_fixture import documents as warehouse_documents
from app.eval.generic_compare import CASES, case_kind, performance_table
from app.indexing.signals import build_generic_index, reset_index_state
from app.llm.base import GenerationResult, Usage


def test_abstract_mare_covers_both_corpora_and_every_kind():
    """Lookup, hop, count, and absence on the shop and the warehouse."""
    reset_index_state()
    corpora = {
        "mare_shop": shop_documents(),
        "mare_warehouse": warehouse_documents(),
    }
    indexes = {
        name: build_generic_index(docs, database=name, use_cache=False)
        for name, docs in corpora.items()
    }
    seen_kinds: dict[str, set[str]] = {name: set() for name in corpora}
    for case in CASES:
        kind = case_kind(case["id"])
        seen_kinds[case["database"]].add(kind)
        result = indexes[case["database"]].investigate(case["question"])
        gold_ids = {source["document_id"] for source in case["gold_sources"]}
        assert set(result["document_ids"]) == gold_ids
        receipt = result["evidence_receipt"]
        assert receipt["exhaustive_database"] is False
        if case["expect_count"] is not None:
            assert result["count"] == case["expect_count"]
            assert receipt["exact"] is True
        if kind == "absence":
            assert result["count"] == 0
            assert receipt["absence_scope"] == "collection"
    assert seen_kinds["mare_shop"] == {"lookup", "hop", "count", "absence"}
    assert seen_kinds["mare_warehouse"] == {"lookup", "hop", "count", "absence"}


def test_performance_table_includes_latency_and_tokens():
    payload = {
        "rag_ks": [1, 8],
        "cases": [
            {
                "id": "shop_lookup",
                "database": "mare_shop",
                "title": "Shop lookup",
                "mare": _engine(True, 1.0, 10.4, 5),
                "rag": {
                    "k1": _engine(True, 1.0, 4.2, 2),
                    "k8": _engine(False, 0.5, 8.0, 9),
                },
            }
        ],
    }
    text = performance_table(payload)
    header = "| case | kind | MARE | recall | ms | tok |"
    row = "| Shop lookup | lookup | yes | 1.00 | 10 | 5 | yes | 1.00 | 4 | 2 | no | 0.50 | 8 | 9 |"
    assert header in text
    assert "lookup" in text
    assert row in text
    assert "| mean |" in text


def _engine(correct: bool, recall: float, elapsed_ms: float, tokens: int) -> dict:
    return {
        "answer_score": {"correct": correct},
        "retrieval": {"gold_evidence_recall": recall},
        "elapsed_ms": elapsed_ms,
        "tokens": tokens,
    }


def test_fixture_questions_match_comparison_cases():
    shop = [case["question"] for case in CASES if case["database"] == "mare_shop"]
    warehouse = [case["question"] for case in CASES if case["database"] == "mare_warehouse"]
    assert shop == [row[0] for row in SHOP_GOLD]
    assert warehouse == [row[0] for row in WAREHOUSE_GOLD]


def test_hybrid_top1_prefers_the_named_order():
    rag = MemoryRag(shop_documents(), embedder=None)
    hits = rag.search("What is the status of order ord_1044?", 1)
    assert hits[0]["document_id"] == "ord_1044"
    assert hits[0]["collection"] == "orders"


def test_comparison_scores_a_scripted_answer(monkeypatch):
    from app.eval import generic_compare

    class Scripted:
        def generate(self, prompt: str, *, system: str | None = None) -> GenerationResult:
            if "count=0" in prompt:
                text = "0"
            elif "shipped" in prompt.lower():
                text = "The order status is shipped."
            elif "ord_1044" in prompt:
                text = "ord_1044"
            else:
                text = "unknown"
            return GenerationResult(text=text, usage=Usage(total_tokens=4))

    monkeypatch.setattr(generic_compare, "CASES", CASES[:1])
    payload = generic_compare.run_generic_comparison(
        {"mare_shop": shop_documents()},
        model=Scripted(),
        embedder=None,
        rag_ks=(1,),
    )
    mare = payload["cases"][0]["mare"]
    rag = payload["cases"][0]["rag"]["k1"]
    assert mare["answer_score"]["correct"] is True
    assert mare["retrieval"]["gold_evidence_recall"] == 1.0
    assert rag["answer_score"]["correct"] is True
    assert rag["retrieved"][0]["document_id"] == "ord_1044"
    assert payload["footprint"]["mare_shop"]["chunks"] == 5
