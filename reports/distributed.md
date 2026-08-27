# Distributed evidence — Northstar identity cutover

- generated: 2026-08-27T06:21:15.831897+00:00
- answer model: `gpt-5`
- agent model: `gpt-5-mini` (reasoning_effort=low)
- MARE mode: **blind** (schema_in_prompt=false)
- max_agent_turns: 10
- vector index: MARE **616** vs RAG **5424** (ratio 0.1136)

## Why this case

No single record states the cause. Ticket, migration, deployment, and log each hold one fragment. The question names Northstar but not issuer, JWT, or the migration id.

## Question

Why did Northstar begin experiencing intermittent authentication failures after recent platform changes?

## Gold answer

Northstar Payments (cust_012) kept the previous authentication configuration after the identity platform cutover (mig_ns_identity) set a new OIDC issuer. Token validation then rejected requests because the issuer did not match.

## Latency and retrieval

| metric | MARE (blind) | Conventional RAG |
| --- | --- | --- |
| end-to-end latency | **26866 ms** | **11719 ms** |
| agent turns | 5 | n/a |
| tool calls | 4 | n/a |
| LLM latency | 25619 ms | n/a |
| Mongo latency | 939 ms | n/a |
| retrieval operations | 2 | 1 |
| LLM tokens | 36345 | 2397 |
| stop reason | completed | rag_topk |
| answer correct | yes | no |
| entity found | yes | no |
| root cause found | yes | no |
| evidence recall vs gold (citations) | 0.5 | 0.25 |
| evidence precision vs gold | 0.125 | 0.1 |
| gold evidence recall (retrieved) | 0.5 | 0.25 |
| documents retrieved | 16 | 10 |
| required evidence | 4 | 4 |
| context efficiency | 0.165 | 0.118 |
| completeness groups | 4/4 | 2/4 |
| gold missed | logs:log_ns_jwt, tickets:tkt_ns_login | deployments:dep_ns_stale, logs:log_ns_jwt, migrations:mig_ns_identity |

Persistent vector indexes (not per-query scan count): MARE searches the 616-node navigation index, then reads raw Mongo documents. RAG searches the 5424-chunk vector index and returns Top-K.

## RAG Top-K sweep

| variant | correct | gold recall | docs retrieved | completeness | ms |
| --- | --- | --- | --- | --- | --- |
| hybrid_10 | no | 0.25 | 10 | 2/4 | 11719 |
| hybrid_20 | yes | 1.0 | 20 | 4/4 | 9099 |
| hybrid_5 | no | 0.25 | 5 | 3/4 | 11654 |
| vector_10 | no | 0.25 | 10 | 2/4 | 16753 |

### RAG answers by variant

**hybrid_10**

Because the SSO issuer endpoint changed during the recent platform work, any clients or services that still had AUTH_ISSUER pointing to the old issuer began failing token validation. This exact pattern (stale AUTH_ISSUER left on auth-v2 after the cutover to auth-v3) caused 401s with “issuer mismatch” in other post-migration incidents; if only some components were updated, sign-in would fail only sometimes, appearing intermittent. [tkt_ns_login] [migrations mig_auth_sso] [incidents inc_1001] [logs log_1001]

**hybrid_20**

Northstar’s identity cutover changed the expected OIDC issuer, but the subsequent auth-service/storefront rollout retained the previous auth configuration in its runtime map. This left some instances validating tokens against the old issuer, producing JWT issuer mismatch errors and causing intermittent sign‑in failures. (tkt_ns_login; mig_ns_identity; dep_ns_stale; log_ns_jwt)

**hybrid_5**

Because after the SSO issuer cutover, some services still had a stale AUTH_ISSUER value (still pointing to auth‑v2). That issuer mismatch caused token validation to fail intermittently—seen as “unauthorized issuer” errors—lining up with Northstar’s reports after the recent platform work. [tkt_ns_login] [inc_1001] [dep_apex_fail_1]

**vector_10**

Because the platform’s SSO issuer changed in the recent upgrade, but some clients/services were still configured to use the old issuer. After the cutover to https://auth-v3.apex.io, any component still pointing at https://auth-v2.apex.io started rejecting tokens with issuer-mismatch 401s, leading to intermittent sign-in failures. This exact pattern was seen right after the SSO migration and traced to a stale AUTH_ISSUER setting (jwt issuer mismatch). [migrations mig_auth_sso], [incidents inc_1001], [deployments dep_apex_fail_1], [logs log_1001], [tickets tkt_ns_login]

## MARE answer (blind)

Northstar’s identity platform was cut over to a new OIDC issuer (https://id.northstar.test/realms/prod), with a note to update relying parties before the next release (mare_demo.migrations:mig_ns_identity). Immediately after, a rollout “kept the previous authentication configuration in the runtime map,” leaving components still using the old auth settings (mare_demo.deployments:dep_ns_stale). This mismatch between the new issuer and stale auth configuration caused intermittent authentication failures until configs were aligned. Evidence doesn’t include explicit failure logs, but it documents the issuer change and the stale runtime config that would produce such symptoms (mare_demo.migrations:mig_ns_identity; mare_demo.deployments:dep_ns_stale).

### Hypothesis

Mismatched OIDC issuer/config between cutover and incomplete rollout caused intermittent auth failures.

### Claims

- `c1` **supported** (0.90): Identity platform cutover changed OIDC issuer URL.
- `c2` **supported** (0.90): Auth-service rollout retained old authentication configuration in runtime map.
- `c3` **supported** (0.85): Mixed configurations produced intermittent authentication failures.

### Citations

- `mare_demo.migrations:mig_ns_identity`
- `mare_demo.deployments:dep_ns_stale`
- `mare_demo.customers:cust_012`
- `mare_demo.migrations:mig_bill_wh`
- `mare_demo.migrations:mig_n_010`
- `mare_demo.logs:log_n_02628`
- `mare_demo.logs:log_n_03820`
- `mare_demo.logs:log_n_03084`
- `mare_demo.logs:log_n_03336`
- `mare_demo.logs:log_n_02828`
- `mare_demo.logs:log_n_03661`
- `mare_demo.deployments:dep_n_0100`
- `mare_demo.deployments:dep_n_0262`
- `mare_demo.deployments:dep_n_0250`
- `mare_demo.deployments:dep_ns_bill_1`
- `mare_demo.deployments:dep_n_0134`

Gold hits: deployments:dep_ns_stale, migrations:mig_ns_identity
Missed gold: logs:log_ns_jwt, tickets:tkt_ns_login

## RAG answer

Because the SSO issuer endpoint changed during the recent platform work, any clients or services that still had AUTH_ISSUER pointing to the old issuer began failing token validation. This exact pattern (stale AUTH_ISSUER left on auth-v2 after the cutover to auth-v3) caused 401s with “issuer mismatch” in other post-migration incidents; if only some components were updated, sign-in would fail only sometimes, appearing intermittent. [tkt_ns_login] [migrations mig_auth_sso] [incidents inc_1001] [logs log_1001]

### Citations

- `mare_demo.tickets:tkt_ns_login`
- `mare_demo.incidents:inc_1001`
- `mare_demo.tickets:tkt_1001`
- `mare_demo.tickets:tkt_apex_apr`
- `mare_demo.deployments:dep_apex_fail_1`
- `mare_demo.deployments:dep_apex_fail_2`
- `mare_demo.tickets:tkt_apex_mar`
- `mare_demo.migrations:mig_auth_sso`
- `mare_demo.incidents:inc_apex_apr`
- `mare_demo.logs:log_1001`

Gold hits: tickets:tkt_ns_login
Missed gold: deployments:dep_ns_stale, logs:log_ns_jwt, migrations:mig_ns_identity

