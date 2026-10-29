# Bridge — entity not named in the question

- generated: 2026-10-29T13:25:03.861313+00:00
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
| end-to-end latency | **51100 ms** | **8279 ms** |
| agent turns | 9 | n/a |
| tool calls | 8 | n/a |
| LLM latency | 39215 ms | n/a |
| Mongo latency | 7927 ms | n/a |
| retrieval operations | 5 | 1 |
| LLM tokens | 26176 | 1566 |
| stop reason | completed | rag_topk |
| answer correct | yes | no |
| entity found | yes | no |
| root cause found | yes | yes |
| evidence recall vs gold (citations) | 0.5 | 0.125 |
| evidence precision vs gold | 0.19 | 0.125 |
| gold evidence recall (retrieved) | 0.5 | 0.125 |
| documents retrieved | 21 | 8 |
| required evidence | 8 | 8 |
| context efficiency | 0.212 | 0.179 |
| completeness groups | 2/2 | 1/2 |
| gold missed | deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, logs:log_1002, tickets:tkt_1001 | customers:cust_007, deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, incidents:inc_1001, logs:log_1001, logs:log_1002, migrations:mig_auth_sso |

Persistent vector indexes (not per-query scan count): MARE searches the 616-node navigation index, then reads raw Mongo documents. RAG searches the 5424-chunk vector index and returns Top-K.

## MARE answer (blind)

Most likely root cause: After the SSO migration on 2024-05-10, the AUTH_ISSUER was cut over to https://auth-v3.apex.io, but the deployer still pointed to the legacy auth-v2 issuer, causing authentication failures on production deployments (mare_demo.migrations:mig_auth_sso notes: “Clients MUST update AUTH_ISSUER from https://auth-v2.apex.io to https://auth-v3.apex.io”; config_changes.AUTH_ISSUER: https://auth-v3.apex.io; mare_demo.incidents:inc_1001 description: “Multiple production deployments failing authentication after mig_auth_sso. Suspected stale AUTH_ISSUER on deployer.”; root_cause: “stale AUTH_ISSUER still pointing at auth-v2 after SSO issuer cutover”).

Context: The affected customer is Apex Logistics in us-east-1 managed by Elena Rossi (mare_demo.customers:cust_007 region: us-east-1; account_manager: Elena Rossi), with the incident opened on 2024-05-11 (mare_demo.incidents:inc_1001 opened_at: 2024-05-11T10:20:00).

### Hypothesis

_(none)_

### Claims

- `C1` **supported** (0.90): SSO migration completed May 10, 2024 and required AUTH_ISSUER to be updated to https://auth-v3.apex.io.
- `C2` **supported** (0.95): Multiple production deployments failed due to authentication failures because the deployer still used the legacy AUTH_ISSUER (auth-v2).
- `C3` **supported** (0.90): Affected customer is Apex Logistics (cust_007), an enterprise customer managed by Elena Rossi in us-east-1.

### Citations

- `mare_demo.customers:cust_007`
- `mare_demo.incidents:inc_1001`
- `mare_demo.migrations:mig_auth_sso`
- `mare_demo.customers:cust_001`
- `mare_demo.customers:cust_030`
- `mare_demo.deployments:dep_n_0045`
- `mare_demo.deployments:dep_n_0119`
- `mare_demo.deployments:dep_n_0355`
- `mare_demo.deployments:dep_apex_mar`
- `mare_demo.deployments:dep_apex_apr`
- `mare_demo.deployments:dep_n_0374`
- `mare_demo.incidents:inc_20074`
- `mare_demo.incidents:inc_apex_mar`
- `mare_demo.incidents:inc_20026`
- `mare_demo.incidents:inc_apex_apr`
- `mare_demo.logs:log_n_02332`
- `mare_demo.logs:log_n_00383`
- `mare_demo.logs:log_n_03603`
- `mare_demo.logs:log_n_02508`
- `mare_demo.logs:log_n_03650`
- `mare_demo.logs:log_1001`

Gold hits: customers:cust_007, incidents:inc_1001, logs:log_1001, migrations:mig_auth_sso
Missed gold: deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, logs:log_1002, tickets:tkt_1001

## RAG answer

SSO migration misconfiguration causing authentication failures (AUTH_401) that began in May 2024. [tkt_1001]

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

