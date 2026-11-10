# Distributed evidence — Northstar identity cutover

- generated: 2026-11-10T07:31:14.672553+00:00
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
| end-to-end latency | **11896 ms** | **17277 ms** |
| agent turns | 3 | n/a |
| tool calls | 3 | n/a |
| LLM latency | 10252 ms | n/a |
| Mongo latency | 1166 ms | n/a |
| retrieval operations | 1 | 1 |
| LLM tokens | 7293 | 3221 |
| stop reason | completed | rag_topk |
| answer correct | no | no |
| entity found | no | yes |
| root cause found | yes | no |
| evidence recall vs gold (citations) | 0.25 | 0.25 |
| evidence precision vs gold | 0.1 | 0.1 |
| gold evidence recall (retrieved) | 0.25 | 0.25 |
| documents retrieved | 10 | 10 |
| required evidence | 4 | 4 |
| context efficiency | 0.094 | 0.118 |
| completeness groups | 2/4 | 3/4 |
| gold missed | deployments:dep_ns_stale, logs:log_ns_jwt, tickets:tkt_ns_login | deployments:dep_ns_stale, logs:log_ns_jwt, migrations:mig_ns_identity |

Persistent vector indexes (not per-query scan count): MARE searches the 616-node navigation index, then reads raw Mongo documents. RAG searches the 5424-chunk vector index and returns Top-K.

## RAG Top-K sweep

| variant | correct | gold recall | docs retrieved | completeness | ms |
| --- | --- | --- | --- | --- | --- |
| hybrid_10 | no | 0.25 | 10 | 3/4 | 17277 |
| hybrid_20 | yes | 1.0 | 20 | 4/4 | 8036 |
| hybrid_5 | no | 0.25 | 5 | 3/4 | 9960 |
| vector_10 | no | 0.25 | 10 | 3/4 | 12539 |

### RAG answers by variant

**hybrid_10**

Because the platform’s SSO issuer was changed during the recent upgrade, any clients/services still configured with the old AUTH_ISSUER started failing token validation. Similar post-migration incidents were traced to a stale AUTH_ISSUER still pointing at https://auth-v2.apex.io after the cutover to https://auth-v3.apex.io, producing issuer-mismatch 401s; Northstar’s timing and symptoms align with this change ([tkt_ns_login], [mig_auth_sso], [inc_1001], [log_1001]).

**hybrid_20**

Because the identity cutover changed Northstar’s OIDC issuer, but the subsequent auth-service rollout kept the old authentication configuration, requests hit mixed configs and JWT validation failed with an issuer mismatch. That stale runtime config caused intermittent sign‑ins to be rejected after the platform work. [mig_ns_identity], [dep_ns_stale], [log_ns_jwt], [tkt_ns_login]

**hybrid_5**

Because the SSO migration changed the authentication issuer, but some services kept a stale AUTH_ISSUER pointing to the old auth-v2. That mismatch causes token validation to fail intermittently (“unauthorized issuer”), matching Northstar’s post-change login issues. [tkt_ns_login] [inc_1001] [dep_apex_fail_1]

**vector_10**

Because the SSO issuer changed during the recent platform work and any clients still pointing at the old issuer began having their tokens rejected. The migration required updating AUTH_ISSUER from https://auth-v2.apex.io to https://auth-v3.apex.io; incidents right after the cutover traced failures to a stale AUTH_ISSUER and “jwt issuer mismatch” 401s. Northstar’s intermittent login problems started immediately after that work, consistent with some components still using the old issuer. [tkt_ns_login], [mig_auth_sso], [inc_1001], [log_1001]

## MARE answer (blind)

Entity: Apex Logistics (customer_id: cust_007)

Why it started: The identity/SSO cutover changed the expected token issuer. A migration (mig_auth_sso) updated AUTH_ISSUER to https://auth-v3.apex.io and notes that the legacy issuer will reject tokens. Apex’s production deploys began failing with AUTH_401 immediately after that SSO migration (ticket tkt_1001). In short, clients that did not update their AUTH_ISSUER to the new v3 issuer had tokens rejected, causing the intermittent authentication failures.

### Hypothesis

Apex services were still using the old AUTH_ISSUER (https://auth-v2.apex.io) after the platform cutover, so some tokens were rejected by the new identity provider, producing AUTH_401 errors.

### Claims

- `c1` **supported** (0.90): The platform SSO endpoint was changed and AUTH_ISSUER was updated to https://auth-v3.apex.io.
- `c2` **supported** (0.92): Apex began seeing AUTH_401 failures after that SSO migration.
- `c3` **supported** (0.88): Clients still using the legacy issuer would have their tokens rejected, causing intermittent auth failures.

### Citations

- `mare_demo.migrations:mig_auth_sso`
- `mare_demo.tickets:tkt_1001`
- `mare_demo.migrations:mig_bill_wh`
- `mare_demo.migrations:mig_ns_identity`
- `mare_demo.migrations:mig_region_eu`
- `mare_demo.migrations:mig_aws_gcp`
- `mare_demo.migrations:mig_catalog_v4`
- `mare_demo.tickets:tkt_apex_mar`
- `mare_demo.tickets:tkt_apex_apr`
- `mare_demo.tickets:tkt_2001`

Gold hits: migrations:mig_ns_identity
Missed gold: deployments:dep_ns_stale, logs:log_ns_jwt, tickets:tkt_ns_login

## RAG answer

Because the platform’s SSO issuer was changed during the recent upgrade, any clients/services still configured with the old AUTH_ISSUER started failing token validation. Similar post-migration incidents were traced to a stale AUTH_ISSUER still pointing at https://auth-v2.apex.io after the cutover to https://auth-v3.apex.io, producing issuer-mismatch 401s; Northstar’s timing and symptoms align with this change ([tkt_ns_login], [mig_auth_sso], [inc_1001], [log_1001]).

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

