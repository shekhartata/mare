# Bridge — entity not named in the question

- generated: 2026-11-10T07:29:39.214336+00:00
- answer model: `gpt-5`
- agent model: `gpt-5-mini` (reasoning_effort=low)
- MARE mode: **blind** (schema_in_prompt=false)
- max_agent_turns: 10
- vector index: MARE **616** vs RAG **5424** (ratio 0.1136)

## Why this case

The question never says Apex, cust_007, AUTH_401, or SSO. Correct requires both identifying the customer and the SSO issuer root cause. MARE must hop via navigation (related_nodes), not a single filter.

## Question

An enterprise customer in us-east-1 whose account manager is Elena Rossi started failing production deployments in May 2024. What is the most likely root cause?

## Gold answer

The customer is Apex Logistics (cust_007). After migration mig_auth_sso (2024-05-10) changed AUTH_ISSUER from https://auth-v2.apex.io to https://auth-v3.apex.io, production deployments dep_apex_fail_1 and dep_apex_fail_2 failed with AUTH_401 (unauthorized / jwt issuer mismatch).

## Latency and retrieval

| metric | MARE (blind) | Conventional RAG |
| --- | --- | --- |
| end-to-end latency | **41849 ms** | **6122 ms** |
| agent turns | 12 | n/a |
| tool calls | 11 | n/a |
| LLM latency | 35746 ms | n/a |
| Mongo latency | 4668 ms | n/a |
| retrieval operations | 7 | 1 |
| LLM tokens | 32682 | 1576 |
| stop reason | max_agent_turns | rag_topk |
| answer correct | no | no |
| entity found | yes | no |
| root cause found | no | yes |
| evidence recall vs gold (citations) | 0.125 | 0.125 |
| evidence precision vs gold | 0.111 | 0.125 |
| gold evidence recall (retrieved) | 0.125 | 0.125 |
| documents retrieved | 9 | 8 |
| required evidence | 8 | 8 |
| context efficiency | 0.105 | 0.179 |
| completeness groups | 1/2 | 1/2 |
| gold missed | deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, incidents:inc_1001, logs:log_1001, logs:log_1002, migrations:mig_auth_sso, tickets:tkt_1001 | customers:cust_007, deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, incidents:inc_1001, logs:log_1001, logs:log_1002, migrations:mig_auth_sso |

Persistent vector indexes (not per-query scan count): MARE searches the 616-node navigation index, then reads raw Mongo documents. RAG searches the 5424-chunk vector index and returns Top-K.

## MARE answer (blind)

Most likely root cause: The April 15, 2024 production rollout for Apex Logistics (enterprise, us-east-1, account_manager: Elena Rossi) reduced auth-service ACCESS_TOKEN_TTL_SEC from 14400 to 1800 seconds, making access tokens expire much sooner and likely causing authentication timeouts during production deployments starting in May 2024 [mare_demo.customers:cust_007; mare_demo.deployments:dep_apex_apr].

### Hypothesis

_(none)_

### Claims

_(none)_

### Citations

- `mare_demo.customers:cust_007`
- `mare_demo.deployments:dep_n_0045`
- `mare_demo.deployments:dep_n_0119`
- `mare_demo.deployments:dep_n_0355`
- `mare_demo.customers:cust_001`
- `mare_demo.customers:cust_030`
- `mare_demo.deployments:dep_apex_mar`
- `mare_demo.deployments:dep_apex_apr`
- `mare_demo.deployments:dep_n_0374`

Gold hits: customers:cust_007
Missed gold: deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, incidents:inc_1001, logs:log_1001, logs:log_1002, migrations:mig_auth_sso, tickets:tkt_1001

## RAG answer

SSO migration–related authentication misconfiguration causing AUTH_401 during deploys. The failures began right after the SSO migration per the customer’s ticket. [tkt_1001]

### Citations

- `mare_demo.tickets:tkt_1001`
- `mare_demo.deployments:dep_n_0274`
- `mare_demo.deployments:dep_n_0081`
- `mare_demo.deployments:dep_n_0162`
- `mare_demo.deployments:dep_n_0283`
- `mare_demo.deployments:dep_n_0109`
- `mare_demo.deployments:dep_rw_1`
- `mare_demo.deployments:dep_n_0170`

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

