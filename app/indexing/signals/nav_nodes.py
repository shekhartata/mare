"""Canonical navigation nodes shared by index builds and asks."""

from __future__ import annotations

from typing import Any

NODE_BUILDER_VERSION = "1"
_SUMMARY = 480


def build_nav_nodes(index: Any) -> list[dict[str, Any]]:
    """Group cards and collection nodes. Ids and embedding text stay stable."""
    nodes: list[dict[str, Any]] = []
    fields_by_col = {
        str(coll["name"]): [
            str(field["path"])
            for field in coll.get("fields") or []
            if "." not in str(field["path"]) and "[]" not in str(field["path"])
        ]
        for coll in index.profile.get("collections") or []
    }
    for card in index.cards:
        collection = str(card["collection"])
        nodes.append(
            {
                "_id": f"card:{collection}:{card['key']}",
                "name": str(card.get("key")),
                "node_type": "group",
                "summary": str(card.get("search_text") or "")[:_SUMMARY],
                "search_text": str(card.get("search_text") or ""),
                "source": {
                    "database": index.database,
                    "collection": collection,
                    "filter": card.get("filter") or {},
                    "document_ids": list(card.get("document_ids") or []),
                },
                "schema": {"important_fields": fields_by_col.get(collection, [])[:12]},
                "metadata": {"document_count": len(card.get("document_ids") or [])},
            }
        )
    for coll in index.profile.get("collections") or []:
        name = str(coll["name"])
        fields = fields_by_col.get(name, [])
        nodes.append(
            {
                "_id": f"col:{name}",
                "name": name,
                "node_type": "collection",
                "summary": f"Collection {name}. Fields: {', '.join(fields[:12])}.",
                "search_text": " ".join([name, *fields]),
                "source": {
                    "database": index.database,
                    "collection": name,
                    "filter": {},
                    "document_ids": [],
                },
                "schema": {"important_fields": fields[:12]},
                "metadata": {
                    "document_count": coll.get("population") or coll.get("inspected") or 0
                },
            }
        )
    return nodes
