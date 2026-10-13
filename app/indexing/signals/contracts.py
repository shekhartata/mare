"""Versioned envelopes for generic indexing. Providers cannot mutate cards."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

CONTRACT_VERSION = "1"


class SignalProvider(Protocol):
    name: str
    version: str
    requires: tuple[str, ...]

    def evaluate(self, context: SignalContext) -> dict[str, Any]: ...


class SignalContext:
    def __init__(
        self,
        *,
        database: str,
        documents: dict[str, list[dict[str, Any]]],
        profile: dict[str, Any],
        text_fields: dict[str, tuple[str, ...]],
        groups: dict[str, list[dict[str, Any]]] | None = None,
        llm: Any | None = None,
        judge: Any | None = None,
        policy: dict[str, Any] | None = None,
    ) -> None:
        self.database = database
        self.documents = documents
        self.profile = profile
        self.text_fields = text_fields
        self.groups = groups or {}
        self.llm = llm
        self.judge = judge
        self.policy = policy or {}


def envelope(
    *,
    provider: str,
    provider_version: str,
    scope: dict[str, Any],
    input_fingerprint: str,
    status: str,
    claims: list[dict[str, Any]] | None = None,
    card_facets: list[dict[str, Any]] | None = None,
    route_candidates: list[dict[str, Any]] | None = None,
    grouping_hints: list[dict[str, Any]] | None = None,
    evidence_refs: list[str] | None = None,
    coverage: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "provider": provider,
        "provider_version": provider_version,
        "scope": scope,
        "input_fingerprint": input_fingerprint,
        "status": status,
        "claims": claims or [],
        "card_facets": card_facets or [],
        "route_candidates": route_candidates or [],
        "grouping_hints": grouping_hints or [],
        "evidence_refs": evidence_refs or [],
        "coverage": coverage or {"inspected_documents": 0, "complete": False},
        "warnings": warnings or [],
        "created_at": datetime.now(UTC).isoformat(),
    }


def evidence_receipt(
    *,
    generation_id: str,
    plan_id: str | None,
    fallback: bool,
    exact: bool,
    collections_checked: list[str],
    document_ids: list[str],
    count: int | None,
    absence_scope: str | None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """A live read over one checked scope. Never a database-wide absence claim."""
    return {
        "generation_id": generation_id,
        "plan_id": plan_id,
        "fallback": fallback,
        "exact": exact,
        "exhaustive_database": False,
        "absence_scope": absence_scope,
        "collections_checked": collections_checked,
        "document_ids": document_ids,
        "count": count,
        "coverage": "exact" if exact else "incomplete",
        "warnings": warnings or [],
    }
