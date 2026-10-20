"""Handler policies and the reference ledger for one ask. The model does not set these."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


class ToolHandlers(dict):
    """Handlers plus policies that name the exact callable that was reviewed."""

    def __init__(self, mapping: dict[str, Any]) -> None:
        super().__init__(mapping)
        self.policies: dict[str, ToolPolicy] = {}
        self.semantic: dict[str, Any] = {}
        self.surface: Any = None


@dataclass(frozen=True)
class ToolPolicy:
    read_only: bool
    concurrent_safe: bool
    barrier: bool
    validate: Callable[[dict[str, Any], Ledger], str | None]
    handler: Callable[..., Any]


@dataclass
class Ledger:
    node_ids: set[str] = field(default_factory=set)
    namespaces: set[str] = field(default_factory=set)


def absorb(ledger: Ledger, result: Any) -> None:
    """Record node ids and namespaces that a finished tool actually returned."""
    if not isinstance(result, dict):
        return
    for row in list(result.get("results") or []) + list(result.get("related_nodes") or []):
        if isinstance(row, dict):
            _take_node(ledger, row)
    for doc in result.get("documents") or []:
        if not isinstance(doc, dict):
            continue
        ref = doc.get("ref") or {}
        _namespace(ledger, ref.get("database"), ref.get("collection"))
    namespace = result.get("namespace")
    if isinstance(namespace, str) and "." in namespace:
        ledger.namespaces.add(namespace)


def validate_search(args: dict[str, Any], ledger: Ledger) -> str | None:
    if not str(args.get("query") or "").strip():
        return "query is empty"
    scope = args.get("scope")
    if scope and str(scope) not in ledger.node_ids:
        return "scope was not returned by an earlier tool"
    return None


def validate_retrieve(args: dict[str, Any], ledger: Ledger) -> str | None:
    ids = [str(node_id) for node_id in (args.get("node_ids") or []) if node_id]
    if not ids:
        return "node_ids is empty"
    missing = [node_id for node_id in ids if node_id not in ledger.node_ids]
    if missing:
        return "node id was not returned by an earlier tool"
    return None


def validate_query(args: dict[str, Any], ledger: Ledger) -> str | None:
    namespace = str(args.get("namespace") or "")
    if "." not in namespace:
        return "namespace must be database.collection"
    if namespace not in ledger.namespaces:
        return "namespace was not returned by an earlier tool"
    blob = json.dumps(args.get("filter") or {})
    if "$where" in blob or "$expr" in blob or "$function" in blob:
        return "operator not allowlisted"
    return None


def _take_node(ledger: Ledger, row: dict[str, Any]) -> None:
    if row.get("node_id"):
        ledger.node_ids.add(str(row["node_id"]))
    source = row.get("source") or {}
    _namespace(ledger, source.get("database"), source.get("collection"))


def _namespace(ledger: Ledger, database: Any, collection: Any) -> None:
    if database and collection:
        ledger.namespaces.add(f"{database}.{collection}")
