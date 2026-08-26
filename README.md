# Mongo Adaptive Retrieval Engine (MARE)

MARE turns MongoDB from a passive RAG data source into an information environment an agent can **navigate**: find where the answer lives, then read the actual records.

Conventional RAG embeds every chunk and returns Top-K. MARE embeds only a small **navigation index** (618 vectors here vs 5424 RAG chunks) and lets the agent hop, filter, and count against live Mongo data.

This repository is the MVP described in `PRD — Mongo-Native Adaptive Retrieval Engine.md`.

## Should you use MARE or RAG?

| Question looks like | Use | Why |
| --- | --- | --- |
| "What tier is cust_007 on?" | RAG or a plain `find` | The ID is in the question. One search is enough, and it is faster. |
| "Why did cust_007 fail after mig_auth_sso?" | Either | Both IDs are named, so Top-K can scoop the whole story. |
| "Which enterprise customer managed by Elena Rossi broke in May?" | **MARE** | The entity is not named. Requires a lookup, then a hop to another collection. |
| "How many customers are on enterprise?" | **MARE** | The answer is a count over the collection, not a nearby chunk. |
| "Did Cedar have any April incidents?" | **MARE** | The answer is *nothing matched*. Top-K always returns something. |

MARE is **not faster** than RAG, and on questions that name the IDs it is not more complete either. It wins on questions Top-K cannot structurally answer.

---

## Quickstart

Python 3.12+ and a MongoDB Atlas cluster (tested on 8.0).

**1. Install**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

**2. Configure** — copy `.env.example` to `.env` and fill in:

```bash
MONGODB_URI=mongodb+srv://USER:PASSWORD@cluster0.xxxxx.mongodb.net/
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5              # final answer synthesis
OPENAI_MODEL_AGENT=gpt-5-mini   # tool loop
MARE_MAX_AGENT_TURNS=10
MARE_SCHEMA_IN_PROMPT=false     # keep false: agent must discover the schema itself
```

Without `OPENAI_API_KEY` a heuristic reasoner runs instead, which is enough for tests but not for real answers.

**3. Bootstrap** — seeds the demo data, builds the navigation hierarchy, and creates Atlas indexes. Takes a few minutes while Search indexes build.

```bash
python scripts/bootstrap.py
```

**4. Ask something**

```bash
uvicorn app.main:app --reload --port 8080

curl -s localhost:8080/ask -H 'Content-Type: application/json' \
  -d '{"question":"How many customers are on the enterprise subscription tier?"}'
```

That is it. `POST /ask/rag` runs the same question through conventional RAG for comparison.

---

## Integrating MARE

### HTTP API

| Endpoint | Purpose |
| --- | --- |
| `POST /ask` | Full agent retrieval loop. Returns a grounded answer with Mongo citations. |
| `POST /ask/rag` | Conventional Top-K RAG baseline, same question. |
| `GET /sessions/{id}` | Answer, claims, citations, stop reason. |
| `GET /sessions/{id}/traces` | Every navigation and retrieval step the agent took. |
| `GET /navigation/...` | Browse the hierarchy: databases, collections, nodes, children. |
| `GET /metrics/vectors` | Persistent vector footprint (MARE vs RAG). |
| `GET /health` | Atlas connectivity check. |

Pass `{"method": "legacy"}` to `/ask` to run the older Python state machine instead of the tool loop.

### MCP server

```bash
python -m app.mcp_server.server
```

Cursor `mcp.json`:

```json
{
  "mare": {
    "command": "python",
    "args": ["-m", "app.mcp_server.server"],
    "cwd": "/absolute/path/to/areProject",
    "env": {
      "MONGODB_URI": "...",
      "OPENAI_API_KEY": "..."
    }
  }
}
```

Tools exposed to a client agent:

| Tool | Purpose |
| --- | --- |
| `ask` | Full retrieval loop, one call |
| `search_information` | Find which neighborhood holds the answer |
| `retrieve_evidence` | Read raw documents for navigation node ids |
| `query_documents` / `read_documents` | Structured Mongo access |
| `lexical_search` / `semantic_search` / `hybrid_search` | Low-level navigation |
| `get_node` / `get_children` / `search_within` | Hierarchy walk |
| `list_databases` / `list_collections` | Catalog |

Authorization is never delegated to the model. Every read passes through `inject_tenant` server-side, so a model-supplied `tenant_id` cannot widen scope.

---

## Where MARE wins, case by case

Five cases, run end to end against Atlas. Each one below shows the actual prompt, so you can see what it is testing.

Two rules make these honest:

1. **The agent is schema-blind.** Its system prompt does not name any database, collection, or field. It has to discover `customers`, `deployments`, `subscription_tier` from the navigation index. Otherwise "MARE can count" would just mean "we told the model the schema."
2. **Bridge requires both hops.** Naming the customer is not enough; the answer must also reach the root cause.

### 1. Simple lookup — RAG's home turf

> **Prompt:** "What is customer cust_007's current subscription tier?"

The ID is in the question, so one search finds it. **Both are correct.** RAG is more than twice as fast (3.9s vs 9.0s). MARE's only edge is precision: it cites the one customer record, while RAG cites eight similar customers.

*Do not sell MARE on this case.*

### 2. Named multi-hop — still RAG's home turf

> **Prompt:** "Why did customer Apex Logistics (cust_007) begin experiencing deployment failures after migration mig_auth_sso, and what evidence supports the most likely root cause?"

The question names both the customer and the migration, so Top-K can scoop the migration, deploys, logs, and ticket in a single shot. **Both are correct**, and RAG actually cites *more* gold documents (recall 0.875 vs 0.375) and is faster.

*Also not a MARE win. Be upfront about it.*

### 3. Bridge — the entity is not named

> **Prompt:** "An enterprise customer in us-east-1 whose account manager is Elena Rossi started failing production deployments in May 2024. What is the most likely root cause?"

Nothing in that prompt says Apex, `cust_007`, SSO, or AUTH_401. Answering it requires two hops: find *who* matches the account manager, then find *what* broke in their deployments.

- **RAG: incorrect.** It pattern-matched vocabulary and answered "SSO migration causing AUTH_401" from a ticket, but never identified which customer. A similar-sounding chunk is not a hop.
- **MARE: correct.** It found Apex Logistics (`cust_007`), followed `related_nodes` into the deployments and migrations neighborhoods, and reported the real cause: `mig_auth_sso` changed `AUTH_ISSUER` from `auth-v2` to `auth-v3`, so tokens were rejected with AUTH_401.

This is the strongest case for MARE, because a plain `find` gets you the customer but not the cause.

### 4. Aggregation — the answer is a count

> **Prompt:** "How many customers in mare_demo are currently on the enterprise subscription tier?"

- **RAG: 8** — exactly its Top-K. It counted what it retrieved, not what exists.
- **MARE: 18** — the correct count, from a structured query.

Cleanest demo of the failure mode: chunk retrieval cannot count a collection.

### 5. Negative — proving nothing matched

> **Prompt:** "Did Cedar Systems (cust_004) have any incidents opened in April 2024?"

Both said "no," but only one grounded it.

- **RAG: incorrect.** It cited April incidents belonging to `cust_030`, `cust_047`, and `cust_033`. Top-K always returns something, so an absence claim has no evidence behind it.
- **MARE: correct.** It queried Cedar's own incidents and showed they fall in January, February, and June — no April.

### Results table

`gpt-5` answering, `gpt-5-mini` tool loop, 10-turn budget. "Informed" is the same run with the schema put back into the prompt, as a control.

| Case | MARE (blind) | MARE (informed) | RAG | Blind | Informed | RAG |
| --- | --- | --- | --- | --- | --- | --- |
| Simple lookup | yes | yes | yes | 9.0s | 8.5s | 3.9s |
| Named multi-hop | yes | yes | yes | 18.6s | 34.3s | 13.5s |
| **Bridge** | **yes** (entity + cause) | yes | **no** (cause, no entity) | 38.7s | 30.4s | 8.6s |
| **Aggregation** | **18** | 18 | **8** | 15.8s | 17.1s | 8.2s |
| **Negative** | **yes** (grounded) | yes | **no** (wrong customers) | 13.4s | 12.3s | 9.7s |

Honest caveats: RAG is faster in every single case. Blind and informed scored the same, which means the navigation index — not a leaked schema — is what carried the blind runs. Persistent vectors stay **618 vs 5424** (11%).

Full detail per case: [reports/README.md](reports/README.md).

### Reproduce it

```bash
python scripts/run_comparison.py              # schema-blind MARE vs RAG (default)
python scripts/run_comparison.py --informed   # control: schema in the prompt
python scripts/run_comparison.py --only bridge
python scripts/run_comparison.py --rescore    # re-score saved runs, no LLM calls
```

Writes `reports/README.md` plus one markdown file per case. Gold labels live in `benchmarks/gold.json`.

For the wider gold set (all 18 queries rather than these 5):

```bash
python scripts/run_benchmark.py
python scripts/run_benchmark.py --class complex_multihop
```

---

## How it works

```text
Question
  → Agent tool loop (gpt-5-mini), schema-blind by default
      search_information   find the neighborhood in the navigation index
      retrieve_evidence    read the raw Mongo documents
      query_documents      structured find, using only observed field names
      submit_answer        stop when the evidence is sufficient
  → Optional gpt-5 synthesis (when OPENAI_MODEL differs from the agent model)
  → Grounded answer with database.collection:document_id citations
```

Two design choices carry the whole approach:

**Vectors live on navigation nodes, not chunks.** A node describes a database, a collection, or a logical group (for example "deployments for cust_007") and *points at* raw documents via `source.filter` or `document_ids`. It never copies payloads. That is why 618 vectors replace 5424 chunks.

**Nodes hand back the schema and the next hop.** Each node returns its `database.collection`, a reusable filter, its important fields with examples, and `related_nodes` — sibling neighborhoods in *other* collections that share the same entity. That is what lets a schema-blind agent complete the bridge hop instead of stalling after the first lookup.

### MongoDB-native primitives

| Layer | Atlas feature |
| --- | --- |
| Lexical navigation | Atlas Search `$search` |
| Semantic navigation | Atlas Vector Search `$vectorSearch` with Automated Embedding (`voyage-4-lite`) |
| Hybrid | `$rankFusion` when available, otherwise reciprocal rank fusion |
| Structured retrieval | `find` / aggregation with mandatory tenant-scope injection |
| Retrieval state | `_agent_retrieval.evidence_sessions` + `retrieval_traces` |
| RAG baseline | `_rag_baseline.chunks`, same embedding model, for a fair vector count |

If Automated Embedding is unavailable on the cluster, MARE falls back to application-side embeddings (`OPENAI_EMBEDDING_MODEL`). The capability probe records which path is active.

### Data layout

| Database | Role |
| --- | --- |
| `mare_demo` | Untouched synthetic source: customers, tickets, deployments, migrations, incidents, logs |
| `_agent_retrieval` | `navigation_nodes`, `evidence_sessions`, `retrieval_traces`, `config` |
| `_rag_baseline` | `chunks` for conventional RAG |

The synthetic dataset contains 10 engineered causal stories whose evidence is deliberately split across collections. The Apex Logistics SSO story (`cust_007` / `mig_auth_sso`) is the one used in the bridge and multi-hop cases.

Nothing is exported. MongoDB stays the system of record, the navigation index, the search system, the evidence source, and the retrieval state store.

---

## Tests

```bash
pytest -q
```

Covers routing, best-first scoring, stopping, tenant injection, the synthetic stories, prompt hygiene (no schema leaks), `related_nodes` selection, and answer scoring. No Atlas connection required.

## Repository map

```text
app/
  indexing/     schema discovery, grouping, hierarchy
  search/       lexical, vector, hybrid, structured query, router, tool surface
  retrieval/    agent tool loop, legacy state machine, evidence ledger, stopping
  eval/         answer and citation scoring
  baseline/     chunk-everything RAG
  llm/          OpenAI + heuristic abstractions
  mcp_server/   FastMCP tools
  datagen/      synthetic multi-hop dataset
  api/          FastAPI routes
scripts/        seed, indexes, bootstrap, benchmark, comparison
tests/
```

## Out of scope (MVP)

Semantic clustering of groups, change-stream incremental refresh, multimodal retrieval, learned routing. Batch rebuild of the hierarchy is the freshness path for now.
