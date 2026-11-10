# Named multi-hop — Apex Logistics SSO failure

- generated: 2026-11-10T07:28:51.101008+00:00
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
| end-to-end latency | **31432 ms** | **13048 ms** |
| agent turns | 9 | n/a |
| tool calls | 9 | n/a |
| LLM latency | 27068 ms | n/a |
| Mongo latency | 3218 ms | n/a |
| retrieval operations | 5 | 1 |
| LLM tokens | 28112 | 1990 |
| stop reason | completed | rag_topk |
| answer correct | yes | yes |
| evidence recall vs gold (citations) | 0.625 | 0.625 |
| evidence precision vs gold | 0.192 | 0.625 |
| gold evidence recall (retrieved) | 0.625 | 0.625 |
| documents retrieved | 26 | 8 |
| required evidence | 8 | 8 |
| context efficiency | 0.206 | 0.656 |
| completeness groups | 0/0 | 0/0 |
| gold missed | customers:cust_007, logs:log_1002, tickets:tkt_1001 | customers:cust_007, logs:log_1001, logs:log_1002 |

Persistent vector indexes (not per-query scan count): MARE searches the 616-node navigation index, then reads raw Mongo documents. RAG searches the 5424-chunk vector index and returns Top-K.

## MARE answer (blind)

Customer: Apex Logistics (cust_007)

Why failures began after migration
- Most likely root cause: The mig_auth_sso migration updated the cluster’s AUTH_ISSUER to https://auth-v3.apex.io, but Apex Logistics’ services (or their tokens) were still using the legacy issuer (https://auth-v2.apex.io). As a result, token validation began failing and deployments that exercise authentication started returning 401s, causing rollout failures.

Evidence supporting this conclusion
1) Migration record shows an SSO issuer change and explicit note that the legacy issuer will reject tokens and clients MUST update AUTH_ISSUER:
   - mare_demo.migrations:mig_auth_sso — notes: “SSO endpoint changed. Clients MUST update AUTH_ISSUER from https://auth-v2.apex.io to https://auth-v3.apex.io. Legacy issuer will reject tokens.” and config_changes.AUTH_ISSUER: https://auth-v3.apex.io
2) Deployments immediately after the migration failed with authentication errors and 401 codes referencing token/issuer problems:
   - mare_demo.deployments:dep_apex_fail_1 — status: failed; migration_id: mig_auth_sso; error_code: AUTH_401; logs_excerpt: “token validation failed: unauthorized issuer” (2024-05-11)
   - mare_demo.deployments:dep_apex_fail_2 — status: failed; migration_id: mig_auth_sso; error_code: AUTH_401; logs_excerpt: “auth-service returned 401 during rollout” (2024-05-12)
3) Prior to the migration, deployments for this customer were succeeding (showing the problem appeared after migration):
   - mare_demo.deployments:dep_n_0119 — status: success (2024-02-12)
   - mare_demo.deployments:dep_n_0045 — status: success (2024-01-25)

Confidence: high — migration explicitly changed AUTH_ISSUER and the failed deployments cite token validation / 401 unauthorized issuer immediately following the migration.

If you’d like, I can:
- Search logs/tickets for evidence that Apex updated (or failed to update) their AUTH_ISSUER config, or
- Identify which services in their stack are still using the legacy issuer so you can contact the customer with exact remediation steps.

### Hypothesis

_(none)_

### Claims

_(none)_

### Citations

- `mare_demo.migrations:mig_auth_sso`
- `mare_demo.deployments:dep_n_0045`
- `mare_demo.deployments:dep_n_0119`
- `mare_demo.deployments:dep_apex_fail_1`
- `mare_demo.deployments:dep_apex_fail_2`
- `mare_demo.deployments:dep_n_0355`
- `mare_demo.deployments:dep_apex_mar`
- `mare_demo.deployments:dep_apex_apr`
- `mare_demo.deployments:dep_n_0374`
- `mare_demo.incidents:inc_1001`
- `mare_demo.incidents:inc_apex_mar`
- `mare_demo.incidents:inc_apex_apr`
- `mare_demo.incidents:inc_20026`
- `mare_demo.incidents:inc_20074`
- `mare_demo.logs:log_n_02332`
- `mare_demo.logs:log_n_00383`
- `mare_demo.logs:log_n_03603`
- `mare_demo.logs:log_n_02508`
- `mare_demo.logs:log_n_03650`
- `mare_demo.logs:log_1001`
- `mare_demo.tickets:tkt_20013`
- `mare_demo.tickets:tkt_20517`
- `mare_demo.tickets:tkt_20510`
- `mare_demo.tickets:tkt_20666`
- `mare_demo.tickets:tkt_apex_mar`
- `mare_demo.tickets:tkt_20721`

Gold hits: deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, incidents:inc_1001, logs:log_1001, migrations:mig_auth_sso
Missed gold: customers:cust_007, logs:log_1002, tickets:tkt_1001

## RAG answer

Most likely root cause
- After mig_auth_sso changed the SSO issuer to auth-v3, Apex’s deployer/services kept a stale AUTH_ISSUER still pointing to auth-v2, causing token validation to fail. [inc_1001], [mig_auth_sso]

Evidence
- Migration notes require updating AUTH_ISSUER to https://auth-v3.apex.io and warn that the legacy issuer will reject tokens. [mig_auth_sso]
- Both post-migration prod deployments failed with AUTH_401; one explicitly logs “token validation failed: unauthorized issuer,” consistent with an issuer mismatch. [dep_apex_fail_1], [dep_apex_fail_2]
- The customer ticket reports failures began right after the SSO migration with AUTH_401 errors. [tkt_1001]
- The incident tracks the root cause as “stale AUTH_ISSUER still pointing at auth-v2 after SSO issuer cutover.” [inc_1001]

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

