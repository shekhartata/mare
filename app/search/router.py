from __future__ import annotations

import re

from app.models.schemas import SearchMethod

_ID_RE = re.compile(
    r"\b(cust_\d{3}|mig_[a-z0-9_]+|dep_[a-z0-9_]+|tkt_\d+|inc_\d+|log_[a-z0-9_]+|AUTH_\d+|HTTP_\d+)\b",
    re.I,
)
_PREDICATE_RE = re.compile(
    r"\b(subscription[_\s]?tier|region|status|error_code|severity|customer_id)\b",
    re.I,
)
_CONCEPT_RE = re.compile(
    r"\b(why|root cause|similar|involving|related to|authentication|billing|failures?)\b",
    re.I,
)


def recommend_method(question: str) -> SearchMethod:
    q = question.strip()
    if _ID_RE.search(q) and not _CONCEPT_RE.search(q):
        return SearchMethod.lexical
    if _PREDICATE_RE.search(q) and re.search(r"\b(what is|current|which region)\b", q, re.I):
        return SearchMethod.mongo_query
    if _CONCEPT_RE.search(q) and not _ID_RE.search(q):
        return SearchMethod.semantic
    if _ID_RE.search(q) and _CONCEPT_RE.search(q):
        return SearchMethod.hybrid
    return SearchMethod.hybrid
