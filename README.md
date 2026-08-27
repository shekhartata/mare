# Mongo Adaptive Retrieval Engine (MARE)

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

MARE turns MongoDB from a passive RAG data source into an information environment an agent can **navigate**: find where the answer lives, then read the actual records.

Conventional RAG embeds every chunk and returns Top-K. MARE embeds only a small **navigation index** (616 vectors here vs 5424 RAG chunks) and lets the agent hop, filter, and count against live Mongo data.

This repository is the working MVP. The rest of this README is the product document: when to use it, how to run it, where it beats RAG, and how navigation and retrieval are implemented.

**Contents:** [When to use MARE](#should-you-use-mare-or-rag) · [Quickstart](#quickstart) · [Integrate](#integrating-mare) · [Where it wins](#where-mare-wins-case-by-case) · [Architecture](#architecture) · [How the agent calls MongoDB](#how-the-agent-calls-mongodb)

## Should you use MARE or RAG?

| Question looks like | Use | Why |
| --- | --- | --- |
| "What tier is cust_007 on?" | RAG or a plain `find` | The ID is in the question. One search is enough, and it is faster. |
| "Why did cust_007 fail after mig_auth_sso?" | Either | Both IDs are named, so Top-K can scoop the whole story. |
| "Which enterprise customer managed by Elena Rossi broke in May?" | **MARE** | The entity is not named. Requires a lookup, then a hop to another collection. |
| "How many customers are on enterprise?" | **MARE** | The answer is a count over the collection, not a nearby chunk. |
| "Did Cedar have any April incidents?" | **MARE** | The answer is *nothing matched*. Top-K always returns something. |
| "Why did Northstar logins break after platform changes?" | **MARE** | The cause is split across four records. Default Top-K latches onto a similar Apex story. |
| "How did Apex auth failures evolve over three months?" | Either | Both can name the three failure modes. RAG recall rises if you raise K; MARE reads more without changing K. |

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

Nine cases, run end to end against Atlas after a full reseed. Each one below shows the actual prompt, so you can see what it is testing. Numbers are **schema-blind** MARE vs conventional hybrid RAG (primary Top-K=10). Informed-schema control numbers for the original five cases were not re-run after this reseed.

Two rules make these honest:

1. **The agent is schema-blind.** Its system prompt does not name any database, collection, or field. It has to discover `customers`, `deployments`, `subscription_tier` from the navigation index. Otherwise "MARE can count" would just mean "we told the model the schema."
2. **Bridge requires both hops.** Naming the customer is not enough; the answer must also reach the root cause.
3. **Distributed evidence is scored on retrieved document ids**, not just what the answer cites. Completeness is whether the answer hits every evidence group.

### 1. Simple lookup — RAG's home turf

> **Prompt:** "What is customer cust_007's current subscription tier?"

The ID is in the question, so one search finds it. **Both are correct.** RAG is more than twice as fast (3.9s vs 11.0s). MARE's only edge is precision: it cites the one customer record, while RAG cites eight similar customers.

*Do not sell MARE on this case.*

### 2. Named multi-hop — still RAG's home turf

> **Prompt:** "Why did customer Apex Logistics (cust_007) begin experiencing deployment failures after migration mig_auth_sso, and what evidence supports the most likely root cause?"

The question names both the customer and the migration, so Top-K can scoop the migration, deploys, logs, and ticket in a single shot. **Both are correct**, and RAG actually cites *more* gold documents (recall 0.625 vs 0.25) and is faster.

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
- **MARE this run: incorrect.** It retrieved all 18 enterprise customers (gold evidence recall 1.0) and then the synthesizer refused to count them, claiming the briefed records had no `subscription_tier` field. Retrieval did the hard part; the answer did not.

Do not treat aggregation as a guaranteed win. The structured-query *path* is still the only one that can count a collection; this run shows the answering model can still drop the ball after the documents are in hand.

### 5. Negative — proving nothing matched

> **Prompt:** "Did Cedar Systems (cust_004) have any incidents opened in April 2024?"

Both said "no," but only one grounded it.

- **RAG: incorrect.** It cited April incidents belonging to `cust_030`, `cust_047`, and `cust_033`. Top-K always returns something, so an absence claim has no evidence behind it.
- **MARE: correct.** It queried Cedar's own incidents and showed they fall in January, February, and June — no April.

### 6. Distributed evidence — no single record has the cause

> **Prompt:** "Why did Northstar begin experiencing intermittent authentication failures after recent platform changes?"

The question names Northstar but not `cust_012`, issuer, JWT, OIDC, or the migration id. The cause is split: a login ticket, an OIDC issuer change, a rollout that kept the previous auth config, and a token-validation log. No one document contains the full sentence.

- **RAG hybrid K=10: incorrect.** It found the Northstar login ticket, then explained it with Apex's SSO story (`mig_auth_sso`, `inc_1001`, auth-v3). Similar chunks, wrong customer.
- **RAG hybrid K=20: correct**, gold evidence recall 1.0 — once K is large enough, Top-K can scoop all four fragments.
- **MARE: correct** (completeness 4/4) from the identity migration and the stale runtime config, without being told those collection names. Gold evidence recall was 0.5 (it missed the ticket and the JWT log) and it still named the real cause.

The honest claim is not "RAG can never assemble distributed evidence." It is that **default Top-K latches onto the nearest similar incident**, and you have to know to raise K.

### 7. Variable K — same subject, three gold-set sizes

Three questions about Apex authentication, gold sets of 2, 7, and 18 records. RAG is swept at hybrid K=5/10/20. MARE keeps the same agent loop.

| Question | MARE complete | RAG K=10 complete | MARE gold recall | RAG K=5 / 10 / 20 recall | MARE docs |
| --- | --- | --- | --- | --- | --- |
| Most recent Apex auth incident | no (cause yes, did not restate Apex) | no (same) | 0.5 | 1.0 / 1.0 / 1.0 | 2 |
| May SSO sequence | yes | yes | 0.143 | 0.714 / 0.857 / 1.0 | 2 |
| Three-month evolution | yes | yes | 0.333 | 0.222 / 0.5 / 0.889 | 23 |

RAG hybrid K=5 and vector K=10 *did* score complete on the small question. At K=10 both engines named the SSO cause but omitted "Apex"/"cust_007" in the answer text.

On the deep question **both answers were complete** at every K we tried, including RAG K=5. The three incident records are enough to name idle-timeout, token TTL, and issuer mismatch. What actually moves is **evidence recall**: RAG's gold recall scales with K (0.222 → 0.889), and MARE's retrieved volume scales with the question (2 docs on small/medium, 23 on deep) without changing a K parameter.

*Do not sell MARE as more correct than RAG on this suite.* Sell it as not having to pick K in advance, and as not confusing Northstar with Apex.

### Results table

`gpt-5` answering, `gpt-5-mini` tool loop, 10-turn budget. Schema-blind vs hybrid RAG (K=10 unless noted).

| Case | MARE (blind) | RAG | MARE time | RAG time |
| --- | --- | --- | --- | --- |
| Simple lookup | yes | yes | 11.0s | 3.9s |
| Named multi-hop | yes | yes | 28.9s | 9.7s |
| **Bridge** | **yes** (entity + cause) | **no** (cause, no entity) | 20.9s | 5.1s |
| Aggregation | no (retrieved 18, did not count) | **8** | 16.8s | 5.8s |
| **Negative** | **yes** (grounded) | **no** (wrong customers) | 15.5s | 4.1s |
| **Distributed** | **yes** (4/4 groups) | **no** at K=10 (Apex story); yes at K=20 | 26.9s | 11.7s |
| Variable K — small | no (cause, no entity) | no at K=10; yes at K=5 | 15.2s | 6.9s |
| Variable K — medium | yes | yes | 22.0s | 12.2s |
| Variable K — deep | yes (4/4); 23 docs | yes (4/4); recall 0.50 at K=10 / 0.89 at K=20 | 33.8s | 12.7s |

Honest caveats: RAG is faster in every single case. On named lookups and the Apex variable-K answers, RAG is as complete or more complete. Persistent vectors stay **616 vs 5424** (11%). Informed-schema A/B was not re-run after this reseed.

Full detail per case: [reports/README.md](reports/README.md).

### Reproduce it

```bash
python scripts/run_comparison.py              # schema-blind MARE vs RAG (default)
python scripts/run_comparison.py --informed   # control: schema in the prompt
python scripts/run_comparison.py --only bridge
python scripts/run_comparison.py --only distributed
python scripts/run_comparison.py --only vk
python scripts/run_comparison.py --rescore    # re-score saved runs, no LLM calls
python scripts/run_comparison.py --rerun-rag  # force RAG after a reseed
```

Writes `reports/README.md` plus one markdown file per case. Gold labels live in `benchmarks/gold.json`.

For the wider gold set (all 22 queries rather than these 9):

```bash
python scripts/run_benchmark.py
python scripts/run_benchmark.py --class complex_multihop
```

Scale / vector-efficiency (retrieval only, no LLM). Gold lives in `benchmarks/scale/gold_queries.json`. Do not put a quality-vs-vectors claim in this README until held-out measurements exist.

```bash
python scripts/seed_scale.py --n 10000
python scripts/build_scale.py --n 10000 --strategy topical --density 100 --chunk-size 512
python scripts/run_scale_retrieval.py --n 10000 --budget 10 --split heldout
```

Details: [reports/scale/README.md](reports/scale/README.md).

---

## Architecture

Conventional RAG treats every question as one problem: embed the prompt, return Top-K chunks, generate. That collapses two jobs that are not the same.

| Job | Question it answers | What RAG does | What MARE does |
| --- | --- | --- | --- |
| **Navigation** | *Where* in this database should I look? | Nowhere. The index is a flat bag of chunks. | Search a hierarchy of neighborhoods, then hop. |
| **Retrieval** | *What* evidence should I read, and when do I stop? | Always the same: Top-K. | Query, read, or skip — then stop when the evidence is enough. |

MARE is the split made concrete. MongoDB stays the system of record. Nothing is exported to PDFs, Markdown, or another vector database. Vectors exist only to help find the right neighborhood; once there, the system prefers `find`, filters, lexical search, and direct document reads.

```text
                     Question
                         │
                         ▼
                  Agent tool loop
                   (schema-blind)
                    /         \
           Navigation          Retrieval
         "where is it?"      "what do I read?"
              │                    │
              ▼                    ▼
     navigation_nodes         raw Mongo docs
     (616 vectors)            (untouched)
              │                    │
              └────────┬───────────┘
                       ▼
              Grounded answer + citations
              database.collection:document_id
```

### Problem 1 — Navigation

Given thousands or millions of records split across collections, the agent does not know which collection, which customer, or which month matters. The prompt is in English; the data is in Mongo.

**Solution: a multi-resolution map, not a chunk pile.**

```text
Database                    mare_demo
  └── Collection            customers | deployments | migrations | …
        └── Group           "deployments for cust_007"
              └── Document  optional pointer (small collections only)
                    └── Raw fields live in the source collection, not here
```

Each of those levels is a **navigation node** in `_agent_retrieval.navigation_nodes`. A node is a pointer plus a description, never a copy of the payload:

```json
{
  "_id": "nav:group:mare_demo:deployments:customer.cust_007",
  "node_type": "group",
  "name": "deployments for cust_007",
  "summary": "…",
  "source": {
    "database": "mare_demo",
    "collection": "deployments",
    "filter": { "customer_id": "cust_007" },
    "pointer_type": "query"
  },
  "schema": {
    "important_fields": ["status", "started_at", "error_code"],
    "field_descriptions": { "status": "failed", "error_code": "AUTH_401" }
  },
  "metadata": { "entities": ["cust_007"], "document_count": 2 }
}
```

How the map is built (`scripts/build_hierarchy.py`):

1. **Database node** — purpose plus the list of collections.
2. **Collection node** — sampled schema, important fields, representative terms, a compact summary. This is how a schema-blind agent learns that `subscription_tier` exists: it is on the node, not in the system prompt.
3. **Groups** — deterministic slices so large collections are not one blob. Operational collections group by `customer_id`; logs also group by month. Semantic clustering is out of scope for the MVP.
4. **Document pointers** — only for small collections (customers, ≤80 docs). Still pointers (`document_ids`), not copied records.

Search text on each node is composed from name, collection, summary, field names, entities, and topics — not the LLM summary alone — so a lossy summary cannot hide an ID or error code.

**How the agent moves on the map**

Four primitives, all over *nodes*, not chunks. A small router picks a default; the agent can override it.

| Need | Primitive | Atlas feature |
| --- | --- | --- |
| IDs, error codes, names | lexical | `$search` |
| "authentication failures", "root cause" | semantic | `$vectorSearch` on node `search_text` (`voyage-4-lite` Automated Embedding when the cluster allows it; otherwise app-side embeddings) |
| Unclear mix | hybrid | `$rankFusion`, or reciprocal rank fusion as fallback |
| Already know `database.collection` and a field | structured `find` | Mongo query with tenant injected |

The high-level tool is `search_information`. It runs that pipeline and returns matching nodes with summaries, `important_fields`, field examples, children, and **`related_nodes`**.

`related_nodes` is the hop. When a result is tied to an entity (`cust_007`), the server looks up sibling nodes in *other* collections whose filter or `metadata.entities` share that id, and returns them in the same tool result. Elena Rossi → Apex is one `find`. Apex → May deployments / `mig_auth_sso` is the next neighborhood, offered immediately. A schema-aware Mongo MCP agent can do the first lookup; it does not get the second for free.

The agent is **schema-blind by default**. The system prompt names no databases, collections, or fields. It is told only: discover those from tool results; never invent them; when `related_nodes` appear, follow them. `--informed` / `MARE_SCHEMA_IN_PROMPT=true` puts the schema back in as a control. Blind and informed scoring the same is the evidence that the index, not a leaked prompt, found the neighborhood.

### Problem 2 — Retrieval

Once the agent is in a neighborhood, the question is no longer "where?" It is "what do I read, in what form, and when is it enough?" RAG's answer is always Top-K chunks. That cannot count a collection, cannot return zero documents, and cannot follow a join that was not in the original embedding.

**Solution: retrieve by policy, from the source of record.**

| Situation | What MARE does | Tool |
| --- | --- | --- |
| Neighborhood identified, need the actual rows | Expand node pointers / filters into raw docs | `retrieve_evidence` |
| Field predicate already observed (`subscription_tier`, `opened_at`, `account_manager`) | Structured `find` on `database.collection` | `query_documents` |
| Need a document by id | Direct read | `read_documents` |
| Enough evidence, or the budget is gone | Stop and answer, citing only docs that were seen | `submit_answer` |

Python does not let the model talk to Mongo raw. Every tool goes through `inject_tenant`: a model-supplied `tenant_id` cannot widen scope. Citations are harvested from retrieved documents (`database.collection:document_id`); unknown/draft placeholders are dropped.

The loop (`app/retrieval/agent_loop.py`):

```text
messages = [blind system prompt, user question]
while turns < max_agent_turns and elapsed < max_elapsed_ms:
    model may call search_information | retrieve_evidence | query_documents | submit_answer
    tool results (including schema fields and related_nodes) go back into the conversation
    if submit_answer → stop
if budget exhausted → force submit_answer from evidence already in hand
if agent model ≠ answer model → one gpt-5 synthesis over the gathered docs
persist session + traces
```

Stopping is a budget plus a decision, not "we got K chunks":

- the model calls `submit_answer` when the retrieved docs answer the question
- hard caps: `MARE_MAX_AGENT_TURNS` (default 10), `MARE_MAX_ELAPSED_MS`, retrieval/token ceilings
- on exhaustion the loop forces a submit rather than inventing more searches
- a session records hypothesis, claims (`supported` / `partially_supported` / `unsupported` / `contradicted`), citations, stop reason, and a step-by-step trace

The older Python state machine (best-first queue, evidence-gap scoring) is still available as `POST /ask` with `"method": "legacy"`. The default path is the tool loop: the model chooses the next primitive; the server enforces tenant, budgets, and citation hygiene.

### How the agent calls MongoDB

The model never gets a Mongo shell, a connection string, or `pymongo`. It only gets **tools**. Each tool is a typed function whose implementation runs on the server, talks to Atlas, injects `tenant_id`, and returns JSON the model can read. That is true for both surfaces:

```text
  Cursor / Claude / any MCP client          POST /ask  (in-process loop)
              │                                        │
              │  MCP tools                             │  OpenAI tool calls
              ▼                                        ▼
        MARE MCP server  ──────────────────►  same service layer
        python -m app.mcp_server.server       app/search/service.py
                                              app/retrieval/tools.py
                       │
                       ▼
                 Atlas MongoDB
            mare_demo  +  _agent_retrieval
            (tenant filter injected here, not by the model)
```

**In-process (`POST /ask`).** `run_agent` sends the schema-blind system prompt plus four function definitions to the agent model (`gpt-5-mini` by default): `search_information`, `retrieve_evidence`, `query_documents`, `submit_answer`. The model emits a tool call; Python dispatches it; the result (nodes, fields, `related_nodes`, or raw docs) is appended to the conversation. Repeat until `submit_answer` or the turn budget. This is ordinary OpenAI tool calling, not MCP, but the functions are the same objects the MCP server wraps.

**MCP (what you give a client agent).** `python -m app.mcp_server.server` exposes that surface over the Model Context Protocol, so Cursor or any MCP host can drive Mongo the same way without embedding MARE in its own process. Point `mcp.json` at the server with `MONGODB_URI` and `OPENAI_API_KEY`. The tools the host advertises to *its* model are:

| Tool | What the agent is allowed to do in Mongo |
| --- | --- |
| `list_databases` / `list_collections` | See which databases MARE will touch (`mare_demo`, `_agent_retrieval`, `_rag_baseline`). |
| `get_node` / `get_children` | Walk the navigation tree by id. |
| `search_information` | “Where does this live?” — hybrid/lexical/semantic search over **nodes**, plus schema fields and `related_nodes`. |
| `lexical_search` / `semantic_search` / `hybrid_search` | Same search, if the agent wants to pick the method itself. |
| `search_within` | Lexical search inside one node’s region of raw documents. |
| `retrieve_evidence` | “Read these neighborhoods” — expand node ids to source documents. |
| `query_documents` | Structured `find` on `database.collection` with a filter the agent observed (never `tenant_id`). |
| `read_documents` | Fetch specific ids from a collection. |
| `ask` | Do not micro-manage: run the full in-process agent loop and return the grounded answer. |

There is a second, unrelated MCP in this project: **MongoDB MCP** (Cursor connection `preconfigured`). That one is for a human or an ops agent — schema inspection, index creation, debug aggregations. It is not the retrieval product. **MARE MCP** is what a client agent should be given: navigate, then retrieve, with tenant and citations enforced.

The important constraint, on both paths: the agent can *request* a query; it cannot *authorize* one. `inject_tenant` runs inside every read. Allowed databases are a server-side allowlist. The model can invent a collection name and get an error; it cannot widen tenant scope or dump another database.

That is why the comparison cases land where they do:

| Case | Navigation | Retrieval |
| --- | --- | --- |
| Simple lookup | Unnecessary — the id is in the prompt | One customer read. RAG also wins this. |
| Named multi-hop | Unnecessary — both ids are named | Top-K can scoop the story. RAG's home turf. |
| Bridge | Find the unnamed customer, then follow `related_nodes` | Read deployments + migration, not a similar ticket. |
| Aggregation | Discover the customers collection and `subscription_tier` from nodes | Count with a filter, not with Top-K. |
| Negative | Discover incidents + the date field | A filter that returns **zero** docs is the evidence. Top-K cannot produce that. |
| Distributed | Find Northstar's identity neighborhood, not Apex's | Read four fragments; default Top-K mixes in the similar SSO incident. |
| Variable K | Same Apex auth neighborhood | Keep reading until the question's depth is covered, instead of committing to a K. |

### Data layout

Raw data is never copied into the navigation index.

| Database | Role |
| --- | --- |
| `mare_demo` | System of record. Untouched synthetic SaaS data: customers, tickets, deployments, migrations, incidents, logs. Ten engineered causal stories; evidence for each is split across collections on purpose. |
| `_agent_retrieval` | `navigation_nodes` (the map), `evidence_sessions` (one per question), `retrieval_traces` (every tool call), `config`. |
| `_rag_baseline` | `chunks` for conventional RAG, same embedding model, so vector count is a fair comparison. |

```text
mare_demo.customers  ──pointers──►  _agent_retrieval.navigation_nodes
mare_demo.deployments ──filter──►   (source.database / collection / filter / document_ids)
mare_demo.migrations
…
```

### MongoDB-native primitives

| Layer | Atlas feature |
| --- | --- |
| Lexical navigation | Atlas Search `$search` |
| Semantic navigation | Atlas Vector Search `$vectorSearch` with Automated Embedding (`voyage-4-lite`) |
| Hybrid | `$rankFusion` when available, otherwise reciprocal rank fusion |
| Structured retrieval | `find` / aggregation with mandatory tenant-scope injection |
| Retrieval state | `_agent_retrieval.evidence_sessions` + `retrieval_traces` |
| RAG baseline | `_rag_baseline.chunks`, same embedding model |

If Automated Embedding is unavailable, MARE falls back to application-side embeddings (`OPENAI_EMBEDDING_MODEL`). `scripts/probe_capabilities.py` records which path is active.

### Vector minimization

Dense vectors exist only where they help *find a neighborhood*. They do not exist on every raw chunk.

```text
RAG (this demo):     every document → chunks → 5424 vectors
MARE (this demo):    database + collections + groups + a few customer pointers → 616 vectors
                     ratio 0.1139
```

Once the neighborhood is known, retrieval is a Mongo query. That is both the cost story and the accuracy story: you cannot count, prove absence, or hop by embedding harder.

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

## License

Licensed under the [Apache License 2.0](LICENSE).
