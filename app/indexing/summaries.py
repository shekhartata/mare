from __future__ import annotations

from typing import Any

from app.indexing.search_text import COLLECTION_TOPICS, collection_description, database_description
from app.llm.base import ReasoningModel


def summarize_database(collections: list[str], model: ReasoningModel | None = None) -> str:
    base = database_description(collections)
    if model is None:
        return base
    result = model.generate(
        f"Write a 2-sentence description of this MongoDB database for an AI retrieval agent.\n{base}",
        system="Be factual and compact. Do not invent collections.",
    )
    return result.text.strip() or base


def summarize_collection(
    name: str, schema: dict[str, Any], model: ReasoningModel | None = None
) -> str:
    base = collection_description(name, schema)
    terms = ", ".join(schema.get("representative_terms", [])[:12])
    topics = ", ".join(COLLECTION_TOPICS.get(name, []))
    if model is None:
        return f"{base} Representative terms: {terms}."
    result = model.generate(
        (
            f"Write a compact collection summary for navigation.\n"
            f"Collection: {name}\nSchema: {schema.get('important_fields')}\n"
            f"Topics: {topics}\nTerms: {terms}\nCounts: {schema.get('document_count')}"
        ),
        system="3 sentences max. Mention what questions this collection can answer.",
    )
    return result.text.strip() or base


def summarize_group(name: str, filter_doc: dict[str, Any], count: int) -> str:
    return (
        f"Logical group '{name}' selecting {count} documents with filter {filter_doc}. "
        "Use structured queries or scoped search to read raw records in this region."
    )
