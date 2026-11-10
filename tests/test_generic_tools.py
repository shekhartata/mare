"""In-memory MARE tools over the generic index. No network."""

from app.datagen.shop_fixture import documents as shop_documents
from app.datagen.warehouse_fixture import documents as warehouse_documents
from app.indexing.signals import build_generic_index, reset_index_state
from app.indexing.signals.nav_nodes import build_nav_nodes
from app.retrieval.generic_tools import MEMBER_PREFETCH_LIMIT, GenericSurface, generic_handlers
from app.retrieval.serialize import doc_to_text


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


def test_named_id_on_large_cards_is_read_from_every_collection():
    index = build_generic_index(shop_documents(), database="mare_shop", use_cache=False)
    surface = GenericSurface(index, reader=_NamedReader())
    groups = [node for node in surface.nodes if node["node_type"] == "group"]
    by_collection: dict[str, dict] = {}
    for group in groups:
        by_collection.setdefault(group["source"]["collection"], group)
    chosen = list(by_collection.values())[:2]
    assert len(chosen) == 2
    named = "415c5349-d293-5e99-9e29-34949c4b8c54"
    for group in chosen:
        fillers = [f"id-{i}" for i in range(MEMBER_PREFETCH_LIMIT)]
        group["source"]["document_ids"] = [named, *fillers]
        group["source"]["filter"] = {"_id": {"$in": list(group["source"]["document_ids"])}}

    found = surface.search_information(
        f"desktop underwriter recommendation {named}",
        tenant_id=None,
        scope=None,
        mode="lexical",
        limit=8,
    )
    payload = str(found["results"])
    assert "$in" not in payload
    assert len(payload) < 20_000
    got = {doc["ref"]["collection"] for doc in found["documents"]}
    assert got == {group["source"]["collection"] for group in chosen}
    assert all("APPROVE-ELIGIBLE" in doc["text"] for doc in found["documents"])
    calls = surface._reader.calls
    assert all(len(ids) <= MEMBER_PREFETCH_LIMIT for _collection, ids in calls)
    named_calls = [(collection, ids) for collection, ids in calls if named in ids]
    assert {collection for collection, _ids in named_calls} == got
    assert all(ids == [named] for _collection, ids in named_calls)

    opened = surface.retrieve_evidence(
        [chosen[0]["_id"]],
        tenant_id=None,
        query=f"desktop underwriter recommendation {named}",
        max_documents=8,
    )
    assert opened["documents"]
    assert "APPROVE-ELIGIBLE" in opened["documents"][0]["text"]
    assert all(len(ids) <= MEMBER_PREFETCH_LIMIT for _collection, ids in surface._reader.calls)


class _ShopReader:
    def __init__(self, docs: dict) -> None:
        self.docs = docs
        self.calls: list[tuple[str, int, dict | None]] = []

    def fetch(self, collection, *, ids=None, filt=None, limit=None):
        from app.retrieval.generic_tools import _matches

        self.calls.append((collection, len(ids or []), filt))
        rows = list(self.docs.get(collection) or [])
        if ids:
            wanted = {str(i) for i in ids}
            rows = [doc for doc in rows if str(doc.get("_id")) in wanted]
        if filt:
            rows = [doc for doc in rows if _matches(doc, filt)]
        return rows[: int(limit)] if limit is not None else rows


def _hop_collections(index) -> set[str]:
    return {plan["collection"] for plan in index.plans if plan.get("op") == "hop"}


def test_related_reads_each_collection_once_and_skips_cards_without_hops():
    docs = shop_documents()
    index = build_generic_index(docs, database="mare_shop", use_cache=False)
    reader = _ShopReader(docs)
    surface = GenericSurface(index, reader=reader)
    hopping = _hop_collections(index)
    groups = [node for node in surface.nodes if node["node_type"] == "group"]
    linked = [g for g in groups if g["source"]["collection"] in hopping]
    unlinked = [g for g in groups if g["source"]["collection"] not in hopping]
    collection = linked[0]["source"]["collection"]
    ids = list(linked[0]["source"]["document_ids"])
    half = max(1, len(ids) // 2)
    same = [
        {"source": {"collection": collection, "document_ids": part}}
        for part in (ids[:half], ids[half:] or ids)
    ]
    asked = [*same, *unlinked[:2]]
    got = surface._related(asked, "")
    assert got
    assert got == GenericSurface(index)._related(asked, "")
    by_ids = [(name, size) for name, size, filt in reader.calls if size and not filt]
    targets = {node["source"]["collection"] for node in got}
    for name in {name for name, _size in by_ids}:
        expected = (name == collection) + (name in targets)
        assert len([1 for read, _size in by_ids if read == name]) <= expected
    assert [read for read, _size in by_ids].count(collection) >= 1
    untouched = {g["source"]["collection"] for g in unlinked} - targets - {collection}
    assert not any(read in untouched for read, _size, _filt in reader.calls)


def test_one_ask_reuses_reads_and_query_vectors():
    docs = shop_documents()
    index = build_generic_index(docs, database="mare_shop", use_cache=False)
    nodes = build_nav_nodes(index)

    class Embed:
        dimensions = 3
        model = "fixed"

        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def embed(self, texts):
            self.calls.append(list(texts))
            return [[1.0, 0.0, 0.0] for _ in texts]

    embed = Embed()
    reader = _ShopReader(docs)
    surface = GenericSurface(
        index,
        reader=reader,
        vectors={node["_id"]: [1.0, 0.0, 0.0] for node in nodes},
        query_embedder=embed,
    )
    surface.begin_ask("sweater pilled after one wash")
    first = surface.search_information("sweater pilled", tenant_id=None, scope=None, limit=4)
    reads = len(reader.calls)
    again = surface.search_information("sweater pilled", tenant_id=None, scope=None, limit=4)
    assert again == first
    assert embed.calls == [["sweater pilled"]]
    assert len(reader.calls) == reads
    assert surface.last_timing["fetch_calls"] == 0

    surface.begin_ask("another question")
    surface.search_information("sweater pilled", tenant_id=None, scope=None, limit=4)
    assert embed.calls == [["sweater pilled"], ["sweater pilled"]]
    assert len(reader.calls) > reads


def test_a_named_document_binds_its_own_hops_first():
    docs = shop_documents()
    index = build_generic_index(docs, database="mare_shop", use_cache=False)
    hopping = _hop_collections(index)
    plan = next(p for p in index.plans if p.get("op") == "hop")
    named = next(d for d in docs[plan["collection"]] if d.get(plan["field"]) is not None)
    reader = _ShopReader(docs)
    surface = GenericSurface(index, reader=reader)
    surface.begin_ask(f"what does {named['_id']} point to")
    found = surface.search_information(
        f"{plan['collection']} {named['_id']}", tenant_id=None, scope=None, limit=8
    )
    assert [doc["ref"]["document_id"] for doc in found["documents"]] == [str(named["_id"])]
    value = named[plan["field"]]
    assert any(str(value) in node["node_id"] for node in found["related_nodes"])
    member_reads = [c for c in reader.calls if c[1] and not c[2] and c[0] in hopping]
    assert all(size == 1 for _name, size, _filt in member_reads if _name == plan["collection"])


class _NamedReader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def fetch(self, collection, *, ids=None, filt=None, limit=None):
        del filt, limit
        wanted = [str(item) for item in (ids or [])]
        self.calls.append((collection, wanted))
        if "415c5349-d293-5e99-9e29-34949c4b8c54" not in wanted:
            return []
        return [
            {
                "_id": "415c5349-d293-5e99-9e29-34949c4b8c54",
                "pad": {f"k{i}": "v" for i in range(12)},
                "underwriting": {
                    **{f"n{i}": "v" for i in range(12)},
                    "desktopUnderwriterRecommendationType": "APPROVE-ELIGIBLE",
                },
            }
        ]


def test_document_text_keeps_a_nested_field_past_the_eighth_key():
    doc = {
        "_id": "415c5349-d293-5e99-9e29-34949c4b8c54",
        "pad": {f"k{i}": "v" for i in range(12)},
        "underwriting": {
            **{f"n{i}": "v" for i in range(12)},
            "desktopUnderwriterRecommendationType": "APPROVE-ELIGIBLE",
        },
    }
    focused = doc_to_text(doc, max_chars=400, focus="desktop underwriter recommendation")
    assert "APPROVE-ELIGIBLE" in focused
    assert focused.index("APPROVE-ELIGIBLE") < 120
    buried = {
        "product_quotes": [{"eligibility": "quote " * 80}],
        "raw_request_ref": "6a7324183bb27cbb2f124d63",
    }
    quote_text = doc_to_text(buried, max_chars=300, focus="which raw payload did quote send")
    assert "6a7324183bb27cbb2f124d63" in quote_text


def test_query_keeps_a_field_named_in_the_question():
    index = build_generic_index(shop_documents(), database="mare_shop", use_cache=False)
    surface = GenericSurface(index)
    collection, rows = next(iter(index.documents.items()))
    doc = rows[0]
    doc["pad"] = {f"k{i}": "v" * 30 for i in range(40)}
    doc["underwriting"] = {
        **{f"n{i}": "v" for i in range(12)},
        "desktopUnderwriterRecommendationType": "APPROVE-ELIGIBLE",
    }
    plain = surface.query_documents(
        f"mare_shop.{collection}",
        {"_id": doc["_id"]},
        tenant_id=None,
        projection=None,
        limit=1,
    )
    assert "APPROVE-ELIGIBLE" not in plain["documents"][0]["text"]
    surface.question = (
        "What was the desktop underwriter recommendation on loan instance "
        f"{doc['_id']}"
    )
    focused = surface.query_documents(
        f"mare_shop.{collection}",
        {"_id": doc["_id"]},
        tenant_id=None,
        projection=None,
        limit=1,
    )
    assert "APPROVE-ELIGIBLE" in focused["documents"][0]["text"]


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
