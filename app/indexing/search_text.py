from __future__ import annotations

from datetime import datetime
from typing import Any


def compose_search_text(
    *,
    name: str,
    database: str,
    collection: str | None,
    description: str,
    summary: str,
    important_fields: list[str],
    entities: list[str],
    topics: list[str],
    representative_terms: list[str] | None = None,
) -> str:
    """PRD §8 — searchable representation is more than the LLM summary."""
    parts = [
        name,
        database,
        collection or "",
        description,
        summary,
        " ".join(important_fields),
        " ".join(entities[:40]),
        " ".join(topics),
        " ".join(representative_terms or []),
    ]
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        text = (part or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return " | ".join(out)


COLLECTION_TOPICS: dict[str, list[str]] = {
    "customers": [
        "accounts",
        "subscription",
        "tier",
        "region",
        "feature flags",
        "customer profile",
    ],
    "tickets": [
        "support",
        "authentication failures",
        "billing issues",
        "deployment problems",
        "severity",
    ],
    "deployments": [
        "rollouts",
        "failed deploys",
        "error codes",
        "migrations",
        "environments",
    ],
    "migrations": [
        "platform upgrades",
        "configuration changes",
        "cutover notes",
        "version changes",
    ],
    "incidents": [
        "outages",
        "root cause",
        "severity",
        "related tickets",
        "authentication",
        "billing",
    ],
    "logs": [
        "errors",
        "stack traces",
        "jwt",
        "tls",
        "rate limits",
        "webhooks",
        "iam",
    ],
}


def collection_description(name: str, schema: dict[str, Any]) -> str:
    topics = ", ".join(COLLECTION_TOPICS.get(name, []))
    fields = ", ".join(schema.get("important_fields", [])[:12])
    count = schema.get("document_count", 0)
    return (
        f"MongoDB collection '{name}' with approximately {count} documents. "
        f"Important fields: {fields}. Topics: {topics}."
    )


def database_description(collections: list[str]) -> str:
    return (
        "Synthetic SaaS operations database used to evaluate adaptive retrieval. "
        "Contains customers, support tickets, deployments, migrations, incidents, and logs. "
        f"Collections: {', '.join(collections)}."
    )


def month_key(ts: datetime) -> str:
    return ts.strftime("%Y-%m")
