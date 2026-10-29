# Variable K — medium (Apex May sequence)

- generated: 2026-10-29T13:29:31.302639+00:00
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
| end-to-end latency | **35912 ms** | **9885 ms** |
| agent turns | 6 | n/a |
| tool calls | 7 | n/a |
| LLM latency | 27764 ms | n/a |
| Mongo latency | 6441 ms | n/a |
| retrieval operations | 3 | 1 |
| LLM tokens | 19312 | 2569 |
| stop reason | completed | rag_topk |
| answer correct | yes | yes |
| entity found | yes | yes |
| root cause found | yes | yes |
| evidence recall vs gold (citations) | 0.286 | 0.857 |
| evidence precision vs gold | 0.286 | 0.6 |
| gold evidence recall (retrieved) | 0.286 | 0.857 |
| documents retrieved | 7 | 10 |
| required evidence | 7 | 7 |
| context efficiency | 0.315 | 0.535 |
| completeness groups | 3/3 | 3/3 |
| gold missed | deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, logs:log_1001, logs:log_1002, tickets:tkt_1001 | logs:log_1002 |

Persistent vector indexes (not per-query scan count): MARE searches the 616-node navigation index, then reads raw Mongo documents. RAG searches the 5424-chunk vector index and returns Top-K.

## RAG Top-K sweep

| variant | correct | gold recall | docs retrieved | completeness | ms |
| --- | --- | --- | --- | --- | --- |
| hybrid_10 | yes | 0.857 | 10 | 3/3 | 9885 |
| hybrid_20 | yes | 1.0 | 20 | 3/3 | 7479 |
| hybrid_5 | yes | 0.714 | 5 | 3/3 | 9133 |
| vector_10 | yes | 0.857 | 10 | 3/3 | 11125 |

### RAG answers by variant

**hybrid_10**

- May 10: SSO migration completed; AUTH_ISSUER changed from https://auth-v2.apex.io to https://auth-v3.apex.io and the legacy issuer would reject tokens [migrations mig_auth_sso].
- May 11: First prod deploy post-cutover failed with AUTH_401; logs showed a JWT issuer mismatch (expected v3, got v2), indicating deployments were still using the old issuer [deployments dep_apex_fail_1; logs log_1001].
- May 11: Support ticket opened noting prod deploys failing after the SSO migration [tickets tkt_1001].
- May 11: Incident raised; root cause identified as a stale AUTH_ISSUER still pointing to auth‑v2 after the issuer cutover [incidents inc_1001].
- May 12: Another prod deploy failed with AUTH_401 during rollout, confirming the ongoing stale-config issue [deployments dep_apex_fail_2].

In short: the SSO issuer was cut over to v3, but Apex’s deployer/services kept AUTH_ISSUER set to v2, causing JWT issuer mismatches and repeated AUTH_401 failures after the migration [migrations mig_auth_sso; incidents inc_1001; deployments dep_apex_fail_1; logs log_1001; deployments dep_apex_fail_2].

**hybrid_20**

- May 10: SSO migration mig_auth_sso completed and changed the issuer from https://auth-v2.apex.io to https://auth-v3.apex.io; clients were required to update AUTH_ISSUER or legacy issuer would reject tokens [migrations mig_auth_sso].
- May 11: First prod deploy (dep_apex_fail_1) failed with AUTH_401; logs show jwt issuer mismatch (expected v3, got v2). A ticket was opened noting failures started after the SSO migration [deployments dep_apex_fail_1; logs log_1001; tickets tkt_1001].
- May 11: Incident opened identifying a suspected stale AUTH_ISSUER on the deployer; root cause recorded as AUTH_ISSUER still pointing at auth-v2 after the issuer cutover [incidents inc_1001].
- May 12: Another prod deploy (dep_apex_fail_2) failed with AUTH_401; deployer logs confirm it was validating against AUTH_ISSUER https://auth-v2.apex.io, evidencing the stale config [deployments dep_apex_fail_2; logs log_1002].

In short: the SSO issuer cut over to v3, but Apex’s deployer/auth config kept a stale AUTH_ISSUER pointing to v2, causing token validation failures (401) on subsequent deployments [migrations mig_auth_sso; incidents inc_1001; deployments dep_apex_fail_1; logs log_1001; deployments dep_apex_fail_2; logs log_1002; tickets tkt_1001].

**hybrid_5**

- May 10: SSO migration completed; AUTH_ISSUER was changed from https://auth-v2.apex.io to https://auth-v3.apex.io and the legacy issuer would reject tokens [mig_auth_sso].
- Post-cutover: The deployer still had a stale AUTH_ISSUER pointing to auth-v2 (root cause) [inc_1001].
- May 11: Prod deploy of auth-service failed with AUTH_401 — “token validation failed: unauthorized issuer” [dep_apex_fail_1]. A ticket was opened noting prod deploys failing after the SSO migration [tkt_1001].
- May 12: Another prod deploy (billing-worker) failed with AUTH_401 during rollout [dep_apex_fail_2].

In short, the issuer cutover to v3 combined with a stale AUTH_ISSUER still set to v2 caused the authentication failures during and after the May migration [mig_auth_sso][inc_1001][dep_apex_fail_1][dep_apex_fail_2][tkt_1001].

**vector_10**

- May 10: SSO migration completed; issuer changed from https://auth-v2.apex.io to https://auth-v3.apex.io and clients were required to update AUTH_ISSUER accordingly [migrations mig_auth_sso].
- Post-cutover: Apex’s deployer/service kept a stale AUTH_ISSUER still pointing to auth-v2 [incidents inc_1001].
- May 11 09:15–09:27: First prod deploy failed (AUTH_401); logs showed “jwt issuer mismatch: expected https://auth-v3.apex.io, got https://auth-v2.apex.io” [deployments dep_apex_fail_1; logs log_1001].
- May 11 10:00: Ticket opened noting all prod deploys failing with AUTH_401 after the SSO migration [tickets tkt_1001].
- May 12 14:02–14:14: Another prod deploy failed with AUTH_401 during rollout [deployments dep_apex_fail_2].
- Root cause: Stale AUTH_ISSUER still pointing at auth-v2 after the issuer cutover to v3 [incidents inc_1001; migrations mig_auth_sso].

## MARE answer (blind)

- 2024-05-10 08:00–11:30: Platform migration mig_auth_sso completed, changing the SSO endpoint and requiring clients to update AUTH_ISSUER from https://auth-v2.apex.io to https://auth-v3.apex.io; legacy issuer would reject tokens (notes: “Clients MUST update AUTH_ISSUER… Legacy issuer will reject tokens.”; config_changes.AUTH_ISSUER: https://auth-v3.apex.io) (mare_demo.migrations:mig_auth_sso).
- Apex Logistics was still configured to the legacy issuer (sso_issuer: https://auth-v2.apex.io) (mare_demo.customers:cust_007), and the incident confirms the deployer had a “stale AUTH_ISSUER still pointing at auth-v2 after SSO issuer cutover” (mare_demo.incidents:inc_1001).
- 2024-05-11 10:20: Multiple production deployments failed authentication “after mig_auth_sso,” leading to sev-1 incident inc_1001 (“Auth failures post SSO migration”; related_deployment_ids: dep_apex_fail_1, dep_apex_fail_2; root_cause: stale AUTH_ISSUER pointing at auth-v2) (mare_demo.incidents:inc_1001).

In short: the migration changed the SSO issuer (to https://auth-v3.apex.io) (mare_demo.migrations:mig_auth_sso), Apex remained on the legacy issuer (https://auth-v2.apex.io) (mare_demo.customers:cust_007), and post-migration deployments then failed authentication due to the stale AUTH_ISSUER (mare_demo.incidents:inc_1001).

### Hypothesis

_(none)_

### Claims

- `c1` **supported** (0.90): Platform migration changed SSO issuer and required clients to update AUTH_ISSUER
- `c2` **supported** (0.90): Apex (cust_007) remained configured with the legacy SSO issuer before the cutover
- `c3` **supported** (0.95): Post-migration production deployments failed authentication because of stale AUTH_ISSUER

### Citations

- `mare_demo.migrations:mig_auth_sso`
- `mare_demo.customers:cust_007`
- `mare_demo.incidents:inc_1001`
- `mare_demo.incidents:inc_20074`
- `mare_demo.incidents:inc_apex_mar`
- `mare_demo.incidents:inc_20026`
- `mare_demo.incidents:inc_apex_apr`

Gold hits: incidents:inc_1001, migrations:mig_auth_sso
Missed gold: deployments:dep_apex_fail_1, deployments:dep_apex_fail_2, logs:log_1001, logs:log_1002, tickets:tkt_1001

## RAG answer

- May 10: SSO migration completed; AUTH_ISSUER changed from https://auth-v2.apex.io to https://auth-v3.apex.io and the legacy issuer would reject tokens [migrations mig_auth_sso].
- May 11: First prod deploy post-cutover failed with AUTH_401; logs showed a JWT issuer mismatch (expected v3, got v2), indicating deployments were still using the old issuer [deployments dep_apex_fail_1; logs log_1001].
- May 11: Support ticket opened noting prod deploys failing after the SSO migration [tickets tkt_1001].
- May 11: Incident raised; root cause identified as a stale AUTH_ISSUER still pointing to auth‑v2 after the issuer cutover [incidents inc_1001].
- May 12: Another prod deploy failed with AUTH_401 during rollout, confirming the ongoing stale-config issue [deployments dep_apex_fail_2].

In short: the SSO issuer was cut over to v3, but Apex’s deployer/services kept AUTH_ISSUER set to v2, causing JWT issuer mismatches and repeated AUTH_401 failures after the migration [migrations mig_auth_sso; incidents inc_1001; deployments dep_apex_fail_1; logs log_1001; deployments dep_apex_fail_2].

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

