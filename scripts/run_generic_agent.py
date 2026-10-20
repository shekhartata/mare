#!/usr/bin/env python3
"""Schema-blind MARE tool loop vs hybrid RAG on the shop and warehouse fixtures."""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.baseline.memory_rag import MemoryRag
from app.config import get_settings
from app.datagen.shop_fixture import documents as shop_documents
from app.datagen.utility_fixture import CASES as UTILITY_CASES
from app.datagen.utility_fixture import documents as utility_documents
from app.datagen.warehouse_fixture import documents as warehouse_documents
from app.eval.generic_compare import CASES
from app.eval.scoring import answer_scores, retrieval_metrics
from app.indexing.signals import build_generic_index, reset_index_state
from app.llm import get_embedding_model, get_reasoning_model
from app.retrieval.agent_loop import run_agent
from app.retrieval.generic_tools import generic_handlers_with_vectors

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "generic_agent.md"
JSON_OUT = ROOT / "reports" / "generic_agent.json"
_RAG_SYSTEM = "You are a conventional RAG answering model."


def main() -> int:
    utility = "--utility" in sys.argv[1:]
    settings = get_settings()
    reset_index_state()
    embedder = get_embedding_model() if settings.openai_api_key else None
    answer_model = get_reasoning_model()
    if utility:
        spec_cases = UTILITY_CASES
        corpora = {"mare_utility": utility_documents()}
        out = ROOT / "reports" / "generic_utility.md"
        json_out = ROOT / "reports" / "generic_utility.json"
    else:
        spec_cases = CASES
        corpora = {"mare_shop": shop_documents(), "mare_warehouse": warehouse_documents()}
        out = OUT
        json_out = JSON_OUT
    indexes = {
        name: build_generic_index(docs, database=name, use_cache=False)
        for name, docs in corpora.items()
    }
    ready = {
        name: generic_handlers_with_vectors(index, embedder) for name, index in indexes.items()
    }
    rags = {name: MemoryRag(docs, embedder) for name, docs in corpora.items()}
    print(f"agent: {settings.openai_model_agent} answer: {settings.openai_model}", flush=True)
    cases = []
    for case in spec_cases:
        database = case["database"]
        print(f"{case['id']}: {case['question'][:72]}", flush=True)
        mare = _run_mare(case, ready[database])
        rag = {
            f"k{k}": _run_rag(
                case, rags[database], answer_model, k=k, rrf_k=settings.rrf_k
            )
            for k in (1, settings.rag_top_k)
        }
        _print_case(case, mare, rag)
        cases.append(
            {
                "id": case["id"],
                "database": database,
                "title": case["title"],
                "question": case["question"],
                "hidden": case.get("hidden") or "",
                "mare": mare,
                "rag": rag,
            }
        )
    doc_count = sum(len(rows) for rows in corpora.values() for rows in rows.values())
    payload = {
        "generated": datetime.now(UTC).isoformat(),
        "agent_model": settings.openai_model_agent,
        "answer_model": settings.openai_model,
        "embedder": embedder is not None,
        "rag_ks": [1, settings.rag_top_k],
        "suite": "utility" if utility else "demo",
        "documents": doc_count,
        "cases": cases,
    }
    json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    out.write_text(_markdown(payload), encoding="utf-8")
    print(f"wrote {out}")
    return 0


def _run_mare(case: dict, handlers: Any) -> dict:
    session = run_agent(
        case["question"],
        handlers=handlers,
        persist=False,
        schema_in_prompt=False,
        compact_context=True,
    )
    retrieved = list(session.retrieved_docs or [])
    return _score(
        case,
        retrieved,
        session.answer,
        session.tokens_consumed,
        session.elapsed_ms,
        extra={
            "agent_turns": session.agent_turns,
            "tool_calls": session.tool_calls,
            "stop_reason": session.stop_reason,
        },
    )


def _run_rag(case: dict, rag: MemoryRag, model: Any, *, k: int, rrf_k: int) -> dict:
    started = time.perf_counter()
    retrieved = rag.search(case["question"], k, rrf_k=rrf_k)
    blocks = [
        f"[{item['collection']} {item['document_id']}]\n{item['text']}" for item in retrieved
    ]
    context = "\n\n".join(blocks) if blocks else "(no documents)"
    prompt = (
        f"Question: {case['question']}\n\nTop-{k} chunks\n\n{context}\n\n"
        "Answer using only these chunks. Cite source ids."
    )
    generated = model.generate(prompt, system=_RAG_SYSTEM)
    elapsed = (time.perf_counter() - started) * 1000
    return _score(case, retrieved, generated.text, generated.usage.total_tokens, elapsed)


def _score(
    case: dict,
    retrieved: list[dict],
    answer: str,
    tokens: int,
    elapsed_ms: float,
    extra: dict | None = None,
) -> dict:
    spec = {
        "must_contain_any": case.get("must_contain_any") or [],
        "must_contain_all": case.get("must_contain_all") or [],
        "must_not_contain": case.get("must_not_contain") or [],
    }
    blob = {
        "answer": (answer or "").strip(),
        "tokens": int(tokens or 0),
        "elapsed_ms": round(float(elapsed_ms or 0), 1),
        "retrieved": [
            {
                "collection": item.get("collection"),
                "document_id": item.get("document_id"),
                "text": item.get("text") or "",
            }
            for item in retrieved
        ],
        "retrieval": retrieval_metrics(retrieved, case["gold_sources"]),
        "answer_score": answer_scores(answer or "", spec),
    }
    blob.update(extra or {})
    return blob


def _print_case(case: dict, mare: dict, rag: dict) -> None:
    print(
        f"  MARE { _yn(mare) } turns={mare.get('agent_turns')} tools={mare.get('tool_calls')} "
        f"tok={mare['tokens']} ms={round(mare['elapsed_ms'])} stop={mare.get('stop_reason')}",
        flush=True,
    )
    for key, blob in rag.items():
        print(
            f"  RAG {key} {_yn(blob)} tok={blob['tokens']} ms={round(blob['elapsed_ms'])}",
            flush=True,
        )


def _markdown(payload: dict) -> str:
    ks = payload["rag_ks"]
    utility = payload.get("suite") == "utility"
    title = (
        "# Generic MARE vs RAG where Top-K cannot see the answer"
        if utility
        else "# Generic MARE agent vs RAG"
    )
    lines = [
        title,
        "",
        f"- generated: {payload['generated']}",
        f"- agent model: `{payload['agent_model']}`",
        f"- answering model: `{payload['answer_model']}`",
        "- schema-blind tool loop: search, retrieve, query, submit",
        "- receipts compact on, same as the SaaS demo. No schema in the prompt.",
        "- RAG is one hybrid Top-K over one chunk per document, then the answering model.",
        "",
    ]
    if utility:
        lines.extend(
            [
                (
                    f"`mare_utility` has {payload['documents']} documents. "
                    "K=8 is the product default and is not the whole database."
                ),
                "",
                (
                    "Bridge: `northwind` is only on the order. The return that matches "
                    "the question stores the order id and does not store the lane."
                ),
                (
                    "Distributed: `chlorogenic` is only on the assay. The complaint that "
                    "matches the question stores the lot id and does not store the finding."
                ),
                (
                    "Absence: no refund has sku `sku_plain`. The nearest refund is "
                    "`sku_plain_plus` and its reason mentions `sku_plain`."
                ),
                "",
                (
                    "A related node is bound to the foreign key on the matched document, "
                    "so retrieve opens that target. Gold recall is the hidden document. "
                    "Absence has no gold document, so recall is n/a."
                ),
                "",
            ]
        )
    else:
        lines.extend(
            ["Shop has 5 documents and warehouse has 7, so K=8 is the whole corpus.", ""]
        )
    lines.extend([_table(payload, ks), "", "## Answers", ""])
    for case in payload["cases"]:
        mare = case["mare"]
        lines.extend(
            [
                f"### {case['title']}",
                "",
                case["question"],
                "",
                f"MARE: {mare['answer']}",
                "",
                (
                    f"stop={mare.get('stop_reason')} turns={mare.get('agent_turns')} "
                    f"tools={mare.get('tool_calls')} tokens={mare['tokens']} "
                    f"ms={round(mare['elapsed_ms'])} docs={_ids(mare)}"
                ),
                "",
            ]
        )
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
    json_name = (
        "generic_utility.json" if payload.get("suite") == "utility" else "generic_agent.json"
    )
    lines.append(f"Machine-readable: [{json_name}]({json_name}).")
    lines.append("")
    return "\n".join(lines)


def _table(payload: dict, ks: list[int]) -> str:
    headers = ["case", "MARE", "recall", "ms", "tok", "turns", "tools"]
    for k in ks:
        headers.extend([f"RAG K={k}", "recall", "ms", "tok"])
    rows = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] + ["---:"] * (len(headers) - 1)) + " |",
    ]
    mare_ok = 0
    rag_ok = {k: 0 for k in ks}
    totals = {"mare_ms": [], "mare_tok": [], "turns": [], "tools": []}
    rag_ms = {k: [] for k in ks}
    rag_tok = {k: [] for k in ks}
    for case in payload["cases"]:
        mare = case["mare"]
        ok = bool(mare["answer_score"]["correct"])
        mare_ok += ok
        totals["mare_ms"].append(mare["elapsed_ms"])
        totals["mare_tok"].append(mare["tokens"])
        totals["turns"].append(mare.get("agent_turns") or 0)
        totals["tools"].append(mare.get("tool_calls") or 0)
        cells = [
            case["title"],
            _yn(mare),
            _recall(mare),
            str(round(mare["elapsed_ms"])),
            str(mare["tokens"]),
            str(mare.get("agent_turns") or 0),
            str(mare.get("tool_calls") or 0),
        ]
        for k in ks:
            blob = case["rag"][f"k{k}"]
            hit = bool(blob["answer_score"]["correct"])
            rag_ok[k] += hit
            rag_ms[k].append(blob["elapsed_ms"])
            rag_tok[k].append(blob["tokens"])
            cells.extend(
                [
                    _yn(blob),
                    _recall(blob),
                    str(round(blob["elapsed_ms"])),
                    str(blob["tokens"]),
                ]
            )
        rows.append("| " + " | ".join(cells) + " |")
    total = len(payload["cases"])
    summary = [
        "mean",
        f"**{mare_ok}/{total}**",
        "",
        f"**{_mean(totals['mare_ms'])}**",
        f"**{_mean(totals['mare_tok'])}**",
        f"**{_mean(totals['turns'])}**",
        f"**{_mean(totals['tools'])}**",
    ]
    for k in ks:
        summary.extend(
            [
                f"**{rag_ok[k]}/{total}**",
                "",
                f"**{_mean(rag_ms[k])}**",
                f"**{_mean(rag_tok[k])}**",
            ]
        )
    rows.append("| " + " | ".join(summary) + " |")
    return "\n".join(rows)


def _ids(blob: dict) -> str:
    refs = [f"{item['collection']}:{item['document_id']}" for item in blob["retrieved"]]
    return ", ".join(refs) if refs else "(none)"


def _recall(blob: dict) -> str:
    value = blob["retrieval"]["gold_evidence_recall"]
    if value is None:
        return "n/a"
    return f"{float(value):.2f}"


def _yn(blob: dict) -> str:
    return "yes" if blob["answer_score"]["correct"] else "no"


def _mean(values: list) -> int:
    if not values:
        return 0
    return round(sum(values) / len(values))


if __name__ == "__main__":
    raise SystemExit(main())
