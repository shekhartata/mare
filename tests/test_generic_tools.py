"""In-memory MARE tools over the generic index. No network."""

from app.datagen.shop_fixture import documents as shop_documents
from app.datagen.warehouse_fixture import documents as warehouse_documents
from app.indexing.signals import build_generic_index, reset_index_state
from app.retrieval.generic_tools import generic_handlers


def setup_function() -> None:
    reset_index_state()


def test_shop_search_retrieve_and_filtered_query():
    index = build_generic_index(shop_documents(), database="mare_shop", use_cache=False)
    handlers = generic_handlers(index)
    found = handlers["search_information"](
        "sweater pilled after one wash",
        tenant_id="generic",
        scope=None,
        mode="lexical",
        limit=4,
    )
    node = next(
        row
        for row in found["results"]
        if "ref_9" in (row["source"].get("document_ids") or [])
    )
    evidence = handlers["retrieve_evidence"](
        [node["node_id"]],
        tenant_id="generic",
        query=None,
        max_documents=4,
    )
    ids = {doc["ref"]["document_id"] for doc in evidence["documents"]}
    assert "ref_9" in ids
    assert any(row["source"]["collection"] == "orders" for row in evidence["related_nodes"])
    none = handlers["query_documents"](
        "mare_shop.refunds",
        {"sku": "sku_mug"},
        tenant_id="generic",
        projection=None,
        limit=5,
    )
    one = handlers["query_documents"](
        "mare_shop.refunds",
        {"sku": "sku_wool"},
        tenant_id="generic",
        projection=None,
        limit=5,
    )
    assert none["count"] == 0
    assert one["documents"][0]["ref"]["document_id"] == "ref_9"
    blocked = handlers["query_documents"](
        "mare_shop.refunds",
        {"$where": "this.sku"},
        tenant_id="generic",
        projection=None,
        limit=5,
    )
    assert "error" in blocked


def test_warehouse_absence_filter_returns_no_documents():
    index = build_generic_index(warehouse_documents(), database="mare_warehouse", use_cache=False)
    handlers = generic_handlers(index)
    result = handlers["query_documents"](
        "mare_warehouse.movements",
        {
            "sku": "sku_bolt",
            "moved_at": {"$gte": "2024-04-01", "$lt": "2024-05-01"},
        },
        tenant_id="generic",
        projection=None,
        limit=5,
    )
    assert result["count"] == 0
