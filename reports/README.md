# MARE vs RAG — LLM-on comparison

- generated: 2026-08-26T08:36:55.653606+00:00
- answering model: `gpt-5`
- agent model: `gpt-5-mini` (reasoning_effort=low)
- MARE modes compared: **blind** (no schema in prompt) and **informed**
- max_agent_turns: 10
- max_elapsed_ms: 90000
- persistent vectors: MARE **618** / RAG **5424** (ratio **0.1139**)

## What this comparison is for

The default MARE run is **schema-blind**: the system prompt does not name databases, collections, or fields. If MARE still finds the right neighborhood, the navigation index is doing the work — not a leaked schema. Pass `--informed` to A/B against the schema-in-prompt variant.

Conventional RAG is not obsolete. Named lookups and named multi-hop questions put the entity IDs in the prompt, so a single Top-K hybrid search can scoop the whole story. Those cases measure RAG on its home turf: expect RAG to be faster, and often to cite more gold documents.

MARE is built for questions Top-K cannot structurally answer, *and* that a schema-aware Mongo MCP agent would still need a map to discover:

- **Bridge** — the question does not name the entity; the next hop's evidence shares no vocabulary with the question. Scoring requires both entity identity and root cause.
- **Aggregation** — the answer is a count over the collection, not a nearby chunk.
- **Negative** — the correct answer is that matching documents do not exist. Top-K always returns something.

The headline index metric is unchanged: **618 navigation vectors vs 5424 RAG chunks**.

## Results

| case | MARE blind | MARE informed | RAG | blind ms | informed ms | RAG ms |
| --- | --- | --- | --- | --- | --- | --- |
| [Simple lookup](simple_lookup.md) | yes | yes | yes | 8991 | 8543 | 3933 |
| [Named multi-hop](multihop.md) | yes | yes | yes | 18593 | 34272 | 13534 |
| [Bridge (unnamed entity)](bridge.md) | yes | yes | no | 38681 | 30376 | 8620 |
| [Aggregation (count)](aggregation.md) | yes | yes | no | 15764 | 17081 | 8168 |
| [Negative (absence)](negative.md) | yes | yes | no | 13364 | 12325 | 9661 |

Full machine-readable dump: [comparison.json](comparison.json).

## How to read the table

- **Simple lookup / named multi-hop:** RAG is allowed to win on latency and gold-source recall. Blind MARE should still be *correct* after discovering schema from navigation nodes.
- **Bridge:** entity-only answers are no longer marked correct. Both `entity_found` and `cause_found` must hold. That is the hop the product claims.
- **Aggregation / negative:** structured query after discovery, not Top-K.

These two levers are what justify MARE over plain Mongo MCP: (1) the agent was not told the schema, and (2) bridge scoring requires the second hop (root cause), not just naming the customer.

## What happened on this run

- **Simple lookup:** Blind MARE yes (8991ms, stop=completed). Informed yes (8543ms). RAG yes (3933ms).
- **Named multi-hop:** Blind MARE yes (18593ms, stop=completed). Informed yes (34272ms). RAG yes (13534ms).
- **Bridge (unnamed entity):** Blind MARE yes (38681ms, stop=completed). Informed yes (30376ms). RAG no (8620ms). entity=yes cause=yes.
- **Aggregation (count):** Blind MARE yes (15764ms, stop=completed). Informed yes (17081ms). RAG no (8168ms).
- **Negative (absence):** Blind MARE yes (13364ms, stop=completed). Informed yes (12325ms). RAG no (9661ms).

## How to rerun

```bash
python scripts/run_comparison.py              # schema-blind MARE vs RAG
python scripts/run_comparison.py --informed   # A/B with schema in the prompt
python scripts/run_comparison.py --only bridge
python scripts/run_comparison.py --turns 10
python scripts/run_comparison.py --rescore    # no LLM; rewrite markdown
```
