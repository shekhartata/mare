from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models.schemas import MongoRef, RetrievedDocument


def doc_to_text(doc: dict[str, Any], max_chars: int = 1800) -> str:
    parts: list[str] = []
    for key, value in doc.items():
        if key in {"embedding", "search_text"}:
            continue
        parts.append(f"{key}: {_fmt(value)}")
    text = "\n".join(parts)
    return text[:max_chars]


def doc_to_retrieved(
    doc: dict[str, Any], database: str, collection: str, score: float = 0.0
) -> RetrievedDocument:
    did = str(doc.get("_id"))
    return RetrievedDocument(
        ref=MongoRef(database=database, collection=collection, document_id=did),
        content=_jsonable(doc),
        text=doc_to_text(doc),
        score=float(doc.get("_score") or score or 0.0),
    )


def _fmt(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{k}={_fmt(v)}" for k, v in list(value.items())[:8]) + " }"
    if isinstance(value, list):
        return "[" + ", ".join(_fmt(v) for v in value[:8]) + "]"
    return str(value)


def _jsonable(doc: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in doc.items():
        if k == "embedding":
            continue
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, dict):
            out[k] = _jsonable(v)
        elif isinstance(v, list):
            out[k] = [x.isoformat() if isinstance(x, datetime) else x for x in v]
        else:
            out[k] = v
    return out
