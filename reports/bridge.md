# Bridge — entity not named in the question

- generated: 2026-08-26T08:40:08.371284+00:00
- answer model: `gpt-5`
- agent model: `gpt-5-mini` (reasoning_effort=low)
- MARE mode: **blind** (schema_in_prompt=false)
- max_agent_turns: 10
- vector index: MARE **618** vs RAG **5424** (ratio 0.1139)

## Why this case

The question never says Apex, cust_007, AUTH_401, or SSO. Correct requires both identifying the customer and the SSO issuer root cause. MARE must hop via navigation (related_nodes), not a single filter.

## Question

An enterprise customer in us-east-1 whose account manager is Elena Rossi started failing production deployments in May 2024. What is the most likely root cause?

## Gold answer

The customer is Apex Logistics (cust_007). After migration mig_auth_sso (2024-05-10) changed AUTH_ISSUER from https://auth-v2.apex.io to https://auth-v3.apex.io, production deployments dep_apex_fail_1 and dep_apex_fail_2 failed with AUTH_401 (unauthorized / jwt issuer mismatch).

## Latency and retrieval

| metric | MARE (blind) | Conventional RAG |
| --- | --- | --- |
| end-to-end latency | **38681 ms** | **8620 ms** |
| agent turns | 9 | n/a |
| tool calls | 8 | n/a |
| LLM latency | 35832 ms | n/a |
| Mongo latency | 2340 ms | n/a |
| retrieval operations | 4 | 1 |
| LLM tokens | 104975 | 1560 |
| stop reason | completed | rag_topk |
| answer correct | yes | no |
| entity found | yes | no |
| root cause found | yes | yes |
| evidence recall vs gold | 0.5 | 0.125 |
| evidence precision vs gold | 0.5 | 0.125 |

Persistent vector indexes (not per-query scan count): MARE searches the 618-node navigation index, then reads raw Mongo documents. RAG searches the 5424-chunk vector index and returns Top-K.

## MARE answer (blind)

Most likely root cause: Following the 2024-05-10 SSO platform migration that changed the required AUTH_ISSUER from https://auth-v2.apex.io to https://auth-v3.apex.io, Apex Logistics (enterprise, us-east-1, AM Elena Rossi) did not update their client config and continued using the old issuer, leading to token validation failures (“unauthorized issuer”) and AUTH_401 errors in production deployments starting May 11–12, 2024 (mare_demo.customers:cust_007; mare_demo.migrations:mig_auth_sso; mare_demo.deployments:dep_apex_fail_1; mare_demo.deployments:dep_apex_fail_2).

### Hypothesis

_(none)_

### Claims

- `c1` **supported** (0.95): Platform migration changed AUTH_ISSUER and required client config update
- `c2` **supported** (0.93): Deployments failed with AUTH_401 because tokens were rejected after migration
- `c3` **supported** (0.90): Affected customer is cust_007 (Apex Logistics) managed by Elena Rossi in us-east-1

### Citations

- `mare_demo.customers:cust_007`
- `mare_demo.deployments:dep_apex_fail_1`
- `mare_demo.deployments:dep_apex_fail_2`
- `mare_demo.migrations:mig_auth_sso`
- `mare_demo.customers:cust_001`
- `mare_demo.customers:cust_030`
- `mare_demo.migrations:mig_n_004`
- `mare_demo.migrations:mig_n_005`

Gold hits: customers:cust_007, deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, migrations:mig_auth_sso
Missed gold: incidents:inc_1001, logs:log_1001, logs:log_1002, tickets:tkt_1001

## RAG answer

SSO migration causing authentication failures (AUTH_401) during deploys. [tkt_1001]

### Citations

- `mare_demo.tickets:tkt_1001`
- `mare_demo.deployments:dep_n_0157`
- `mare_demo.deployments:dep_n_0076`
- `mare_demo.deployments:dep_n_0109`
- `mare_demo.deployments:dep_n_0154`
- `mare_demo.deployments:dep_rw_1`
- `mare_demo.deployments:dep_n_0314`
- `mare_demo.deployments:dep_n_0130`

Gold hits: tickets:tkt_1001
Missed gold: customers:cust_007, deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, incidents:inc_1001, logs:log_1001, logs:log_1002, migrations:mig_auth_sso

## MARE answer (informed)

- correct: yes · 30376 ms · turns=8 · stop=completed

Most likely root cause: the SSO issuer change in migration mig_auth_sso on 2024-05-10 updated AUTH_ISSUER to https://auth-v3.apex.io, but the customer remained configured with the legacy issuer https://auth-v2.apex.io, causing token validation to fail with AUTH_401 “unauthorized issuer” during subsequent prod rollouts on May 11–12, 2024 (mare_demo.migrations:mig_auth_sso; mare_demo.deployments:dep_apex_fail_1; mare_demo.deployments:dep_apex_fail_2; mare_demo.customers:cust_007).

### Citations

- `mare_demo.customers:cust_007`
- `mare_demo.deployments:dep_apex_fail_1`
- `mare_demo.deployments:dep_apex_fail_2`
- `mare_demo.migrations:mig_auth_sso`
- `mare_demo.deployments:dep_n_0040`
- `mare_demo.deployments:dep_n_0114`
- `mare_demo.deployments:dep_n_0350`
- `mare_demo.deployments:dep_n_0369`
- `mare_demo.deployments:dep_n_0025`
- `mare_demo.deployments:dep_n_0355`
- `mare_demo.deployments:dep_n_0295`
- `mare_demo.migrations:mig_n_004`
- `mare_demo.migrations:mig_n_005`

entity=yes cause=yes

