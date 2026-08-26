# Simple lookup — subscription tier

- generated: 2026-08-26T08:40:08.369443+00:00
- answer model: `gpt-5`
- agent model: `gpt-5-mini` (reasoning_effort=low)
- MARE mode: **blind** (schema_in_prompt=false)
- max_agent_turns: 10
- vector index: MARE **618** vs RAG **5424** (ratio 0.1139)

## Why this case

ID is in the question. RAG is the fast path; MARE should match accuracy with higher citation precision. Blind mode must discover the customer collection via the navigation index.

## Question

What is customer cust_007's current subscription tier?

## Gold answer

Apex Logistics (cust_007) began failing production deployments after migration mig_auth_sso (2024-05-10) changed the SSO issuer from https://auth-v2 (see customer record for tier).

## Latency and retrieval

| metric | MARE (blind) | Conventional RAG |
| --- | --- | --- |
| end-to-end latency | **8991 ms** | **3933 ms** |
| agent turns | 4 | n/a |
| tool calls | 3 | n/a |
| LLM latency | 8421 ms | n/a |
| Mongo latency | 346 ms | n/a |
| retrieval operations | 1 | 1 |
| LLM tokens | 11735 | 1033 |
| stop reason | completed | rag_topk |
| answer correct | yes | yes |
| evidence recall vs gold | 1.0 | 1.0 |
| evidence precision vs gold | 1.0 | 0.125 |

Persistent vector indexes (not per-query scan count): MARE searches the 618-node navigation index, then reads raw Mongo documents. RAG searches the 5424-chunk vector index and returns Top-K.

## MARE answer (blind)

enterprise (mare_demo.customers:cust_007)

### Hypothesis

_(none)_

### Claims

- `C1` **supported** (0.86): cust_007 subscription_tier is enterprise

### Citations

- `mare_demo.customers:cust_007`

Gold hits: customers:cust_007
Missed gold: none

## RAG answer

Enterprise [customers cust_007]

### Citations

- `mare_demo.customers:cust_007`
- `mare_demo.customers:cust_017`
- `mare_demo.customers:cust_037`
- `mare_demo.customers:cust_003`
- `mare_demo.customers:cust_047`
- `mare_demo.customers:cust_008`
- `mare_demo.customers:cust_027`
- `mare_demo.customers:cust_046`

Gold hits: customers:cust_007
Missed gold: none

## MARE answer (informed)

- correct: yes · 8543 ms · turns=4 · stop=completed

cust_007 is on the enterprise subscription tier (mare_demo.customers:cust_007).

### Citations

- `mare_demo.customers:cust_007`

