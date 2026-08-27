# Variable K — deep (Apex three-month evolution)

- generated: 2026-08-27T06:24:38.541354+00:00
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
| end-to-end latency | **33757 ms** | **12686 ms** |
| agent turns | 7 | n/a |
| tool calls | 6 | n/a |
| LLM latency | 32027 ms | n/a |
| Mongo latency | 1332 ms | n/a |
| retrieval operations | 3 | 1 |
| LLM tokens | 87457 | 2685 |
| stop reason | completed | rag_topk |
| answer correct | yes | yes |
| entity found | yes | yes |
| root cause found | yes | yes |
| evidence recall vs gold (citations) | 0.333 | 0.5 |
| evidence precision vs gold | 0.261 | 0.9 |
| gold evidence recall (retrieved) | 0.333 | 0.5 |
| documents retrieved | 23 | 10 |
| required evidence | 18 | 18 |
| context efficiency | 0.342 | 0.885 |
| completeness groups | 4/4 | 4/4 |
| gold missed | deployments:dep_apex_apr, deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, deployments:dep_apex_mar, logs:log_1001, logs:log_1002, logs:log_apex_apr_1, logs:log_apex_apr_2, logs:log_apex_apr_3, logs:log_apex_mar_1, logs:log_apex_mar_2, migrations:mig_auth_sso | deployments:dep_apex_apr, deployments:dep_apex_mar, logs:log_1002, logs:log_apex_apr_1, logs:log_apex_apr_2, logs:log_apex_apr_3, logs:log_apex_mar_1, logs:log_apex_mar_2, migrations:mig_auth_sso |

Persistent vector indexes (not per-query scan count): MARE searches the 616-node navigation index, then reads raw Mongo documents. RAG searches the 5424-chunk vector index and returns Top-K.

## RAG Top-K sweep

| variant | correct | gold recall | docs retrieved | completeness | ms |
| --- | --- | --- | --- | --- | --- |
| hybrid_10 | yes | 0.5 | 10 | 4/4 | 12686 |
| hybrid_20 | yes | 0.889 | 20 | 4/4 | 15051 |
| hybrid_5 | yes | 0.222 | 5 | 4/4 | 15229 |
| vector_10 | yes | 0.5 | 10 | 4/4 | 13262 |

### RAG answers by variant

**hybrid_10**

Summary of recurring factors
- Repeated auth configuration changes that shortened or misaligned credential validity with real workloads:
  - Session idle-timeout on the dashboard cookie was shortened, causing user sessions to end early [inc_apex_mar][tkt_apex_mar].
  - ACCESS_TOKEN_TTL_SEC was reduced, so long-running Apex jobs outlived their tokens and halted for re‑auth [inc_apex_apr][tkt_apex_apr].
  - After an SSO cutover, a stale AUTH_ISSUER kept pointing to the old issuer (auth‑v2), triggering issuer mismatches and AUTH_401s in production deploys [inc_1001][dep_apex_fail_1][dep_apex_fail_2][log_1001][tkt_1001].

How the failure mode evolved month by month
- March: User-facing idle logouts in the dashboard due to a shortened cookie idle-timeout (sessions end after short idle) [inc_apex_mar][tkt_apex_mar].
- April: Mid-run worker/batch job interruptions because access tokens expired before jobs finished (shorter token TTL) [inc_apex_apr][tkt_apex_apr].
- May: Environment-wide deployment authentication failures (AUTH_401) caused by an issuer mismatch after SSO migration; logs show expected auth‑v3 vs got auth‑v2 [inc_1001][dep_apex_fail_1][dep_apex_fail_2][log_1001][tkt_1001].

Throughline: each incident stems from auth settings drifting or changing without aligning clients/services and runtimes, progressing from user idle sessions to long-running jobs, then to systemic deploy-time failures as identity provider settings changed.

**hybrid_20**

Recurring factors
- Authentication configuration changes not aligned to usage and clients:
  - Session idle timeout shortened on the dashboard cookie, causing unexpected logouts for idle users [inc_apex_mar; logs log_apex_mar_1; logs log_apex_mar_2; tkt_apex_mar].
  - Access-token lifetime reduced, so long-running batch/worker jobs outlived tokens and needed re-auth mid-run [inc_apex_apr; logs log_apex_apr_1; logs log_apex_apr_2; logs log_apex_apr_3; tkt_apex_apr].
  - SSO issuer cutover required clients to update AUTH_ISSUER; a stale issuer value left some services validating against the old endpoint, triggering AUTH_401 [migrations mig_auth_sso; inc_1001; logs log_1001; logs log_1002; dep_apex_fail_1; dep_apex_fail_2; tkt_1001].

How the failure mode evolved
- March (user sessions): Early idle logouts due to shortened SESSION_IDLE_TIMEOUT_SEC on dashboard cookies (sev-3) [inc_apex_mar; logs log_apex_mar_1; logs log_apex_mar_2; tkt_apex_mar].
- April (batch jobs): Tokens expiring during long-running jobs after ACCESS_TOKEN_TTL_SEC was reduced; workers and scheduler aborted and prompted re-auth (sev-2) [inc_apex_apr; logs log_apex_apr_1; logs log_apex_apr_2; logs log_apex_apr_3; tkt_apex_apr].
- May (deployments/platform): Post-SSO migration, deployments failed with AUTH_401 due to jwt issuer mismatch from a stale AUTH_ISSUER still pointing at auth-v2 instead of auth-v3 (sev-1) [migrations mig_auth_sso; inc_1001; dep_apex_fail_1; dep_apex_fail_2; logs log_1001; logs log_1002; tkt_1001].

In short, Apex’s auth issues progressed from shortened session lifetimes to shortened token lifetimes, then to an issuer mismatch after an SSO cutover—all configuration-driven and not matched to user/job duration or updated client settings [inc_apex_mar; inc_apex_apr; inc_1001; migrations mig_auth_sso].

**hybrid_5**

Recurring factors
- Authentication configuration/policy changes not coordinated across services:
  - Token lifetime cut too short, causing long-running Apex jobs to outlive access tokens and prompt mid-run re‑auth [inc_apex_apr; tkt_apex_apr].
  - SSO issuer cutover left deployers with stale AUTH_ISSUER, so tokens were rejected for unauthorized issuer [inc_1001; dep_apex_fail_1].

Failure-mode evolution
- Pre-April: Users reported “idle-logout”–type symptoms (referenced by Apex) [tkt_apex_apr].
- April: Shift to short-lived access tokens interrupting batch/worker jobs; root cause was reduced ACCESS_TOKEN_TTL_SEC [tkt_apex_apr; inc_apex_apr].
- May: Escalated to hard auth failures during prod deployments after SSO migration due to stale AUTH_ISSUER (unauthorized issuer) [inc_1001; dep_apex_fail_1].

**vector_10**

Recurring factors
- Regressive auth configuration changes:
  - Session idle-timeout on the dashboard cookie was shortened, causing user sessions to end early [inc_apex_mar; tkt_apex_mar].
  - Access token lifetime was reduced (ACCESS_TOKEN_TTL_SEC), so long-running Apex jobs outlived tokens and prompted re‑sign‑in mid-run [inc_apex_apr; tkt_apex_apr].
- Post-SSO cutover misconfiguration:
  - Deployer kept a stale AUTH_ISSUER pointing at auth‑v2, producing issuer mismatches and AUTH_401s during prod deployments [inc_1001; tkt_1001; dep_apex_fail_1; log_1001; dep_apex_fail_2].

How the failure mode evolved (Mar → May)
- March: User-facing idle logouts due to shortened dashboard session idle-timeout (sev‑3) [inc_apex_mar; tkt_apex_mar].
- April: Active, long-running jobs interrupted by short-lived access tokens (sev‑2) [inc_apex_apr; tkt_apex_apr].
- May: System-level deployment failures after SSO migration from issuer mismatch (sev‑1) [inc_1001; tkt_1001; dep_apex_fail_1; log_1001; dep_apex_fail_2].

In short: each month’s failures trace to auth configuration or cutover changes not aligned with clients/jobs/deploy tooling—first shorter session cookies, then shorter token TTLs, then an incorrect issuer after SSO migration [inc_apex_mar; inc_apex_apr; inc_1001].

## MARE answer (blind)

Recurring factors and evolution:
- March: Idle logouts were caused by a configuration change that shortened the dashboard cookie’s session idle-timeout, forcing operators to reauthenticate after brief inactivity (mare_demo.incidents:inc_apex_mar; mare_demo.tickets:tkt_apex_mar).
- April: Authentication failures shifted to long-running worker jobs when ACCESS_TOKEN_TTL_SEC was reduced, causing tokens to expire mid-run and prompt for re-sign-in (mare_demo.incidents:inc_apex_apr; mare_demo.tickets:tkt_apex_apr).
- May: After an SSO migration, deploys failed with AUTH_401 because the deployer kept a stale AUTH_ISSUER still pointing at auth-v2; this aligns with Apex’s issuer reference and the incident’s root cause (mare_demo.incidents:inc_1001; mare_demo.tickets:tkt_1001; mare_demo.customers:cust_007).

In short, the failures consistently stemmed from auth configuration changes—first session idle-timeout, then access-token TTL, then SSO issuer settings—evolving from UI idle logouts to job interruptions to deployment failures (mare_demo.incidents:inc_apex_mar; mare_demo.incidents:inc_apex_apr; mare_demo.incidents:inc_1001).

Claim checks:
- c1 supported: “March failures were due to a shortened dashboard cookie idle-timeout causing idle logouts.” Evidence: root cause and user reports (mare_demo.incidents:inc_apex_mar; mare_demo.tickets:tkt_apex_mar).
- c2 supported: “April failures were due to reduced ACCESS_TOKEN_TTL_SEC causing long-running jobs to lose authentication mid-run.” Evidence: root cause and job prompts (mare_demo.incidents:inc_apex_apr; mare_demo.tickets:tkt_apex_apr).
- c3 supported: “May failures were caused by a stale AUTH_ISSUER after an SSO migration, producing AUTH_401 on deploys.” Evidence: incident root cause and ticket error details; issuer reference corroborates auth-v2 endpoint (mare_demo.incidents:inc_1001; mare_demo.tickets:tkt_1001; mare_demo.customers:cust_007).

### Hypothesis

_(none)_

### Claims

- `c1` **supported** (0.90): March failures were due to a shortened dashboard cookie idle-timeout causing idle logouts.
- `c2` **supported** (0.90): April failures were due to reduced ACCESS_TOKEN_TTL_SEC causing long-running jobs to lose authentication mid-run.
- `c3` **supported** (0.95): May failures were caused by a stale AUTH_ISSUER after an SSO migration, producing AUTH_401 on deploys.

### Citations

- `mare_demo.customers:cust_007`
- `mare_demo.incidents:inc_1001`
- `mare_demo.incidents:inc_apex_mar`
- `mare_demo.incidents:inc_apex_apr`
- `mare_demo.tickets:tkt_apex_mar`
- `mare_demo.tickets:tkt_apex_apr`
- `mare_demo.tickets:tkt_1001`
- `mare_demo.incidents:inc_20026`
- `mare_demo.incidents:inc_20074`
- `mare_demo.tickets:tkt_20013`
- `mare_demo.tickets:tkt_20517`
- `mare_demo.tickets:tkt_20510`
- `mare_demo.tickets:tkt_20666`
- `mare_demo.tickets:tkt_20721`
- `mare_demo.tickets:tkt_20425`
- `mare_demo.tickets:tkt_20325`
- `mare_demo.tickets:tkt_20319`
- `mare_demo.tickets:tkt_20292`
- `mare_demo.tickets:tkt_20072`
- `mare_demo.tickets:tkt_20513`
- `mare_demo.tickets:tkt_20465`
- `mare_demo.tickets:tkt_20450`
- `mare_demo.tickets:tkt_20557`

Gold hits: incidents:inc_1001, incidents:inc_apex_apr, incidents:inc_apex_mar, tickets:tkt_1001, tickets:tkt_apex_apr, tickets:tkt_apex_mar
Missed gold: deployments:dep_apex_apr, deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, deployments:dep_apex_mar, logs:log_1001, logs:log_1002, logs:log_apex_apr_1, logs:log_apex_apr_2, logs:log_apex_apr_3, logs:log_apex_mar_1, logs:log_apex_mar_2, migrations:mig_auth_sso

## RAG answer

Summary of recurring factors
- Repeated auth configuration changes that shortened or misaligned credential validity with real workloads:
  - Session idle-timeout on the dashboard cookie was shortened, causing user sessions to end early [inc_apex_mar][tkt_apex_mar].
  - ACCESS_TOKEN_TTL_SEC was reduced, so long-running Apex jobs outlived their tokens and halted for re‑auth [inc_apex_apr][tkt_apex_apr].
  - After an SSO cutover, a stale AUTH_ISSUER kept pointing to the old issuer (auth‑v2), triggering issuer mismatches and AUTH_401s in production deploys [inc_1001][dep_apex_fail_1][dep_apex_fail_2][log_1001][tkt_1001].

How the failure mode evolved month by month
- March: User-facing idle logouts in the dashboard due to a shortened cookie idle-timeout (sessions end after short idle) [inc_apex_mar][tkt_apex_mar].
- April: Mid-run worker/batch job interruptions because access tokens expired before jobs finished (shorter token TTL) [inc_apex_apr][tkt_apex_apr].
- May: Environment-wide deployment authentication failures (AUTH_401) caused by an issuer mismatch after SSO migration; logs show expected auth‑v3 vs got auth‑v2 [inc_1001][dep_apex_fail_1][dep_apex_fail_2][log_1001][tkt_1001].

Throughline: each incident stems from auth settings drifting or changing without aligning clients/services and runtimes, progressing from user idle sessions to long-running jobs, then to systemic deploy-time failures as identity provider settings changed.

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

