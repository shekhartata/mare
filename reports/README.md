# MARE vs RAG — LLM-on comparison

- generated: 2026-11-10T07:27:55.478271+00:00
- answering model: `gpt-5`
- agent model: `gpt-5-mini` (reasoning_effort=low)
- MARE modes compared: **blind** (no schema in prompt) and **informed**
- max_agent_turns: 10
- max_elapsed_ms: 90000
- persistent vectors: MARE **616** / RAG **5424** (ratio **0.1136**)

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

## Latency

Same nine questions, schema-blind, against the 29 Oct run. Mean time went from **39 seconds to 21 seconds**. Mean tokens went from **19k to 15k**. Correct answers stayed **7 of 9**.

The index stays in memory after the first question. Search reads fewer documents. When the agent has already cited documents it read, that answer is kept instead of paying for a second rewrite. The informed column below is the 29 Oct run. This run measured the schema-blind agent.

## Results

| case | MARE blind | MARE informed | RAG | blind ms | informed ms | RAG ms |
| --- | --- | --- | --- | --- | --- | --- |
| [Simple lookup](simple_lookup.md) | yes | yes | yes | 6819 | 8543 | 4034 |
| [Named multi-hop](multihop.md) | yes | yes | yes | 31432 | 34272 | 13048 |
| [Bridge (unnamed entity)](bridge.md) | no | yes | no | 41849 | 30376 | 6122 |
| [Aggregation (count)](aggregation.md) | yes | yes | no | 12369 | 17081 | 7260 |
| [Negative (absence)](negative.md) | yes | yes | no | 8883 | 12325 | 6812 |
| [Distributed evidence](distributed.md) | no | n/a | no | 11896 | 0 | 17277 |
| [Variable K — small](vk_small.md) | yes | n/a | no | 21004 | 0 | 5960 |
| [Variable K — medium](vk_medium.md) | yes | n/a | yes | 19463 | 0 | 11806 |
| [Variable K — deep](vk_deep.md) | yes | n/a | yes | 38953 | 0 | 26145 |

Full machine-readable dump: [comparison.json](comparison.json).

## How to read the table

- **Simple lookup / named multi-hop:** RAG is allowed to win on latency and gold-source recall. Blind MARE should still be *correct* after discovering schema from navigation nodes.
- **Bridge:** entity-only answers are no longer marked correct. Both `entity_found` and `cause_found` must hold. That is the hop the product claims.
- **Aggregation / negative:** structured query after discovery, not Top-K.
- **Distributed:** completeness requires all four evidence fragments (entity, identity cutover, stale runtime config, token rejection). Citation-only recall is not enough — we score retrieved document ids.
- **Variable K:** MARE retrieval volume should rise from small → medium → deep. RAG at a fixed K either misses the deep gold set or over-retrieves the small question.

These two levers are what justify MARE over plain Mongo MCP: (1) the agent was not told the schema, and (2) bridge scoring requires the second hop (root cause), not just naming the customer.

Measured control (same questions, `find`/`count`, no nav index): [mongo_mcp.md](mongo_mcp.md).

## Semantic retrieval (B1 / B2)

Gold evidence recall is scored on **retrieved document ids**, not answer citations. Completeness is `groups_hit / groups_total` on the answer.

| case | MARE gold recall | RAG hybrid_10 recall | MARE docs | RAG docs | MARE complete | RAG complete |
| --- | --- | --- | --- | --- | --- | --- |
| [Distributed (B1)](distributed.md) | 0.25 | 0.25 | 10 | 10 | 2/4 | 3/4 |
| [Variable K — small](vk_small.md) | 0.5 | 1.0 | 5 | 10 | 2/2 | 1/2 |
| [Variable K — medium](vk_medium.md) | 0.286 | 0.857 | 12 | 10 | 3/3 | 3/3 |
| [Variable K — deep](vk_deep.md) | 0.444 | 0.5 | 37 | 10 | 4/4 | 4/4 |

RAG Top-K sweep on the deep Apex question:

| variant | correct | gold recall | docs | completeness |
| --- | --- | --- | --- | --- |
| hybrid_10 | yes | 0.5 | 10 | 4/4 |
| hybrid_20 | yes | 0.889 | 20 | 4/4 |
| hybrid_5 | yes | 0.222 | 5 | 4/4 |
| vector_10 | yes | 0.5 | 10 | 4/4 |

## What happened on this run

- **Simple lookup:** Blind MARE yes (6819ms, stop=completed). Informed yes (8543ms). RAG yes (4034ms).
- **Named multi-hop:** Blind MARE yes (31432ms, stop=completed). Informed yes (34272ms). RAG yes (13048ms).
- **Bridge (unnamed entity):** Blind MARE no (41849ms, stop=max_agent_turns). Informed yes (30376ms). RAG no (6122ms). entity=yes cause=no.
- **Aggregation (count):** Blind MARE yes (12369ms, stop=completed). Informed yes (17081ms). RAG no (7260ms).
- **Negative (absence):** Blind MARE yes (8883ms, stop=completed). Informed yes (12325ms). RAG no (6812ms).
- **Distributed evidence:** Blind MARE no (11896ms, stop=completed). RAG no (17277ms). entity=no cause=yes.
- **Variable K — small:** Blind MARE yes (21004ms, stop=completed). RAG no (5960ms). entity=yes cause=yes.
- **Variable K — medium:** Blind MARE yes (19463ms, stop=completed). RAG yes (11806ms). entity=yes cause=yes.
- **Variable K — deep:** Blind MARE yes (38953ms, stop=completed). RAG yes (26145ms). entity=yes cause=yes.

## How to rerun

```bash
python scripts/run_comparison.py              # schema-blind MARE vs RAG
python scripts/run_comparison.py --informed   # A/B with schema in the prompt
python scripts/run_comparison.py --mongo-mcp  # find/count agent; reuse stored MARE/RAG
python scripts/run_comparison.py --only bridge
python scripts/run_comparison.py --only distributed
python scripts/run_comparison.py --only vk
python scripts/run_comparison.py --turns 10
python scripts/run_comparison.py --rescore    # no LLM; rewrite markdown
python scripts/run_comparison.py --rerun-rag  # force RAG after a reseed
```
