# MARE vs RAG — LLM-on comparison

- generated: 2026-08-27T06:17:57.602240+00:00
- answering model: `gpt-5`
- agent model: `gpt-5-mini` (reasoning_effort=low)
- MARE modes compared: **blind** (no schema in prompt) and **informed**
- max_agent_turns: 10
- max_elapsed_ms: 90000
- persistent vectors: MARE **616** / RAG **5424** (ratio **0.1136**)

Informed-schema blobs for simple lookup, named multi-hop, bridge, aggregation, and negative were **reused from the previous comparison.json** and were not re-run after this reseed. Treat those informed columns as a prior control, not as this run.

## What this comparison is for

The default MARE run is **schema-blind**: the system prompt does not name databases, collections, or fields. If MARE still finds the right neighborhood, the navigation index is doing the work — not a leaked schema. Pass `--informed` to A/B against the schema-in-prompt variant.

Conventional RAG is not obsolete. Named lookups and named multi-hop questions put the entity IDs in the prompt, so a single Top-K hybrid search can scoop the whole story. Those cases measure RAG on its home turf: expect RAG to be faster, and often to cite more gold documents.

MARE is built for questions Top-K cannot structurally answer, *and* that a schema-aware Mongo MCP agent would still need a map to discover:

- **Bridge** — the question does not name the entity; the next hop's evidence shares no vocabulary with the question. Scoring requires both entity identity and root cause.
- **Aggregation** — the answer is a count over the collection, not a nearby chunk.
- **Negative** — the correct answer is that matching documents do not exist. Top-K always returns something.
- **Distributed (B1)** — no single record contains the causal sentence. Headline metric is gold evidence recall over retrieved docs, plus answer completeness groups.
- **Variable K (B2)** — three Apex auth questions that need ~2, ~7, and ~18 gold records. RAG is swept at hybrid Top-K 5/10/20 (and vector K=10).

The headline index metric is unchanged: **616 navigation vectors vs 5424 RAG chunks**.

## Results

| case | MARE blind | MARE informed | RAG | blind ms | informed ms | RAG ms |
| --- | --- | --- | --- | --- | --- | --- |
| [Simple lookup](simple_lookup.md) | yes | yes | yes | 10977 | 8543 | 3931 |
| [Named multi-hop](multihop.md) | yes | yes | yes | 28942 | 34272 | 9663 |
| [Bridge (unnamed entity)](bridge.md) | yes | yes | no | 20875 | 30376 | 5114 |
| [Aggregation (count)](aggregation.md) | no | yes | no | 16783 | 17081 | 5845 |
| [Negative (absence)](negative.md) | yes | yes | no | 15504 | 12325 | 4126 |
| [Distributed evidence](distributed.md) | yes | n/a | no | 26866 | 0 | 11719 |
| [Variable K — small](vk_small.md) | no | n/a | no | 15159 | 0 | 6861 |
| [Variable K — medium](vk_medium.md) | yes | n/a | yes | 21989 | 0 | 12190 |
| [Variable K — deep](vk_deep.md) | yes | n/a | yes | 33757 | 0 | 12686 |

Full machine-readable dump: [comparison.json](comparison.json).

## How to read the table

- **Simple lookup / named multi-hop:** RAG is allowed to win on latency and gold-source recall. Blind MARE should still be *correct* after discovering schema from navigation nodes.
- **Bridge:** entity-only answers are no longer marked correct. Both `entity_found` and `cause_found` must hold. That is the hop the product claims.
- **Aggregation / negative:** structured query after discovery, not Top-K.
- **Distributed:** completeness requires all four evidence fragments (entity, identity cutover, stale runtime config, token rejection). Citation-only recall is not enough — we score retrieved document ids.
- **Variable K:** MARE retrieval volume should rise from small → medium → deep. RAG at a fixed K either misses the deep gold set or over-retrieves the small question.

These two levers are what justify MARE over plain Mongo MCP: (1) the agent was not told the schema, and (2) bridge scoring requires the second hop (root cause), not just naming the customer.

## Semantic retrieval (B1 / B2)

Gold evidence recall is scored on **retrieved document ids**, not answer citations. Completeness is `groups_hit / groups_total` on the answer.

| case | MARE gold recall | RAG hybrid_10 recall | MARE docs | RAG docs | MARE complete | RAG complete |
| --- | --- | --- | --- | --- | --- | --- |
| [Distributed (B1)](distributed.md) | 0.5 | 0.25 | 16 | 10 | 4/4 | 2/4 |
| [Variable K — small](vk_small.md) | 0.5 | 1.0 | 2 | 10 | 1/2 | 1/2 |
| [Variable K — medium](vk_medium.md) | 0.143 | 0.857 | 2 | 10 | 3/3 | 3/3 |
| [Variable K — deep](vk_deep.md) | 0.333 | 0.5 | 23 | 10 | 4/4 | 4/4 |

RAG Top-K sweep on the deep Apex question:

| variant | correct | gold recall | docs | completeness |
| --- | --- | --- | --- | --- |
| hybrid_10 | yes | 0.5 | 10 | 4/4 |
| hybrid_20 | yes | 0.889 | 20 | 4/4 |
| hybrid_5 | yes | 0.222 | 5 | 4/4 |
| vector_10 | yes | 0.5 | 10 | 4/4 |

## What happened on this run

- **Simple lookup:** Blind MARE yes (10977ms, stop=completed). Informed yes (8543ms). RAG yes (3931ms).
- **Named multi-hop:** Blind MARE yes (28942ms, stop=completed). Informed yes (34272ms). RAG yes (9663ms).
- **Bridge (unnamed entity):** Blind MARE yes (20875ms, stop=completed). Informed yes (30376ms). RAG no (5114ms). entity=yes cause=yes.
- **Aggregation (count):** Blind MARE no (16783ms, stop=completed). Informed yes (17081ms). RAG no (5845ms).
- **Negative (absence):** Blind MARE yes (15504ms, stop=completed). Informed yes (12325ms). RAG no (4126ms).
- **Distributed evidence:** Blind MARE yes (26866ms, stop=completed). RAG no (11719ms). entity=yes cause=yes.
- **Variable K — small:** Blind MARE no (15159ms, stop=completed). RAG no (6861ms). entity=no cause=yes.
- **Variable K — medium:** Blind MARE yes (21989ms, stop=completed). RAG yes (12190ms). entity=yes cause=yes.
- **Variable K — deep:** Blind MARE yes (33757ms, stop=completed). RAG yes (12686ms). entity=yes cause=yes.

## How to rerun

```bash
python scripts/run_comparison.py              # schema-blind MARE vs RAG
python scripts/run_comparison.py --informed   # A/B with schema in the prompt
python scripts/run_comparison.py --only bridge
python scripts/run_comparison.py --only distributed
python scripts/run_comparison.py --only vk
python scripts/run_comparison.py --turns 10
python scripts/run_comparison.py --rescore    # no LLM; rewrite markdown
```

## Scale index (LLM-off)

The 10K navigation layer is also scored as a **map** (ranked document ids, no agent): Recall@K, nDCG, MRR. That pass is not the product loop — it checks that neighborhoods are findable. Semantic prototypes: **604 vs 60,000** vectors, Recall@10 0.137 vs 0.230, MRR 0.481 vs 0.488. Density sweep and category breakout: [scale/README.md](scale/README.md).
