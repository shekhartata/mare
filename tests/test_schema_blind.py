import json

from app.eval.scoring import answer_scores
from app.retrieval.tools import (
    TOOL_DEFINITIONS,
    _brief_node,
    extract_entity_ids,
    related_nodes_for,
    select_related_nodes,
)

SCHEMA_LEAKS = (
    "mare_demo",
    "customers",
    "tickets",
    "deployments",
    "migrations",
    "incidents",
    "subscription_tier",
    "customer_id",
    "error_code",
)


def test_tool_schemas_do_not_leak_dataset_names():
    blob = json.dumps(TOOL_DEFINITIONS).lower()
    for token in SCHEMA_LEAKS:
        assert token not in blob, token


def test_brief_node_exposes_schema_fields():
    brief = _brief_node(
        {
            "_id": "nav:col:db:accounts",
            "name": "accounts",
            "node_type": "collection",
            "summary": "Account records",
            "source": {"database": "ops", "collection": "accounts", "filter": {}, "document_ids": []},
            "schema": {
                "important_fields": ["tier", "region", "manager"],
                "field_descriptions": {"tier": "enterprise", "region": "us-east-1"},
            },
            "metadata": {"document_count": 18, "time_min": "2024-01-01", "time_max": "2024-06-01"},
        }
    )
    assert brief["important_fields"] == ["tier", "region", "manager"]
    assert brief["field_examples"]["tier"] == "enterprise"
    assert brief["document_count"] == 18
    assert brief["time_min"] == "2024-01-01"


def test_extract_entity_ids_from_nodes_and_docs():
    nodes = [
        {
            "source": {"filter": {"customer_id": "cust_007"}, "document_ids": []},
            "metadata": {"entities": ["cust_007", "2024-05"]},
        }
    ]
    docs = [
        {
            "ref": {"collection": "customers", "document_id": "cust_007"},
            "text": "account_manager: Elena Rossi",
        }
    ]
    assert extract_entity_ids(nodes=nodes, documents=docs) == ["cust_007"]


def test_select_related_nodes_picks_other_collections():
    candidates = [
        {
            "_id": "nav:group:deployments:cust_007",
            "node_type": "group",
            "source": {
                "collection": "deployments",
                "filter": {"customer_id": "cust_007"},
            },
            "metadata": {"entities": ["cust_007"]},
        },
        {
            "_id": "nav:group:tickets:cust_007",
            "node_type": "group",
            "source": {
                "collection": "tickets",
                "filter": {"customer_id": "cust_007"},
            },
            "metadata": {"entities": ["cust_007"]},
        },
        {
            "_id": "nav:group:customers:cust_007",
            "node_type": "document",
            "source": {
                "collection": "customers",
                "document_ids": ["cust_007"],
                "filter": {},
            },
            "metadata": {"entities": ["cust_007"]},
        },
        {
            "_id": "nav:group:deployments:cust_004",
            "node_type": "group",
            "source": {
                "collection": "deployments",
                "filter": {"customer_id": "cust_004"},
            },
            "metadata": {"entities": ["cust_004"]},
        },
    ]
    picked = select_related_nodes(
        candidates,
        entities=["cust_007"],
        exclude_ids={"nav:group:customers:cust_007"},
        exclude_collections={"customers"},
        limit=6,
    )
    ids = [n["_id"] for n in picked]
    assert "nav:group:deployments:cust_007" in ids
    assert "nav:group:tickets:cust_007" in ids
    assert "nav:group:customers:cust_007" not in ids
    assert "nav:group:deployments:cust_004" not in ids


def test_related_nodes_for_uses_injected_candidates():
    origin = {
        "_id": "nav:doc:customers:cust_007",
        "node_type": "document",
        "name": "Apex",
        "source": {
            "database": "ops",
            "collection": "customers",
            "document_ids": ["cust_007"],
            "filter": {},
        },
        "metadata": {"entities": ["cust_007"], "document_count": 1},
        "schema": {"important_fields": ["tier"]},
    }
    sibling = {
        "_id": "nav:group:deployments:cust_007",
        "node_type": "group",
        "name": "deployments for cust_007",
        "source": {
            "database": "ops",
            "collection": "deployments",
            "filter": {"customer_id": "cust_007"},
            "document_ids": [],
        },
        "metadata": {"entities": ["cust_007"], "document_count": 2},
        "schema": {"important_fields": ["status"]},
    }
    related = related_nodes_for(
        tenant_id="demo",
        nodes=[origin],
        candidates=[origin, sibling],
    )
    assert len(related) == 1
    assert related[0]["node_id"] == "nav:group:deployments:cust_007"
    assert related[0]["source"]["collection"] == "deployments"
    assert "important_fields" in related[0]


def test_grouped_scoring_requires_entity_and_cause():
    spec = {
        "must_contain_groups": [
            ["cust_007", "apex"],
            ["auth_401", "issuer", "mig_auth_sso", "sso"],
        ]
    }
    entity_only = answer_scores(
        "The customer is Apex Logistics (cust_007). Root cause unknown.", spec
    )
    assert entity_only["entity_found"] is True
    assert entity_only["cause_found"] is False
    assert entity_only["correct"] is False
    both = answer_scores(
        "Apex (cust_007) failed after mig_auth_sso with AUTH_401 issuer mismatch.", spec
    )
    assert both["entity_found"] is True
    assert both["cause_found"] is True
    assert both["correct"] is True
    cause_only = answer_scores("AUTH_401 after SSO issuer change.", spec)
    assert cause_only["entity_found"] is False
    assert cause_only["correct"] is False


def test_negative_scoring_allows_subject_incidents_not_foreign():
    spec = {
        "must_contain_any": ["no", "none", "zero"],
        "no_foreign_incident_cites": True,
        "allowed_incident_cites": ["inc_20006", "inc_20051"],
        "_citations": [
            {"collection": "incidents", "document_id": "inc_20006"},
        ],
    }
    grounded = answer_scores("No incidents in April 2024.", spec)
    assert grounded["foreign_incident_cites"] == []
    assert grounded["correct"] is True
    spec["_citations"] = [{"collection": "incidents", "document_id": "inc_20044"}]
    leaked = answer_scores("No. April incidents belong to other customers.", spec)
    assert leaked["foreign_incident_cites"] == ["incidents:inc_20044"]
    assert leaked["correct"] is False
