# Variable K — deep (Apex three-month evolution)

- generated: 2026-10-29T13:31:41.698611+00:00
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
| end-to-end latency | **72184 ms** | **16643 ms** |
| agent turns | 11 | n/a |
| tool calls | 10 | n/a |
| LLM latency | 59978 ms | n/a |
| Mongo latency | 9103 ms | n/a |
| retrieval operations | 6 | 1 |
| LLM tokens | 42225 | 2747 |
| stop reason | completed | rag_topk |
| answer correct | no | yes |
| entity found | no | yes |
| root cause found | no | yes |
| evidence recall vs gold (citations) | 0.389 | 0.5 |
| evidence precision vs gold | 0.226 | 0.9 |
| gold evidence recall (retrieved) | 0.389 | 0.5 |
| documents retrieved | 31 | 10 |
| required evidence | 18 | 18 |
| context efficiency | 0.322 | 0.885 |
| completeness groups | 1/4 | 4/4 |
| gold missed | deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, logs:log_1001, logs:log_1002, logs:log_apex_apr_1, logs:log_apex_apr_2, logs:log_apex_apr_3, logs:log_apex_mar_1, logs:log_apex_mar_2, tickets:tkt_1001, tickets:tkt_apex_apr | deployments:dep_apex_apr, deployments:dep_apex_mar, logs:log_1002, logs:log_apex_apr_1, logs:log_apex_apr_2, logs:log_apex_apr_3, logs:log_apex_mar_1, logs:log_apex_mar_2, migrations:mig_auth_sso |

Persistent vector indexes (not per-query scan count): MARE searches the 616-node navigation index, then reads raw Mongo documents. RAG searches the 5424-chunk vector index and returns Top-K.

## RAG Top-K sweep

| variant | correct | gold recall | docs retrieved | completeness | ms |
| --- | --- | --- | --- | --- | --- |
| hybrid_10 | yes | 0.5 | 10 | 4/4 | 16643 |
| hybrid_20 | yes | 0.889 | 20 | 4/4 | 14505 |
| hybrid_5 | yes | 0.278 | 5 | 4/4 | 13238 |
| vector_10 | yes | 0.5 | 10 | 4/4 | 13603 |

### RAG answers by variant

**hybrid_10**

Recurring factors
- Auth configuration changes, not user credentials, repeatedly caused breakage:
  - Session lifetime policy shortened, forcing unexpected logouts (session idle-timeout on dashboard cookie) [tkt_apex_mar, inc_apex_mar].
  - Access token lifetime shortened, causing long-running jobs to outlive tokens (ACCESS_TOKEN_TTL_SEC reduced) [tkt_apex_apr, inc_apex_apr].
  - SSO cutover left stale auth config (AUTH_ISSUER pointing to old issuer), triggering 401s during deployments [inc_1001, tkt_1001, dep_apex_fail_1, dep_apex_fail_2, log_1001].
- Common theme: authentication policy/config drift during platform changes without coordinating with workload durations or fully updating dependent services [inc_apex_mar, inc_apex_apr, inc_1001].

How the failure mode evolved (Mar → May)
- March: Interactive users are logged out after short idle due to shortened dashboard session idle-timeout (sev-3) [tkt_apex_mar, inc_apex_mar].
- April: Batch/worker jobs fail mid-run, repeatedly prompting for sign-in because access tokens expire before jobs finish (sev-2). Not an idle cookie issue; explicitly a shorter access-token lifetime [tkt_apex_apr, inc_apex_apr].
- May: Platform deployments fail outright with AUTH_401 after SSO migration due to issuer mismatch (expected auth-v3, got auth-v2), affecting services like auth-service and billing-worker (sev-1) [inc_1001, tkt_1001, dep_apex_fail_1, dep_apex_fail_2, log_1001].

**hybrid_20**

- Recurring factors
  - Authentication configuration changes/misconfigurations: shortened session or token lifetimes and a stale issuer setting after SSO cutover [inc_apex_mar; log_apex_mar_1; inc_apex_apr; log_apex_apr_1; inc_1001; log_1001; mig_auth_sso].
  - Lifetimes not aligned with real workloads: sessions/tokens expiring before users or jobs finish [log_apex_mar_1; log_apex_apr_1; log_apex_apr_3].
  - Incomplete/unclean rollout of auth configs across services (config drift), notably AUTH_ISSUER left on the old endpoint post-migration, causing 401s [inc_1001; dep_apex_fail_1; dep_apex_fail_2; log_1001; log_1002; mig_auth_sso].

- How the failure mode evolved
  - March: End-user impact—dashboard sessions ended early due to a shortened cookie idle timeout (SESSION_IDLE_TIMEOUT_SEC=900), forcing re-login after brief idle periods [tkt_apex_mar; inc_apex_mar; log_apex_mar_1; log_apex_mar_2].
  - April: Backend impact—long-running jobs failed mid-run because access tokens expired sooner (ACCESS_TOKEN_TTL_SEC=1800), prompting re-auth during jobs [tkt_apex_apr; inc_apex_apr; log_apex_apr_1; log_apex_apr_2; log_apex_apr_3].
  - May: Platform/deploy impact—after SSO migration, deployments failed authentication with 401 due to a stale AUTH_ISSUER still pointing to auth-v2; logs show issuer mismatch against the new v3 issuer [tkt_1001; inc_1001; dep_apex_fail_1; dep_apex_fail_2; log_1001; log_1002; mig_auth_sso].

**hybrid_5**

Summary of recurring factors
- Auth configuration changes without coordinated client/deployer updates:
  - Access-token lifetime was shortened, so long-running Apex jobs outlived tokens [inc_apex_apr, tkt_apex_apr].
  - After the SSO cutover, deployer config kept a stale AUTH_ISSUER pointing to the old issuer, causing validation failures [inc_1001, dep_apex_fail_1, tkt_1001].

How the failure mode evolved
- April (Apr 16): Failures during long-running jobs that paused mid-run and demanded re‑sign‑in; traced to reduced ACCESS_TOKEN_TTL_SEC (not idle cookie timeouts) [tkt_apex_apr, inc_apex_apr].
- May (May 11): Shift to hard AUTH_401 errors on production deployments; token validation failed due to “unauthorized issuer” from stale AUTH_ISSUER after the SSO migration [dep_apex_fail_1, tkt_1001, inc_1001].
- Impact/severity increased from sev‑2 job interruptions to sev‑1 deployment‑blocking auth failures [inc_apex_apr, inc_1001].

**vector_10**

Recurring factors
- Repeated auth configuration changes/misconfigurations that shortened or invalidated credentials (cookie idle-timeout, access-token TTL, SSO issuer), without aligning with user workflows or deployment tooling [inc_apex_mar] [inc_apex_apr] [inc_1001].

How the failure mode evolved
- March: Users were logged out after being idle due to a shortened dashboard cookie idle-timeout (idle sessions ending early) [tkt_apex_mar] [inc_apex_mar].
- April: Long-running worker jobs were interrupted mid-run because ACCESS_TOKEN_TTL_SEC was reduced; tokens expired before jobs finished, prompting fresh sign-ins (not an idle cookie issue) [tkt_apex_apr] [inc_apex_apr].
- May: Following an SSO migration, production deployments failed with AUTH_401 due to a stale AUTH_ISSUER still pointing to auth-v2; logs show issuer mismatch (expected v3, got v2) [tkt_1001] [inc_1001] [dep_apex_fail_1] [dep_apex_fail_2] [log_1001].

Severity trended upward over time: sev-3 (March) → sev-2 (April) → sev-1 (May) [inc_apex_mar] [inc_apex_apr] [inc_1001].

## MARE answer (blind)

Recurring factors
- Post-SSO migration config drift: multiple prod deployments failed auth because AUTH_ISSUER remained pointed at the old issuer after the cutover (description: “Multiple production deployments failing authentication after mig_auth_sso. Suspected stale AUTH_ISSUER on deployer.”; root_cause: “stale AUTH_ISSUER still pointing at auth-v2 after SSO issuer cutover”; status: open) (mare_demo.incidents:inc_1001).
- Ongoing downstream instability from the auth-service, evidenced by repeated “retrying downstream call attempt=1” during June and July (2024-06-27 and 2024-07-06) (mare_demo.logs:log_n_00882; mare_demo.logs:log_n_01060).

Evolution of the failure mode
- Immediately post-migration (opened_at 2024-05-11), authentication failures were systemic across deployments due to the wrong issuer configuration (mare_demo.incidents:inc_1001).
- By late June–early July, the symptom set shifted toward intermittent downstream-call retries in auth-service rather than outright failure, as shown in the logs (mare_demo.logs:log_n_00882; mare_demo.logs:log_n_01060).
- August evidence provided contains no auth-service errors; the incident remains open with closed_at: None, so continued impact cannot be ruled out, but the available August logs are not sufficient to confirm further evolution (mare_demo.incidents:inc_1001; mare_demo.logs:log_n_02895).

### Hypothesis

_(none)_

### Claims

_(none)_

### Citations

- `mare_demo.incidents:inc_1001`
- `mare_demo.incidents:inc_apex_mar`
- `mare_demo.incidents:inc_apex_apr`
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
- `mare_demo.logs:log_n_02895`
- `mare_demo.tickets:tkt_20013`
- `mare_demo.tickets:tkt_20517`
- `mare_demo.tickets:tkt_20510`
- `mare_demo.tickets:tkt_20666`
- `mare_demo.tickets:tkt_apex_mar`
- `mare_demo.tickets:tkt_20721`
- `mare_demo.incidents:inc_20074`
- `mare_demo.incidents:inc_20026`
- `mare_demo.deployments:dep_n_0045`
- `mare_demo.deployments:dep_n_0119`
- `mare_demo.deployments:dep_n_0355`
- `mare_demo.deployments:dep_apex_mar`
- `mare_demo.deployments:dep_apex_apr`
- `mare_demo.deployments:dep_n_0374`
- `mare_demo.migrations:mig_auth_sso`

Gold hits: deployments:dep_apex_apr, deployments:dep_apex_mar, incidents:inc_1001, incidents:inc_apex_apr, incidents:inc_apex_mar, migrations:mig_auth_sso, tickets:tkt_apex_mar
Missed gold: deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, logs:log_1001, logs:log_1002, logs:log_apex_apr_1, logs:log_apex_apr_2, logs:log_apex_apr_3, logs:log_apex_mar_1, logs:log_apex_mar_2, tickets:tkt_1001, tickets:tkt_apex_apr

## RAG answer

Recurring factors
- Auth configuration changes, not user credentials, repeatedly caused breakage:
  - Session lifetime policy shortened, forcing unexpected logouts (session idle-timeout on dashboard cookie) [tkt_apex_mar, inc_apex_mar].
  - Access token lifetime shortened, causing long-running jobs to outlive tokens (ACCESS_TOKEN_TTL_SEC reduced) [tkt_apex_apr, inc_apex_apr].
  - SSO cutover left stale auth config (AUTH_ISSUER pointing to old issuer), triggering 401s during deployments [inc_1001, tkt_1001, dep_apex_fail_1, dep_apex_fail_2, log_1001].
- Common theme: authentication policy/config drift during platform changes without coordinating with workload durations or fully updating dependent services [inc_apex_mar, inc_apex_apr, inc_1001].

How the failure mode evolved (Mar → May)
- March: Interactive users are logged out after short idle due to shortened dashboard session idle-timeout (sev-3) [tkt_apex_mar, inc_apex_mar].
- April: Batch/worker jobs fail mid-run, repeatedly prompting for sign-in because access tokens expire before jobs finish (sev-2). Not an idle cookie issue; explicitly a shorter access-token lifetime [tkt_apex_apr, inc_apex_apr].
- May: Platform deployments fail outright with AUTH_401 after SSO migration due to issuer mismatch (expected auth-v3, got auth-v2), affecting services like auth-service and billing-worker (sev-1) [inc_1001, tkt_1001, dep_apex_fail_1, dep_apex_fail_2, log_1001].

### Citations

- `mare_demo.tickets:tkt_apex_apr`
- `mare_demo.incidents:inc_1001`
- `mare_demo.incidents:inc_apex_apr`
- `mare_demo.deployments:dep_apex_fail_1`
- `mare_demo.tickets:tkt_1001`
- `mare_demo.tickets:tkt_ns_login`
- `mare_demo.deployments:dep_apex_fail_2`
- `mare_demo.tickets:tkt_apex_mar`
- `mare_demo.incidents:inc_apex_mar`
- `mare_demo.logs:log_1001`

Gold hits: deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, incidents:inc_1001, incidents:inc_apex_apr, incidents:inc_apex_mar, logs:log_1001, tickets:tkt_1001, tickets:tkt_apex_apr, tickets:tkt_apex_mar
Missed gold: deployments:dep_apex_apr, deployments:dep_apex_mar, logs:log_1002, logs:log_apex_apr_1, logs:log_apex_apr_2, logs:log_apex_apr_3, logs:log_apex_mar_1, logs:log_apex_mar_2, migrations:mig_auth_sso

