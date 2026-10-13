"""Generic-index MARE vs in-memory hybrid RAG. Same answer model on both sides."""

from __future__ import annotations

import time
from typing import Any

from app.baseline.memory_rag import Embedder, MemoryRag
from app.eval.scoring import answer_scores, retrieval_metrics
from app.indexing.signals import build_generic_index
from app.llm.base import ReasoningModel

CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "shop_lookup",
        "database": "mare_shop",
        "title": "Shop lookup",
        "question": "What is the status of order ord_1044?",
        "gold_sources": [{"collection": "orders", "document_id": "ord_1044"}],
        "expect_count": None,
        "must_contain_any": ["shipped"],
    },
    {
        "id": "shop_hop",
        "database": "mare_shop",
        "title": "Shop hop",
        "question": "Which order was refunded because a sweater pilled after one wash?",
        "gold_sources": [{"collection": "orders", "document_id": "ord_1044"}],
        "expect_count": None,
        "must_contain_any": ["ord_1044"],
        "must_not_contain": ["unknown", "cannot", "can't", "no matching", "no refund"],
    },
    {
        "id": "shop_count",
        "database": "mare_shop",
        "title": "Shop count",
        "question": "How many refunds are for sku_wool?",
        "gold_sources": [{"collection": "refunds", "document_id": "ref_9"}],
        "expect_count": 1,
        "must_contain_any": ["1", "one"],
    },
    {
        "id": "shop_absence",
        "database": "mare_shop",
        "title": "Shop absence",
        "question": "How many refunds are for sku_mug?",
        "gold_sources": [],
        "expect_count": 0,
        "must_contain_any": ["0", "zero", "none"],
    },
    {
        "id": "wh_lookup",
        "database": "mare_warehouse",
        "title": "Warehouse lookup",
        "question": "Where is bin_a3?",
        "gold_sources": [{"collection": "bins", "document_id": "bin_a3"}],
        "expect_count": None,
        "must_contain_any": ["bin_a3"],
    },
    {
        "id": "wh_count",
        "database": "mare_warehouse",
        "title": "Warehouse count",
        "question": "How many movements of sku_bolt are recorded?",
        "gold_sources": [{"collection": "movements", "document_id": "mov_1"}],
        "expect_count": 1,
        "must_contain_any": ["1", "one"],
    },
    {
        "id": "wh_absence",
        "database": "mare_warehouse",
        "title": "Warehouse absence",
        "question": "How many movements of sku_bolt happened in April 2024?",
        "gold_sources": [],
        "expect_count": 0,
        "must_contain_any": ["0", "zero", "none"],
    },
    {
        "id": "wh_hop",
        "database": "mare_warehouse",
        "title": "Warehouse hop",
        "question": "Which sku is stored in bin_a3?",
        "gold_sources": [{"collection": "skus", "document_id": "sku_bolt"}],
        "expect_count": None,
        "must_contain_any": ["sku_bolt"],
        "must_not_contain": ["unknown", "cannot", "can't", "does not mention"],
    },
)

_RAG_SYSTEM = "You are a conventional RAG answering model."
_MARE_SYSTEM = (
    "You answer from a retrieval receipt. "
    "If exact is true, the count is the answer, including 0 with no attached documents. "
    "Attached documents are the records that answer the question. "
    "Do not call the evidence missing when the receipt gives a count or document ids."
)


def run_generic_comparison(
    corpora: dict[str, dict[str, list[dict[str, Any]]]],
    *,
    model: ReasoningModel,
    embedder: Embedder | None = None,
    rag_ks: tuple[int, ...] = (1, 8),
    rrf_k: int = 60,
) -> dict[str, Any]:
    indexes = {
        name: build_generic_index(docs, database=name, use_cache=False)
        for name, docs in corpora.items()
    }
    rags = {name: MemoryRag(docs, embedder) for name, docs in corpora.items()}
    cases = []
    for case in CASES:
        database = case["database"]
        print(f"{case['id']}: {case['question'][:72]}")
        cases.append(
            _run_case(
                case,
                index=indexes[database],
                rag=rags[database],
                model=model,
                rag_ks=rag_ks,
                rrf_k=rrf_k,
            )
        )
    return {
        "rag_ks": list(rag_ks),
        "embedder": embedder is not None,
        "footprint": {
            name: {
                "cards": len(indexes[name].cards),
                "chunks": len(rags[name].chunks),
            }
            for name in corpora
        },
        "cases": cases,
    }


def _run_case(
    case: dict[str, Any],
    *,
    index: Any,
    rag: MemoryRag,
    model: ReasoningModel,
    rag_ks: tuple[int, ...],
    rrf_k: int,
) -> dict[str, Any]:
    question = case["question"]
    mare = _answer_mare(index, question, model)
    rag_runs = {
        f"k{k}": _answer_rag(rag, question, model, k=k, rrf_k=rrf_k) for k in rag_ks
    }
    return {
        "id": case["id"],
        "database": case["database"],
        "title": case["title"],
        "question": question,
        "mare": mare,
        "rag": rag_runs,
    }


def _answer_mare(index: Any, question: str, model: ReasoningModel) -> dict[str, Any]:
    started = time.perf_counter()
    found = index.investigate(question)
    retrieved = _docs_for_ids(index, found["document_ids"])
    supporting = _supporting_docs(index, found["evidence_receipt"], found["document_ids"])
    receipt = found["evidence_receipt"]
    prompt = _prompt(
        question,
        retrieved,
        supporting=supporting,
        preamble=(
            "Retrieval receipt:\n"
            f"- exact: {receipt['exact']}\n"
            f"- count: {receipt['count']}\n"
            f"- absence_scope: {receipt['absence_scope']}\n"
            f"- plan: {receipt['plan_id']}\n"
            f"- exhaustive_database: {receipt['exhaustive_database']}"
        ),
    )
    generated = model.generate(prompt, system=_MARE_SYSTEM)
    elapsed = (time.perf_counter() - started) * 1000
    blob = _blob(question, retrieved, generated.text, generated.usage.total_tokens, elapsed)
    blob["receipt"] = receipt
    blob["count"] = found["count"]
    return blob


def _answer_rag(
    rag: MemoryRag,
    question: str,
    model: ReasoningModel,
    *,
    k: int,
    rrf_k: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    retrieved = rag.search(question, k, rrf_k=rrf_k)
    prompt = _prompt(question, retrieved, preamble=f"Top-{k} chunks")
    generated = model.generate(prompt, system=_RAG_SYSTEM)
    elapsed = (time.perf_counter() - started) * 1000
    blob = _blob(question, retrieved, generated.text, generated.usage.total_tokens, elapsed)
    blob["k"] = k
    return blob


def _docs_for_ids(index: Any, document_ids: list[str]) -> list[dict[str, str]]:
    from app.baseline.memory_rag import render_document

    wanted = set(document_ids)
    found = []
    for collection, docs in index.documents.items():
        for doc in docs:
            doc_id = str(doc.get("_id"))
            if doc_id in wanted:
                found.append(
                    {
                        "collection": collection,
                        "document_id": doc_id,
                        "text": render_document(doc),
                    }
                )
    order = {doc_id: i for i, doc_id in enumerate(document_ids)}
    found.sort(key=lambda item: order.get(item["document_id"], 0))
    return found


def _supporting_docs(
    index: Any, receipt: dict[str, Any], document_ids: list[str]
) -> list[dict[str, str]]:
    """Documents on the other side of a hop. The answer ids stay the hop target."""
    from app.baseline.memory_rag import render_document

    plan_id = str(receipt.get("plan_id") or "")
    if not plan_id.startswith("hop:"):
        return []
    wanted = set(document_ids)
    pairs: list[tuple[str, str]] = []
    body = plan_id.split(":", 1)[1]
    if "->" in body and "." in body.split("->", 1)[0]:
        left, _right = body.split("->", 1)
        collection, field = left.split(".", 1)
        pairs.append((collection, field))
    else:
        target = body
        for plan in index.plans:
            if plan.get("op") == "hop" and plan.get("to_collection") == target:
                pairs.append((str(plan["collection"]), str(plan["field"])))
    found = []
    seen: set[str] = set()
    for collection, field in pairs:
        for doc in index.documents.get(collection) or []:
            if str(doc.get(field)) not in wanted:
                continue
            doc_id = str(doc.get("_id"))
            if doc_id in seen:
                continue
            seen.add(doc_id)
            found.append(
                {
                    "collection": collection,
                    "document_id": doc_id,
                    "text": render_document(doc),
                }
            )
    return found


def _prompt(
    question: str,
    retrieved: list[dict[str, str]],
    *,
    preamble: str,
    supporting: list[dict[str, str]] | None = None,
) -> str:
    def blocks(items: list[dict[str, str]]) -> str:
        if not items:
            return "(none)"
        return "\n\n".join(
            f"[{item['collection']} {item['document_id']}]\n{item['text']}" for item in items
        )

    support = ""
    if supporting:
        support = f"\n\nSupporting documents:\n{blocks(supporting)}"
    return (
        f"Question: {question}\n\n{preamble}\n\n"
        f"Answer documents:\n{blocks(retrieved)}{support}\n\n"
        "Answer using only this evidence. Cite source ids."
    )


def _blob(
    question: str,
    retrieved: list[dict[str, str]],
    answer: str,
    tokens: int,
    elapsed_ms: float,
) -> dict[str, Any]:
    case = _case_for(question)
    spec = {
        "must_contain_any": case.get("must_contain_any") or [],
        "must_contain_all": case.get("must_contain_all") or [],
        "must_not_contain": case.get("must_not_contain") or [],
    }
    return {
        "answer": answer.strip(),
        "tokens": tokens,
        "elapsed_ms": round(elapsed_ms, 1),
        "retrieved": retrieved,
        "retrieval": retrieval_metrics(retrieved, case["gold_sources"]),
        "answer_score": answer_scores(answer, spec),
    }


def case_kind(case_id: str) -> str:
    return case_id.split("_", 1)[1]


def performance_table(payload: dict[str, Any]) -> str:
    """One row per question: answer, gold recall, latency, and tokens for each engine."""
    ks = [int(k) for k in payload["rag_ks"]]
    headers = ["case", "kind", "MARE", "recall", "ms", "tok"]
    for k in ks:
        headers.extend([f"RAG K={k}", "recall", "ms", "tok"])
    rows = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---", "---"] + ["---:"] * (len(headers) - 2)) + " |",
    ]
    mare_ok = 0
    rag_ok = {k: 0 for k in ks}
    mare_ms: list[float] = []
    mare_tok: list[int] = []
    rag_ms = {k: [] for k in ks}
    rag_tok = {k: [] for k in ks}
    for case in payload["cases"]:
        mare = case["mare"]
        ok = bool(mare["answer_score"]["correct"])
        mare_ok += ok
        mare_ms.append(float(mare["elapsed_ms"]))
        mare_tok.append(int(mare["tokens"]))
        cells = [
            case["title"],
            case_kind(case["id"]),
            _yn(ok),
            _recall(mare),
            str(round(mare["elapsed_ms"])),
            str(mare["tokens"]),
        ]
        for k in ks:
            blob = case["rag"][f"k{k}"]
            hit = bool(blob["answer_score"]["correct"])
            rag_ok[k] += hit
            rag_ms[k].append(float(blob["elapsed_ms"]))
            rag_tok[k].append(int(blob["tokens"]))
            cells.extend(
                [
                    _yn(hit),
                    _recall(blob),
                    str(round(blob["elapsed_ms"])),
                    str(blob["tokens"]),
                ]
            )
        rows.append("| " + " | ".join(cells) + " |")
    total = len(payload["cases"])
    summary = [
        "mean",
        "",
        f"**{mare_ok}/{total}**",
        "",
        f"**{_mean(mare_ms)}**",
        f"**{_mean(mare_tok)}**",
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


def _mean(values: list[float] | list[int]) -> int:
    if not values:
        return 0
    return round(sum(values) / len(values))


def _yn(flag: bool) -> str:
    return "yes" if flag else "no"


def _recall(blob: dict[str, Any]) -> str:
    value = blob["retrieval"]["gold_evidence_recall"]
    if value is None:
        return "n/a"
    return f"{float(value):.2f}"


def _case_for(question: str) -> dict[str, Any]:
    for case in CASES:
        if case["question"] == question:
            return case
    raise KeyError(question)
