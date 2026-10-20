"""Build-time navigation vectors and the contract that asks must match."""

from __future__ import annotations

import hashlib
from typing import Any

from app.indexing.signals.nav_nodes import NODE_BUILDER_VERSION


def usable_embedder(embedder: Any | None) -> Any | None:
    """Null stand-in vectors are not a semantic index."""
    if embedder is None:
        return None
    if embedder.__class__.__name__ == "NullEmbeddingModel":
        return None
    return embedder


def contract_for(embedder: Any) -> dict[str, Any]:
    provider = (
        "openai"
        if embedder.__class__.__name__ == "OpenAIEmbeddingModel"
        else embedder.__class__.__name__
    )
    return {
        "provider": provider,
        "model": str(getattr(embedder, "model", "")),
        "dimensions": int(embedder.dimensions),
        "builder_version": NODE_BUILDER_VERSION,
    }


def same_contract(saved: dict[str, Any] | None, embedder: Any | None) -> bool:
    current_embedder = usable_embedder(embedder)
    if not saved or current_embedder is None:
        return False
    current = contract_for(current_embedder)
    return all(saved.get(key) == current[key] for key in current)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def embed_nav_nodes(
    nodes: list[dict[str, Any]],
    embedder: Any,
    previous: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Embed changed node text. Reuse a stored vector when the text hash matches."""
    pending: list[tuple[dict[str, Any], str]] = []
    reused: dict[str, dict[str, Any]] = {}
    for node in nodes:
        digest = text_hash(str(node.get("search_text") or ""))
        prior = previous.get(str(node["_id"]))
        if prior and prior.get("text_hash") == digest and prior.get("vector"):
            reused[str(node["_id"])] = prior
        else:
            pending.append((node, digest))
    fresh: dict[str, dict[str, Any]] = {}
    if pending:
        vectors = embedder.embed([str(node.get("search_text") or "") for node, _digest in pending])
        if len(vectors) != len(pending):
            raise ValueError("embedding provider returned the wrong number of vectors")
        for (node, digest), vector in zip(pending, vectors, strict=True):
            fresh[str(node["_id"])] = {"text_hash": digest, "vector": list(vector)}
    expected = int(embedder.dimensions)
    records: list[dict[str, Any]] = []
    for node in nodes:
        chosen = fresh.get(str(node["_id"])) or reused[str(node["_id"])]
        vector = list(chosen["vector"])
        if len(vector) != expected:
            raise ValueError("embedding dimensions do not match the model")
        records.append(
            {
                "node_id": str(node["_id"]),
                "node_type": node.get("node_type"),
                "text_hash": chosen["text_hash"],
                "vector": vector,
            }
        )
    return records, {"embedded": len(fresh), "reused": len(reused), "dimensions": expected}
