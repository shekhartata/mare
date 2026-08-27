# Named multi-hop — Apex Logistics SSO failure

- generated: 2026-08-27T06:18:51.245740+00:00
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
| end-to-end latency | **28942 ms** | **9663 ms** |
| agent turns | 5 | n/a |
| tool calls | 4 | n/a |
| LLM latency | 27422 ms | n/a |
| Mongo latency | 891 ms | n/a |
| retrieval operations | 2 | 1 |
| LLM tokens | 33613 | 2050 |
| stop reason | completed | rag_topk |
| answer correct | yes | yes |
| evidence recall vs gold (citations) | 0.25 | 0.625 |
| evidence precision vs gold | 0.111 | 0.625 |
| gold evidence recall (retrieved) | 0.25 | 0.625 |
| documents retrieved | 18 | 8 |
| required evidence | 8 | 8 |
| context efficiency | 0.152 | 0.656 |
| completeness groups | 0/0 | 0/0 |
| gold missed | customers:cust_007, deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, logs:log_1001, logs:log_1002, tickets:tkt_1001 | customers:cust_007, logs:log_1001, logs:log_1002 |

Persistent vector indexes (not per-query scan count): MARE searches the 616-node navigation index, then reads raw Mongo documents. RAG searches the 5424-chunk vector index and returns Top-K.

## MARE answer (blind)

Apex’s deployments began failing right after mig_auth_sso because the SSO issuer changed to https://auth-v3.apex.io and the legacy issuer would reject tokens, but the deployer was still configured with the old AUTH_ISSUER (auth‑v2). Evidence:
- The migration explicitly required updating AUTH_ISSUER to https://auth-v3.apex.io and warned the legacy issuer would reject tokens (mare_demo.migrations:mig_auth_sso).
- Incident inc_1001, opened the day after the migration, reports multiple production deployments failing authentication “post SSO migration” and records the root cause as a stale AUTH_ISSUER still pointing at auth‑v2 on the deployer, with failed deployments dep_apex_fail_1 and dep_apex_fail_2 (mare_demo.incidents:inc_1001).

Note: The specific failed deployment records aren’t included here, but the incident’s description and root cause directly tie the failures to the stale issuer after the migration (mare_demo.incidents:inc_1001; mare_demo.migrations:mig_auth_sso).

### Hypothesis

_(none)_

### Claims

- `c1` **supported** (0.90): Migration mig_auth_sso changed AUTH_ISSUER to https://auth-v3.apex.io and warned legacy issuer would be rejected.
- `c2` **supported** (0.92): Incident inc_1001 attributes deployment authentication failures to a stale AUTH_ISSUER still pointing at auth-v2.

### Citations

- `mare_demo.incidents:inc_1001`
- `mare_demo.migrations:mig_auth_sso`
- `mare_demo.deployments:dep_n_0045`
- `mare_demo.deployments:dep_n_0119`
- `mare_demo.deployments:dep_n_0355`
- `mare_demo.deployments:dep_apex_mar`
- `mare_demo.deployments:dep_apex_apr`
- `mare_demo.deployments:dep_n_0374`
- `mare_demo.incidents:inc_apex_mar`
- `mare_demo.incidents:inc_apex_apr`
- `mare_demo.incidents:inc_20026`
- `mare_demo.incidents:inc_20074`
- `mare_demo.logs:log_n_00262`
- `mare_demo.logs:log_apex_mar_1`
- `mare_demo.logs:log_apex_mar_2`
- `mare_demo.logs:log_n_01030`
- `mare_demo.logs:log_n_03145`
- `mare_demo.logs:log_n_00807`

Gold hits: incidents:inc_1001, migrations:mig_auth_sso
Missed gold: customers:cust_007, deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, logs:log_1001, logs:log_1002, tickets:tkt_1001

## RAG answer

Most likely root cause:
- The SSO migration changed the issuer to https://auth-v3.apex.io, but Apex’s deployment/auth config kept a stale AUTH_ISSUER still pointing to auth-v2, causing token validation to fail. [migrations mig_auth_sso], [incidents inc_1001]

Evidence:
- Migration notes require updating AUTH_ISSUER to https://auth-v3.apex.io; legacy issuer will reject tokens. [migrations mig_auth_sso]
- Incident explicitly calls out “stale AUTH_ISSUER still pointing at auth-v2 after SSO issuer cutover” and links the failing deployments. [incidents inc_1001]
- Failed deployments show AUTH_401 and “unauthorized issuer” during rollout. [deployments dep_apex_fail_1], [deployments dep_apex_fail_2]
- Ticket states the failures started right after the SSO migration. [tickets tkt_1001]

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

