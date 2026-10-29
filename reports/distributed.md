# Distributed evidence — Northstar identity cutover

- generated: 2026-10-29T13:27:31.443520+00:00
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
| end-to-end latency | **43466 ms** | **10528 ms** |
| agent turns | 9 | n/a |
| tool calls | 8 | n/a |
| LLM latency | 34950 ms | n/a |
| Mongo latency | 6506 ms | n/a |
| retrieval operations | 5 | 1 |
| LLM tokens | 29031 | 2465 |
| stop reason | completed | rag_topk |
| answer correct | yes | no |
| entity found | yes | yes |
| root cause found | yes | no |
| evidence recall vs gold (citations) | 0.75 | 0.25 |
| evidence precision vs gold | 0.12 | 0.1 |
| gold evidence recall (retrieved) | 0.75 | 0.25 |
| documents retrieved | 25 | 10 |
| required evidence | 4 | 4 |
| context efficiency | 0.142 | 0.118 |
| completeness groups | 4/4 | 3/4 |
| gold missed | tickets:tkt_ns_login | deployments:dep_ns_stale, logs:log_ns_jwt, migrations:mig_ns_identity |

Persistent vector indexes (not per-query scan count): MARE searches the 616-node navigation index, then reads raw Mongo documents. RAG searches the 5424-chunk vector index and returns Top-K.

## RAG Top-K sweep

| variant | correct | gold recall | docs retrieved | completeness | ms |
| --- | --- | --- | --- | --- | --- |
| hybrid_10 | no | 0.25 | 10 | 3/4 | 10528 |
| hybrid_20 | yes | 1.0 | 20 | 4/4 | 8188 |
| hybrid_5 | no | 0.25 | 5 | 3/4 | 8451 |
| vector_10 | no | 0.25 | 10 | 2/4 | 14231 |

### RAG answers by variant

**hybrid_10**

Northstar’s logins started failing intermittently because the platform’s SSO issuer was cut over from https://auth-v2.apex.io to https://auth-v3.apex.io, but some components were still using the old AUTH_ISSUER. That issuer mismatch causes 401s, matching the post-change timing and symptoms. Similar incidents identify the root cause as a stale AUTH_ISSUER after the SSO migration, with logs showing “expected … v3, got … v2.” [tkt_ns_login] [mig_auth_sso] [inc_1001] [log_1001]

**hybrid_20**

Because the identity cutover changed Northstar’s OIDC issuer URL, but the June 4 rollout left some auth-service instances running with the previous auth configuration. That stale config caused issuer mismatches during token validation, so logins would pass or fail depending on which instance handled the request, producing intermittent failures. [mig_ns_identity], [dep_ns_stale], [log_ns_jwt], [tkt_ns_login]

**hybrid_5**

Because the SSO cutover changed the authentication issuer, but some components still had a stale AUTH_ISSUER pointing to the old issuer (auth‑v2). That mismatch caused token validation to fail with “unauthorized issuer,” leading to the intermittent sign-in failures Northstar reported after the platform work. [tkt_ns_login], [inc_1001], [dep_apex_fail_1]

**vector_10**

Because the SSO issuer was changed during the recent platform upgrade, any client/service still configured with the old AUTH_ISSUER intermittently fails token validation. After the cutover from https://auth-v2.apex.io to https://auth-v3.apex.io, stale configs trigger 401 “issuer mismatch” errors, which explains the come-and-go sign‑in failures when traffic hits mixed/partially updated components [mig_auth_sso], [inc_1001], [log_1001], [dep_apex_fail_1].

## MARE answer (blind)

Northstar’s identity platform was cut over from identity-2.1 to identity-3.0, which changed the OIDC issuer to https://id.northstar.test/realms/prod (config_changes.OIDC_ISSUER: https://id.northstar.test/realms/prod; notes: “Update relying parties before the next release.”) (mare_demo.migrations:mig_ns_identity). After the cutover, the auth-service began rejecting tokens with “token validation rejected because issuer did not match expected value,” indicating at least one relying party was still configured with the old issuer (service: auth-service, deployment_id: dep_ns_stale) (mare_demo.logs:log_ns_jwt).

### Hypothesis

_(none)_

### Claims

_(none)_

### Citations

- `mare_demo.migrations:mig_ns_identity`
- `mare_demo.logs:log_ns_jwt`
- `mare_demo.deployments:dep_ns_stale`
- `mare_demo.customers:cust_012`
- `mare_demo.incidents:inc_20017`
- `mare_demo.incidents:inc_20030`
- `mare_demo.incidents:inc_20054`
- `mare_demo.incidents:inc_2001`
- `mare_demo.incidents:inc_20089`
- `mare_demo.incidents:inc_20123`
- `mare_demo.migrations:mig_bill_wh`
- `mare_demo.migrations:mig_n_010`
- `mare_demo.logs:log_n_02628`
- `mare_demo.logs:log_n_03967`
- `mare_demo.logs:log_n_02616`
- `mare_demo.logs:log_n_00408`
- `mare_demo.logs:log_n_01417`
- `mare_demo.logs:log_n_03835`
- `mare_demo.logs:log_n_03825`
- `mare_demo.logs:log_n_01580`
- `mare_demo.deployments:dep_n_0100`
- `mare_demo.deployments:dep_n_0262`
- `mare_demo.deployments:dep_n_0250`
- `mare_demo.deployments:dep_ns_bill_1`
- `mare_demo.deployments:dep_n_0134`

Gold hits: deployments:dep_ns_stale, logs:log_ns_jwt, migrations:mig_ns_identity
Missed gold: tickets:tkt_ns_login

## RAG answer

Northstar’s logins started failing intermittently because the platform’s SSO issuer was cut over from https://auth-v2.apex.io to https://auth-v3.apex.io, but some components were still using the old AUTH_ISSUER. That issuer mismatch causes 401s, matching the post-change timing and symptoms. Similar incidents identify the root cause as a stale AUTH_ISSUER after the SSO migration, with logs showing “expected … v3, got … v2.” [tkt_ns_login] [mig_auth_sso] [inc_1001] [log_1001]

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

