# Aggregation — count enterprise customers

- generated: 2026-08-26T08:40:08.371514+00:00
- answer model: `gpt-5`
- agent model: `gpt-5-mini` (reasoning_effort=low)
- MARE mode: **blind** (schema_in_prompt=false)
- max_agent_turns: 10
- vector index: MARE **618** vs RAG **5424** (ratio 0.1139)

## Why this case

The correct answer is a full-collection count. RAG can only count what fits in Top-K chunks; MARE can run a structured Mongo query after discovering the collection from the navigation index.

## Question

How many customers in mare_demo are currently on the enterprise subscription tier?

## Gold answer

18 customers are on the enterprise subscription tier.

## Latency and retrieval

| metric | MARE (blind) | Conventional RAG |
| --- | --- | --- |
| end-to-end latency | **15764 ms** | **8168 ms** |
| agent turns | 4 | n/a |
| tool calls | 3 | n/a |
| LLM latency | 15021 ms | n/a |
| Mongo latency | 519 ms | n/a |
| retrieval operations | 1 | 1 |
| LLM tokens | 13423 | 1408 |
| stop reason | completed | rag_topk |
| answer correct | yes | no |
| evidence recall vs gold | 1.0 | 0.444 |
| evidence precision vs gold | 1.0 | 1.0 |

Persistent vector indexes (not per-query scan count): MARE searches the 618-node navigation index, then reads raw Mongo documents. RAG searches the 5424-chunk vector index and returns Top-K.

## MARE answer (blind)

18 (mare_demo.customers:cust_002, mare_demo.customers:cust_004, mare_demo.customers:cust_005, mare_demo.customers:cust_007, mare_demo.customers:cust_012, mare_demo.customers:cust_015, mare_demo.customers:cust_017, mare_demo.customers:cust_018, mare_demo.customers:cust_019, mare_demo.customers:cust_021, mare_demo.customers:cust_022, mare_demo.customers:cust_025, mare_demo.customers:cust_031, mare_demo.customers:cust_037, mare_demo.customers:cust_040, mare_demo.customers:cust_041, mare_demo.customers:cust_045, mare_demo.customers:cust_046)

### Hypothesis

_(none)_

### Claims

- `C1` **supported** (0.90): Count of customers with subscription_tier = 'enterprise'

### Citations

- `mare_demo.customers:cust_002`
- `mare_demo.customers:cust_004`
- `mare_demo.customers:cust_005`
- `mare_demo.customers:cust_007`
- `mare_demo.customers:cust_012`
- `mare_demo.customers:cust_015`
- `mare_demo.customers:cust_017`
- `mare_demo.customers:cust_018`
- `mare_demo.customers:cust_019`
- `mare_demo.customers:cust_021`
- `mare_demo.customers:cust_022`
- `mare_demo.customers:cust_025`
- `mare_demo.customers:cust_031`
- `mare_demo.customers:cust_037`
- `mare_demo.customers:cust_040`
- `mare_demo.customers:cust_041`
- `mare_demo.customers:cust_045`
- `mare_demo.customers:cust_046`

Gold hits: customers:cust_002, customers:cust_004, customers:cust_005, customers:cust_007, customers:cust_012, customers:cust_015, customers:cust_017, customers:cust_018, customers:cust_019, customers:cust_021, customers:cust_022, customers:cust_025, customers:cust_031, customers:cust_037, customers:cust_040, customers:cust_041, customers:cust_045, customers:cust_046
Missed gold: none

## RAG answer

8 (sources: cust_018, cust_004, cust_005, cust_041, cust_025, cust_037, cust_045, cust_046)

### Citations

- `mare_demo.customers:cust_018`
- `mare_demo.customers:cust_004`
- `mare_demo.customers:cust_005`
- `mare_demo.customers:cust_041`
- `mare_demo.customers:cust_025`
- `mare_demo.customers:cust_037`
- `mare_demo.customers:cust_045`
- `mare_demo.customers:cust_046`

Gold hits: customers:cust_004, customers:cust_005, customers:cust_018, customers:cust_025, customers:cust_037, customers:cust_041, customers:cust_045, customers:cust_046
Missed gold: customers:cust_002, customers:cust_007, customers:cust_012, customers:cust_015, customers:cust_017, customers:cust_019, customers:cust_021, customers:cust_022, customers:cust_031, customers:cust_040

## MARE answer (informed)

- correct: yes · 17081 ms · turns=4 · stop=completed

18 (mare_demo.customers:cust_002, mare_demo.customers:cust_004, mare_demo.customers:cust_005, mare_demo.customers:cust_007, mare_demo.customers:cust_012, mare_demo.customers:cust_015, mare_demo.customers:cust_017, mare_demo.customers:cust_018, mare_demo.customers:cust_019, mare_demo.customers:cust_021, mare_demo.customers:cust_022, mare_demo.customers:cust_025, mare_demo.customers:cust_031, mare_demo.customers:cust_037, mare_demo.customers:cust_040, mare_demo.customers:cust_041, mare_demo.customers:cust_045, mare_demo.customers:cust_046)

### Citations

- `mare_demo.customers:cust_002`
- `mare_demo.customers:cust_004`
- `mare_demo.customers:cust_005`
- `mare_demo.customers:cust_007`
- `mare_demo.customers:cust_012`
- `mare_demo.customers:cust_015`
- `mare_demo.customers:cust_017`
- `mare_demo.customers:cust_018`
- `mare_demo.customers:cust_019`
- `mare_demo.customers:cust_021`
- `mare_demo.customers:cust_022`
- `mare_demo.customers:cust_025`
- `mare_demo.customers:cust_031`
- `mare_demo.customers:cust_037`
- `mare_demo.customers:cust_040`
- `mare_demo.customers:cust_041`
- `mare_demo.customers:cust_045`
- `mare_demo.customers:cust_046`

