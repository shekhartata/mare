"""In-memory MARE tools over the generic index. No network."""

from app.datagen.shop_fixture import documents as shop_documents
from app.datagen.warehouse_fixture import documents as warehouse_documents
from app.indexing.signals import build_generic_index, reset_index_state
from app.indexing.signals.nav_nodes import build_nav_nodes
from app.retrieval.generic_tools import MEMBER_PREFETCH_LIMIT, GenericSurface, generic_handlers


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


def test_query_embed_failure_keeps_lexical_hits():
    index = build_generic_index(shop_documents(), database="mare_shop", use_cache=False)

    class Boom:
        dimensions = 3
        model = "boom"

        def embed(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("embedding down")

    nodes = build_nav_nodes(index)
    surface = GenericSurface(
        index,
        vectors={node["_id"]: [1.0, 0.0, 0.0] for node in nodes},
        query_embedder=Boom(),
    )
    hits = surface.search_information(
        "sweater pilled after one wash",
        tenant_id=None,
        scope=None,
        mode=None,
        limit=4,
    )
    assert hits["results"]
    assert surface.embed_calls["queries"] == 0
    assert "error" not in hits


def test_large_card_is_not_prefetched_and_a_bounded_card_still_is():
    index = build_generic_index(shop_documents(), database="mare_shop", use_cache=False)

    class Reader:
        def __init__(self) -> None:
            self.sizes: list[int] = []

        def fetch(self, collection, *, ids=None, filt=None, limit=None):
            del collection, filt, limit
            self.sizes.append(len(ids or []))
            return []

    reader = Reader()
    surface = GenericSurface(index, reader=reader)
    groups = [node for node in surface.nodes if node["node_type"] == "group"]
    large, bounded = groups[0], groups[1]
    large["source"]["document_ids"] = [f"id-{i}" for i in range(MEMBER_PREFETCH_LIMIT + 1)]
    large["search_text"] = "loan purpose purchase"
    bounded["source"]["document_ids"] = [f"ok-{i}" for i in range(MEMBER_PREFETCH_LIMIT)]

    found = surface.search_information(
        "loan purpose purchase",
        tenant_id=None,
        scope=None,
        mode="lexical",
        limit=8,
    )
    assert large["_id"] in [row["node_id"] for row in found["results"]]
    assert all(size <= MEMBER_PREFETCH_LIMIT for size in reader.sizes)

    skipped = surface.retrieve_evidence(
        [large["_id"]], tenant_id=None, query=None, max_documents=8
    )
    assert skipped["documents"] == []
    assert skipped["hints"][0]["document_count"] == MEMBER_PREFETCH_LIMIT + 1
    assert "query_documents" in skipped["hints"][0]["hint"]
    assert all(size <= MEMBER_PREFETCH_LIMIT for size in reader.sizes)

    before = len(reader.sizes)
    surface.retrieve_evidence([bounded["_id"]], tenant_id=None, query=None, max_documents=8)
    assert MEMBER_PREFETCH_LIMIT in reader.sizes[before:]


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
