from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.models.schemas import MongoRef, RetrievedDocument

_FOCUS = re.compile(r"[a-z0-9]{3,}")
_SKIP = {"embedding", "search_text"}


def doc_to_text(doc: dict[str, Any], max_chars: int = 1800, focus: str = "") -> str:
    """Flatten nested fields to dotted paths so a late key is not dropped."""
    lines: list[str] = []
    _flatten(doc, "", lines)
    tokens = _FOCUS.findall((focus or "").lower())
    if tokens:
        def rank(line: str) -> tuple[int, int, int]:
            folded = line.lower()
            hits = sum(token in folded for token in tokens)
            depth = line.split(":", 1)[0].count(".")
            return (0 if hits else 1, depth, -hits)

        lines.sort(key=rank)
    return "\n".join(lines)[:max_chars]


def _flatten(value: Any, prefix: str, lines: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _SKIP:
                continue
            path = f"{prefix}.{key}" if prefix else str(key)
            _flatten(item, path, lines)
        return
    if isinstance(value, list):
        for index, item in enumerate(value[:8]):
            _flatten(item, f"{prefix}.{index}", lines)
        return
    if not prefix:
        return
    shown = value.isoformat() if isinstance(value, datetime) else str(value)
    lines.append(f"{prefix}: {shown}")


def doc_to_retrieved(
    doc: dict[str, Any],
    database: str,
    collection: str,
    score: float = 0.0,
    focus: str = "",
) -> RetrievedDocument:
    did = str(doc.get("_id"))
    return RetrievedDocument(
        ref=MongoRef(database=database, collection=collection, document_id=did),
        content=_jsonable(doc),
        text=doc_to_text(doc, focus=focus),
        score=float(doc.get("_score") or score or 0.0),
    )


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
