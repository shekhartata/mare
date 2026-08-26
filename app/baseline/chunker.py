from __future__ import annotations

from typing import Any


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    if size <= 0:
        return [text]
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(n, start + size)
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


def document_to_chunks(doc: dict[str, Any], collection: str, size: int, overlap: int) -> list[dict[str, Any]]:
    from app.retrieval.serialize import doc_to_text

    text = doc_to_text(doc, max_chars=20_000)
    parts = chunk_text(text, size, overlap)
    out = []
    for i, part in enumerate(parts):
        out.append(
            {
                "source_id": str(doc.get("_id")),
                "collection": collection,
                "chunk_index": i,
                "text": part,
                "tenant_id": doc.get("tenant_id"),
                "customer_id": doc.get("customer_id"),
            }
        )
    return out
