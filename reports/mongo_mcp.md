# MARE vs Mongo MCP

- generated: 2026-10-29T13:22:22.806703+00:00
- answering model: `gpt-5`
- agent model: `gpt-5-mini`

Same demo questions as [README.md](README.md). **Mongo MCP** is a schema-blind agent with `list_databases` / `list_collections` / `collection_schema` / `find` / `count` only — no `navigation_nodes`, no `related_nodes`. MARE and RAG numbers are reused from `comparison.json` when present.

| case | MARE | MCP | RAG | MARE ms | MCP ms | RAG ms | MARE tok | MCP tok | MARE tools | MCP tools |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Simple lookup | yes | yes | yes | 19070 | 14982 | 8207 | 5013 | 4446 | 3 | 5 |
| Named multi-hop | yes | yes | yes | 62810 | 35294 | 10576 | 24922 | 20678 | 8 | 11 |
| Bridge (unnamed entity) | yes | no | no | 51100 | 28343 | 8279 | 26176 | 19309 | 8 | 11 |
| Aggregation (count) | yes | no | no | 25707 | 16140 | 5523 | 6636 | 6164 | 3 | 6 |
| Negative (absence) | yes | yes | no | 24323 | 17982 | 5817 | 8863 | 5093 | 4 | 5 |
| Distributed evidence | yes | no | no | 43466 | 27782 | 10528 | 29031 | 18114 | 8 | 11 |
| Variable K — small | no | no | yes | 19981 | 25187 | 7119 | 9628 | 17894 | 4 | 11 |
| Variable K — medium | yes | no | yes | 35912 | 31369 | 9885 | 19312 | 16925 | 7 | 11 |
| Variable K — deep | no | no | yes | 72184 | 29964 | 16643 | 42225 | 17255 | 10 | 11 |

## Answers

### Simple lookup

cust_007 is on the enterprise tier (mare_demo.customers:cust_007).

stop=completed turns=6 tools=5 tokens=4446

### Named multi-hop

Most likely root cause: The mig_auth_sso migration changed the SSO issuer to https://auth-v3.apex.io and required clients to update AUTH_ISSUER, but Apex Logistics remained configured with the old issuer (https://auth-v2.apex.io). As a result, token validation failed with “unauthorized issuer,” causing AUTH_401 deployment failures.

Evidence:
- Migration notes: “SSO endpoint changed. Clients MUST update AUTH_ISSUER from https://auth-v2.apex.io to https://auth-v3.apex.io. Legacy issuer will reject tokens.” (mare_demo.migrations:mig_auth_sso)
- Apex Logistics customer record still shows sso_issuer=https://auth-v2.apex.io after the migration (mare_demo.customers:cust_007)
- Post-migration deployments failed with AUTH_401 and logs indicating “token validation failed: unauthorized issuer” (mare_demo.deployments:dep_apex_fail_1) and “auth-service returned 401 during rollout” (mare_demo.deployments:dep_apex_fail_2), both tied to migration_id=mig_auth_sso.

stop=max_agent_turns turns=12 tools=11 tokens=20678

### Bridge (unnamed entity)

Insufficient evidence. The only matching customer is Apex Logistics (enterprise, us-east-1, AM: Elena Rossi) [mare_demo.customers:cust_007], but the provided data contains no deployment or incident details for May 2024, so a root cause cannot be determined from the available Mongo record.

stop=max_agent_turns turns=12 tools=11 tokens=19309

### Aggregation (count)

From the provided records, 3 customers are on the enterprise tier (mare_demo.customers:cust_002; mare_demo.customers:cust_004; mare_demo.customers:cust_005). The evidence is incomplete, so the total across all mare_demo customers cannot be confirmed.

stop=completed turns=7 tools=6 tokens=6164

### Negative (absence)

No. A query of mare_demo.incidents for customer_id "cust_004" with opened_at between 2024-04-01 and 2024-04-30 returned no results (mare_demo.unknown:draft). Note: this is based on a query result summary rather than specific incident documents.

stop=completed turns=6 tools=5 tokens=5093

### Distributed evidence

After the SSO issuer cutover, the deployer was still configured with a stale AUTH_ISSUER pointing to the old auth-v2 issuer, which led to authentication failures in production deployments (mare_demo.incidents:inc_1001). Note: the record cites multiple production deployments failing authentication but doesn’t explicitly describe the failures as “intermittent” (mare_demo.incidents:inc_1001).

stop=max_agent_turns turns=12 tools=11 tokens=18114

### Variable K — small

A stale AUTH_ISSUER configuration still pointed to auth-v2 after the SSO issuer cutover, causing authentication failures (mare_demo.incidents:inc_1001).

stop=max_agent_turns turns=12 tools=11 tokens=17894

### Variable K — medium

Insufficient evidence. No migration, deployment, incident, or log records for Apex in May were found in the searched collections, so a sequence of events cannot be reconstructed from the available data (mare_demo.unknown:draft).

stop=max_agent_turns turns=12 tools=11 tokens=16925

### Variable K — deep

- The only provided evidence is a customer record showing Apex Logistics (customer_id cust_007) with an SSO issuer configured at https://auth-v2.apex.io (mare_demo.customers:cust_007).
- No incident, ticket, or authentication failure records for the last three months were provided, so recurring factors behind authentication failures and any evolution in the failure mode cannot be determined from the available data. Evidence is incomplete (mare_demo.customers:cust_007).

stop=max_agent_turns turns=12 tools=11 tokens=17255

## Reproduce

```bash
python scripts/run_comparison.py --mongo-mcp
```

Reuses MARE/RAG blobs already in `comparison.json`. Does not rewrite the per-case MARE vs RAG markdown.
