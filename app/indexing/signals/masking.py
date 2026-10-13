"""Strip values before any schema model call. Fail closed."""

from __future__ import annotations

import json
import re
from typing import Any

_DYNAMIC_KEY = re.compile(r"(?:[0-9a-f]{6,}|.*\d{4,}.*)", re.I)


class DisclosureError(RuntimeError):
    pass


def normalize_key(key: str) -> str:
    if key in {"_id"} or key.endswith("_id") or key.endswith("_at"):
        return key
    if _DYNAMIC_KEY.search(key):
        return "dynamic_key"
    return key


def type_marker(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "double"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    name = type(value).__name__
    if name == "datetime":
        return "date"
    return name


def mask_document(doc: dict[str, Any]) -> dict[str, Any]:
    return _mask(doc)


def _mask(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key == "_id":
                out["_id"] = "string"
                continue
            out[normalize_key(str(key))] = _mask(item)
        return out
    if isinstance(value, list):
        if not value:
            return ["empty"]
        return [_mask(value[0])]
    return type_marker(value)


def masked_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Field names, types, and presence only. No scalar examples."""
    collections = []
    for coll in profile.get("collections") or []:
        fields = []
        for field in coll.get("fields") or []:
            fields.append(
                {
                    "path": field.get("path"),
                    "types": list(field.get("types") or []),
                    "presence": field.get("presence"),
                    "denominator": field.get("denominator"),
                }
            )
        collections.append(
            {
                "name": coll.get("name"),
                "inspected": coll.get("inspected"),
                "complete": coll.get("complete"),
                "fields": fields,
            }
        )
    return {
        "database": profile.get("database"),
        "sample_size": profile.get("sample_size"),
        "collections": collections,
    }


def assert_disclosed(payload: Any, forbidden: list[str]) -> None:
    blob = json.dumps(payload, default=str)
    leaked = [value for value in forbidden if value and value in blob]
    if leaked:
        raise DisclosureError(f"masked payload contains forbidden values: {leaked}")
