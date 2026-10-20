"""Navigation vectors are saved at index time and are not rebuilt on ask."""

from app.config import get_settings
from app.datagen.shop_fixture import documents as shop_documents
from app.indexing.signals import build_generic_index, reset_index_state
from app.indexing.signals.nav_nodes import build_nav_nodes
from app.indexing.signals.store import (
    SemanticIndexError,
    load_generic_handlers,
    save_generic_index,
    upgrade_vectors,
)
from app.retrieval.generic_ask import run_saved_generic
from app.retrieval.generic_tools import GenericSurface
from tests.test_generic_store import _Client


class FakeEmbed:
    def __init__(self, model: str = "fake-embed") -> None:
        self.model = model
        self.dimensions = 3
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[float(len(text)), 1.0, 0.0] for text in texts]


def setup_function() -> None:
    reset_index_state()
    get_settings().generic_semantic_required = False


def _scope(docs: dict) -> dict:
    return {name: {"complete": True} for name in docs}


def test_build_persists_a_vector_for_every_node():
    docs = shop_documents()
    index = build_generic_index(docs, database="mare_shop", use_cache=False)
    embedder = FakeEmbed()
    client = _Client()
    saved = save_generic_index(client, index, _scope(docs), embedder=embedder)
    nodes = build_nav_nodes(index)
    assert saved["semantic"] == "ready"
    assert saved["embedded"] == len(nodes)
    assert saved["reused"] == 0
    stored = client["_agent_retrieval"]["generic_nav_vectors"].docs
    assert len(stored) == len(nodes)
    assert {row["node_id"] for row in stored} == {node["_id"] for node in nodes}


def test_reload_embeds_queries_only():
    docs = shop_documents()
    index = build_generic_index(docs, database="mare_shop", use_cache=False)
    embedder = FakeEmbed()
    client = _Client()
    save_generic_index(client, index, _scope(docs), embedder=embedder)
    embedder.calls.clear()
    handlers = load_generic_handlers(client, embedder)
    handlers["search_information"]("pilled", tenant_id="generic", scope=None, mode=None, limit=4)
    assert handlers.semantic["status"] == "ready"
    assert embedder.calls == [["pilled"]]
    assert handlers.surface.embed_calls["nodes"] == 0
    assert handlers.surface.embed_calls["queries"] == 1


def test_rebuild_reuses_unchanged_vectors():
    docs = shop_documents()
    index = build_generic_index(docs, database="mare_shop", use_cache=False)
    embedder = FakeEmbed()
    client = _Client()
    scope = _scope(docs)
    save_generic_index(client, index, scope, embedder=embedder)
    embedder.calls.clear()
    again = save_generic_index(client, index, scope, embedder=embedder)
    assert again["embedded"] == 0
    assert again["reused"] == len(build_nav_nodes(index))
    assert embedder.calls == []
    index.cards[0]["search_text"] += " unique-token"
    changed = save_generic_index(client, index, scope, embedder=embedder)
    assert changed["embedded"] == 1


def test_model_mismatch_does_not_mix_vectors():
    docs = shop_documents()
    index = build_generic_index(docs, database="mare_shop", use_cache=False)
    client = _Client()
    save_generic_index(client, index, _scope(docs), embedder=FakeEmbed("model-a"))
    other = FakeEmbed("model-b")
    handlers = load_generic_handlers(client, other)
    assert handlers.semantic["status"] == "unavailable"
    handlers["search_information"]("pilled", tenant_id="generic", scope=None, mode=None, limit=2)
    assert other.calls == []
    get_settings().generic_semantic_required = True
    try:
        load_generic_handlers(client, other)
    except SemanticIndexError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("expected SemanticIndexError")


def test_failed_publish_keeps_the_previous_build():
    docs = shop_documents()
    index = build_generic_index(docs, database="mare_shop", use_cache=False)
    client = _Client()
    scope = _scope(docs)
    first = save_generic_index(client, index, scope, embedder=FakeEmbed())
    cards = client["_agent_retrieval"]["generic_cards"]
    original = cards.insert_many

    def fail_next(rows: list[dict]) -> None:
        raise RuntimeError("write failed")

    cards.insert_many = fail_next
    try:
        save_generic_index(client, index, scope, embedder=FakeEmbed())
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected the write to fail")
    finally:
        cards.insert_many = original
    catalog = client["_agent_retrieval"]["generic_catalog"].find_one({"_id": "active"})
    assert catalog["build_id"] == first["build_id"]
    loaded, _scope_out = load_generic_handlers(client, FakeEmbed()), None
    assert loaded.semantic["status"] == "ready"


def test_legacy_catalog_stays_lexical_until_upgrade():
    docs = shop_documents()
    index = build_generic_index(docs, database="mare_shop", use_cache=False)
    client = _Client()
    client["_agent_retrieval"]["generic_catalog"].docs = [
        {
            "_id": "active",
            "database": "mare_shop",
            "profile": index.profile,
            "plans": index.plans,
            "text_fields": {},
            "scope": _scope(docs),
        }
    ]
    client["_agent_retrieval"]["generic_cards"].docs = [
        {"collection": card["collection"], **card} for card in index.cards
    ]
    embedder = FakeEmbed()
    handlers = load_generic_handlers(client, embedder)
    assert handlers.semantic["status"] == "unavailable"
    assert "legacy" in handlers.semantic["reason"]
    assert embedder.calls == []
    upgraded = upgrade_vectors(client, embedder)
    assert upgraded["embedded"] == len(build_nav_nodes(index))
    reloaded = load_generic_handlers(client, embedder)
    assert reloaded.semantic["status"] == "ready"


def test_fixed_vectors_rank_the_matching_card_first():
    docs = shop_documents()
    index = build_generic_index(docs, database="mare_shop", use_cache=False)
    nodes = build_nav_nodes(index)
    refund = next(
        node
        for node in nodes
        if node["node_type"] == "group" and node["source"]["collection"] == "refunds"
    )
    neutral = {node["_id"]: [0.0, 1.0, 0.0] for node in nodes}
    boosted = dict(neutral)
    boosted[refund["_id"]] = [1.0, 0.0, 0.0]

    class TowardRefund(FakeEmbed):
        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0, 0.0] for _text in texts]

    def order(vectors: dict[str, list[float]]) -> list[str]:
        surface = GenericSurface(index, vectors=vectors, query_embedder=TowardRefund())
        hits = surface.search_information(
            "zzzz", tenant_id=None, scope=None, mode=None, limit=8
        )
        return [row["node_id"] for row in hits["results"]]

    plain = order(neutral)
    lifted = order(boosted)
    assert lifted == order(boosted)
    assert lifted.index(refund["_id"]) < plain.index(refund["_id"])


def test_request_time_includes_handler_load(monkeypatch):
    def slow_load(client, embedder=None):
        del client, embedder
        from app.retrieval.tool_policy import ToolHandlers

        handlers = ToolHandlers({})
        handlers.semantic = {"status": "ready", "reason": ""}
        handlers.surface = None
        return handlers

    def fake_run(question, **kwargs):
        del kwargs
        from app.models.schemas import EvidenceSession

        return EvidenceSession(
            _id="sess_test", tenant_id="generic", question=question, elapsed_ms=5, answer="ok"
        )

    monkeypatch.setattr("app.retrieval.generic_ask.load_generic_handlers", slow_load)
    monkeypatch.setattr("app.retrieval.generic_ask.run_agent", fake_run)
    session, timing = run_saved_generic(object(), "question", None)
    assert session.answer == "ok"
    assert timing["request_ms"] >= timing["load_ms"]
    assert timing["index_status"]["status"] == "ready"
