"""MARE MCP server — agent tool surface over MongoDB (PRD §11)."""

from __future__ import annotations

from typing import Any

try:
    from mcp.server.fastmcp import FastMCP as MCPServer
except ModuleNotFoundError:
    from mcp.server.mcpserver import MCPServer

from app.config import get_settings
from app.models.schemas import SearchMethod
from app.mongo.jsonutil import jsonable
from app.retrieval import tools as retrieval_tools
from app.retrieval.agent_loop import run_agent
from app.search import service as search_service

mcp = MCPServer(
    "mare",
    instructions=(
        "Mongo Adaptive Retrieval Engine. Navigate MongoDB via hierarchical nodes, "
        "then retrieve raw evidence with lexical/semantic/hybrid search or structured queries. "
        "Prefer structured queries when the need is a known field predicate. "
        "Every result includes a stable Mongo source reference. "
        "Use search_information then retrieve_evidence for multi-hop questions; "
        "use ask() to run the full agent loop."
    ),
)


def _tenant() -> str:
    return get_settings().tenant_id


@mcp.tool()
def list_databases() -> list[str]:
    """List databases reachable by MARE."""
    return search_service.list_databases()


@mcp.tool()
def list_collections(database: str) -> list[str]:
    """List collections in a MARE-reachable database."""
    return search_service.list_collections(database)


@mcp.tool()
def get_node(node_id: str) -> dict[str, Any]:
    """Fetch a navigation node by id. Raw customer data is not copied into the node."""
    node = search_service.get_node(node_id, _tenant())
    return jsonable(node) if node else {"error": "not found"}


@mcp.tool()
def get_children(node_id: str) -> list[dict[str, Any]]:
    """List child navigation nodes."""
    return jsonable(search_service.get_children(node_id, _tenant()))


@mcp.tool()
def search_information(
    query: str,
    scope: str | None = None,
    mode: str = "auto",
    limit: int = 8,
) -> dict[str, Any]:
    """High-level navigation search: route + search + children preview in one call."""
    return jsonable(
        retrieval_tools.search_information(
            query, tenant_id=_tenant(), scope=scope, mode=mode, limit=limit
        )
    )


@mcp.tool()
def retrieve_evidence(
    node_ids: list[str],
    query: str | None = None,
    max_documents: int = 8,
) -> dict[str, Any]:
    """Read raw Mongo documents for one or more navigation node ids (batched)."""
    return jsonable(
        retrieval_tools.retrieve_evidence(
            node_ids, tenant_id=_tenant(), query=query, max_documents=max_documents
        )
    )


@mcp.tool()
def lexical_search(query: str, scope: str | None = None, limit: int = 8) -> dict[str, Any]:
    """Lexical Atlas Search over navigation nodes. Best for ids, error codes, names."""
    method, hits = search_service.navigation_search(
        query, method=SearchMethod.lexical, tenant_id=_tenant(), scope=scope, limit=limit
    )
    return {"method": method.value, "results": jsonable(hits)}


@mcp.tool()
def semantic_search(query: str, scope: str | None = None, limit: int = 8) -> dict[str, Any]:
    """Semantic search over navigation representations (not raw chunks)."""
    method, hits = search_service.navigation_search(
        query, method=SearchMethod.semantic, tenant_id=_tenant(), scope=scope, limit=limit
    )
    return {"method": method.value, "results": jsonable(hits)}


@mcp.tool()
def hybrid_search(query: str, scope: str | None = None, limit: int = 8) -> dict[str, Any]:
    """Hybrid lexical + semantic search over navigation nodes."""
    method, hits = search_service.navigation_search(
        query, method=SearchMethod.hybrid, tenant_id=_tenant(), scope=scope, limit=limit
    )
    return {"method": method.value, "results": jsonable(hits)}


@mcp.tool()
def search_within(node_id: str, query: str, limit: int = 8) -> list[dict[str, Any]]:
    """Search raw Mongo documents inside a navigation node's region."""
    return jsonable(
        search_service.search_within(node_id, query, tenant_id=_tenant(), limit=limit)
    )


@mcp.tool()
def query_documents(
    namespace: str,
    filter: dict[str, Any] | None = None,
    projection: dict[str, Any] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Structured Mongo find. namespace is database.collection. Tenant is injected."""
    return jsonable(
        search_service.query_namespace(
            namespace, filter or {}, tenant_id=_tenant(), projection=projection, limit=limit
        )
    )


@mcp.tool()
def read_documents(
    namespace: str,
    ids: list[str],
    projection: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Read raw documents by id from database.collection. Tenant scope is injected server-side."""
    return jsonable(
        search_service.read_namespace(
            namespace, ids, tenant_id=_tenant(), projection=projection
        )
    )


@mcp.tool()
def ask(question: str) -> dict[str, Any]:
    """Run the agent retrieval loop and return a grounded answer with Mongo citations."""
    session = run_agent(question, tenant_id=_tenant())
    return {
        "session_id": session.id,
        "answer": session.answer,
        "status": session.status.value,
        "stop_reason": session.stop_reason,
        "hypothesis": session.hypothesis,
        "claims": [c.model_dump() for c in session.claims],
        "citations": [c.model_dump() for c in session.citations],
        "retrieval_count": session.retrieval_count,
        "tokens_consumed": session.tokens_consumed,
        "elapsed_ms": session.elapsed_ms,
        "agent_turns": session.agent_turns,
        "tool_calls": session.tool_calls,
        "llm_latency_ms": session.llm_latency_ms,
        "mongo_latency_ms": session.mongo_latency_ms,
        "router_recommendation": session.router_recommendation.value
        if session.router_recommendation
        else None,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
