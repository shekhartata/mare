"""Saved generic index, reloaded and queried as a second process would. No network."""

from __future__ import annotations

from datetime import datetime

from bson import ObjectId

from app.datagen.shop_fixture import documents as shop_documents
from app.indexing.signals import build_generic_index, reset_index_state
from app.indexing.signals.store import (
    MissingGenericIndex,
    _mongo_query,
    index_database,
    load_generic_handlers,
    load_generic_index,
    read_source,
    save_generic_index,
    saved_index_summary,
)


class _Cursor:
    def __init__(self, docs: list[dict]) -> None:
        self.docs = list(docs)

    def limit(self, count: int) -> _Cursor:
        return _Cursor(self.docs[:count])

    def __iter__(self):
        return iter(self.docs)


def _doc_matches(doc: dict, query: dict | None) -> bool:
    if not query:
        return True
    if "$and" in query:
        return all(_doc_matches(doc, part) for part in query["$and"] if isinstance(part, dict))
    if "$or" in query:
        return any(_doc_matches(doc, part) for part in query["$or"] if isinstance(part, dict))
    for key, expected in query.items():
        if str(key).startswith("$"):
            continue
        if isinstance(expected, dict):
            if "$ne" in expected and doc.get(key) == expected["$ne"]:
                return False
            if "$in" in expected and not any(
                doc.get(key) == item or str(doc.get(key)) == str(item) for item in expected["$in"]
            ):
                return False
            if "$eq" in expected and str(doc.get(key)) != str(expected["$eq"]):
                return False
            continue
        if doc.get(key) != expected and str(doc.get(key)) != str(expected):
            return False
    return True


class _Collection:
    def __init__(self, docs: list[dict] | None = None) -> None:
        self.docs = list(docs or [])

    def find(self, query: dict | None = None) -> _Cursor:
        return _Cursor([doc for doc in self.docs if _doc_matches(doc, query)])

    def find_one(self, query: dict) -> dict | None:
        for doc in self.docs:
            if _doc_matches(doc, query):
                return doc
        return None

    def replace_one(self, query: dict, doc: dict, upsert: bool = False) -> None:
        for index, existing in enumerate(self.docs):
            if _doc_matches(existing, query):
                self.docs[index] = doc
                return
        if upsert:
            self.docs.append(doc)

    def delete_many(self, query: dict) -> None:
        self.docs = [doc for doc in self.docs if not _doc_matches(doc, query)]

    def insert_many(self, rows: list[dict]) -> None:
        self.docs.extend(rows)

    def count_documents(self, query: dict) -> int:
        return sum(1 for doc in self.docs if _doc_matches(doc, query))


class _Database:
    def __init__(self) -> None:
        self.cols: dict[str, _Collection] = {}

    def __getitem__(self, name: str) -> _Collection:
        return self.cols.setdefault(name, _Collection())

    def list_collection_names(self) -> list[str]:
        return sorted(self.cols)


class _Client:
    def __init__(self) -> None:
        self.dbs: dict[str, _Database] = {}

    def __getitem__(self, name: str) -> _Database:
        return self.dbs.setdefault(name, _Database())


def setup_function() -> None:
    reset_index_state()


def test_saved_index_answers_from_a_second_load():
    docs = shop_documents()
    index = build_generic_index(docs, database="mare_shop", use_cache=False)
    client = _Client()
    save_generic_index(client, index, {name: {"complete": True} for name in docs})
    for name, rows in docs.items():
        client["mare_shop"][name].docs = rows

    loaded, scope = load_generic_index(client)
    assert loaded.database == "mare_shop"
    assert loaded.documents == {}
    assert scope["orders"]["complete"] is True
    assert any(plan.get("op") == "hop" for plan in loaded.plans)

    handlers = load_generic_handlers(client)
    found = handlers["search_information"](
        "sweater pilled after one wash",
        tenant_id="generic",
        scope=None,
        mode="lexical",
        limit=4,
    )
    bound = next(row for row in found["related_nodes"] if row["node_id"].endswith("ord_1044"))
    evidence = handlers["retrieve_evidence"](
        [bound["node_id"]],
        tenant_id="generic",
        query=None,
        max_documents=4,
    )
    assert evidence["documents"][0]["ref"]["document_id"] == "ord_1044"
    assert "shipped" in evidence["documents"][0]["text"]
    none = handlers["query_documents"](
        "mare_shop.refunds",
        {"sku": "sku_mug"},
        tenant_id="generic",
        projection=None,
        limit=5,
    )
    assert none["count"] == 0


def test_partial_scope_hides_documents_outside_the_index():
    docs = shop_documents()
    extra = {
        "_id": "ref_late",
        "order_id": "ord_2001",
        "sku": "sku_mug",
        "reason": "arrived cracked",
        "requested_at": datetime(2024, 4, 2),
    }
    index = build_generic_index(docs, database="mare_shop", use_cache=False)
    client = _Client()
    scope = {name: {"complete": True} for name in docs}
    scope["refunds"] = {"complete": False, "ids": ["ref_9"]}
    save_generic_index(client, index, scope)
    for name, rows in docs.items():
        client["mare_shop"][name].docs = list(rows)
    client["mare_shop"]["refunds"].docs.append(extra)
    handlers = load_generic_handlers(client)
    result = handlers["query_documents"](
        "mare_shop.refunds",
        {"sku": "sku_mug"},
        tenant_id="generic",
        projection=None,
        limit=5,
    )
    assert result["count"] == 0


def test_read_source_marks_a_short_read_incomplete():
    database = _Database()
    database["orders"].docs = [{"_id": "a"}, {"_id": "b"}]
    documents, scope = read_source(database, ["orders"], limit=1)
    assert [doc["_id"] for doc in documents["orders"]] == ["a"]
    assert scope["orders"]["complete"] is False
    assert scope["orders"]["ids"] == ["a"]


def test_index_database_saves_cards_for_a_later_load():
    docs = shop_documents()
    client = _Client()
    for name, rows in docs.items():
        client["mare_shop"][name].docs = list(rows)
    summary = index_database(client, "mare_shop")
    assert summary["documents"] == 5
    assert summary["cards"] >= 1
    loaded, scope = load_generic_index(client)
    assert loaded.database == "mare_shop"
    assert scope["refunds"]["complete"] is True


def test_connect_page_offers_index_and_ask():
    from app.api.generic_ui import PAGE

    assert "Connection string" in PAGE
    assert "already indexed" in PAGE
    assert "/ui/index" in PAGE
    assert "/ui/ask" in PAGE


def test_saved_summary_reports_an_existing_database_without_rereading_it():
    docs = shop_documents()
    client = _Client()
    for name, rows in docs.items():
        client["mare_shop"][name].docs = list(rows)
    index_database(client, "mare_shop")
    client["mare_shop"]["orders"].docs.clear()
    summary = saved_index_summary(client)
    assert summary is not None
    assert summary["already"] is True
    assert summary["database"] == "mare_shop"
    assert summary["cards"] >= 1
    assert saved_index_summary(_Client()) is None


def test_ui_index_returns_the_saved_catalog(monkeypatch):
    from app.api.generic_ui import IndexBody, build_index

    docs = shop_documents()
    client = _Client()
    for name, rows in docs.items():
        client["mare_shop"][name].docs = list(rows)
    index_database(client, "mare_shop")
    client.close = lambda: None

    def fail_rebuild(*_args, **_kwargs):
        raise AssertionError("index should not rebuild")

    monkeypatch.setattr("app.api.generic_ui._open", lambda _uri: client)
    monkeypatch.setattr("app.api.generic_ui.index_database", fail_rebuild)
    summary = build_index(IndexBody(uri="mongodb://example", database="mare_shop"))
    assert summary["already"] is True
    assert summary["database"] == "mare_shop"


def test_missing_catalog_raises():
    try:
        load_generic_index(_Client())
    except MissingGenericIndex as exc:
        assert "index_generic.py" in str(exc)
    else:
        raise AssertionError("expected MissingGenericIndex")


def test_date_and_object_id_queries_cover_both_storage_forms():
    query = _mongo_query(
        None,
        {"requested_at": {"$gte": "2024-04-01", "$lt": "2024-05-01"}},
        None,
    )
    assert "$or" in query
    stored = [clause["requested_at"]["$gte"] for clause in query["$or"]]
    assert "2024-04-01" in stored
    assert datetime(2024, 4, 1) in stored
    hex_id = "a" * 24
    by_id = _mongo_query([hex_id], None, None)
    assert ObjectId(hex_id) in by_id["_id"]["$in"]
