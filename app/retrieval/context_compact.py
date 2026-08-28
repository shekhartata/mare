"""Protocol-safe compaction of the MARE tool-loop transcript.

ACGC's GetState RPC does not return node bodies, so MARE compact the OpenAI
`messages` here (receipts for old tool JSON) and only uses the sidecar to
capture events / trigger GC / read metrics.
"""

from __future__ import annotations

import json
from typing import Any

RECEIPT_CHARS = 1_200
LAST_ROUND_CHARS = 8_000
FORCE_MARKER = "You have reached the retrieval budget"


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    return max(1, len(json.dumps(messages, default=str)) // 4)


def compact_messages(
    messages: list[dict[str, Any]],
    *,
    token_budget: int = 8_000,
) -> list[dict[str, Any]]:
    """Keep system + question + tool_call pairing; stub older tool payloads."""
    if len(messages) <= 2:
        return [dict(m) for m in messages]

    prefix, body, force = _split(messages)
    if not body:
        return [dict(m) for m in prefix] + [dict(m) for m in force]

    last_start = _last_assistant_index(body)
    compacted: list[dict[str, Any]] = [dict(m) for m in prefix]
    for i, msg in enumerate(body):
        item = dict(msg)
        if item.get("role") == "tool":
            cap = LAST_ROUND_CHARS if i >= last_start else RECEIPT_CHARS
            item["content"] = _receipt(str(item.get("content") or ""), cap=cap)
        compacted.append(item)

    out = compacted + [dict(m) for m in force]
    if estimate_tokens(out) <= token_budget:
        return out
    tighter: list[dict[str, Any]] = []
    for msg in out:
        item = dict(msg)
        if item.get("role") == "tool":
            item["content"] = _receipt(str(item.get("content") or ""), cap=RECEIPT_CHARS)
        tighter.append(item)
    return tighter


def receipt_payload(result: dict[str, Any] | str, *, cap: int = RECEIPT_CHARS) -> str:
    if isinstance(result, str):
        return _receipt(result, cap=cap)
    return json.dumps(_brief(result), default=str)[:cap]


def assert_tool_pairing(messages: list[dict[str, Any]]) -> None:
    pending: set[str] = set()
    for msg in messages:
        role = msg.get("role")
        if role == "assistant":
            pending = {
                str(tc.get("id") or "")
                for tc in (msg.get("tool_calls") or [])
                if isinstance(tc, dict) and tc.get("id")
            }
            continue
        if role == "tool":
            tid = str(msg.get("tool_call_id") or "")
            if tid not in pending:
                raise AssertionError(f"tool message {tid!r} has no matching assistant tool_call")
            pending.discard(tid)


def _split(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    prefix = [messages[0]]
    i = 1
    if i < len(messages) and messages[i].get("role") == "user":
        prefix.append(messages[i])
        i += 1
    rest = list(messages[i:])
    force: list[dict[str, Any]] = []
    if rest and rest[-1].get("role") == "user":
        content = str(rest[-1].get("content") or "")
        if content.startswith(FORCE_MARKER) or "retrieval budget" in content:
            force = [rest[-1]]
            rest = rest[:-1]
    return prefix, rest, force


def _last_assistant_index(body: list[dict[str, Any]]) -> int:
    for i in range(len(body) - 1, -1, -1):
        if body[i].get("role") == "assistant" and body[i].get("tool_calls"):
            return i
    return len(body)


def _receipt(content: str, *, cap: int) -> str:
    text = content.strip()
    if not text:
        return text
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text[:cap]
    if isinstance(data, dict) and data.get("compacted"):
        return json.dumps(data, default=str)[:cap]
    brief = _brief(data) if isinstance(data, dict) else {"preview": str(data)[:400]}
    brief["compacted"] = True
    return json.dumps(brief, default=str)[:cap]


def _brief(data: dict[str, Any]) -> dict[str, Any]:
    if "results" in data:
        related = [_related(n) for n in (data.get("related_nodes") or [])[:8] if isinstance(n, dict)]
        return {
            "method": data.get("method"),
            "count": data.get("count"),
            "results": [_node(n) for n in (data.get("results") or [])[:8] if isinstance(n, dict)],
            "related_nodes": related,
        }
    if "documents" in data:
        related = [_related(n) for n in (data.get("related_nodes") or [])[:8] if isinstance(n, dict)]
        docs = []
        for d in (data.get("documents") or [])[:8]:
            if not isinstance(d, dict):
                continue
            ref = d.get("ref") or {}
            docs.append(
                {
                    "ref": {
                        "database": ref.get("database"),
                        "collection": ref.get("collection"),
                        "document_id": ref.get("document_id"),
                    },
                    "text": str(d.get("text") or "")[:280],
                }
            )
        out: dict[str, Any] = {"count": data.get("count"), "documents": docs}
        if data.get("namespace"):
            out["namespace"] = data.get("namespace")
        if related:
            out["related_nodes"] = related
        if data.get("missing_nodes"):
            out["missing_nodes"] = data.get("missing_nodes")
        return out
    if data.get("error"):
        return {"error": str(data["error"])[:400]}
    return {k: data[k] for k in list(data)[:8]}


def _node(node: dict[str, Any]) -> dict[str, Any]:
    source = node.get("source") or {}
    out: dict[str, Any] = {
        "node_id": node.get("node_id") or node.get("_id"),
        "name": node.get("name"),
        "node_type": node.get("node_type"),
        "source": {
            "database": source.get("database"),
            "collection": source.get("collection"),
            "filter": source.get("filter") or {},
        },
        "important_fields": list(node.get("important_fields") or [])[:12],
    }
    if node.get("field_examples"):
        out["field_examples"] = node.get("field_examples")
    return out


def _related(node: dict[str, Any]) -> dict[str, Any]:
    source = node.get("source") or {}
    return {
        "node_id": node.get("node_id") or node.get("_id"),
        "name": node.get("name"),
        "collection": source.get("collection"),
    }
