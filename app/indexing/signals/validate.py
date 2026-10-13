"""Drop claims and routes the profile cannot support. The judge cannot add routes."""

from __future__ import annotations

from typing import Any

from app.indexing.signals.discovery import collection_names, field_paths

_OPS = {"find", "count", "hop", "search_cards"}


def validate_signals(
    profile: dict[str, Any],
    results: list[dict[str, Any]],
    *,
    judge: Any | None = None,
) -> dict[str, Any]:
    known_collections = collection_names(profile)
    claims: list[dict[str, Any]] = []
    routes: list[dict[str, Any]] = []
    facets: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for result in results:
        if result.get("status") == "degraded" and not result.get("claims"):
            continue
        for claim in result.get("claims") or []:
            collection = str(claim.get("collection") or "")
            field = str(claim.get("field") or "")
            if collection not in known_collections or (
                field and field not in field_paths(profile, collection)
            ):
                rejected.append({**claim, "status": "rejected", "reason": "unknown field"})
                continue
            claim = {**claim, "status": claim.get("status") or "inferred"}
            claims.append(claim)
        for route in result.get("route_candidates") or []:
            if not _route_ok(route, profile, known_collections):
                rejected.append({**route, "status": "rejected", "reason": "invalid route"})
                continue
            if route.get("status") != "validated":
                rejected.append({**route, "status": "unreviewed"})
                continue
            if route.get("op") and route["op"] not in _OPS:
                rejected.append({**route, "status": "rejected", "reason": "op not allowlisted"})
                continue
            routes.append(route)
        for facet in result.get("card_facets") or []:
            facets.append(facet)
    if judge is not None:
        claims = _apply_judge(claims, judge)
    return {"claims": claims, "routes": routes, "facets": facets, "rejected": rejected}


def _route_ok(route: dict[str, Any], profile: dict[str, Any], collections: set[str]) -> bool:
    source = str(route.get("from_collection") or route.get("collection") or "")
    if source not in collections:
        return False
    field = str(route.get("from_field") or route.get("field") or "")
    if field and field not in field_paths(profile, source):
        return False
    target = route.get("to_collection")
    if target is not None and str(target) not in collections:
        return False
    to_field = route.get("to_field")
    if target and to_field and str(to_field) not in field_paths(profile, str(target)):
        return False
    return True


def _apply_judge(claims: list[dict[str, Any]], judge: Any) -> list[dict[str, Any]]:
    reviewed = []
    try:
        verdicts = judge(claims)
    except Exception:
        return [{**c, "status": "unreviewed"} for c in claims]
    by_field = {str(v.get("field")): v for v in verdicts or [] if isinstance(v, dict)}
    for claim in claims:
        verdict = by_field.get(str(claim.get("field")))
        if verdict and verdict.get("status") == "rejected":
            continue
        reviewed.append(claim)
    return reviewed
