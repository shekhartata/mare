# Negative — prove April incidents do not exist

- generated: 2026-10-29T13:26:06.487813+00:00
- answer model: `gpt-5`
- agent model: `gpt-5-mini` (reasoning_effort=low)
- MARE mode: **blind** (schema_in_prompt=false)
- max_agent_turns: 10
- vector index: MARE **616** vs RAG **5424** (ratio 0.1136)

## Why this case

Top-K always returns something. MARE can filter and return zero documents, which is the only way to ground a negative.

## Question

Did Cedar Systems (cust_004) have any incidents opened in April 2024?

## Gold answer

No. Cedar Systems (cust_004) has no incidents with opened_at in April 2024.

## Latency and retrieval

| metric | MARE (blind) | Conventional RAG |
| --- | --- | --- |
| end-to-end latency | **24323 ms** | **5817 ms** |
| agent turns | 5 | n/a |
| tool calls | 4 | n/a |
| LLM latency | 19067 ms | n/a |
| Mongo latency | 3193 ms | n/a |
| retrieval operations | 2 | 1 |
| LLM tokens | 8863 | 1395 |
| stop reason | completed | rag_topk |
| answer correct | yes | no |
| evidence recall vs gold (citations) | n/a | n/a |
| evidence precision vs gold | 0.0 | 0.0 |
| gold evidence recall (retrieved) | n/a | n/a |
| documents retrieved | 4 | 8 |
| required evidence | None | None |
| context efficiency | 0.0 | 0.0 |
| completeness groups | 0/0 | 0/0 |
| gold missed | none | none |

Persistent vector indexes (not per-query scan count): MARE searches the 616-node navigation index, then reads raw Mongo documents. RAG searches the 5424-chunk vector index and returns Top-K.

## MARE answer (blind)

No. In the provided records for Cedar Systems (customer_id: cust_004), the incidents were opened on 2024-01-29 (inc_20060), 2024-02-19 (inc_20015), and 2024-06-04 (inc_20105); none were opened in April 2024 [mare_demo.customers:cust_004; mare_demo.incidents:inc_20060; mare_demo.incidents:inc_20015; mare_demo.incidents:inc_20105].

### Hypothesis

_(none)_

### Claims

- `c1` **supported** (0.90): No incidents opened in April 2024 for cust_004

### Citations

- `mare_demo.incidents:inc_20060`
- `mare_demo.incidents:inc_20105`
- `mare_demo.incidents:inc_20015`
- `mare_demo.customers:cust_004`

Gold hits: none
Missed gold: none

## RAG answer

No. In the provided records, the April 2024 incidents are for cust_033 (Apr 10) and cust_030 (Apr 17, Apr 28), not for Cedar Systems (cust_004) [inc_20108][inc_20035][inc_20053].

### Citations

- `mare_demo.incidents:inc_20014`
- `mare_demo.incidents:inc_20108`
- `mare_demo.incidents:inc_20051`
- `mare_demo.incidents:inc_20053`
- `mare_demo.incidents:inc_20114`
- `mare_demo.incidents:inc_20035`
- `mare_demo.incidents:inc_20031`
- `mare_demo.incidents:inc_20066`

Gold hits: none
Missed gold: none

## MARE answer (informed)

- correct: yes · 12325 ms · turns=4 · stop=completed

No. In the provided records for Cedar Systems (cust_004), incidents were opened on 2024-01-29 (mare_demo.incidents:inc_20051), 2024-02-19 (mare_demo.incidents:inc_20006), and 2024-06-04 (mare_demo.incidents:inc_20096); none were opened in April 2024. This conclusion is limited to the evidence shown.

### Citations

- `mare_demo.incidents:inc_20006`
- `mare_demo.incidents:inc_20051`
- `mare_demo.incidents:inc_20096`

