# Negative — prove April incidents do not exist

- generated: 2026-11-10T07:30:14.815315+00:00
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
| end-to-end latency | **8883 ms** | **6812 ms** |
| agent turns | 3 | n/a |
| tool calls | 3 | n/a |
| LLM latency | 7781 ms | n/a |
| Mongo latency | 675 ms | n/a |
| retrieval operations | 1 | 1 |
| LLM tokens | 5235 | 1645 |
| stop reason | completed | rag_topk |
| answer correct | yes | no |
| evidence recall vs gold (citations) | n/a | n/a |
| evidence precision vs gold | 0.0 | 0.0 |
| gold evidence recall (retrieved) | n/a | n/a |
| documents retrieved | 3 | 8 |
| required evidence | None | None |
| context efficiency | 0.0 | 0.0 |
| completeness groups | 0/0 | 0/0 |
| gold missed | none | none |

Persistent vector indexes (not per-query scan count): MARE searches the 616-node navigation index, then reads raw Mongo documents. RAG searches the 5424-chunk vector index and returns Top-K.

## MARE answer (blind)

Cedar Systems (cust_004) did not have any incidents opened in April 2024. The incidents for this customer in the dataset were opened on 2024-01-29 (inc_20060), 2024-02-19 (inc_20015), and 2024-06-04 (inc_20105).

### Hypothesis

_(none)_

### Claims

_(none)_

### Citations

- `mare_demo.incidents:inc_20015`
- `mare_demo.incidents:inc_20060`
- `mare_demo.incidents:inc_20105`

Gold hits: none
Missed gold: none

## RAG answer

No. In the provided data, the April 2024 incidents are for other customers (cust_033 and cust_030): [inc_20108], [inc_20035], [inc_20053]; none are for cust_004 (Cedar Systems).

### Citations

- `mare_demo.incidents:inc_20014`
- `mare_demo.incidents:inc_20108`
- `mare_demo.incidents:inc_20051`
- `mare_demo.incidents:inc_20114`
- `mare_demo.incidents:inc_20053`
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

