from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.constants import RETRIEVAL_TRACES
from app.models.schemas import TraceEvent
from app.mongo.client import agent_db


def write_trace(event: TraceEvent) -> None:
    doc = event.model_dump()
    doc["created_at"] = datetime.now(UTC)
    agent_db()[RETRIEVAL_TRACES].insert_one(doc)


def traces_for(session_id: str) -> list[dict[str, Any]]:
    return list(
        agent_db()[RETRIEVAL_TRACES].find({"session_id": session_id}, {"_id": 0}).sort("step", 1)
    )
