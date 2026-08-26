# Named multi-hop — Apex Logistics SSO failure

- generated: 2026-08-26T08:40:08.371024+00:00
- answer model: `gpt-5`
- agent model: `gpt-5-mini` (reasoning_effort=low)
- MARE mode: **blind** (schema_in_prompt=false)
- max_agent_turns: 10
- vector index: MARE **618** vs RAG **5424** (ratio 0.1139)

## Why this case

The question names cust_007 and mig_auth_sso, so Top-K can scoop the whole story in one shot. This is RAG's home turf.

## Question

Why did customer Apex Logistics (cust_007) begin experiencing deployment failures after migration mig_auth_sso, and what evidence supports the most likely root cause?

## Gold answer

Apex Logistics (cust_007) began failing production deployments after migration mig_auth_sso (2024-05-10) changed the SSO issuer from https://auth-v2.apex.io to https://auth-v3.apex.io. Deployments dep_apex_fail_1 and dep_apex_fail_2 failed with AUTH_401. Logs show jwt issuer mismatch: expected auth-v3, got auth-v2. Ticket tkt_1001 and incident inc_1001 corroborate authentication failures after the migration.

## Latency and retrieval

| metric | MARE (blind) | Conventional RAG |
| --- | --- | --- |
| end-to-end latency | **18593 ms** | **13534 ms** |
| agent turns | 4 | n/a |
| tool calls | 3 | n/a |
| LLM latency | 17892 ms | n/a |
| Mongo latency | 483 ms | n/a |
| retrieval operations | 1 | 1 |
| LLM tokens | 22528 | 2024 |
| stop reason | completed | rag_topk |
| answer correct | yes | yes |
| evidence recall vs gold | 0.375 | 0.875 |
| evidence precision vs gold | 0.15 | 0.875 |

Persistent vector indexes (not per-query scan count): MARE searches the 618-node navigation index, then reads raw Mongo documents. RAG searches the 5424-chunk vector index and returns Top-K.

## MARE answer (blind)

Most likely root cause
- After mig_auth_sso, the SSO issuer changed to https://auth-v3.apex.io, but Apex Logistics continued using the old issuer https://auth-v2.apex.io, causing JWT validation to fail with AUTH_401 during deployment of auth-service.

Evidence
- Migration required clients to update AUTH_ISSUER to https://auth-v3.apex.io and warned the legacy issuer would reject tokens (mare_demo.migrations:mig_auth_sso).
- The first post-migration prod deployment failed with AUTH_401 and “token validation failed: unauthorized issuer,” and it’s linked to mig_auth_sso (mare_demo.deployments:dep_apex_fail_1).
- Auth-service error log from that failed deployment shows “jwt issuer mismatch: expected https://auth-v3.apex.io, got https://auth-v2.apex.io” (mare_demo.logs:log_1001).

### Hypothesis

_(none)_

### Claims

_(none)_

### Citations

- `mare_demo.migrations:mig_auth_sso`
- `mare_demo.deployments:dep_apex_fail_1`
- `mare_demo.logs:log_1001`
- `mare_demo.migrations:mig_n_004`
- `mare_demo.migrations:mig_n_005`
- `mare_demo.deployments:dep_n_0040`
- `mare_demo.deployments:dep_n_0114`
- `mare_demo.deployments:dep_n_0350`
- `mare_demo.deployments:dep_n_0369`
- `mare_demo.deployments:dep_n_0025`
- `mare_demo.logs:log_n_02324`
- `mare_demo.logs:log_n_00375`
- `mare_demo.logs:log_n_03595`
- `mare_demo.logs:log_n_02500`
- `mare_demo.logs:log_n_03642`
- `mare_demo.logs:log_n_01963`
- `mare_demo.logs:log_n_01052`
- `mare_demo.logs:log_n_03087`
- `mare_demo.logs:log_n_00790`
- `mare_demo.logs:log_n_03922`

Gold hits: deployments:dep_apex_fail_1, logs:log_1001, migrations:mig_auth_sso
Missed gold: customers:cust_007, deployments:dep_apex_fail_2, incidents:inc_1001, logs:log_1002, tickets:tkt_1001

## RAG answer

Most likely root cause
- A stale AUTH_ISSUER configuration still pointing to https://auth-v2.apex.io after the SSO cutover to https://auth-v3.apex.io, causing JWT issuer mismatches and 401s, particularly on the deployer. [incidents inc_1001], [migrations mig_auth_sso], [logs log_1002]

Evidence
- Migration required updating AUTH_ISSUER to https://auth-v3.apex.io; legacy issuer would reject tokens. [migrations mig_auth_sso]
- Failures started immediately after the SSO migration with AUTH_401 errors. [tickets tkt_1001], [deployments dep_apex_fail_1], [deployments dep_apex_fail_2]
- Auth-service log shows issuer mismatch: expected v3, got v2. [logs log_1001]
- Deployer log shows token validation attempted against AUTH_ISSUER https://auth-v2.apex.io, indicating stale config on the deployer. [logs log_1002]
- Incident record identifies root cause as stale AUTH_ISSUER still pointing at auth-v2 after the issuer cutover. [incidents inc_1001]

### Citations

- `mare_demo.incidents:inc_1001`
- `mare_demo.tickets:tkt_1001`
- `mare_demo.deployments:dep_apex_fail_2`
- `mare_demo.deployments:dep_apex_fail_1`
- `mare_demo.migrations:mig_auth_sso`
- `mare_demo.deployments:dep_quilt_1`
- `mare_demo.logs:log_1002`
- `mare_demo.logs:log_1001`

Gold hits: deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, incidents:inc_1001, logs:log_1001, logs:log_1002, migrations:mig_auth_sso, tickets:tkt_1001
Missed gold: customers:cust_007

## MARE answer (informed)

- correct: yes · 34272 ms · turns=6 · stop=completed

Most likely root cause
After mig_auth_sso, the SSO issuer changed to https://auth-v3.apex.io, but Apex Logistics continued using the old issuer (https://auth-v2.apex.io) in clients/service accounts, causing JWT issuer mismatches and 401s during deployments (mare_demo.migrations:mig_auth_sso).

Evidence
- Migration notes required updating AUTH_ISSUER from https://auth-v2.apex.io to https://auth-v3.apex.io; legacy issuer would reject tokens (mare_demo.migrations:mig_auth_sso).
- Immediately after migration, prod deployments failed with AUTH_401 errors tied to mig_auth_sso:
  - dep_apex_fail_1: “token validation failed: unauthorized issuer” in auth-service (mare_demo.deployments:dep_apex_fail_1).
  - dep_apex_fail_2: “auth-service returned 401 during rollout” for billing-worker (mare_demo.deployments:dep_apex_fail_2).
- Logs show explicit issuer mismatch and continued use of v2:
  - “jwt issuer mismatch: expected https://auth-v3.apex.io, got https://auth-v2.apex.io” during dep_apex_fail_1 (mare_demo.logs:log_1001).
  - “token validation failed for deployer service account against AUTH_ISSUER https://auth-v2.apex.io” during dep_apex_fail_2 (mare_demo.logs:log_1002).

Conclusion
Deployment failures began because not all components updated AUTH_ISSUER to the new v3 issuer after mig_auth_sso, leading to token validation failures (AUTH_401) during rollout (mare_demo.migrations:mig_auth_sso; mare_demo.deployments:dep_apex_fail_1; mare_demo.deployments:dep_apex_fail_2; mare_demo.logs:log_1001; mare_demo.logs:log_1002).

### Citations

- `mare_demo.migrations:mig_auth_sso`
- `mare_demo.deployments:dep_apex_fail_1`
- `mare_demo.deployments:dep_apex_fail_2`
- `mare_demo.logs:log_1001`
- `mare_demo.logs:log_1002`

