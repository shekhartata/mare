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


def test_a_deeper_line_that_matches_more_of_the_question_is_kept():
    doc = {
        "terms_of_loan": {f"loan_type_{i}": "Conventional" for i in range(30)},
        "property": {"address": {"state_code": "WI"}},
    }
    text = doc_to_text(doc, max_chars=500, focus="What is the property state on the loan?")
    assert "state_code: WI" in text


def test_common_question_words_do_not_push_out_the_asked_field():
    doc = {
        "_id": "00000ca5-ce7c-478a-bce9-9d739bd47d42",
        "underwriting": {
            **{f"there_the_and_what_{i}": "Other" for i in range(10)},
            "automated_underwriting_response_type": "ReferEligible",
        },
    }
    text = doc_to_text(
        doc,
        max_chars=200,
        focus="What is the automated underwriting response, and what is there?",
    )
    assert "ReferEligible" in text


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


def test_a_buried_member_is_shown_without_reading_documents():
    index = build_generic_index(shop_documents(), database="mare_shop", use_cache=False)

    class Reader:
        def __init__(self) -> None:
            self.calls = 0

        def fetch(self, collection, *, ids=None, filt=None, limit=None):
            del collection, filt, limit
            self.calls += 1
            self.asked = [str(item) for item in (ids or [])]
            if "uat-1" in self.asked:
                return [{"_id": "uat-1", "problem_summary": "UAT atlas M50 queries"}]
            return []

    def search(snippets: list[dict[str, str]]) -> tuple[dict, list, int]:
        reader = Reader()
        surface = GenericSurface(index, reader=reader)
        group = next(node for node in surface.nodes if node["node_type"] == "group")
        group["summary"] = "Kafka stream processing into a timeseries collection"
        group["search_text"] = group["summary"]
        group["member_snippets"] = snippets
        found = surface.search_information(
            "Atlas M50 UAT queries",
            tenant_id=None,
            scope=None,
            mode="lexical",
            limit=8,
        )
        row = next(item for item in found["results"] if item["node_id"] == group["_id"])
        return row, list(found.get("documents") or []), reader.calls

    plain, plain_docs, plain_reads = search([])
    shown, shown_docs, shown_reads = search(
        [
            {"id": "kafka-1", "text": "Atlas Stream Processing from Kafka"},
            {"id": "uat-1", "text": "UAT environment running mongodb atlas M50 tier queries"},
        ]
    )
    assert "uat-1" not in plain["summary"]
    assert plain_docs == []
    assert "uat-1" in shown["summary"]
    assert len(shown["summary"]) <= 480
    assert shown["source"]["document_ids"][0] == "uat-1"
    assert [doc["ref"]["document_id"] for doc in shown_docs] == ["uat-1"]
    assert shown_reads == plain_reads + 1


def test_opening_the_debugging_card_reads_the_matching_session():
    index = build_generic_index(shop_documents(), database="mare_shop", use_cache=False)
    batches: list[list[str]] = []

    class Reader:
        def fetch(self, collection, *, ids=None, filt=None, limit=None):
            del collection, filt, limit
            asked = [str(item) for item in (ids or [])]
            batches.append(asked)
            if "uat-1" in asked:
                return [{"_id": "uat-1", "problem_summary": "UAT atlas M50 queries"}]
            return []

    surface = GenericSurface(index, reader=Reader())
    group = next(node for node in surface.nodes if node["node_type"] == "group")
    group["summary"] = "Kafka stream processing into a timeseries collection"
    group["search_text"] = group["summary"]
    group["source"]["document_ids"] = [f"sess-{i}" for i in range(40)]
    group["member_snippets"] = [
        {"id": "kafka-1", "text": "Atlas Stream Processing from Kafka"},
        {"id": "uat-1", "text": "UAT environment running mongodb atlas M50 tier queries"},
    ]
    found = surface.search_information(
        "Atlas M50 UAT queries",
        tenant_id=None,
        scope=None,
        mode="lexical",
        limit=8,
    )
    assert "hint" not in found
    opened = surface.retrieve_evidence(
        [group["_id"]],
        tenant_id=None,
        query="Atlas M50 UAT queries",
        max_documents=8,
    )
    assert [doc["ref"]["document_id"] for doc in opened["documents"]] == ["uat-1"]
    assert batches
    assert all(len(batch) <= 2 for batch in batches)


def test_a_business_id_reads_the_matching_member_and_not_the_card():
    index = build_generic_index(shop_documents(), database="mare_shop", use_cache=False)

    class Reader:
        def __init__(self) -> None:
            self.batches: list[list[str]] = []

        def fetch(self, collection, *, ids=None, filt=None, limit=None):
            del collection, filt, limit
            batch = [str(item) for item in (ids or [])]
            self.batches.append(batch)
            if "right-quote" in batch:
                return [{"_id": "right-quote"}]
            return []

    reader = Reader()
    surface = GenericSurface(index, reader=reader)
    group = next(node for node in surface.nodes if node["node_type"] == "group")
    group["summary"] = "quoted standard purchase"
    group["search_text"] = group["summary"]
    group["source"]["document_ids"] = ["right-quote", *[f"q-{i}" for i in range(109)]]
    group["member_snippets"] = [
        {"id": "q-0", "text": "quoted in 2025 for a standard purchase"},
        {"id": "right-quote", "text": "MIT-2025-0825-022147 quoted standard purchase"},
    ]
    found = surface.search_information(
        "MIT-2025-0825-022147",
        tenant_id=None,
        scope=None,
        mode="lexical",
        limit=8,
    )
    assert all(len(batch) <= 2 for batch in reader.batches)
    assert [doc["ref"]["document_id"] for doc in found.get("documents") or []] == ["right-quote"]
    assert "hint" not in found
    opened = surface.retrieve_evidence(
        [group["_id"]],
        tenant_id=None,
        query="MIT-2025-0825-022147",
        max_documents=8,
    )
    assert [doc["ref"]["document_id"] for doc in opened["documents"]] == ["right-quote"]
    assert all(len(batch) <= 2 for batch in reader.batches)

    missed = Reader()
    surface = GenericSurface(index, reader=missed)
    group = next(node for node in surface.nodes if node["node_type"] == "group")
    group["summary"] = "quoted standard purchase"
    group["search_text"] = group["summary"]
    group["source"]["document_ids"] = [f"q-{i}" for i in range(110)]
    group["member_snippets"] = [
        {"id": "q-0", "text": "quoted in 2025 for a standard purchase"}
    ]
    found = surface.search_information(
        "MIT-2025-0825-022147",
        tenant_id=None,
        scope=None,
        mode="lexical",
        limit=8,
    )
    assert all(len(batch) <= 2 for batch in missed.batches)
    assert "q-0" not in [doc["ref"]["document_id"] for doc in found.get("documents") or []]
    assert "query_documents" in found["hint"]
    opened = surface.retrieve_evidence(
        [group["_id"]],
        tenant_id=None,
        query="MIT-2025-0825-022147",
        max_documents=8,
    )
    assert opened["documents"] == []
    assert "query_documents" in opened["hints"][0]["hint"]
    assert all(len(batch) <= 2 for batch in missed.batches)


def test_a_card_whose_summary_already_matches_keeps_that_summary():
    index = build_generic_index(shop_documents(), database="mare_shop", use_cache=False)
    surface = GenericSurface(index)
    group = next(node for node in surface.nodes if node["node_type"] == "group")
    group["summary"] = "Atlas M50 UAT queries already on the card"
    group["search_text"] = group["summary"]
    group["member_snippets"] = [
        {"id": "uat-1", "text": "Atlas M50 UAT queries from a later member"}
    ]
    original = [str(doc_id) for doc_id in group["source"]["document_ids"][:8]]
    found = surface.search_information(
        "Atlas M50 UAT queries",
        tenant_id=None,
        scope=None,
        mode="lexical",
        limit=8,
    )
    row = next(item for item in found["results"] if item["node_id"] == group["_id"])
    assert row["summary"] == group["summary"]
    assert row["source"]["document_ids"] == original
    assert not found.get("documents")


def test_a_member_line_ranks_only_when_the_card_front_misses():
    index = build_generic_index(shop_documents(), database="mare_shop", use_cache=False)
    surface = GenericSurface(index)
    buried = {
        "_id": "card:buried",
        "name": "kafka",
        "summary": "kafka only",
        "search_text": "kafka only",
        "member_snippets": [{"id": "uat-1", "text": "UAT atlas M50 workload"}],
    }
    other = {
        "_id": "card:other",
        "name": "notes",
        "summary": "unrelated notes",
        "search_text": "unrelated notes",
        "member_snippets": [],
    }
    strong = {
        "_id": "card:strong",
        "name": "visible",
        "summary": "UAT atlas M50 workload already visible",
        "search_text": "UAT atlas M50 workload already visible",
        "member_snippets": [],
    }
    ranked = surface._rank(
        "UAT atlas M50 workload already visible", [buried, other, strong]
    )
    assert [node["_id"] for node in ranked] == ["card:strong", "card:buried", "card:other"]


def test_collection_node_returns_a_filter_hint_and_no_documents():
    index = build_generic_index(shop_documents(), database="mare_shop", use_cache=False)

    class Reader:
        def fetch(self, collection, *, ids=None, filt=None, limit=None):
            del collection, ids, filt, limit
            raise AssertionError("collection node must not be read")

    surface = GenericSurface(index, reader=Reader())
    collection = next(node for node in surface.nodes if node["node_type"] == "collection")
    got = surface.retrieve_evidence(
        [collection["_id"]],
        tenant_id=None,
        query="Atlas M50 UAT",
        max_documents=8,
    )
    assert got["documents"] == []
    assert got["hints"][0]["node_id"] == collection["_id"]
    assert "query_documents" in got["hints"][0]["hint"]


def test_a_join_field_past_the_twelfth_name_stays_visible():
    from app.indexing.signals.nav_nodes import _shown_fields

    fields = [f"field_{i:02d}" for i in range(12)] + ["session_id"]
    shown = _shown_fields(
        "hypotheses",
        fields,
        [{"op": "hop", "collection": "hypotheses", "field": "session_id"}],
    )
    assert shown[0] == "session_id"
    assert len(shown) == 12


def test_small_cards_store_one_short_line_per_member():
    from app.indexing.signals.orchestrator import _member_snippets

    line = _member_snippets(
        {"a": {"problem_summary": "UAT " + ("x" * 400)}},
        ["a"],
        ("problem_summary",),
    )
    assert line == [{"id": "a", "text": ("UAT " + ("x" * 400))[:160]}]
    assert _member_snippets(
        {"a": {"problem_summary": "kept"}},
        [str(i) for i in range(201)],
        ("problem_summary",),
    ) == []
    index = build_generic_index(shop_documents(), database="mare_shop", use_cache=False)
    for card in index.cards:
        ids = {str(doc_id) for doc_id in card["document_ids"]}
        assert {item["id"] for item in card["member_snippets"]} <= ids
        assert all(len(item["text"]) <= 160 for item in card["member_snippets"])


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
