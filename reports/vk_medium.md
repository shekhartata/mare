# Variable K — medium (Apex May sequence)

- generated: 2026-11-10T07:33:01.349291+00:00
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
| end-to-end latency | **19463 ms** | **11806 ms** |
| agent turns | 4 | n/a |
| tool calls | 4 | n/a |
| LLM latency | 16657 ms | n/a |
| Mongo latency | 2203 ms | n/a |
| retrieval operations | 1 | 1 |
| LLM tokens | 8990 | 2743 |
| stop reason | completed | rag_topk |
| answer correct | yes | yes |
| entity found | yes | yes |
| root cause found | yes | yes |
| evidence recall vs gold (citations) | 0.286 | 0.857 |
| evidence precision vs gold | 0.167 | 0.6 |
| gold evidence recall (retrieved) | 0.286 | 0.857 |
| documents retrieved | 12 | 10 |
| required evidence | 7 | 7 |
| context efficiency | 0.209 | 0.535 |
| completeness groups | 3/3 | 3/3 |
| gold missed | deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, logs:log_1001, logs:log_1002, tickets:tkt_1001 | logs:log_1002 |

Persistent vector indexes (not per-query scan count): MARE searches the 616-node navigation index, then reads raw Mongo documents. RAG searches the 5424-chunk vector index and returns Top-K.

## RAG Top-K sweep

| variant | correct | gold recall | docs retrieved | completeness | ms |
| --- | --- | --- | --- | --- | --- |
| hybrid_10 | yes | 0.857 | 10 | 3/3 | 11806 |
| hybrid_20 | yes | 1.0 | 20 | 3/3 | 10185 |
| hybrid_5 | yes | 0.714 | 5 | 3/3 | 11907 |
| vector_10 | yes | 0.857 | 10 | 3/3 | 8771 |

### RAG answers by variant

**hybrid_10**

- May 10: SSO migration completed and the required issuer changed from https://auth-v2.apex.io to https://auth-v3.apex.io; legacy issuer would reject tokens (mig_auth_sso).
- Post-cutover, Apex’s deploy configuration still pointed AUTH_ISSUER at auth-v2 (inc_1001).
- May 11: A prod deploy failed with AUTH_401; logs showed “jwt issuer mismatch: expected https://auth-v3.apex.io, got https://auth-v2.apex.io.” A ticket was opened noting failures after the SSO migration (dep_apex_fail_1, log_1001, tkt_1001).
- May 12: A subsequent prod deploy also failed with AUTH_401 during rollout, confirming the stale issuer persisted (dep_apex_fail_2).
- Incident root cause: stale AUTH_ISSUER still pointing at auth-v2 after the issuer cutover (inc_1001).

**hybrid_20**

- May 10: The SSO migration cut over the issuer from https://auth-v2.apex.io to https://auth-v3.apex.io, and the legacy issuer would reject tokens unless clients updated AUTH_ISSUER accordingly [migrations mig_auth_sso].
- Post-cutover, Apex’s deployer/config still referenced the old issuer (stale AUTH_ISSUER pointing to auth‑v2), setting up authentication mismatches [incidents inc_1001].
- May 11: A prod deploy of auth-service failed with AUTH_401; logs show a JWT issuer mismatch (expected v3, got v2), and a ticket was opened noting failures started after the SSO migration [deployments dep_apex_fail_1; logs log_1001; tickets tkt_1001].
- May 12: Another prod deploy (billing-worker) failed with AUTH_401; deployer logs confirm token validation attempted against the old auth‑v2 issuer, reinforcing the stale configuration issue [deployments dep_apex_fail_2; logs log_1002].
- Root cause: stale AUTH_ISSUER still pointing at auth‑v2 after the SSO issuer cutover, causing repeated authentication failures during deployments [incidents inc_1001].

**hybrid_5**

- May 10: The SSO migration completed and changed the issuer to https://auth-v3.apex.io; legacy auth-v2 would reject tokens unless clients updated AUTH_ISSUER. [migrations mig_auth_sso]
- Post-cutover: Apex’s deployer kept a stale AUTH_ISSUER pointing at auth-v2. This became the root cause. [incidents inc_1001]
- May 11, 09:15: First prod deploy failed with AUTH_401; logs showed “unauthorized issuer.” [deployments dep_apex_fail_1]
- May 11, 10:00: Apex opened a ticket reporting prod deploy failures since the SSO migration. [tickets tkt_1001]
- May 11, 10:20: Incident declared; suspected stale AUTH_ISSUER on the deployer (later confirmed as root cause). [incidents inc_1001]
- May 12, 14:02: Another prod deploy failed with 401 during rollout. [deployments dep_apex_fail_2]

In short: the SSO issuer cutover required updating AUTH_ISSUER to auth-v3, but Apex’s deployer remained on auth-v2, causing token validation failures (401) in subsequent prod deployments. [migrations mig_auth_sso] [incidents inc_1001] [deployments dep_apex_fail_1] [deployments dep_apex_fail_2] [tickets tkt_1001]

**vector_10**

- May 10: The SSO migration completed and changed the issuer from https://auth-v2.apex.io to https://auth-v3.apex.io; clients were required to update AUTH_ISSUER or the legacy issuer would reject tokens [migrations mig_auth_sso].
- Post-cutover: Apex’s deployer/config kept a stale AUTH_ISSUER still pointing to auth-v2, identified as the root cause [incidents inc_1001].
- May 11: The first prod deployment failed with AUTH_401; logs show token validation failed due to issuer mismatch (expected v3, got v2) [deployments dep_apex_fail_1; logs log_1001]. A ticket reported prod deploy failures since the SSO migration on Friday [tickets tkt_1001].
- May 12: Another prod deployment failed with AUTH_401 during rollout, confirming ongoing impact [deployments dep_apex_fail_2].

In short: SSO issuer cutover → AUTH_ISSUER not updated (still v2) → subsequent prod deploys returned 401s due to issuer mismatch [migrations mig_auth_sso; incidents inc_1001; deployments dep_apex_fail_1; logs log_1001; deployments dep_apex_fail_2; tickets tkt_1001].

## MARE answer (blind)

Apex Logistics (cust_007): The May migration replaced the SSO issuer; some deployments kept the old issuer and began failing authentication.

Sequence of events (supported by docs):
1) 2024-05-10 — Migration mig_auth_sso moved Apex from platform-2.4 → platform-3.0 and changed the AUTH_ISSUER to https://auth-v3.apex.io (config change: AUTH_ISSUER set to https://auth-v3.apex.io). (mare_demo.migrations:mig_auth_sso)
2) After the cutover, several production deployments continued using the legacy AUTH_ISSUER (https://auth-v2.apex.io). Those stale configurations caused incoming tokens to be rejected against the new issuer, producing widespread auth failures. An incident was opened (inc_1001) describing multiple production deployments failing authentication and identifying the root cause as stale AUTH_ISSUER still pointing at auth-v2. (mare_demo.incidents:inc_1001)

Impact: production deployments failed to authenticate until deployers updated their AUTH_ISSUER to the new https://auth-v3.apex.io.

### Hypothesis

_(none)_

### Claims

- `c1` **supported** (0.90): Migration changed SSO issuer to https://auth-v3.apex.io
- `c2` **supported** (0.95): Auth failures were caused by stale AUTH_ISSUER still pointing at auth-v2

### Citations

- `mare_demo.migrations:mig_auth_sso`
- `mare_demo.incidents:inc_1001`
- `mare_demo.incidents:inc_apex_mar`
- `mare_demo.incidents:inc_apex_apr`
- `mare_demo.incidents:inc_20026`
- `mare_demo.incidents:inc_20074`
- `mare_demo.deployments:dep_n_0045`
- `mare_demo.deployments:dep_n_0119`
- `mare_demo.deployments:dep_n_0355`
- `mare_demo.deployments:dep_apex_mar`
- `mare_demo.deployments:dep_apex_apr`
- `mare_demo.deployments:dep_n_0374`

Gold hits: incidents:inc_1001, migrations:mig_auth_sso
Missed gold: deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, logs:log_1001, logs:log_1002, tickets:tkt_1001

## RAG answer

- May 10: SSO migration completed and the required issuer changed from https://auth-v2.apex.io to https://auth-v3.apex.io; legacy issuer would reject tokens (mig_auth_sso).
- Post-cutover, Apex’s deploy configuration still pointed AUTH_ISSUER at auth-v2 (inc_1001).
- May 11: A prod deploy failed with AUTH_401; logs showed “jwt issuer mismatch: expected https://auth-v3.apex.io, got https://auth-v2.apex.io.” A ticket was opened noting failures after the SSO migration (dep_apex_fail_1, log_1001, tkt_1001).
- May 12: A subsequent prod deploy also failed with AUTH_401 during rollout, confirming the stale issuer persisted (dep_apex_fail_2).
- Incident root cause: stale AUTH_ISSUER still pointing at auth-v2 after the issuer cutover (inc_1001).

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

