# Named multi-hop — Apex Logistics SSO failure

- generated: 2026-10-29T13:24:03.917178+00:00
- answer model: `gpt-5`
- agent model: `gpt-5-mini` (reasoning_effort=low)
- MARE mode: **blind** (schema_in_prompt=false)
- max_agent_turns: 10
- vector index: MARE **616** vs RAG **5424** (ratio 0.1136)

## Why this case

The question names cust_007 and mig_auth_sso, so Top-K can scoop the whole story in one shot. This is RAG's home turf.

## Question

Why did customer Apex Logistics (cust_007) begin experiencing deployment failures after migration mig_auth_sso, and what evidence supports the most likely root cause?

## Gold answer

Apex Logistics (cust_007) began failing production deployments after migration mig_auth_sso (2024-05-10) changed the SSO issuer from https://auth-v2.apex.io to https://auth-v3.apex.io. Deployments dep_apex_fail_1 and dep_apex_fail_2 failed with AUTH_401. Logs show jwt issuer mismatch: expected auth-v3, got auth-v2. Ticket tkt_1001 and incident inc_1001 corroborate authentication failures after the migration.

## Latency and retrieval

| metric | MARE (blind) | Conventional RAG |
| --- | --- | --- |
| end-to-end latency | **62810 ms** | **10576 ms** |
| agent turns | 9 | n/a |
| tool calls | 8 | n/a |
| LLM latency | 49711 ms | n/a |
| Mongo latency | 7845 ms | n/a |
| retrieval operations | 4 | 1 |
| LLM tokens | 24922 | 1897 |
| stop reason | completed | rag_topk |
| answer correct | yes | yes |
| evidence recall vs gold (citations) | 0.5 | 0.625 |
| evidence precision vs gold | 0.211 | 0.625 |
| gold evidence recall (retrieved) | 0.5 | 0.625 |
| documents retrieved | 19 | 8 |
| required evidence | 8 | 8 |
| context efficiency | 0.236 | 0.656 |
| completeness groups | 0/0 | 0/0 |
| gold missed | deployments:dep_apex_fail_2, logs:log_1001, logs:log_1002, tickets:tkt_1001 | customers:cust_007, logs:log_1001, logs:log_1002 |

Persistent vector indexes (not per-query scan count): MARE searches the 616-node navigation index, then reads raw Mongo documents. RAG searches the 5424-chunk vector index and returns Top-K.

## MARE answer (blind)

Most likely root cause
Apex Logistics’ deployments began failing because the SSO migration changed the required AUTH_ISSUER to https://auth-v3.apex.io and the legacy issuer would reject tokens, but the customer remained configured on the v2 issuer, creating an issuer mismatch that led to 401 “unauthorized issuer” errors during auth-service deployments.

Supporting evidence
- The migration explicitly changed AUTH_ISSUER and warned that the legacy issuer would reject tokens: notes: “SSO endpoint changed. Clients MUST update AUTH_ISSUER from https://auth-v2.apex.io to https://auth-v3.apex.io. Legacy issuer will reject tokens.” and config_changes.AUTH_ISSUER: https://auth-v3.apex.io (mare_demo.migrations:mig_auth_sso).
- Apex Logistics is still configured with sso_issuer: https://auth-v2.apex.io (mare_demo.customers:cust_007).
- A post-migration production deployment failed in auth-service with error_code: AUTH_401 and logs_excerpt: “token validation failed: unauthorized issuer”; it’s tied to migration_id: mig_auth_sso and occurred after the migration completed (started_at: 2024-05-11T09:15:00 vs. migration completed_at: 2024-05-10T11:30:00) (mare_demo.deployments:dep_apex_fail_1; mare_demo.migrations:mig_auth_sso).
- The active incident documents the same root cause: root_cause: “stale AUTH_ISSUER still pointing at auth-v2 after SSO issuer cutover,” with title “Auth failures post SSO migration” (mare_demo.incidents:inc_1001).

Assessment of the draft claims
- C1 supported: Migration changed AUTH_ISSUER to https://auth-v3.apex.io and noted legacy issuer will reject tokens (mare_demo.migrations:mig_auth_sso).
- C2 supported: Apex Logistics is still on https://auth-v2.apex.io (mare_demo.customers:cust_007).
- C3 supported: Deployment failures show AUTH_401 “unauthorized issuer,” and the incident records the issuer mismatch as root cause (mare_demo.deployments:dep_apex_fail_1; mare_demo.incidents:inc_1001).

### Hypothesis

_(none)_

### Claims

- `C1` **supported** (0.90): Migration mig_auth_sso changed AUTH_ISSUER to https://auth-v3.apex.io and noted legacy issuer will reject tokens.
- `C2` **supported** (0.90): Apex Logistics (cust_007) is still configured to use sso_issuer https://auth-v2.apex.io.
- `C3` **partially_supported** (0.85): The mismatch caused token rejection and deployment/auth failures after migration.

### Citations

- `mare_demo.customers:cust_007`
- `mare_demo.migrations:mig_auth_sso`
- `mare_demo.migrations:mig_catalog_v4`
- `mare_demo.migrations:mig_n_003`
- `mare_demo.migrations:mig_n_005`
- `mare_demo.migrations:mig_n_012`
- `mare_demo.migrations:mig_n_016`
- `mare_demo.deployments:dep_apex_fail_1`
- `mare_demo.deployments:dep_ns_bill_1`
- `mare_demo.deployments:dep_ns_stale`
- `mare_demo.deployments:dep_cascade_pool`
- `mare_demo.deployments:dep_n_0001`
- `mare_demo.deployments:dep_n_0003`
- `mare_demo.incidents:inc_1001`
- `mare_demo.incidents:inc_4001`
- `mare_demo.incidents:inc_20008`
- `mare_demo.incidents:inc_20012`
- `mare_demo.incidents:inc_20016`
- `mare_demo.incidents:inc_20020`

Gold hits: customers:cust_007, deployments:dep_apex_fail_1, incidents:inc_1001, migrations:mig_auth_sso
Missed gold: deployments:dep_apex_fail_2, logs:log_1001, logs:log_1002, tickets:tkt_1001

## RAG answer

Most likely root cause
Apex’s deployer kept a stale AUTH_ISSUER pointing to auth-v2 after the SSO cutover to auth-v3, causing token validation to fail during deployments.

Evidence
- Migration required changing AUTH_ISSUER to https://auth-v3.apex.io; legacy issuer would reject tokens (mig_auth_sso).
- Incident identifies root cause as “stale AUTH_ISSUER still pointing at auth-v2 after SSO issuer cutover” (inc_1001).
- Failed deployment log shows “token validation failed: unauthorized issuer” on the auth-service (dep_apex_fail_1).
- Subsequent prod deployment returned AUTH_401 during rollout (dep_apex_fail_2).
- Ticket reports deploy failures with AUTH_401 starting right after the SSO migration (tkt_1001).

### Citations

- `mare_demo.incidents:inc_1001`
- `mare_demo.tickets:tkt_1001`
- `mare_demo.deployments:dep_apex_fail_2`
- `mare_demo.deployments:dep_apex_fail_1`
- `mare_demo.migrations:mig_auth_sso`
- `mare_demo.deployments:dep_ns_stale`
- `mare_demo.deployments:dep_apex_apr`
- `mare_demo.deployments:dep_apex_mar`

Gold hits: deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, incidents:inc_1001, migrations:mig_auth_sso, tickets:tkt_1001
Missed gold: customers:cust_007, logs:log_1001, logs:log_1002

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

