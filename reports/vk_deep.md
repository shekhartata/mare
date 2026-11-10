# Variable K — deep (Apex three-month evolution)

- generated: 2026-11-10T07:34:57.001096+00:00
- answer model: `gpt-5`
- agent model: `gpt-5-mini` (reasoning_effort=low)
- MARE mode: **blind** (schema_in_prompt=false)
- max_agent_turns: 10
- vector index: MARE **616** vs RAG **5424** (ratio 0.1136)

## Why this case

March idle-timeout, April token TTL, May issuer mismatch. Fifteen or more gold records. Fixed Top-K under-retrieves unless K is huge, which over-retrieves the small sibling question.

## Question

What recurring factors explain Apex's authentication failures across the last three months, and how did the failure mode evolve?

## Gold answer

Apex (cust_007) authentication problems evolved: March idle-session timeouts (SESSION_EXPIRED / cookie max-age), April shortened ACCESS_TOKEN_TTL_SEC (TOKEN_TTL), then May SSO issuer mismatch after mig_auth_sso (AUTH_401).

## Latency and retrieval

| metric | MARE (blind) | Conventional RAG |
| --- | --- | --- |
| end-to-end latency | **38953 ms** | **26145 ms** |
| agent turns | 8 | n/a |
| tool calls | 8 | n/a |
| LLM latency | 34139 ms | n/a |
| Mongo latency | 3712 ms | n/a |
| retrieval operations | 3 | 1 |
| LLM tokens | 29107 | 3632 |
| stop reason | completed | rag_topk |
| answer correct | yes | yes |
| entity found | yes | yes |
| root cause found | yes | yes |
| evidence recall vs gold (citations) | 0.444 | 0.5 |
| evidence precision vs gold | 0.216 | 0.9 |
| gold evidence recall (retrieved) | 0.444 | 0.5 |
| documents retrieved | 37 | 10 |
| required evidence | 18 | 18 |
| context efficiency | 0.304 | 0.885 |
| completeness groups | 4/4 | 4/4 |
| gold missed | deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, logs:log_1002, logs:log_apex_apr_1, logs:log_apex_apr_2, logs:log_apex_apr_3, logs:log_apex_mar_1, logs:log_apex_mar_2, tickets:tkt_1001, tickets:tkt_apex_apr | deployments:dep_apex_apr, deployments:dep_apex_mar, logs:log_1002, logs:log_apex_apr_1, logs:log_apex_apr_2, logs:log_apex_apr_3, logs:log_apex_mar_1, logs:log_apex_mar_2, migrations:mig_auth_sso |

Persistent vector indexes (not per-query scan count): MARE searches the 616-node navigation index, then reads raw Mongo documents. RAG searches the 5424-chunk vector index and returns Top-K.

## RAG Top-K sweep

| variant | correct | gold recall | docs retrieved | completeness | ms |
| --- | --- | --- | --- | --- | --- |
| hybrid_10 | yes | 0.5 | 10 | 4/4 | 26145 |
| hybrid_20 | yes | 0.889 | 20 | 4/4 | 15537 |
| hybrid_5 | yes | 0.222 | 5 | 4/4 | 16582 |
| vector_10 | yes | 0.5 | 10 | 4/4 | 18287 |

### RAG answers by variant

**hybrid_10**

Recurring factors
- Authentication configuration changes shortened validity windows, causing premature expiry: session idle-timeout on the dashboard cookie and ACCESS_TOKEN_TTL_SEC for API tokens [inc_apex_mar][inc_apex_apr].
- Configuration drift during auth-system changeovers: stale AUTH_ISSUER left pointing to the old issuer after the SSO cutover, leading to issuer mismatches [inc_1001].
- Long-running activities exceeded auth validity: operators away for lunch (dashboard), multi‑hour batch jobs, and deployment rollouts—all in production—were most affected [tkt_apex_mar][tkt_apex_apr][dep_apex_fail_1][dep_apex_fail_2].

Failure-mode evolution
- March: Users were logged out after short idle periods on the dashboard due to a shortened cookie idle-timeout (sev‑3) [tkt_apex_mar][inc_apex_mar].
- April: Failures shifted from idle UI sessions to active, long-running jobs; batch workers failed mid-run and demanded re‑auth because access tokens expired sooner after ACCESS_TOKEN_TTL_SEC was reduced (sev‑2) [tkt_apex_apr][inc_apex_apr].
- May: The mode changed to outright authentication rejection during production deployments (AUTH_401) post‑SSO migration; root cause was a stale AUTH_ISSUER pointing to auth‑v2, producing a JWT issuer mismatch vs expected auth‑v3, confirmed in logs, impacting auth-service and billing-worker rollouts (sev‑1) [tkt_1001][inc_1001][dep_apex_fail_1][dep_apex_fail_2][log_1001].

**hybrid_20**

Recurring factors
- Authentication configuration changes not aligned with real usage:
  - Shortened session idle timeout on the dashboard cookie caused unexpected user logouts after brief inactivity [inc_apex_mar; log_apex_mar_1; tkt_apex_mar].
  - Reduced access-token lifetime meant long-running jobs outlived their tokens, forcing mid-run re-authentication [inc_apex_apr; log_apex_apr_1; log_apex_apr_2; tkt_apex_apr].
- Configuration drift after a platform/SSO change:
  - Post-SSO migration, services still pointed to the old AUTH_ISSUER, causing issuer mismatches and AUTH_401 errors during deployments [mig_auth_sso; inc_1001; dep_apex_fail_1; dep_apex_fail_2; log_1001; log_1002].

How the failure mode evolved
- March: User-facing issue. Operators were logged out after short idle periods due to a shortened session idle-timeout on the dashboard cookie [inc_apex_mar; log_apex_mar_1; tkt_apex_mar].
- April: Background job impact. Failures shifted from idle sessions to token TTLs; access tokens expired mid-run, interrupting worker and scheduled jobs and prompting re-authentication [inc_apex_apr; log_apex_apr_1; log_apex_apr_2; log_apex_apr_3; tkt_apex_apr].
- May: Deployment-time hard failures. After migrating SSO, deployments failed with AUTH_401 due to a stale AUTH_ISSUER still set to auth-v2 instead of auth-v3; logs show issuer mismatch during token validation [mig_auth_sso; inc_1001; dep_apex_fail_1; dep_apex_fail_2; log_1001; log_1002].

**hybrid_5**

Recurring factors
- Auth configuration changes/misconfigurations: reduced ACCESS_TOKEN_TTL_SEC and a stale AUTH_ISSUER after SSO cutover, both causing token-related failures [inc_apex_apr], [inc_1001], [dep_apex_fail_1].
- Long-running Apex jobs and deployments were especially exposed: jobs outlived tokens and deployments rejected tokens due to issuer mismatch [tkt_apex_apr], [inc_apex_apr], [dep_apex_fail_1].

How the failure mode evolved (month by month)
- March: Idle-logout symptoms were reported previously (users signed out when idle) [tkt_apex_apr].
- April: Shifted to mid-run interruptions of Apex batch/worker jobs—short-lived access tokens prompted re‑sign‑ins; root cause was ACCESS_TOKEN_TTL_SEC being reduced so jobs outlived the token. Not an idle-cookie issue [tkt_apex_apr], [inc_apex_apr].
- May: After SSO migration, auth started failing at deploy time due to a stale AUTH_ISSUER still pointing at the old issuer; logs show “unauthorized issuer” during token validation, breaking production deployments [inc_1001], [dep_apex_fail_1].

**vector_10**

Recurring factors
- Aggressive auth/session configuration changes:
  - Dashboard session idle-timeout was shortened, causing unexpected logouts when users were idle [inc_apex_mar, tkt_apex_mar].
  - Access-token lifetime was reduced (ACCESS_TOKEN_TTL_SEC), so long-running jobs outlived tokens and prompted mid-run re-authentication [inc_apex_apr, tkt_apex_apr].
- Configuration drift during SSO migration:
  - A stale AUTH_ISSUER still pointed at the old issuer (auth‑v2) after the SSO cutover to auth‑v3, producing AUTH_401 errors and issuer mismatches [inc_1001, dep_apex_fail_1, dep_apex_fail_2, log_1001, tkt_1001].

How the failure mode evolved (Mar → Apr → May)
- March: Users were logged out after short idle periods on the dashboard due to a shortened cookie idle-timeout; not password failures (sev‑3) [inc_apex_mar, tkt_apex_mar].
- April: Failures shifted from idle UI sessions to backend/worker flows: batch jobs were interrupted mid-run because access tokens expired sooner than the jobs ran (sev‑2) [inc_apex_apr, tkt_apex_apr].
- May: Breakage escalated to deployment-time authentication failures after the SSO migration, with AUTH_401s caused by a jwt issuer mismatch (expected auth‑v3, got auth‑v2) and a stale AUTH_ISSUER config (sev‑1) [inc_1001, dep_apex_fail_1, dep_apex_fail_2, log_1001, tkt_1001].

## MARE answer (blind)

Identified entity: Apex Logistics (customer_id cust_007)

Summary answer
- Recurring root factors: configuration changes and SSO migration-related configuration drift. Over the last three months Apex’s auth problems repeatedly trace to changes in authentication-related configuration (session/cookie settings, token TTL, and SSO issuer configuration) introduced either via dashboard changes or migrations/deploys.
- Evolution of failure mode: March — users experienced sudden logouts caused by a shortened session idle-timeout; April — background worker jobs and long-running flows failed because ACCESS_TOKEN_TTL_SEC was reduced (tokens expired mid-job); May — after an SSO issuer cutover, production deployments failed authentication because deployer components still pointed at the old/stale AUTH_ISSUER (auth-v2), producing broad auth failures.

Supporting evidence
- March incident documents session idle-timeout change as the root cause of user logouts (session endings): incidents:inc_apex_mar (customer_id cust_007) supports the March finding.
- April incident attributes root cause to reduced ACCESS_TOKEN_TTL_SEC causing jobs to outlive tokens: incidents:inc_apex_apr (customer_id cust_007) supports the April finding.
- May high-severity incident points to a stale AUTH_ISSUER left pointing at auth-v2 after the SSO issuer cutover as the root cause of production auth failures: incidents:inc_1001 (customer_id cust_007) and the customer record shows the previous sso_issuer value (customers:cust_007) supporting the SSO-migration linkage.

Implication
- Common theme is configuration drift or incomplete cutover during deploys/migrations (token and cookie lifetimes, and SSO issuer settings). To prevent recurrence, rollbacks or toggles for auth-related settings, stronger deploy-time checks for issuer values, and a post-migration verification of token/cookie lifetimes and issuer endpoints are recommended.

### Hypothesis

_(none)_

### Claims

- `c1` **supported** (0.90): March failures were caused by a shortened session idle-timeout causing sudden logouts.
- `c2` **supported** (0.90): April failures were caused by reduced ACCESS_TOKEN_TTL_SEC causing long-running jobs to fail.
- `c3` **supported** (0.95): May failures were caused by a stale AUTH_ISSUER still pointing at auth-v2 after SSO cutover.

### Citations

- `mare_demo.customers:cust_007`
- `mare_demo.incidents:inc_1001`
- `mare_demo.incidents:inc_apex_mar`
- `mare_demo.incidents:inc_apex_apr`
- `mare_demo.deployments:dep_n_0045`
- `mare_demo.deployments:dep_n_0119`
- `mare_demo.deployments:dep_n_0355`
- `mare_demo.deployments:dep_apex_mar`
- `mare_demo.deployments:dep_apex_apr`
- `mare_demo.deployments:dep_n_0374`
- `mare_demo.migrations:mig_auth_sso`
- `mare_demo.logs:log_n_02332`
- `mare_demo.logs:log_n_00383`
- `mare_demo.logs:log_n_03603`
- `mare_demo.logs:log_n_02508`
- `mare_demo.logs:log_n_03650`
- `mare_demo.logs:log_1001`
- `mare_demo.logs:log_n_00952`
- `mare_demo.logs:log_n_03778`
- `mare_demo.logs:log_n_03780`
- `mare_demo.logs:log_n_00589`
- `mare_demo.logs:log_n_03445`
- `mare_demo.logs:log_n_00882`
- `mare_demo.logs:log_n_01971`
- `mare_demo.logs:log_n_01060`
- `mare_demo.logs:log_n_03095`
- `mare_demo.logs:log_n_00798`
- `mare_demo.logs:log_n_03930`
- `mare_demo.logs:log_n_01471`
- `mare_demo.incidents:inc_20026`
- `mare_demo.incidents:inc_20074`
- `mare_demo.tickets:tkt_20013`
- `mare_demo.tickets:tkt_20517`
- `mare_demo.tickets:tkt_20510`
- `mare_demo.tickets:tkt_20666`
- `mare_demo.tickets:tkt_apex_mar`
- `mare_demo.tickets:tkt_20721`

Gold hits: deployments:dep_apex_apr, deployments:dep_apex_mar, incidents:inc_1001, incidents:inc_apex_apr, incidents:inc_apex_mar, logs:log_1001, migrations:mig_auth_sso, tickets:tkt_apex_mar
Missed gold: deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, logs:log_1002, logs:log_apex_apr_1, logs:log_apex_apr_2, logs:log_apex_apr_3, logs:log_apex_mar_1, logs:log_apex_mar_2, tickets:tkt_1001, tickets:tkt_apex_apr

## RAG answer

Recurring factors
- Authentication configuration changes shortened validity windows, causing premature expiry: session idle-timeout on the dashboard cookie and ACCESS_TOKEN_TTL_SEC for API tokens [inc_apex_mar][inc_apex_apr].
- Configuration drift during auth-system changeovers: stale AUTH_ISSUER left pointing to the old issuer after the SSO cutover, leading to issuer mismatches [inc_1001].
- Long-running activities exceeded auth validity: operators away for lunch (dashboard), multi‑hour batch jobs, and deployment rollouts—all in production—were most affected [tkt_apex_mar][tkt_apex_apr][dep_apex_fail_1][dep_apex_fail_2].

Failure-mode evolution
- March: Users were logged out after short idle periods on the dashboard due to a shortened cookie idle-timeout (sev‑3) [tkt_apex_mar][inc_apex_mar].
- April: Failures shifted from idle UI sessions to active, long-running jobs; batch workers failed mid-run and demanded re‑auth because access tokens expired sooner after ACCESS_TOKEN_TTL_SEC was reduced (sev‑2) [tkt_apex_apr][inc_apex_apr].
- May: The mode changed to outright authentication rejection during production deployments (AUTH_401) post‑SSO migration; root cause was a stale AUTH_ISSUER pointing to auth‑v2, producing a JWT issuer mismatch vs expected auth‑v3, confirmed in logs, impacting auth-service and billing-worker rollouts (sev‑1) [tkt_1001][inc_1001][dep_apex_fail_1][dep_apex_fail_2][log_1001].

### Citations

- `mare_demo.tickets:tkt_apex_apr`
- `mare_demo.incidents:inc_1001`
- `mare_demo.incidents:inc_apex_apr`
- `mare_demo.deployments:dep_apex_fail_1`
- `mare_demo.tickets:tkt_ns_login`
- `mare_demo.tickets:tkt_1001`
- `mare_demo.deployments:dep_apex_fail_2`
- `mare_demo.tickets:tkt_apex_mar`
- `mare_demo.incidents:inc_apex_mar`
- `mare_demo.logs:log_1001`

Gold hits: deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, incidents:inc_1001, incidents:inc_apex_apr, incidents:inc_apex_mar, logs:log_1001, tickets:tkt_1001, tickets:tkt_apex_apr, tickets:tkt_apex_mar
Missed gold: deployments:dep_apex_apr, deployments:dep_apex_mar, logs:log_1002, logs:log_apex_apr_1, logs:log_apex_apr_2, logs:log_apex_apr_3, logs:log_apex_mar_1, logs:log_apex_mar_2, migrations:mig_auth_sso

