"""Phase 1 generic index. The SaaS tool loop is not on this path."""

import json

import pytest

from app.config import Settings
from app.datagen.shop_fixture import GOLD as SHOP_GOLD
from app.datagen.shop_fixture import documents as shop_documents
from app.datagen.warehouse_fixture import GOLD as WAREHOUSE_GOLD
from app.datagen.warehouse_fixture import documents as warehouse_documents
from app.indexing.semantic_grouping import semantic_groups_from_docs
from app.indexing.signals import (
    active_generation,
    build_generic_index,
    reset_index_state,
    rollback_generation,
)
from app.indexing.signals.contracts import envelope
from app.indexing.signals.masking import DisclosureError, assert_disclosed, mask_document
from app.indexing.signals.registry import register
from app.retrieval.tools import TOOL_DEFINITIONS


@pytest.fixture(autouse=True)
def _clean_index():
    reset_index_state()
    yield
    reset_index_state()


def test_generic_index_defaults_off_and_demo_tools_stay():
    assert Settings.model_fields["generic_index"].default is False
    assert Settings.model_fields["generic_sample_size"].default == 1000
    names = {tool["function"]["name"] for tool in TOOL_DEFINITIONS}
    assert "search_information" in names
    assert "retrieve_evidence" in names


def test_masked_profile_hides_values_and_dynamic_keys():
    secret = "sweater-pilled-secret"
    masked = mask_document(
        {"_id": "ord_1044", "note": secret, "user_9f3a2b1c": "raw-value"}
    )
    blob = json.dumps(masked)
    assert secret not in blob
    assert "ord_1044" not in blob
    assert "raw-value" not in blob
    assert masked["note"] == "string"
    assert "dynamic_key" in masked
    assert_disclosed(masked, [secret, "ord_1044"])
    with pytest.raises(DisclosureError):
        assert_disclosed({"note": secret}, [secret])


def test_schema_model_sees_types_only():
    secret = "do-not-disclose-this"
    seen = []

    def llm(payload):
        seen.append(payload)
        return {"claims": []}

    docs = shop_documents()
    docs["refunds"][0]["reason"] = secret
    build_generic_index(docs, database="mare_shop", llm=llm, policy={"forbidden_values": [secret]})
    assert seen
    blob = json.dumps(seen[0])
    assert secret not in blob
    assert "ord_1044" not in blob
    assert "sku_wool" not in blob


def test_enrichment_does_not_change_group_membership():
    docs = [
        {
            "_id": "n1",
            "title": "wool pilling",
            "description": "sweater pilled after one wash",
            "resolution": "replaced",
        },
        {
            "_id": "n2",
            "title": "mug crack",
            "description": "handle broke in transit",
            "resolution": "refunded",
        },
    ]
    fields = ("title", "description", "resolution")
    direct = semantic_groups_from_docs(
        docs, tenant_id="generic", collection="notes", text_fields=fields
    )

    def llm(_payload):
        return {"grouping_hints": [{"ignored": True}], "claims": []}

    enriched = build_generic_index(
        {"notes": docs},
        database="parity",
        text_field_overrides={"notes": fields},
        llm=llm,
    )
    plain = build_generic_index(
        {"notes": docs},
        database="parity",
        text_field_overrides={"notes": fields},
        llm=None,
        use_cache=False,
    )

    def membership(groups):
        return {frozenset(group["document_ids"]) for group in groups}

    assert membership(direct) == membership(enriched.groups["notes"])
    assert membership(enriched.groups["notes"]) == membership(plain.groups["notes"])
    assert "tenant_id" not in enriched.cards[0]["filter"]
    shop = build_generic_index(shop_documents(), database="mare_shop", use_cache=False)
    assert "pilled" in json.dumps(shop.groups["refunds"]).lower()
    empty = build_generic_index(
        {"moves": [{"_id": "m1", "qty": 1}]},
        database="empty_text",
        text_field_overrides={"moves": ()},
        use_cache=False,
    )
    assert empty.groups["moves"] == []
    assert empty.text_fields["moves"] == ()


def test_extra_providers_register_without_orchestrator_edits():
    class Mark:
        def __init__(self, name: str) -> None:
            self.name = name
            self.version = "1"
            self.requires = ()

        def evaluate(self, context):
            return envelope(
                provider=self.name,
                provider_version="1",
                scope={"database": context.database},
                input_fingerprint="mark",
                status="ok",
            )

    register(Mark("mark_a"))
    register(Mark("mark_b"))
    index = build_generic_index(
        shop_documents(),
        database="mare_shop",
        providers=["schema_profile", "mark_a", "mark_b"],
    )
    assert [row["provider"] for row in index.signals] == ["schema_profile", "mark_a", "mark_b"]


def test_hallucinated_fields_and_unreviewed_routes_are_not_executable():
    def llm(_payload):
        return {
            "claims": [{"collection": "refunds", "field": "not_a_field", "role": "join"}],
            "route_candidates": [
                {
                    "op": "hop",
                    "from_collection": "refunds",
                    "from_field": "imaginary",
                    "to_collection": "nowhere",
                    "to_field": "_id",
                    "status": "validated",
                }
            ],
        }

    def judge(claims):
        return [{"field": "invented_field", "status": "validated"}]

    index = build_generic_index(shop_documents(), database="mare_shop", llm=llm, judge=judge)
    blob = json.dumps(index.plans)
    assert "not_a_field" not in blob
    assert "imaginary" not in blob
    assert "nowhere" not in blob
    assert "invented_field" not in json.dumps(index.validation["claims"])
    weak = {
        "left": [
            {"_id": "left_1", "ref": "right_1"},
            {"_id": "left_2", "ref": "no_match"},
        ],
        "right": [{"_id": "right_1", "name": "kept"}],
    }
    probed = build_generic_index(weak, database="overlap", use_cache=False)
    assert all(plan.get("to_collection") != "right" for plan in probed.plans if plan["op"] == "hop")


def test_provider_failure_leaves_structural_plans():
    class Boom:
        name = "boom"
        version = "1"
        requires = ()

        def evaluate(self, _context):
            raise RuntimeError("provider down")

    register(Boom())

    def llm(_payload):
        raise RuntimeError("model down")

    index = build_generic_index(
        shop_documents(),
        database="mare_shop",
        providers=["schema_profile", "schema_llm", "lexical", "boom"],
        llm=llm,
    )
    by_name = {row["provider"]: row for row in index.signals}
    assert by_name["schema_llm"]["status"] == "degraded"
    assert by_name["boom"]["status"] == "degraded"
    assert by_name["schema_profile"]["status"] == "ok"
    assert any(plan["op"] == "find" for plan in index.plans)


def test_sample_budget_marks_incomplete_coverage():
    docs = [{"_id": f"d{i}", "note": f"note {i}"} for i in range(5)]
    index = build_generic_index({"notes": docs}, database="sample", sample_size=2)
    coll = index.profile["collections"][0]
    assert coll["inspected"] == 2
    assert coll["complete"] is False
    profile_signal = next(row for row in index.signals if row["provider"] == "schema_profile")
    assert profile_signal["coverage"]["complete"] is False


def test_same_profile_reuses_schema_model_cache():
    calls = []

    def llm(payload):
        calls.append(payload)
        return {"claims": []}

    build_generic_index(shop_documents(), database="mare_shop", llm=llm)
    build_generic_index(shop_documents(), database="mare_shop", llm=llm)
    assert len(calls) == 1


def test_failed_generation_does_not_replace_active_and_rollback_restores():
    first = build_generic_index(shop_documents(), database="mare_shop")
    active = active_generation()
    assert active == first.generation_id
    build_generic_index(
        warehouse_documents(),
        database="mare_warehouse",
        policy={"force_fail": True},
        use_cache=False,
    )
    assert active_generation() == active
    second = build_generic_index(warehouse_documents(), database="mare_warehouse")
    assert active_generation() == second.generation_id
    assert rollback_generation() == active


def test_shop_and_warehouse_gold_questions():
    cases = (
        ("mare_shop", shop_documents(), SHOP_GOLD),
        ("mare_warehouse", warehouse_documents(), WAREHOUSE_GOLD),
    )
    for database, docs, gold in cases:
        index = build_generic_index(docs, database=database, use_cache=False)
        assert index.traces == []
        for question, expect_ids, expect_count in gold:
            result = index.investigate(question)
            receipt = result["evidence_receipt"]
            assert receipt["exhaustive_database"] is False
            assert receipt["generation_id"] == index.generation_id
            if expect_ids is not None:
                assert tuple(result["document_ids"]) == tuple(expect_ids)
            if expect_count is not None:
                assert result["count"] == expect_count
                assert receipt["exact"] is True
                if expect_count == 0:
                    assert receipt["absence_scope"] == "collection"
                    assert receipt["coverage"] == "exact"
            else:
                assert receipt["fallback"] is False
        assert index.traces
