# Variable K — small (Apex most recent auth incident)

- generated: 2026-11-10T07:31:59.068543+00:00
- answer model: `gpt-5`
- agent model: `gpt-5-mini` (reasoning_effort=low)
- MARE mode: **blind** (schema_in_prompt=false)
- max_agent_turns: 10
- vector index: MARE **616** vs RAG **5424** (ratio 0.1136)

## Why this case

Same Apex authentication subject as the larger K cases, but only two gold records are required. RAG with a small Top-K should be competitive.

## Question

What caused Apex's most recent authentication incident?

## Gold answer

The most recent Apex (cust_007) authentication incident (inc_1001) is the May production auth failure after the SSO cutover; logs show jwt issuer mismatch (log_1001).

## Latency and retrieval

| metric | MARE (blind) | Conventional RAG |
| --- | --- | --- |
| end-to-end latency | **21004 ms** | **5960 ms** |
| agent turns | 5 | n/a |
| tool calls | 5 | n/a |
| LLM latency | 18332 ms | n/a |
| Mongo latency | 2004 ms | n/a |
| retrieval operations | 1 | 1 |
| LLM tokens | 11334 | 2034 |
| stop reason | completed | rag_topk |
| answer correct | yes | no |
| entity found | yes | no |
| root cause found | yes | yes |
| evidence recall vs gold (citations) | 0.5 | 1.0 |
| evidence precision vs gold | 0.2 | 0.2 |
| gold evidence recall (retrieved) | 0.5 | 1.0 |
| documents retrieved | 5 | 10 |
| required evidence | 2 | 2 |
| context efficiency | 0.232 | 0.186 |
| completeness groups | 2/2 | 1/2 |
| gold missed | logs:log_1001 | none |

Persistent vector indexes (not per-query scan count): MARE searches the 616-node navigation index, then reads raw Mongo documents. RAG searches the 5424-chunk vector index and returns Top-K.

## RAG Top-K sweep

| variant | correct | gold recall | docs retrieved | completeness | ms |
| --- | --- | --- | --- | --- | --- |
| hybrid_10 | no | 1.0 | 10 | 1/2 | 5960 |
| hybrid_20 | yes | 1.0 | 20 | 2/2 | 5711 |
| hybrid_5 | yes | 1.0 | 5 | 2/2 | 5065 |
| vector_10 | no | 1.0 | 10 | 1/2 | 6507 |

### RAG answers by variant

**hybrid_10**

A stale AUTH_ISSUER still pointing to auth‑v2 after the SSO issuer cutover, causing JWT issuer mismatches and 401s [inc_1001, log_1001].

**hybrid_20**

A stale AUTH_ISSUER configuration still pointed to https://auth-v2.apex.io after the SSO issuer cutover (expected https://auth-v3.apex.io), causing issuer mismatches and 401s during deployments. [inc_1001; log_1001; log_1002]

**hybrid_5**

A stale AUTH_ISSUER config still pointed to the old auth-v2 issuer after the SSO cutover to auth-v3, causing issuer mismatches and auth failures. [inc_1001] [log_1001] [dep_apex_fail_1]

**vector_10**

A stale AUTH_ISSUER configuration still pointed to auth-v2 after the SSO issuer cutover (to auth-v3), causing JWT issuer mismatches and AUTH_401 errors. [inc_1001; log_1001; log_1002]

## MARE answer (blind)

Apex Logistics (cust_007) — The most recent authentication incident (inc_1001) was caused by a stale AUTH_ISSUER configuration on the deployer that was still pointing at auth-v2 after the SSO issuer cutover.

### Hypothesis

_(none)_

### Claims

- `c1` **supported** (0.90): Root cause was stale AUTH_ISSUER still pointing at auth-v2 after SSO issuer cutover.

### Citations

- `mare_demo.incidents:inc_1001`
- `mare_demo.incidents:inc_apex_mar`
- `mare_demo.incidents:inc_apex_apr`
- `mare_demo.incidents:inc_20026`
- `mare_demo.incidents:inc_20074`

Gold hits: incidents:inc_1001
Missed gold: logs:log_1001

## RAG answer

A stale AUTH_ISSUER still pointing to auth‑v2 after the SSO issuer cutover, causing JWT issuer mismatches and 401s [inc_1001, log_1001].

### Citations

- `mare_demo.incidents:inc_1001`
- `mare_demo.incidents:inc_apex_apr`
- `mare_demo.deployments:dep_apex_fail_1`
- `mare_demo.tickets:tkt_apex_apr`
- `mare_demo.tickets:tkt_apex_mar`
- `mare_demo.logs:log_1001`
- `mare_demo.tickets:tkt_1001`
- `mare_demo.deployments:dep_apex_fail_2`
- `mare_demo.incidents:inc_apex_mar`
- `mare_demo.logs:log_1002`

Gold hits: incidents:inc_1001, logs:log_1001
Missed gold: none

