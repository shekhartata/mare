from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pymongo.collection import Collection

from app.config import get_settings
from app.constants import AGENT_DB, NAV_NODES, RAW_COLLECTIONS, RAW_DB
from app.indexing.grouping import customer_groups, customer_month_groups
from app.indexing.schema_discovery import discover_schema
from app.indexing.search_text import COLLECTION_TOPICS, compose_search_text
from app.indexing.summaries import summarize_collection, summarize_database, summarize_group
from app.indexing.semantic_grouping import semantic_groups_from_docs
from app.indexing.topical_grouping import grouping_projection, topical_groups_from_docs
from app.llm import get_reasoning_model
from app.llm.heuristic import HeuristicReasoningModel
from app.mongo.client import get_client


def node_id(*parts: str) -> str:
    return "nav:" + ":".join(parts)


def build_hierarchy(
    tenant_id: str | None = None,
    *,
    use_llm: bool = False,
    source_db: str = RAW_DB,
    collections: tuple[str, ...] | None = None,
    agent_database: str = AGENT_DB,
    grouping_strategy: str = "entity",
    target_docs_per_group: int | None = None,
    extra_match: dict[str, Any] | None = None,
) -> dict[str, int]:
    settings = get_settings()
    tenant_id = tenant_id or settings.tenant_id
    collections = collections or settings.source_collections or RAW_COLLECTIONS
    model = get_reasoning_model() if use_llm else HeuristicReasoningModel()
    client = get_client()
    rdb = client[source_db]
    nodes_coll: Collection = client[agent_database][NAV_NODES]
    nodes_coll.delete_many({"tenant_id": tenant_id})

    now = datetime.now(UTC)
    nodes: list[dict[str, Any]] = []
    schemas: dict[str, dict[str, Any]] = {}
    for name in collections:
        schemas[name] = discover_schema(rdb[name])

    db_summary = summarize_database(list(collections), model if use_llm else None)
    db_node_id = node_id("db", source_db)
    nodes.append(
        _node(
            _id=db_node_id,
            tenant_id=tenant_id,
            node_type="database",
            name=source_db,
            description="SaaS operations database for adaptive retrieval evaluation.",
            summary=db_summary,
            parent_id=None,
            depth=0,
            source={"database": source_db, "collection": None, "document_ids": [], "filter": {}, "pointer_type": "query"},
            schema_info={"important_fields": list(collections), "field_descriptions": {}},
            metadata={
                "topics": ["saas", "operations", "support", "deployments"],
                "entities": list(collections),
                "time_min": None,
                "time_max": None,
                "document_count": sum(s.get("document_count", 0) for s in schemas.values()),
            },
            children_count=len(collections),
            now=now,
            extra_terms=["mongodb", "adaptive retrieval", "multi-hop"],
        )
    )

    for name in collections:
        schema = schemas[name]
        summary = summarize_collection(name, schema, model if use_llm else None)
        cid = node_id("col", source_db, name)
        col_count = schema.get("document_count", 0)
        nodes.append(
            _node(
                _id=cid,
                tenant_id=tenant_id,
                node_type="collection",
                name=name,
                description=f"Collection {source_db}.{name}",
                summary=summary,
                parent_id=db_node_id,
                depth=1,
                source={
                    "database": source_db,
                    "collection": name,
                    "document_ids": [],
                    "filter": {"tenant_id": tenant_id},
                    "pointer_type": "query",
                },
                schema_info={
                    "important_fields": schema.get("important_fields", []),
                    "field_descriptions": {
                        f["name"]: f.get("example", "") for f in schema.get("fields", [])[:12]
                    },
                },
                metadata={
                    "topics": COLLECTION_TOPICS.get(name, []),
                    "entities": schema.get("entities", [])[:20],
                    "time_min": schema.get("time_min"),
                    "time_max": schema.get("time_max"),
                    "document_count": col_count,
                },
                children_count=0,
                now=now,
                extra_terms=schema.get("representative_terms", []),
            )
        )

        groups = list(
            _groups_for(
                rdb[name],
                tenant_id,
                name,
                strategy=grouping_strategy,
                target_docs_per_group=target_docs_per_group,
                extra_match=extra_match,
            )
        )
        col_index = len(nodes) - 1
        nodes[col_index]["children_count"] = len(groups)
        for g in groups:
            gid = node_id("group", source_db, name, g["key"].replace(":", "."))
            filt = dict(g["filter"])
            nodes.append(
                _node(
                    _id=gid,
                    tenant_id=tenant_id,
                    node_type="group",
                    name=g["name"],
                    description=f"Deterministic group over {name}",
                    summary=g.get("summary")
                    or summarize_group(g["name"], filt, g["document_count"]),
                    parent_id=cid,
                    depth=2,
                    source={
                        "database": source_db,
                        "collection": name,
                        "document_ids": list(g.get("document_ids") or []),
                        "filter": filt,
                        "pointer_type": "query",
                    },
                    schema_info={
                        "important_fields": schema.get("important_fields", [])[:8],
                        "field_descriptions": {},
                    },
                    metadata={
                        "topics": g.get("topics", []),
                        "entities": g.get("entities", []),
                        "time_min": g.get("time_min"),
                        "time_max": g.get("time_max"),
                        "document_count": g["document_count"],
                    },
                    children_count=0,
                    now=now,
                    extra_terms=g.get("extra_terms") or g.get("entities", []),
                )
            )

        if name == "customers" and col_count <= 80:
            for doc in rdb[name].find({"tenant_id": tenant_id}, {"_id": 1, "name": 1, "customer_id": 1, "region": 1, "subscription_tier": 1, "industry": 1}):
                did = str(doc["_id"])
                nid = node_id("doc", source_db, name, did)
                label = doc.get("name") or did
                nodes.append(
                    _node(
                        _id=nid,
                        tenant_id=tenant_id,
                        node_type="document",
                        name=f"{label} ({did})",
                        description="Customer record pointer — raw document is not copied.",
                        summary=(
                            f"Customer {label} id={did} region={doc.get('region')} "
                            f"tier={doc.get('subscription_tier')} industry={doc.get('industry')}"
                        ),
                        parent_id=cid,
                        depth=2,
                        source={
                            "database": source_db,
                            "collection": name,
                            "document_ids": [did],
                            "filter": {"_id": did},
                            "pointer_type": "document",
                        },
                        schema_info={"important_fields": ["subscription_tier", "region", "name"], "field_descriptions": {}},
                        metadata={
                            "topics": ["customer", doc.get("industry") or ""],
                            "entities": [did, label],
                            "time_min": None,
                            "time_max": None,
                            "document_count": 1,
                        },
                        children_count=0,
                        now=now,
                        extra_terms=[str(doc.get("subscription_tier") or ""), str(doc.get("region") or "")],
                    )
                )
            nodes[col_index]["children_count"] = nodes[col_index]["children_count"] + col_count

    if nodes:
        nodes_coll.insert_many(nodes)
    return {
        "nodes": len(nodes),
        "database": 1,
        "collections": len(collections),
        "database_name": source_db,
        "agent_db": agent_database,
        "grouping_strategy": grouping_strategy,
        "target_docs_per_group": target_docs_per_group,
    }


def _groups_for(
    coll: Collection,
    tenant_id: str,
    name: str,
    *,
    strategy: str = "entity",
    target_docs_per_group: int | None = None,
    extra_match: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if strategy in {"topical", "semantic"}:
        match = {"tenant_id": tenant_id, **(extra_match or {})}
        docs = list(coll.find(match, grouping_projection()))
        target = int(target_docs_per_group or (20 if strategy == "semantic" else 100))
        if strategy == "semantic":
            return semantic_groups_from_docs(
                docs,
                tenant_id=tenant_id,
                collection=name,
                target_docs_per_group=target,
            )
        return topical_groups_from_docs(
            docs,
            tenant_id=tenant_id,
            collection=name,
            target_docs_per_group=target,
        )
    if extra_match:
        return _entity_groups_from_match(coll, tenant_id, name, extra_match)
    if name == "customers":
        return []
    if name == "logs":
        return list(customer_month_groups(coll, tenant_id))
    return list(customer_groups(coll, tenant_id))


def _entity_groups_from_match(
    coll: Collection,
    tenant_id: str,
    name: str,
    extra_match: dict[str, Any],
) -> list[dict[str, Any]]:
    from collections import defaultdict

    match = {"tenant_id": tenant_id, **extra_match}
    cursor = coll.find(match, {"_id": 1, "customer_id": 1, "timestamp": 1})
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for doc in cursor:
        cid = doc.get("customer_id")
        if not cid:
            continue
        buckets[str(cid)].append(doc)
    out: list[dict[str, Any]] = []
    for cid, members in buckets.items():
        times = [d.get("timestamp") for d in members if isinstance(d.get("timestamp"), datetime)]
        ids = [str(d["_id"]) for d in members]
        out.append(
            {
                "key": f"customer:{cid}",
                "name": f"{name} for {cid}",
                "filter": {"tenant_id": tenant_id, "customer_id": cid, **extra_match},
                "document_ids": ids,
                "document_count": len(ids),
                "time_min": min(times) if times else None,
                "time_max": max(times) if times else None,
                "entities": [cid],
                "topics": [name, cid],
            }
        )
    return out


def _node(
    *,
    _id: str,
    tenant_id: str,
    node_type: str,
    name: str,
    description: str,
    summary: str,
    parent_id: str | None,
    depth: int,
    source: dict[str, Any],
    schema_info: dict[str, Any],
    metadata: dict[str, Any],
    children_count: int,
    now: datetime,
    extra_terms: list[str],
) -> dict[str, Any]:
    search_text = compose_search_text(
        name=name,
        database=source.get("database") or "",
        collection=source.get("collection"),
        description=description,
        summary=summary,
        important_fields=schema_info.get("important_fields", []),
        entities=metadata.get("entities", []),
        topics=metadata.get("topics", []),
        representative_terms=extra_terms,
    )
    return {
        "_id": _id,
        "tenant_id": tenant_id,
        "node_type": node_type,
        "name": name,
        "description": description,
        "summary": summary,
        "search_text": search_text,
        "parent_id": parent_id,
        "depth": depth,
        "source": source,
        "schema": schema_info,
        "metadata": metadata,
        "embedding": [],
        "children_count": children_count,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
