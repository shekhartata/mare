# Variable K — medium (Apex May sequence)

- generated: 2026-08-27T06:23:08.442628+00:00
- answer model: `gpt-5`
- agent model: `gpt-5-mini` (reasoning_effort=low)
- MARE mode: **blind** (schema_in_prompt=false)
- max_agent_turns: 10
- vector index: MARE **616** vs RAG **5424** (ratio 0.1136)

## Why this case

The May SSO sequence: migration, failed deploys, ticket, incident, logs. About 7 gold records. Fixed Top-K=5 is likely incomplete; K=10 may suffice.

## Question

What sequence of events caused Apex's authentication problems during the May migration?

## Gold answer

In May, mig_auth_sso changed AUTH_ISSUER to auth-v3. Apex production deployments dep_apex_fail_1 and dep_apex_fail_2 then failed with AUTH_401; ticket tkt_1001, incident inc_1001, and logs log_1001/log_1002 document the jwt issuer mismatch.

## Latency and retrieval

| metric | MARE (blind) | Conventional RAG |
| --- | --- | --- |
| end-to-end latency | **21989 ms** | **12190 ms** |
| agent turns | 4 | n/a |
| tool calls | 3 | n/a |
| LLM latency | 20975 ms | n/a |
| Mongo latency | 781 ms | n/a |
| retrieval operations | 1 | 1 |
| LLM tokens | 20859 | 2714 |
| stop reason | completed | rag_topk |
| answer correct | yes | yes |
| entity found | yes | yes |
| root cause found | yes | yes |
| evidence recall vs gold (citations) | 0.143 | 0.857 |
| evidence precision vs gold | 0.5 | 0.6 |
| gold evidence recall (retrieved) | 0.143 | 0.857 |
| documents retrieved | 2 | 10 |
| required evidence | 7 | 7 |
| context efficiency | 0.588 | 0.535 |
| completeness groups | 3/3 | 3/3 |
| gold missed | deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, incidents:inc_1001, logs:log_1001, logs:log_1002, tickets:tkt_1001 | logs:log_1002 |

Persistent vector indexes (not per-query scan count): MARE searches the 616-node navigation index, then reads raw Mongo documents. RAG searches the 5424-chunk vector index and returns Top-K.

## RAG Top-K sweep

| variant | correct | gold recall | docs retrieved | completeness | ms |
| --- | --- | --- | --- | --- | --- |
| hybrid_10 | yes | 0.857 | 10 | 3/3 | 12190 |
| hybrid_20 | yes | 1.0 | 20 | 3/3 | 15677 |
| hybrid_5 | yes | 0.714 | 5 | 3/3 | 10534 |
| vector_10 | yes | 0.857 | 10 | 3/3 | 11943 |

### RAG answers by variant

**hybrid_10**

- May 10: The SSO migration completed and changed the issuer from https://auth-v2.apex.io to https://auth-v3.apex.io, requiring clients to update AUTH_ISSUER; the legacy issuer would reject tokens. [mig_auth_sso]
- After the cutover, Apex’s deployer/config still had a stale AUTH_ISSUER pointing at auth-v2 (root cause). [inc_1001]
- May 11, 09:15–09:27: The auth-service deployment failed with AUTH_401; logs show a JWT issuer mismatch (expected v3, got v2). [dep_apex_fail_1] [log_1001]
- May 11, 10:00: A ticket was opened reporting production deploys failing with AUTH_401 since the SSO migration. [tkt_1001]
- May 12, 14:02–14:14: A billing-worker deployment also failed with AUTH_401 as auth-service returned 401 during rollout. [dep_apex_fail_2]

In short: the SSO issuer cutover to v3 happened, but Apex deployments continued using the old v2 AUTH_ISSUER, causing token validation failures and 401s. [mig_auth_sso] [inc_1001] [dep_apex_fail_1] [log_1001] [dep_apex_fail_2] [tkt_1001]

**hybrid_20**

- May 10: SSO migration completed and changed the issuer from https://auth-v2.apex.io to https://auth-v3.apex.io; clients were required to update AUTH_ISSUER or the legacy issuer would reject tokens (mig_auth_sso).
- May 11: First prod deploy after the cutover failed with AUTH_401; logs showed a JWT issuer mismatch—expected v3 but received v2. A ticket reported deploys failing right after the SSO migration (dep_apex_fail_1; log_1001; tkt_1001).
- May 12: Another prod deploy failed with AUTH_401; the deployer service account was still validating against AUTH_ISSUER https://auth-v2.apex.io (dep_apex_fail_2; log_1002).
- Root cause: A stale AUTH_ISSUER configuration still pointed at auth-v2 after the SSO issuer cutover, causing authentication failures during deployments (inc_1001).

**hybrid_5**

- May 10: SSO migration completed, changing the AUTH_ISSUER from https://auth-v2.apex.io to https://auth-v3.apex.io; legacy issuer would reject tokens if not updated [migrations mig_auth_sso].
- Post-cutover: Apex’s deployer/config still pointed to the old issuer (stale AUTH_ISSUER) [incidents inc_1001].
- May 11: First prod deploy failed in auth-service with AUTH_401 and “unauthorized issuer” during token validation [deployments dep_apex_fail_1]. A ticket reported prod deploys failing after the SSO migration [tickets tkt_1001].
- May 12: Another prod deploy failed with AUTH_401 as auth-service returned 401 during rollout [deployments dep_apex_fail_2].
- Root cause: stale AUTH_ISSUER still pointing at auth-v2 after the issuer cutover [incidents inc_1001; migrations mig_auth_sso].

**vector_10**

- May 10: SSO migration completed; the issuer changed to https://auth-v3.apex.io and clients were required to update AUTH_ISSUER. [migrations mig_auth_sso]
- After the cutover, Apex’s deployer/config still pointed AUTH_ISSUER at https://auth-v2.apex.io (stale setting). [incidents inc_1001]
- May 11: A prod deploy of auth-service failed with AUTH_401; logs showed a JWT issuer mismatch (expected v3, got v2). A ticket was opened noting deploy failures starting right after the SSO migration. [deployments dep_apex_fail_1; logs log_1001; tickets tkt_1001]
- May 12: A subsequent prod deploy of billing-worker also failed with AUTH_401 during rollout. [deployments dep_apex_fail_2]
- Root cause: stale AUTH_ISSUER left on auth-v2 after the SSO issuer cutover, causing token validation failures. [incidents inc_1001; migrations mig_auth_sso]

## MARE answer (blind)

- May 10 migration to platform-3.0 changed the SSO issuer and required clients to switch AUTH_ISSUER from https://auth-v2.apex.io to https://auth-v3.apex.io; the legacy issuer would reject tokens (mare_demo.migrations:mig_auth_sso).
- Apex Logistics still had its SSO issuer set to https://auth-v2.apex.io (mare_demo.customers:cust_007).
- Consequently, after the migration, Apex continued using the legacy issuer and its tokens were rejected, causing authentication failures (mare_demo.migrations:mig_auth_sso; mare_demo.customers:cust_007).

### Hypothesis

_(none)_

### Claims

_(none)_

### Citations

- `mare_demo.migrations:mig_auth_sso`
- `mare_demo.customers:cust_007`

Gold hits: migrations:mig_auth_sso
Missed gold: deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, incidents:inc_1001, logs:log_1001, logs:log_1002, tickets:tkt_1001

## RAG answer

- May 10: The SSO migration completed and changed the issuer from https://auth-v2.apex.io to https://auth-v3.apex.io, requiring clients to update AUTH_ISSUER; the legacy issuer would reject tokens. [mig_auth_sso]
- After the cutover, Apex’s deployer/config still had a stale AUTH_ISSUER pointing at auth-v2 (root cause). [inc_1001]
- May 11, 09:15–09:27: The auth-service deployment failed with AUTH_401; logs show a JWT issuer mismatch (expected v3, got v2). [dep_apex_fail_1] [log_1001]
- May 11, 10:00: A ticket was opened reporting production deploys failing with AUTH_401 since the SSO migration. [tkt_1001]
- May 12, 14:02–14:14: A billing-worker deployment also failed with AUTH_401 as auth-service returned 401 during rollout. [dep_apex_fail_2]

In short: the SSO issuer cutover to v3 happened, but Apex deployments continued using the old v2 AUTH_ISSUER, causing token validation failures and 401s. [mig_auth_sso] [inc_1001] [dep_apex_fail_1] [log_1001] [dep_apex_fail_2] [tkt_1001]

### Citations

- `mare_demo.incidents:inc_1001`
- `mare_demo.deployments:dep_apex_fail_2`
- `mare_demo.deployments:dep_apex_fail_1`
- `mare_demo.tickets:tkt_1001`
- `mare_demo.migrations:mig_auth_sso`
- `mare_demo.tickets:tkt_apex_apr`
- `mare_demo.deployments:dep_apex_apr`
- `mare_demo.incidents:inc_apex_apr`
- `mare_demo.tickets:tkt_apex_mar`
- `mare_demo.logs:log_1001`

Gold hits: deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, incidents:inc_1001, logs:log_1001, migrations:mig_auth_sso, tickets:tkt_1001
Missed gold: logs:log_1002

