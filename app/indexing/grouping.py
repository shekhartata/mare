from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Iterator

from pymongo.collection import Collection

from app.indexing.search_text import month_key


def customer_groups(coll: Collection, tenant_id: str) -> Iterator[dict[str, Any]]:
    pipeline = [
        {"$match": {"tenant_id": tenant_id}},
        {
            "$group": {
                "_id": "$customer_id",
                "count": {"$sum": 1},
                "time_min": {"$min": _time_expr(coll.name)},
                "time_max": {"$max": _time_expr(coll.name)},
            }
        },
    ]
    for row in coll.aggregate(pipeline, allowDiskUse=True):
        cid = row["_id"]
        if not cid:
            continue
        yield {
            "key": f"customer:{cid}",
            "name": f"{coll.name} for {cid}",
            "filter": {"tenant_id": tenant_id, "customer_id": cid},
            "document_count": int(row["count"]),
            "time_min": row.get("time_min"),
            "time_max": row.get("time_max"),
            "entities": [cid],
            "topics": [coll.name, cid],
        }


def customer_month_groups(coll: Collection, tenant_id: str) -> Iterator[dict[str, Any]]:
    time_field = _time_field(coll.name)
    cursor = coll.find(
        {"tenant_id": tenant_id},
        {"customer_id": 1, time_field: 1},
    )
    buckets: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "tmin": None, "tmax": None}
    )
    for doc in cursor:
        cid = doc.get("customer_id")
        ts = doc.get(time_field)
        if not cid or not isinstance(ts, datetime):
            continue
        mk = month_key(ts)
        b = buckets[(cid, mk)]
        b["count"] += 1
        b["tmin"] = ts if b["tmin"] is None else min(b["tmin"], ts)
        b["tmax"] = ts if b["tmax"] is None else max(b["tmax"], ts)
    for (cid, mk), b in buckets.items():
        start, end = _month_bounds(mk)
        yield {
            "key": f"customer:{cid}:month:{mk}",
            "name": f"{coll.name} {cid} {mk}",
            "filter": {
                "tenant_id": tenant_id,
                "customer_id": cid,
                time_field: {"$gte": start, "$lt": end},
            },
            "range": {"field": time_field, "month": mk},
            "document_count": b["count"],
            "time_min": b["tmin"],
            "time_max": b["tmax"],
            "entities": [cid, mk],
            "topics": [coll.name, cid, "monthly"],
        }


def _time_field(collection: str) -> str:
    return {
        "tickets": "created_at",
        "deployments": "started_at",
        "migrations": "started_at",
        "incidents": "opened_at",
        "logs": "timestamp",
        "customers": "created_at",
    }.get(collection, "created_at")


def _time_expr(collection: str) -> str:
    return f"${_time_field(collection)}"


def _month_bounds(mk: str) -> tuple[datetime, datetime]:
    year, month = int(mk[:4]), int(mk[5:7])
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)
    return start, end
