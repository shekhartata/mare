from typing import Any


def inject_tenant(filter_doc: dict[str, Any] | None, tenant_id: str) -> dict[str, Any]:
    """Authorization is never delegated to the model (PRD §22)."""
    scoped = dict(filter_doc or {})
    scoped["tenant_id"] = tenant_id
    return scoped


def sanitize_projection(projection: dict[str, Any] | None) -> dict[str, Any] | None:
    if not projection:
        return None
    cleaned = {k: v for k, v in projection.items() if not str(k).startswith("$")}
    return cleaned or None
