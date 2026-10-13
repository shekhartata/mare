"""Bound hops on the padded utility corpus. No network."""

from app.baseline.memory_rag import MemoryRag
from app.datagen.utility_fixture import CASES, DATABASE, documents
from app.indexing.signals import build_generic_index, reset_index_state
from app.retrieval.generic_tools import generic_handlers


def setup_function() -> None:
    reset_index_state()


def _case(case_id: str) -> dict:
    return next(item for item in CASES if item["id"] == case_id)


def test_bridge_related_node_opens_the_order_top_k_misses():
    docs = documents()
    index = build_generic_index(docs, database=DATABASE, use_cache=False)
    hops = [plan for plan in index.plans if plan.get("op") == "hop"]
    assert any(
        plan["collection"] == "returns" and plan["to_collection"] == "orders" for plan in hops
    )
    question = _case("util_bridge")["question"]
    handlers = generic_handlers(index)
    found = handlers["search_information"](
        question,
        tenant_id="generic",
        scope=None,
        mode="lexical",
        limit=4,
    )
    bound = next(row for row in found["related_nodes"] if row["node_id"].endswith("ord_pill"))
    assert bound["source"]["filter"] == {"_id": "ord_pill"}
    evidence = handlers["retrieve_evidence"](
        [bound["node_id"]],
        tenant_id="generic",
        query=question,
        max_documents=4,
    )
    text = evidence["documents"][0]["text"]
    assert "northwind" in text
    assert "pilled" not in text
    top = MemoryRag(docs).search(question, 8)
    assert len(docs["returns"]) + len(docs["orders"]) > 8
    assert all("northwind" not in item["text"] for item in top)
    assert all(item["document_id"] != "ord_pill" for item in top)


def test_distributed_cause_is_outside_lexical_top_8():
    docs = documents()
    index = build_generic_index(docs, database=DATABASE, use_cache=False)
    question = _case("util_distributed")["question"]
    handlers = generic_handlers(index)
    found = handlers["search_information"](
        question,
        tenant_id="generic",
        scope=None,
        mode="lexical",
        limit=4,
    )
    bound = next(row for row in found["related_nodes"] if "lot_77" in row["node_id"])
    evidence = handlers["retrieve_evidence"](
        [bound["node_id"]],
        tenant_id="generic",
        query=question,
        max_documents=4,
    )
    assert "chlorogenic" in evidence["documents"][0]["text"]
    top = MemoryRag(docs).search(question, 8)
    assert all("chlorogenic" not in item["text"] for item in top)


def test_absence_filter_rejects_the_lookalike():
    docs = documents()
    index = build_generic_index(docs, database=DATABASE, use_cache=False)
    handlers = generic_handlers(index)
    result = handlers["query_documents"](
        f"{DATABASE}.refunds",
        {
            "sku": "sku_plain",
            "requested_at": {"$gte": "2024-04-01", "$lt": "2024-05-01"},
        },
        tenant_id="generic",
        projection=None,
        limit=5,
    )
    assert result["count"] == 0
    question = _case("util_absence")["question"]
    top = MemoryRag(docs).search(question, 8)
    assert top[0]["document_id"] == "ref_look"
    assert "sku_plain" in top[0]["text"]
    assert "sku: sku_plain_plus" in top[0]["text"]
