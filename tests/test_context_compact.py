import json

from app.retrieval.context_compact import assert_tool_pairing, compact_messages, estimate_tokens


def _assistant(call_id: str, name: str) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": "{}"},
            }
        ],
    }


def _tool(call_id: str, payload: dict) -> dict:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps(payload),
    }


def test_compact_keeps_pairing_and_node_ids():
    fat_search = {
        "method": "hybrid",
        "count": 1,
        "results": [
            {
                "node_id": "nav:group:cust_007",
                "name": "logs",
                "node_type": "group",
                "summary": "x" * 4000,
                "source": {"database": "mare_demo", "collection": "logs", "filter": {}},
                "important_fields": ["error_code", "customer_id"],
            }
        ],
        "related_nodes": [
            {
                "node_id": "nav:group:tix",
                "name": "tickets",
                "source": {"collection": "tickets"},
            }
        ],
    }
    docs = {
        "count": 1,
        "documents": [
            {
                "ref": {
                    "database": "mare_demo",
                    "collection": "logs",
                    "document_id": "log_1001",
                },
                "text": "AUTH_401 " + ("y" * 2000),
            }
        ],
    }
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "why did logins fail?"},
        _assistant("c1", "search_information"),
        _tool("c1", fat_search),
        _assistant("c2", "retrieve_evidence"),
        _tool("c2", docs),
    ]
    before = estimate_tokens(messages)
    out = compact_messages(messages, token_budget=8000)
    assert_tool_pairing(out)
    blob = json.dumps(out)
    assert "nav:group:cust_007" in blob
    assert "error_code" in blob
    assert "nav:group:tix" in blob
    assert "log_1001" in blob
    assert estimate_tokens(out) < before
    assert "xxxx" not in json.loads(out[3]["content"]).get("results", [{}])[0].get("summary", "")


def test_compact_keeps_a_document_returned_with_search_hits():
    payload = {
        "method": "hybrid",
        "count": 1,
        "documents": [
            {
                "ref": {
                    "database": "mi_transformation",
                    "collection": "api_loan_instances",
                    "document_id": "415c5349-d293-5e99-9e29-34949c4b8c54",
                },
                "text": (
                    "underwriting.desktopUnderwriterRecommendationType: APPROVE-ELIGIBLE\n"
                    + ("x" * 3000)
                ),
            }
        ],
        "results": [
            {
                "node_id": "card:api_loan_instances:sem:root:p0",
                "name": "sem:root:p0",
                "source": {
                    "collection": "api_loan_instances",
                    "filter": {"_id": {"$in": [f"id-{i}" for i in range(5000)]}},
                },
            }
        ],
        "related_nodes": [],
    }
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "recommendation"},
        _assistant("c1", "search_information"),
        _tool("c1", payload),
    ]
    out = compact_messages(messages, token_budget=8000)
    seen = json.loads(out[-1]["content"])
    assert "APPROVE-ELIGIBLE" in seen["documents"][0]["text"]
    assert seen["results"][0]["source"]["filter"] == {}
    assert "id-4999" not in out[-1]["content"]


def test_older_receipt_keeps_every_document_whole():
    partner = "status: Active\nmismo_version: 3.4\n" + ("p" * 500)
    instance = (
        "underwriting.automated_underwriting_response_type: ReferEligible\n"
        "terms_of_loan.loan_purpose_type: Refinance\n"
        "terms_of_loan.mortgage_type: Conventional\n"
        + ("i" * 800)
    )
    retrieve = {
        "count": 2,
        "documents": [
            {
                "ref": {
                    "database": "mi_transformation",
                    "collection": "trading_partners",
                    "document_id": "A0000142",
                },
                "text": partner,
            },
            {
                "ref": {
                    "database": "mi_transformation",
                    "collection": "loan_instances",
                    "document_id": "00000ca5-ce7c-478a-bce9-9d739bd47d42",
                },
                "text": instance,
            },
        ],
    }
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "compare the loan instance with the loan"},
        _assistant("c1", "retrieve_evidence"),
        _tool("c1", retrieve),
        _assistant("c2", "search_information"),
        _tool("c2", {"method": "hybrid", "count": 0, "results": [], "related_nodes": []}),
    ]
    out = compact_messages(messages, token_budget=8000)
    seen = json.loads(out[3]["content"])
    texts = [doc["text"] for doc in seen["documents"]]
    assert "Active" in texts[0]
    assert "ReferEligible" in texts[1]
    assert "Refinance" in texts[1]
    assert "Conventional" in texts[1]
    assert seen["documents"][1]["ref"]["document_id"] == "00000ca5-ce7c-478a-bce9-9d739bd47d42"


def test_compact_noop_on_prefix_only():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q"},
    ]
    assert compact_messages(messages) == messages
