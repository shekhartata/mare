"""Choose text fields before grouping. The choice is recorded, not applied inside TF-IDF."""

from __future__ import annotations

from typing import Any

_TEXT_HINTS = ("reason", "description", "title", "note", "text", "summary", "comment", "name")


def select_text_fields(
    profile: dict[str, Any],
    *,
    overrides: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, tuple[str, ...]]:
    overrides = overrides or {}
    chosen: dict[str, tuple[str, ...]] = {}
    for coll in profile.get("collections") or []:
        name = str(coll["name"])
        if name in overrides:
            chosen[name] = tuple(overrides[name])
            continue
        strings = [
            str(field["path"])
            for field in coll.get("fields") or []
            if "string" in (field.get("types") or [])
            and "." not in str(field["path"])
            and "[]" not in str(field["path"])
            and str(field["path"]) not in {"_id"}
            and not str(field["path"]).endswith("_id")
        ]
        hinted = [path for path in strings if any(hint in path for hint in _TEXT_HINTS)]
        chosen[name] = tuple(hinted or strings[:3])
    return chosen
