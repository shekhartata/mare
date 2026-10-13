"""Built-in providers. grouping_hints are returned and ignored by Phase 1."""

from __future__ import annotations

from typing import Any

from app.indexing.signals.contracts import SignalContext, envelope
from app.indexing.signals.discovery import fingerprint_profile
from app.indexing.signals.masking import assert_disclosed, masked_profile

OVERLAP_MIN = 0.8


class SchemaProfileProvider:
    name = "schema_profile"
    version = "1"
    requires = ()

    def evaluate(self, context: SignalContext) -> dict[str, Any]:
        claims = []
        for coll in context.profile.get("collections") or []:
            for field in coll.get("fields") or []:
                claims.append(
                    {
                        "collection": coll["name"],
                        "field": field["path"],
                        "role": "observed",
                        "status": "observed",
                        "evidence": f"profile:{coll['name']}:v1",
                    }
                )
        collections = context.profile.get("collections") or []
        inspected = sum(int(coll.get("inspected") or 0) for coll in collections)
        complete = all(coll.get("complete") for coll in collections)
        return envelope(
            provider=self.name,
            provider_version=self.version,
            scope={"database": context.database},
            input_fingerprint=fingerprint_profile(context.profile),
            status="ok",
            claims=claims,
            evidence_refs=[f"profile:{context.database}:v1"],
            coverage={"inspected_documents": inspected, "complete": complete},
        )


class SchemaLLMProvider:
    name = "schema_llm"
    version = "1"
    requires = ("schema_profile",)

    def evaluate(self, context: SignalContext) -> dict[str, Any]:
        masked = masked_profile(context.profile)
        forbidden = list(context.policy.get("forbidden_values") or [])
        assert_disclosed(masked, forbidden)
        if context.llm is None:
            return envelope(
                provider=self.name,
                provider_version=self.version,
                scope={"database": context.database},
                input_fingerprint=fingerprint_profile(context.profile),
                status="degraded",
                warnings=["schema model unavailable"],
                coverage={"complete": False},
            )
        try:
            raw = context.llm(masked)
        except Exception as exc:
            return envelope(
                provider=self.name,
                provider_version=self.version,
                scope={"database": context.database},
                input_fingerprint=fingerprint_profile(context.profile),
                status="degraded",
                warnings=[str(exc)],
                coverage={"complete": False},
            )
        claims = []
        routes = []
        if isinstance(raw, dict):
            for claim in raw.get("claims") or []:
                if isinstance(claim, dict):
                    claims.append({**claim, "status": "inferred"})
            for route in raw.get("route_candidates") or []:
                if isinstance(route, dict):
                    routes.append(route)
        return envelope(
            provider=self.name,
            provider_version=self.version,
            scope={"database": context.database},
            input_fingerprint=fingerprint_profile(context.profile),
            status="ok",
            claims=claims,
            route_candidates=routes,
            grouping_hints=[{"ignored": True}],
        )


class LexicalProvider:
    """Attest groups already built by the existing TF-IDF function. Does not regroup."""

    name = "lexical"
    version = "1"
    requires = ()

    def evaluate(self, context: SignalContext) -> dict[str, Any]:
        facets = []
        for collection, groups in context.groups.items():
            facets.append(
                {
                    "collection": collection,
                    "group_count": len(groups),
                    "group_ids": [g.get("key") for g in groups],
                }
            )
        return envelope(
            provider=self.name,
            provider_version=self.version,
            scope={"database": context.database},
            input_fingerprint=fingerprint_profile(context.profile),
            status="ok",
            card_facets=facets,
            grouping_hints=[],
        )


class RelationshipProbe:
    name = "relationship_probe"
    version = "1"
    requires = ("schema_profile",)

    def evaluate(self, context: SignalContext) -> dict[str, Any]:
        routes = []
        ids = {
            name: {str(doc.get("_id")) for doc in docs if doc.get("_id") is not None}
            for name, docs in context.documents.items()
        }
        for source, docs in context.documents.items():
            fields = _string_fields(docs)
            for field, values in fields.items():
                if not values:
                    continue
                for target, target_ids in ids.items():
                    if target == source or not target_ids:
                        continue
                    overlap = len(values & target_ids) / len(values)
                    status = "validated" if overlap >= OVERLAP_MIN else "unreviewed"
                    if status != "validated" and overlap <= 0:
                        continue
                    routes.append(
                        {
                            "op": "hop",
                            "from_collection": source,
                            "from_field": field,
                            "to_collection": target,
                            "to_field": "_id",
                            "overlap": round(overlap, 4),
                            "status": status,
                        }
                    )
        return envelope(
            provider=self.name,
            provider_version=self.version,
            scope={"database": context.database},
            input_fingerprint=fingerprint_profile(context.profile),
            status="ok",
            route_candidates=routes,
        )


def _string_fields(docs: list[dict[str, Any]]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for doc in docs:
        for key, value in doc.items():
            if key == "_id" or not isinstance(value, str):
                continue
            found.setdefault(key, set()).add(value)
    return found


def builtin_providers() -> list[Any]:
    return [
        SchemaProfileProvider(),
        SchemaLLMProvider(),
        LexicalProvider(),
        RelationshipProbe(),
    ]
