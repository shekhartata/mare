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


def test_compact_noop_on_prefix_only():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q"},
    ]
    assert compact_messages(messages) == messages
