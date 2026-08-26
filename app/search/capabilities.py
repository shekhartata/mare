from __future__ import annotations

from typing import Any

from app.constants import AGENT_DB, RUNTIME_CONFIG
from app.models.schemas import ClusterCapabilities
from app.mongo.client import agent_db


CONFIG_ID = "runtime_capabilities"


def load_capabilities() -> ClusterCapabilities | None:
    doc = agent_db()[RUNTIME_CONFIG].find_one({"_id": CONFIG_ID})
    if not doc:
        return None
    data = {k: v for k, v in doc.items() if k != "_id"}
    return ClusterCapabilities.model_validate(data)


def save_capabilities(caps: ClusterCapabilities) -> None:
    agent_db()[RUNTIME_CONFIG].replace_one(
        {"_id": CONFIG_ID},
        {"_id": CONFIG_ID, **caps.model_dump()},
        upsert=True,
    )


def capabilities_or_default() -> ClusterCapabilities:
    return load_capabilities() or ClusterCapabilities(
        auto_embed=False,
        rank_fusion=False,
        hybrid_strategy="rrf",
        embedding_path="manual",
    )
