#!/usr/bin/env python3
"""Run MARE vs RAG on lookup, multi-hop, and RAG-unfriendly cases; write reports/."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.baseline.rag import run_rag, vector_counts
from app.config import get_settings
from app.eval.scoring import answer_scores, evidence_scores
from app.llm import get_reasoning_model
from app.llm.openai_model import OpenAIReasoningModel
from app.mongo.client import ping
from app.retrieval.agent_loop import run_agent

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "benchmarks" / "gold.json"
OUT = ROOT / "reports"

CASES = [
    (
        "simple_lookup",
        "simple_apex_tier",
        "Simple lookup — subscription tier",
        "ID is in the question. RAG is the fast path; MARE should match accuracy "
        "with higher citation precision. Blind mode must discover the customer "
        "collection via the navigation index.",
    ),
    (
        "multihop",
        "mh_auth_sso",
        "Named multi-hop — Apex Logistics SSO failure",
        "The question names cust_007 and mig_auth_sso, so Top-K can scoop the whole "
        "story in one shot. This is RAG's home turf.",
    ),
    (
        "bridge",
        "bridge_elena_may_deploys",
        "Bridge — entity not named in the question",
        "The question never says Apex, cust_007, AUTH_401, or SSO. Correct requires "
        "both identifying the customer and the SSO issuer root cause. MARE must hop "
        "via navigation (related_nodes), not a single filter.",
    ),
    (
        "aggregation",
        "agg_enterprise_count",
        "Aggregation — count enterprise customers",
        "The correct answer is a full-collection count. RAG can only count what "
        "fits in Top-K chunks; MARE can run a structured Mongo query after discovering "
        "the collection from the navigation index.",
    ),
    (
        "negative",
        "neg_cedar_april_incidents",
        "Negative — prove April incidents do not exist",
        "Top-K always returns something. MARE can filter and return zero documents, "
        "which is the only way to ground a negative.",
    ),
]


def _session_blob(session) -> dict:
    return {
        "session_id": session.id,
        "engine_status": session.status.value
        if hasattr(session.status, "value")
        else str(session.status),
        "stop_reason": session.stop_reason,
        "answer": session.answer,
        "hypothesis": session.hypothesis,
        "claims": [c.model_dump(mode="json") for c in session.claims],
        "citations": [c.model_dump(mode="json") for c in session.citations],
        "retrieval_count": session.retrieval_count,
        "tokens_consumed": session.tokens_consumed,
        "elapsed_ms": session.elapsed_ms,
        "agent_turns": getattr(session, "agent_turns", 0) or 0,
        "tool_calls": getattr(session, "tool_calls", 0) or 0,
        "llm_latency_ms": getattr(session, "llm_latency_ms", 0) or 0,
        "mongo_latency_ms": getattr(session, "mongo_latency_ms", 0) or 0,
        "router_recommendation": (
            session.router_recommendation.value
            if session.router_recommendation is not None
            else None
        ),
    }


def _answer_spec(gold_query: dict) -> dict:
    spec = dict(gold_query)
    qid = spec.get("id")
    if qid == "simple_apex_tier":
        spec.setdefault("must_contain_any", ["enterprise"])
    if qid == "mh_auth_sso":
        spec.setdefault("must_contain_any", ["issuer", "auth_401", "auth-v3", "mig_auth_sso"])
    return spec


def _score_engine(blob: dict, gold_query: dict) -> None:
    gold_sources = gold_query.get("gold_sources") or []
    blob["evidence"] = evidence_scores(blob.get("citations") or [], gold_sources)
    blob["answer_score"] = answer_scores(
        blob.get("answer") or "",
        {**_answer_spec(gold_query), "_citations": blob.get("citations") or []},
    )


def run_pair(
    question: str,
    gold_query: dict,
    *,
    schema_in_prompt: bool,
    max_turns: int,
    skip_rag: bool = False,
    existing_rag: dict | None = None,
) -> dict:
    gold_sources = gold_query.get("gold_sources") or []
    mode = "informed" if schema_in_prompt else "blind"
    print(f"  MARE ({mode}): {question[:80]}...")
    adaptive = run_agent(
        question, schema_in_prompt=schema_in_prompt, max_turns=max_turns
    )
    print(
        f"    done {adaptive.status.value} {round(adaptive.elapsed_ms)}ms "
        f"turns={adaptive.agent_turns} tools={adaptive.tool_calls} "
        f"llm={round(adaptive.llm_latency_ms)}ms mongo={round(adaptive.mongo_latency_ms)}ms"
    )
    a = _session_blob(adaptive)
    a["evidence"] = evidence_scores(a["citations"], gold_sources)
    a["answer_score"] = answer_scores(
        a["answer"], {**_answer_spec(gold_query), "_citations": a["citations"]}
    )
    if skip_rag and existing_rag:
        r = existing_rag
        print("  RAG:  reused from previous comparison.json")
    else:
        print(f"  RAG:  {question[:80]}...")
        rag = run_rag(question)
        print(f"    done {rag.status.value} {round(rag.elapsed_ms)}ms")
        r = _session_blob(rag)
        r["evidence"] = evidence_scores(r["citations"], gold_sources)
        r["answer_score"] = answer_scores(
            r["answer"], {**_answer_spec(gold_query), "_citations": r["citations"]}
        )
    return {"adaptive": a, "rag": r}


def markdown_case(
    title: str,
    why: str,
    question: str,
    gold_answer: str,
    pair: dict,
    footprint: dict,
    *,
    schema_in_prompt: bool,
    max_turns: int,
) -> str:
    a, r = pair["adaptive"], pair["rag"]
    informed = pair.get("informed")
    mode = "informed" if schema_in_prompt and not pair.get("blind_primary") else "blind"
    if pair.get("blind_primary"):
        mode = "blind"
    lines = [
        f"# {title}",
        "",
        f"- generated: {datetime.now(UTC).isoformat()}",
        f"- answer model: `{get_settings().openai_model}`",
        f"- agent model: `{get_settings().openai_model_agent}` "
        f"(reasoning_effort={get_settings().openai_reasoning_effort})",
        f"- MARE mode: **{mode}** (schema_in_prompt={str(schema_in_prompt).lower()})",
        f"- max_agent_turns: {max_turns}",
        f"- vector index: MARE **{footprint['adaptive_vector_count']}** vs RAG "
        f"**{footprint['rag_vector_count']}** (ratio {footprint['adaptive_over_rag']})",
        "",
        "## Why this case",
        "",
        why,
        "",
        "## Question",
        "",
        question,
        "",
        "## Gold answer",
        "",
        gold_answer,
        "",
        "## Latency and retrieval",
        "",
        f"| metric | MARE ({mode}) | Conventional RAG |",
        "| --- | --- | --- |",
        f"| end-to-end latency | **{round(a['elapsed_ms'])} ms** | "
        f"**{round(r['elapsed_ms'])} ms** |",
        f"| agent turns | {a.get('agent_turns', 0)} | n/a |",
        f"| tool calls | {a.get('tool_calls', 0)} | n/a |",
        f"| LLM latency | {round(a.get('llm_latency_ms') or 0)} ms | n/a |",
        f"| Mongo latency | {round(a.get('mongo_latency_ms') or 0)} ms | n/a |",
        f"| retrieval operations | {a['retrieval_count']} | {r['retrieval_count']} |",
        f"| LLM tokens | {a['tokens_consumed']} | {r['tokens_consumed']} |",
        f"| stop reason | {a['stop_reason']} | {r['stop_reason']} |",
        f"| answer correct | {_yn(a['answer_score']['correct'])} | "
        f"{_yn(r['answer_score']['correct'])} |",
    ]
    if a["answer_score"].get("entity_found") is not None:
        lines += [
            f"| entity found | {_yn(a['answer_score']['entity_found'])} | "
            f"{_yn(r['answer_score'].get('entity_found'))} |",
            f"| root cause found | {_yn(a['answer_score']['cause_found'])} | "
            f"{_yn(r['answer_score'].get('cause_found'))} |",
        ]
    lines += [
        f"| evidence recall vs gold | {_fmt_recall(a['evidence'])} | "
        f"{_fmt_recall(r['evidence'])} |",
        f"| evidence precision vs gold | {a['evidence']['precision']} | "
        f"{r['evidence']['precision']} |",
        "",
        "Persistent vector indexes (not per-query scan count): MARE searches the "
        f"{footprint['adaptive_vector_count']}-node navigation index, then reads "
        "raw Mongo documents. "
        f"RAG searches the {footprint['rag_vector_count']}-chunk vector index "
        "and returns Top-K.",
        "",
        f"## MARE answer ({mode})",
        "",
        a["answer"] or "_(empty)_",
        "",
        "### Hypothesis",
        "",
        a["hypothesis"] or "_(none)_",
        "",
        "### Claims",
        "",
    ]
    if a["claims"]:
        for c in a["claims"]:
            status = c["status"]
            if hasattr(status, "value"):
                status = status.value
            lines.append(
                f"- `{c['claim_id']}` **{status}** ({c['confidence']:.2f}): {c['claim']}"
            )
    else:
        lines.append("_(none)_")
    lines += [
        "",
        "### Citations",
        "",
        _cite_list(a["citations"]),
        "",
        f"Gold hits: {', '.join(a['evidence']['hit']) or 'none'}",
        f"Missed gold: {', '.join(a['evidence']['missed']) or 'none'}",
        "",
        "## RAG answer",
        "",
        r["answer"] or "_(empty)_",
        "",
        "### Citations",
        "",
        _cite_list(r["citations"]),
        "",
        f"Gold hits: {', '.join(r['evidence']['hit']) or 'none'}",
        f"Missed gold: {', '.join(r['evidence']['missed']) or 'none'}",
        "",
    ]
    if informed and informed is not a:
        iscore = informed.get("answer_score") or {}
        lines += [
            "## MARE answer (informed)",
            "",
            f"- correct: {_yn(iscore.get('correct'))} · {round(informed.get('elapsed_ms') or 0)} ms · "
            f"turns={informed.get('agent_turns', 0)} · stop={informed.get('stop_reason')}",
            "",
            informed.get("answer") or "_(empty)_",
            "",
            "### Citations",
            "",
            _cite_list(informed.get("citations") or []),
            "",
        ]
        if iscore.get("entity_found") is not None:
            lines += [
                f"entity={_yn(iscore.get('entity_found'))} "
                f"cause={_yn(iscore.get('cause_found'))}",
                "",
            ]
    return "\n".join(lines)


def _cite_list(citations: list[dict]) -> str:
    if not citations:
        return "_(none)_"
    return "\n".join(
        f"- `{c.get('database')}.{c.get('collection')}:{c.get('document_id')}`"
        for c in citations
    )


def _yn(flag: bool | None) -> str:
    if flag is None:
        return "n/a"
    return "yes" if flag else "no"


def _fmt_recall(evidence: dict) -> str:
    rec = evidence.get("recall")
    return "n/a" if rec is None else str(rec)


def _parse_cli(argv: list[str]) -> dict:
    informed = "--informed" in argv
    rescore = "--rescore" in argv
    rerun_rag = "--rerun-rag" in argv
    only = None
    if "--only" in argv:
        only = argv[argv.index("--only") + 1]
    turns = None
    if "--turns" in argv:
        turns = int(argv[argv.index("--turns") + 1])
    return {
        "informed": informed,
        "rescore": rescore,
        "rerun_rag": rerun_rag,
        "only": only,
        "turns": turns,
    }


def _rescore_from_payload() -> None:
    gold = {q["id"]: q for q in json.loads(GOLD.read_text())["queries"]}
    payload = json.loads((OUT / "comparison.json").read_text())
    footprint = payload["vector_footprint"]
    by_slug = {c[0]: c for c in CASES}
    schema_in_prompt = bool(payload.get("schema_in_prompt"))
    max_turns = int(payload.get("max_agent_turns") or get_settings().max_agent_turns)
    for slug, case in payload["cases"].items():
        q = gold[case["id"]]
        for key in ("adaptive", "adaptive_blind", "adaptive_informed", "rag"):
            if key in case:
                _score_engine(case[key], q)
        meta = by_slug.get(slug)
        if not meta:
            continue
        _, _, title, why = meta
        blind = case.get("adaptive_blind") or case.get("adaptive")
        informed = case.get("adaptive_informed")
        current = {
            "adaptive": blind,
            "rag": case["rag"],
            "informed": informed,
            "blind_primary": bool(case.get("adaptive_blind")),
        }
        md = markdown_case(
            title,
            why,
            case["question"],
            case["gold_answer"],
            current,
            footprint,
            schema_in_prompt=False,
            max_turns=max_turns,
        )
        (OUT / f"{slug}.md").write_text(md + "\n", encoding="utf-8")
        print(
            f"rescored {slug} MARE={current['adaptive']['answer_score']['correct']} "
            f"RAG={case['rag']['answer_score']['correct']}"
        )
    (OUT / "comparison.json").write_text(json.dumps(payload, indent=2, default=str) + "\n")
    (OUT / "README.md").write_text(_summary_md(payload), encoding="utf-8")
    print(f"wrote {OUT / 'README.md'}")


def main() -> None:
    cli = _parse_cli(sys.argv)
    if cli["rescore"]:
        _rescore_from_payload()
        return
    ping()
    settings = get_settings()
    model = get_reasoning_model()
    if not isinstance(model, OpenAIReasoningModel):
        raise SystemExit("OPENAI_API_KEY is not loaded; refusing to run LLM-off comparison.")
    schema_in_prompt = bool(cli["informed"])
    max_turns = int(cli["turns"] if cli["turns"] is not None else settings.max_agent_turns)
    mode = "informed" if schema_in_prompt else "blind"
    print(
        f"using {type(model).__name__} answer={settings.openai_model} "
        f"agent={settings.openai_model_agent} mode={mode} turns={max_turns}"
    )

    gold = {q["id"]: q for q in json.loads(GOLD.read_text())["queries"]}
    footprint = vector_counts()
    OUT.mkdir(parents=True, exist_ok=True)

    cases = list(CASES)
    if cli["only"]:
        cases = [c for c in cases if c[0] == cli["only"]]
        if not cases:
            slugs = ", ".join(c[0] for c in CASES)
            raise SystemExit(f"unknown --only {cli['only']}; use {slugs}")

    prev: dict = {}
    prev_path = OUT / "comparison.json"
    if prev_path.exists():
        prev = json.loads(prev_path.read_text())

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "model": settings.openai_model,
        "agent_model": settings.openai_model_agent,
        "reasoning_effort": settings.openai_reasoning_effort,
        "max_agent_turns": max_turns,
        "schema_in_prompt": schema_in_prompt,
        "mode": mode,
        "reasoner": type(model).__name__,
        "vector_footprint": footprint,
        "max_elapsed_ms": settings.max_elapsed_ms,
        "cases": prev.get("cases", {}),
    }

    for slug, qid, title, why in cases:
        q = gold[qid]
        print(f"\n=== {title} ({qid}) ===")
        existing = payload["cases"].get(slug) or {}
        skip_rag = (
            (schema_in_prompt or bool(cli["only"]))
            and bool(existing.get("rag"))
            and not cli["rerun_rag"]
        )
        pair = run_pair(
            q["question"],
            q,
            schema_in_prompt=schema_in_prompt,
            max_turns=max_turns,
            skip_rag=skip_rag,
            existing_rag=existing.get("rag"),
        )
        stored = {
            "id": qid,
            "class": q["class"],
            "question": q["question"],
            "gold_answer": q["gold_answer"],
            "why": why,
            "rag": pair["rag"],
            "adaptive": pair["adaptive"],
        }
        if existing.get("adaptive_blind") and schema_in_prompt:
            stored["adaptive_blind"] = existing["adaptive_blind"]
        if existing.get("adaptive_informed") and not schema_in_prompt:
            stored["adaptive_informed"] = existing["adaptive_informed"]
        if schema_in_prompt:
            stored["adaptive_informed"] = pair["adaptive"]
            if existing.get("adaptive_blind"):
                stored["adaptive_blind"] = existing["adaptive_blind"]
        else:
            stored["adaptive_blind"] = pair["adaptive"]
            if existing.get("adaptive_informed"):
                stored["adaptive_informed"] = existing["adaptive_informed"]
        payload["cases"][slug] = stored
        primary = stored.get("adaptive_blind") or pair["adaptive"]
        md = markdown_case(
            title,
            why,
            q["question"],
            q["gold_answer"],
            {
                "adaptive": primary,
                "rag": pair["rag"],
                "informed": stored.get("adaptive_informed"),
                "blind_primary": bool(stored.get("adaptive_blind")),
            },
            footprint,
            schema_in_prompt=schema_in_prompt and not stored.get("adaptive_blind"),
            max_turns=max_turns,
        )
        (OUT / f"{slug}.md").write_text(md + "\n", encoding="utf-8")
        print(f"wrote {OUT / f'{slug}.md'}")

    (OUT / "comparison.json").write_text(json.dumps(payload, indent=2, default=str) + "\n")
    (OUT / "README.md").write_text(_summary_md(payload), encoding="utf-8")
    print(f"\nwrote {OUT / 'README.md'}")
    print(json.dumps({"model": settings.openai_model, "mode": mode, "footprint": footprint}, indent=2))


def _mare_blob(case: dict) -> dict:
    return case.get("adaptive_blind") or case.get("adaptive") or {}


def _summary_md(payload: dict) -> str:
    fp = payload["vector_footprint"]
    mode = payload.get("mode") or ("informed" if payload.get("schema_in_prompt") else "blind")
    has_both = any(
        "adaptive_blind" in c and "adaptive_informed" in c
        for c in payload.get("cases", {}).values()
    )
    mode_line = (
        "- MARE modes compared: **blind** (no schema in prompt) and **informed**"
        if has_both
        else f"- MARE mode: **{mode}** (schema_in_prompt="
        f"{str(bool(payload.get('schema_in_prompt'))).lower()})"
    )
    lines = [
        "# MARE vs RAG — LLM-on comparison",
        "",
        f"- generated: {payload['generated_at']}",
        f"- answering model: `{payload['model']}`",
        f"- agent model: `{payload.get('agent_model', 'n/a')}` "
        f"(reasoning_effort={payload.get('reasoning_effort', 'n/a')})",
        mode_line,
        f"- max_agent_turns: {payload.get('max_agent_turns', 'n/a')}",
        f"- max_elapsed_ms: {payload.get('max_elapsed_ms', 'n/a')}",
        f"- persistent vectors: MARE **{fp['adaptive_vector_count']}** / RAG "
        f"**{fp['rag_vector_count']}** (ratio **{fp['adaptive_over_rag']}**)",
        "",
        "## What this comparison is for",
        "",
        "The default MARE run is **schema-blind**: the system prompt does not name "
        "databases, collections, or fields. If MARE still finds the right "
        "neighborhood, the navigation index is doing the work — not a leaked schema. "
        "Pass `--informed` to A/B against the schema-in-prompt variant.",
        "",
        "Conventional RAG is not obsolete. Named lookups and named multi-hop "
        "questions put the entity IDs in the prompt, so a single Top-K hybrid "
        "search can scoop the whole story. Those cases measure RAG on its home "
        "turf: expect RAG to be faster, and often to cite more gold documents.",
        "",
        "MARE is built for questions Top-K cannot structurally answer, *and* that "
        "a schema-aware Mongo MCP agent would still need a map to discover:",
        "",
        "- **Bridge** — the question does not name the entity; the next hop's "
        "evidence shares no vocabulary with the question. Scoring requires both "
        "entity identity and root cause.",
        "- **Aggregation** — the answer is a count over the collection, not a "
        "nearby chunk.",
        "- **Negative** — the correct answer is that matching documents do not "
        "exist. Top-K always returns something.",
        "",
        "The headline index metric is unchanged: "
        f"**{fp['adaptive_vector_count']} navigation vectors vs "
        f"{fp['rag_vector_count']} RAG chunks**.",
        "",
        "## Results",
        "",
    ]
    if has_both:
        lines += [
            "| case | MARE blind | MARE informed | RAG | blind ms | informed ms | RAG ms |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    else:
        lines += [
            "| case | MARE correct | RAG correct | MARE ms | RAG ms | "
            "MARE recall | RAG recall |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    labels = (
        ("simple_lookup", "Simple lookup"),
        ("multihop", "Named multi-hop"),
        ("bridge", "Bridge (unnamed entity)"),
        ("aggregation", "Aggregation (count)"),
        ("negative", "Negative (absence)"),
    )
    for slug, label in labels:
        c = payload["cases"].get(slug)
        if not c:
            continue
        a = _mare_blob(c)
        r = c["rag"]
        if has_both:
            b = c.get("adaptive_blind") or {}
            inf = c.get("adaptive_informed") or {}
            lines.append(
                f"| [{label}]({slug}.md) | "
                f"{_yn((b.get('answer_score') or {}).get('correct'))} | "
                f"{_yn((inf.get('answer_score') or {}).get('correct'))} | "
                f"{_yn(r['answer_score']['correct'])} | "
                f"{round(b.get('elapsed_ms') or 0)} | "
                f"{round(inf.get('elapsed_ms') or 0)} | "
                f"{round(r['elapsed_ms'])} |"
            )
        else:
            lines.append(
                f"| [{label}]({slug}.md) | {_yn(a['answer_score']['correct'])} | "
                f"{_yn(r['answer_score']['correct'])} | "
                f"{round(a['elapsed_ms'])} | {round(r['elapsed_ms'])} | "
                f"{_fmt_recall(a['evidence'])} | {_fmt_recall(r['evidence'])} |"
            )
    lines += [
        "",
        "Full machine-readable dump: [comparison.json](comparison.json).",
        "",
        "## How to read the table",
        "",
        "- **Simple lookup / named multi-hop:** RAG is allowed to win on latency "
        "and gold-source recall. Blind MARE should still be *correct* after discovering "
        "schema from navigation nodes.",
        "- **Bridge:** entity-only answers are no longer marked correct. Both "
        "`entity_found` and `cause_found` must hold. That is the hop the product claims.",
        "- **Aggregation / negative:** structured query after discovery, not Top-K.",
        "",
        "These two levers are what justify MARE over plain Mongo MCP: (1) the "
        "agent was not told the schema, and (2) bridge scoring requires the second "
        "hop (root cause), not just naming the customer.",
        "",
        "## What happened on this run",
        "",
    ]
    for slug, label in labels:
        c = payload["cases"].get(slug)
        if not c:
            continue
        a = _mare_blob(c)
        r = c["rag"]
        score = a.get("answer_score") or {}
        extra = ""
        if score.get("entity_found") is not None:
            extra = (
                f" entity={_yn(score.get('entity_found'))} "
                f"cause={_yn(score.get('cause_found'))}."
            )
        informed = c.get("adaptive_informed")
        informed_bit = ""
        if informed:
            iscore = informed.get("answer_score") or {}
            informed_bit = (
                f" Informed {_yn(iscore.get('correct'))} "
                f"({round(informed.get('elapsed_ms') or 0)}ms)."
            )
        lines.append(
            f"- **{label}:** Blind MARE {_yn(score.get('correct'))} "
            f"({round(a.get('elapsed_ms') or 0)}ms, stop={a.get('stop_reason')})."
            f"{informed_bit} "
            f"RAG {_yn((r.get('answer_score') or {}).get('correct'))} "
            f"({round(r.get('elapsed_ms') or 0)}ms).{extra}"
        )
    lines += [
        "",
        "## How to rerun",
        "",
        "```bash",
        "python scripts/run_comparison.py              # schema-blind MARE vs RAG",
        "python scripts/run_comparison.py --informed   # A/B with schema in the prompt",
        "python scripts/run_comparison.py --only bridge",
        "python scripts/run_comparison.py --turns 10",
        "python scripts/run_comparison.py --rescore    # no LLM; rewrite markdown",
        "```",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
