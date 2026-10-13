"""Hybrid top-k over in-memory documents. One chunk per document."""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any, Protocol

_TOKEN = re.compile(r"[a-z0-9_]+")


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def render_document(doc: dict[str, Any]) -> str:
    lines = []
    for key, value in doc.items():
        if isinstance(value, datetime):
            value = value.strftime("%Y-%m-%d")
        lines.append(f"{key}: {value}")
    return "\n".join(lines)


def chunk_documents(documents: dict[str, list[dict[str, Any]]]) -> list[dict[str, str]]:
    chunks = []
    for collection, docs in documents.items():
        for doc in docs:
            chunks.append(
                {
                    "collection": collection,
                    "document_id": str(doc.get("_id")),
                    "text": render_document(doc),
                }
            )
    return chunks


class MemoryRag:
    def __init__(
        self,
        documents: dict[str, list[dict[str, Any]]],
        embedder: Embedder | None = None,
    ):
        self.chunks = chunk_documents(documents)
        self._embedder = embedder
        self._vectors: list[list[float]] | None = None
        self._query_vectors: dict[str, list[float]] = {}
        if embedder is not None and self.chunks:
            self._vectors = embedder.embed([chunk["text"] for chunk in self.chunks])

    def search(self, question: str, k: int, *, rrf_k: int = 60) -> list[dict[str, str]]:
        if k < 1:
            raise ValueError("k must be >= 1")
        scores = {i: 0.0 for i in range(len(self.chunks))}
        for rank, index in enumerate(_lexical_order(question, self.chunks)):
            scores[index] += 1.0 / (rrf_k + rank + 1)
        if self._vectors is not None and self._embedder is not None:
            query = self._query_vector(question)
            order = sorted(
                range(len(self.chunks)),
                key=lambda i: (-_cosine(query, self._vectors[i]), self.chunks[i]["document_id"]),
            )
            for rank, index in enumerate(order):
                scores[index] += 1.0 / (rrf_k + rank + 1)
        ranked = sorted(scores, key=lambda i: (-scores[i], self.chunks[i]["document_id"]))
        return [dict(self.chunks[i]) for i in ranked[:k]]

    def _query_vector(self, question: str) -> list[float]:
        cached = self._query_vectors.get(question)
        if cached is None:
            assert self._embedder is not None
            cached = self._embedder.embed([question])[0]
            self._query_vectors[question] = cached
        return cached


def _lexical_order(question: str, chunks: list[dict[str, str]]) -> list[int]:
    wanted = _tokens(question)
    scored = []
    for index, chunk in enumerate(chunks):
        bag = _tokens(chunk["text"])
        score = sum(bag.get(token, 0) for token in wanted)
        scored.append((score, chunk["document_id"], index))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored]


def _tokens(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for token in _TOKEN.findall(text.lower()):
        if len(token) < 2:
            continue
        counts[token] = counts.get(token, 0) + 1
    return counts


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_n = math.sqrt(sum(a * a for a in left))
    right_n = math.sqrt(sum(b * b for b in right))
    if left_n == 0 or right_n == 0:
        return 0.0
    return dot / (left_n * right_n)
