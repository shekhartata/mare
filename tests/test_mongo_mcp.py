import json

from app.models.schemas import SessionStatus
from app.retrieval.mongo_mcp import TOOL_DEFINITIONS as MCP_TOOLS
from app.retrieval.mongo_mcp import find_tool
from tests.test_agent_loop import _response, _run, _tool_call

SUBMIT = {
    "answer": "18 customers are on the enterprise subscription tier.",
    "hypothesis": "Count from customers.find",
    "claims": [],
    "cited_source_ids": ["mare_demo.customers:cust_007"],
}


def test_mongo_mcp_tools_have_no_navigation():
    names = {t["function"]["name"] for t in MCP_TOOLS}
    assert names == {
        "list_databases",
        "list_collections",
        "collection_schema",
        "find",
        "count",
        "submit_answer",
    }
    assert "search_information" not in names
    assert "retrieve_evidence" not in names


def test_mongo_mcp_loop_find_count_submit():
    def handlers():
        return {
            "list_databases": lambda **kwargs: {"databases": ["mare_demo"]},
            "list_collections": lambda database, **kwargs: {
                "database": database,
                "collections": ["customers"],
            },
            "collection_schema": lambda namespace, **kwargs: {
                "namespace": namespace,
                "important_fields": ["subscription_tier"],
                "fields": [{"name": "subscription_tier", "example": "enterprise"}],
            },
            "find": lambda namespace, filter=None, **kwargs: {
                "count": 1,
                "namespace": namespace,
                "documents": [
                    {
                        "ref": {
                            "database": "mare_demo",
                            "collection": "customers",
                            "document_id": "cust_007",
                            "fields": [],
                        },
                        "text": "subscription_tier: enterprise",
                        "score": 1.0,
                    }
                ],
            },
            "count": lambda namespace, filter=None, **kwargs: {
                "count": 18,
                "namespace": namespace,
            },
        }

    session, client = _run(
        [
            _response([_tool_call("c1", "list_databases", {})]),
            _response(
                [_tool_call("c2", "list_collections", {"database": "mare_demo"})]
            ),
            _response(
                [_tool_call("c3", "find", {"namespace": "mare_demo.customers", "filter": {}})]
            ),
            _response([_tool_call("c4", "submit_answer", SUBMIT)]),
        ],
        handlers=handlers(),
        tool_surface="mongo_mcp",
    )
    assert session.status == SessionStatus.complete
    assert session.tool_calls == 4
    assert session.retrieval_count == 1
    assert session.citations[0].document_id == "cust_007"
    names = [
        n["function"]["name"]
        for n in client.calls[0]["tools"]
        if n.get("type") == "function"
    ]
    assert "search_information" not in names
    assert "find" in names
    assert "MongoDB assistant" in client.calls[0]["messages"][0]["content"]
    assert "search_information" not in json.dumps(client.calls[0]["messages"][0])


def test_find_rejects_navigation_database():
    out = find_tool("_agent_retrieval.navigation_nodes", {}, tenant_id="demo")
    assert "error" in out
