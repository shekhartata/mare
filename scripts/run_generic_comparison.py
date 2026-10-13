#!/usr/bin/env python3
"""Score generic-index MARE against in-memory hybrid RAG. Writes reports/generic_mare.md."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.datagen.shop_fixture import documents as shop_documents
from app.datagen.warehouse_fixture import documents as warehouse_documents
from app.eval.generic_compare import CASES, performance_table, run_generic_comparison
from app.indexing.signals import reset_index_state
from app.llm import get_embedding_model, get_reasoning_model

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "generic_mare.md"
JSON_OUT = ROOT / "reports" / "generic_comparison.json"


def main() -> int:
    settings = get_settings()
    reset_index_state()
    model = get_reasoning_model()
    embedder = get_embedding_model() if settings.openai_api_key else None
    print(f"answer model: {getattr(model, 'model', type(model).__name__)}")
    print(f"embeddings: {embedder is not None}")
    payload = run_generic_comparison(
        {"mare_shop": shop_documents(), "mare_warehouse": warehouse_documents()},
        model=model,
        embedder=embedder,
        rag_ks=(1, settings.rag_top_k),
        rrf_k=settings.rrf_k,
    )
    payload["generated"] = datetime.now(UTC).isoformat()
    payload["answer_model"] = getattr(model, "model", type(model).__name__)
    payload["cases_expected"] = len(CASES)
    JSON_OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    OUT.write_text(_markdown(payload), encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"wrote {JSON_OUT}")
    return 0


def _markdown(payload: dict) -> str:
    ks = payload["rag_ks"]
    lines = [
        "# Generic MARE vs RAG",
        "",
        f"- generated: {payload['generated']}",
        f"- answering model: `{payload['answer_model']}`",
        f"- embeddings: {'openai hybrid' if payload['embedder'] else 'lexical only'}",
        "",
        "Generic MARE is one `investigate` call plus this answer model. "
        "It is not the SaaS tool loop. RAG is hybrid Top-K over one chunk per document, "
        "in memory, because these fixtures are not in Atlas.",
        "",
        "These corpora have 5 and 7 documents, so K=8 is the whole database. "
        "K=1 is the single nearest chunk.",
        "",
        _footprint(payload),
        "",
        performance_table(payload),
        "",
        _differed(payload, ks),
        "",
        "## Answers",
        "",
    ]
    for case in payload["cases"]:
        lines.extend(_case_block(case, ks))
    lines.append("Machine-readable: [generic_comparison.json](generic_comparison.json).")
    lines.append("")
    return "\n".join(lines)


def _footprint(payload: dict) -> str:
    parts = []
    for name, counts in payload["footprint"].items():
        parts.append(f"{name} cards **{counts['cards']}** / chunks **{counts['chunks']}**")
    return "Vectors: " + "; ".join(parts) + "."


def _differed(payload: dict, ks: list[int]) -> str:
    primary = ks[0]
    lines = ["## What differed", ""]
    hop_notes = []
    absence_notes = []
    for case in payload["cases"]:
        mare = case["mare"]
        rag = case["rag"][f"k{primary}"]
        mare_recall = mare["retrieval"]["gold_evidence_recall"]
        rag_recall = rag["retrieval"]["gold_evidence_recall"]
        if mare_recall == 1 and rag_recall == 0:
            hop_notes.append(
                f"{case['title']}: MARE returned {_ids(mare)}. "
                f"RAG K={primary} returned {_ids(rag)}. "
                "The answer was on that chunk, so the model still matched."
            )
        if mare["receipt"]["count"] == 0 and mare["receipt"]["exact"]:
            absence_notes.append(
                f"{case['title']}: MARE receipt is an exact count of 0 "
                f"over {mare['receipt']['absence_scope']}. "
                f"RAG K={primary} answered from {_ids(rag)}."
            )
    if hop_notes:
        lines.append("Hops, gold-document recall:")
        lines.append("")
        lines.extend(f"- {note}" for note in hop_notes)
        lines.append("")
    if absence_notes:
        lines.append("Absence:")
        lines.append("")
        lines.extend(f"- {note}" for note in absence_notes)
        lines.append("")
    return "\n".join(lines).rstrip()


def _case_block(case: dict, ks: list[int]) -> list[str]:
    mare = case["mare"]
    lines = [
        f"### {case['title']}",
        "",
        case["question"],
        "",
        f"MARE: {mare['answer']}",
        "",
        (
            f"receipt exact={mare['receipt']['exact']} count={mare['receipt']['count']} "
            f"absence_scope={mare['receipt']['absence_scope']} "
            f"docs={_ids(mare)} tokens={mare['tokens']} ms={round(mare['elapsed_ms'])}"
        ),
        "",
    ]
    for k in ks:
        blob = case["rag"][f"k{k}"]
        lines.extend(
            [
                f"RAG K={k}: {blob['answer']}",
                "",
                f"docs={_ids(blob)} tokens={blob['tokens']} ms={round(blob['elapsed_ms'])}",
                "",
            ]
        )
    return lines


def _ids(blob: dict) -> str:
    refs = [f"{item['collection']}:{item['document_id']}" for item in blob["retrieved"]]
    return ", ".join(refs) if refs else "(none)"


if __name__ == "__main__":
    raise SystemExit(main())
