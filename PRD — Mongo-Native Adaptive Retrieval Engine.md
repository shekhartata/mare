# PRD: Mongo-Native Adaptive Retrieval Engine

**Status:** MVP / Research Prototype  
**Working name:** Mongo Adaptive Retrieval Engine (MARE)  
**Primary objective:** Build a MongoDB-native alternative/complement to conventional RAG for workloads where static Top-K retrieval is insufficient.

---

# 1. Executive Summary

Traditional RAG generally follows:

```text
Query
  ↓
Embed Query
  ↓
Vector Search
  ↓
Top-K Chunks
  ↓
LLM
  ↓
Answer
```

This works well for relatively simple semantic retrieval, but becomes weaker for:

- multi-hop questions,
- information distributed across many records,
- large documents,
- questions requiring varying amounts of context,
- exact lexical/structured lookups,
- workloads where embedding every chunk creates significant storage and indexing overhead.

This project proposes a MongoDB-native **Adaptive Retrieval Engine**.

Instead of deciding all context before invoking the agent, MongoDB becomes a navigable information environment.

The system has two core layers:

1. **Semantic Navigation Layer**
   - Helps the agent determine where useful information exists.
   - Uses hierarchical metadata, summaries, MongoDB Search, Vector Search, hybrid search, and structured queries.

2. **Adaptive Retrieval Layer**
   - Determines what evidence to retrieve.
   - Uses best-first search.
   - Maintains hypotheses and an evidence ledger.
   - Finds evidence gaps.
   - Stops when additional retrieval has low expected value.

MongoDB remains:

- system of record,
- navigation/index substrate,
- search system,
- raw evidence source,
- retrieval state store.

No requirement should exist to export MongoDB data into PDFs, Markdown, another vector database, or another knowledge system.

---

# 2. Product Thesis

The central product idea is:

> **Turn MongoDB from a passive RAG data source into an information environment that AI agents can progressively navigate and reason over.**

The product should complement MongoDB Search and Vector Search rather than replace them.

Vector Search becomes **one retrieval primitive available to the system**, instead of defining the entire architecture.

Eventually two paths should coexist:

```text
                     Query
                       ↓
               Retrieval Router
                /             \
         Simple Query       Complex Query
              ↓                  ↓
        Conventional RAG    Adaptive Retrieval
              ↓                  ↓
        Search / Vector     Navigate → Retrieve
              ↓             → Verify → Stop
             LLM                 ↓
                               LLM
```

---

# 3. Core Architectural Principle: Vector Minimization

Dense vectors should exist **only where they materially improve navigation or retrieval**.

The system must NOT default to:

```text
Every document
   ↓
Every chunk
   ↓
Embedding
   ↓
Millions of vectors
```

Instead:

```text
Database
   ↓
Collection
   ↓
Logical / Semantic Groups
   ↓
Relevant Data Region
   ↓
Raw Mongo reads / lexical search / structured query
```

Vectors primarily help identify the **right information neighborhood**.

Once that neighborhood is identified, the system should prefer cheaper or more deterministic mechanisms when appropriate:

- MongoDB queries,
- metadata filters,
- lexical search,
- direct document reads,
- field projections,
- aggregation,
- optionally on-demand embeddings.

Example:

```text
Traditional RAG:

1M documents
× 10 chunks/document
≈ 10M vectors
```

Adaptive navigation may instead require vectors only for:

```text
database summaries
+
collection summaries
+
logical / semantic groups
+
selected document summaries
```

Potentially reducing vector count by orders of magnitude.

The architecture must therefore measure:

```text
adaptive_vector_count / rag_vector_count
```

and:

```text
adaptive_vector_index_size / rag_vector_index_size
```

as first-class product metrics.

---

# 4. Core Problems

## Problem 1 — Navigation

Given potentially millions of MongoDB records:

> How does the agent determine where useful information exists?

Use a multi-resolution hierarchy:

```text
Database
  ↓
Collection
  ↓
Logical / Semantic Group
  ↓
Documents
  ↓
Raw Fields / Content
```

Navigation can use:

- collection/database descriptions,
- generated summaries,
- schema information,
- lexical search,
- summary embeddings,
- hybrid search,
- metadata filters,
- structured Mongo queries.

---

## Problem 2 — Retrieval Policy

After reaching a promising region:

> What should the system retrieve next?

Candidate priority should consider:

```text
relevance
+ expected evidence gain
+ uncertainty reduction
+ novelty
+ source diversity
- token cost
- latency cost
```

Use a best-first search strategy rather than fixed `Top-K`.

---

## Problem 3 — Stopping

The system must determine:

> When is enough evidence available?

Stopping should combine:

- claim coverage,
- evidence strength,
- unresolved contradictions,
- answer stability,
- marginal information gain,
- remaining candidate quality,
- hard token/latency/retrieval budgets.

---

# 5. Non-Goals

The MVP should NOT:

- replace MongoDB Search,
- replace MongoDB Vector Search,
- implement a new vector database,
- reproduce PageIndex, GraphRAG, or another existing framework,
- require external document conversion,
- train custom embedding models,
- solve multimodal retrieval,
- create embeddings for every raw document by default,
- build a fully autonomous general-purpose agent platform.

The MVP exists to test whether **Mongo-native adaptive retrieval materially improves difficult retrieval workloads**.

---

# 6. Data Architecture

Raw customer data remains untouched:

```text
production.customers
production.tickets
production.logs
production.incidents
production.documents
```

Derived system collections:

```text
_agent_retrieval.navigation_nodes
_agent_retrieval.evidence_sessions
_agent_retrieval.retrieval_traces
_agent_retrieval.config
```

Navigation nodes should reference raw Mongo data rather than duplicate it.

---

# 7. Navigation Node Model

Suggested schema:

```json
{
  "_id": "ObjectId",

  "tenant_id": "string",

  "node_type": "database | collection | group | document",

  "name": "string",
  "description": "string",
  "summary": "string",
  "search_text": "string",

  "parent_id": "ObjectId | null",
  "depth": 0,

  "source": {
    "database": "string",
    "collection": "string",
    "document_ids": [],
    "filter": {},
    "pointer_type": "document | query | range"
  },

  "schema": {
    "important_fields": [],
    "field_descriptions": {}
  },

  "metadata": {
    "topics": [],
    "entities": [],
    "time_min": null,
    "time_max": null,
    "document_count": 0
  },

  "embedding": [],

  "children_count": 0,
  "version": 1,

  "created_at": "date",
  "updated_at": "date"
}
```

Raw data should not normally be copied into these nodes.

---

# 8. Searchable Representation

Do not rely solely on an LLM-generated summary.

Construct navigation search content from:

```text
node name
+ database / collection name
+ description
+ summary
+ important field names
+ entities
+ topics
+ representative terms
```

This helps prevent lossy summaries from hiding important information.

---

# 9. Building the Hierarchy

## Database Level

Generate:

- database purpose,
- available collections,
- broad domain description.

## Collection Level

Inspect:

- collection name,
- sampled schema,
- representative records,
- important fields,
- timestamps,
- indexed fields,
- approximate cardinality.

Generate a compact collection description.

## Large Collections

Do NOT create an LLM summary/vector for every record automatically.

Introduce intermediate groups.

Possible grouping strategies:

### Deterministic

```text
customer_id
region
product
year/month
document_type
severity
```

### Semantic

```text
authentication failures
billing issues
deployment failures
performance incidents
```

### Hybrid

```text
customer
   ↓
time range
   ↓
semantic topic
```

MVP priority:

1. deterministic grouping,
2. temporal grouping,
3. optional semantic clustering later.

---

# 10. Navigation Interfaces

Expose four primary mechanisms.

## Lexical Search

Best for:

- IDs,
- error codes,
- exact phrases,
- names,
- dates,
- terminology.

## Semantic Search

Search embeddings of **navigation representations**, not necessarily raw chunks.

Its primary purpose is:

> Find the right region of the information space.

## Hybrid Search

Combine lexical + semantic results.

Default where query type is uncertain.

## Structured Mongo Query

Use when the information need can be expressed directly:

```text
customer_id = X
timestamp > Y
status = failed
```

Structured queries should be preferred when they are more precise and cheaper.

---

# 11. Agent Tool Surface

Keep the interface deliberately small:

```text
list_databases()

list_collections(database)

get_node(node_id)

get_children(node_id)

lexical_search(query, scope?, filters?, limit?)

semantic_search(query, scope?, filters?, limit?)

hybrid_search(query, scope?, filters?, limit?)

search_within(node_id, query)

query_documents(namespace, filter, projection?, limit?)

read_documents(namespace, ids, projection?)
```

All retrieved evidence must expose stable Mongo source references.

---

# 12. Retrieval Router

Use deterministic routing where obvious.

Example:

```text
Exact code / identifier
        → lexical

Conceptual question
        → semantic

Mixed / unclear
        → hybrid

Known field predicates
        → Mongo query
```

The agent may override the router.

Log:

```text
router_recommendation
agent_selected_method
```

for later evaluation.

---

# 13. Best-First Retrieval

Maintain candidate nodes in a priority queue.

Conceptual score:

```text
priority =

  relevance
+ evidence_gap
+ uncertainty_reduction
+ novelty
+ source_diversity

-

  retrieval_cost
```

Initial implementation should use configurable weighted features rather than a complex learned optimizer.

Example:

```python
priority = (
    0.30 * relevance
    + 0.30 * evidence_gap
    + 0.15 * uncertainty_reduction
    + 0.10 * novelty
    + 0.05 * diversity
    - 0.10 * normalized_cost
)
```

Weights must be configurable.

---

# 14. Hypothesis-Driven Retrieval

Initial retrieval should produce a tentative answer or hypothesis.

Example:

```text
Question:
Why did deployment X fail after migration Y?
```

Hypothesis:

```text
Deployment X likely failed because authentication
configuration was not updated after migration Y.
```

Break this into claims:

```text
C1 migration Y changed authentication behavior
C2 deployment X used old configuration
C3 deployment logs contain authentication failures
C4 failure happened after migration Y
```

The system should retrieve evidence specifically to:

- support claims,
- contradict claims,
- resolve uncertainty.

This is the core adaptive loop.

---

# 15. Evidence Ledger

Create one structured retrieval session per query.

Example:

```json
{
  "_id": "session-id",

  "question": "...",

  "hypothesis": "...",

  "claims": [
    {
      "claim_id": "C1",
      "claim": "...",

      "status":
        "supported | partially_supported | unsupported | contradicted",

      "confidence": 0.0,

      "supporting_sources": [],
      "contradicting_sources": [],

      "missing_information": []
    }
  ],

  "open_questions": [],

  "retrieval_count": 7,
  "tokens_consumed": 12000,
  "elapsed_ms": 3400
}
```

Do not rely exclusively on free-form model reasoning.

---

# 16. Evidence Extraction

Every retrieval step should generate structured output.

Example:

```json
{
  "relevant": true,

  "claims_supported": [
    {
      "claim_id": "C2",
      "support_strength": 0.88,
      "evidence": "..."
    }
  ],

  "claims_contradicted": [],
  "new_claims": [],
  "new_questions": []
}
```

Store source references instead of copying large raw documents.

---

# 17. Retrieval Loop

```python
state = initialize(question)

candidates = navigate(question)

while not should_stop(state):

    candidate = best_candidate(candidates)

    evidence = retrieve(candidate)

    observations = extract_evidence(
        question,
        evidence,
        state.hypothesis
    )

    update_evidence_ledger(state, observations)

    state.hypothesis = update_hypothesis(state)

    gaps = identify_evidence_gaps(state)

    candidates += search_for_gaps(gaps)

    candidates = rerank(candidates, state)

return generate_answer(state)
```

---

# 18. Stopping Policy

Stopping must be a first-class component.

## Claim Coverage

Measure:

```text
supported material claims / total material claims
```

## Evidence Strength

Critical claims require sufficient evidence.

## Contradictions

Do not stop while major contradictions remain unresolved.

## Marginal Information Gain

If repeated retrievals produce:

```text
no new claims
no material confidence improvement
no answer change
```

retrieval should stop.

## Answer Stability

Track changes between hypothesis versions:

- claims added,
- claims removed,
- claims changed,
- confidence delta.

## Search Frontier

Stop when no candidate remains above a minimum priority threshold.

## Hard Budget

Always support:

```text
max_retrieval_operations
max_search_operations
max_documents_read
max_llm_tokens
max_elapsed_time
```

Possible final status:

```text
complete
partial
insufficient_evidence
budget_exhausted
```

---

# 19. Stopping Algorithm

```python
def should_stop(state):

    if hard_budget_exceeded(state):
        return True

    if unresolved_critical_contradictions(state):
        return False

    if evidence_coverage(state) >= COVERAGE_THRESHOLD:
        if answer_stable(state):
            return True

    if marginal_information_gain(state) < MIN_GAIN:
        if consecutive_low_gain_rounds(state) >= N:
            return True

    if highest_candidate_priority(state) < MIN_PRIORITY:
        return True

    return False
```

All thresholds must remain configurable.

---

# 20. Explicit Retrieval State Machine

```text
INITIALIZE
    ↓
NAVIGATE
    ↓
RETRIEVE
    ↓
EXTRACT EVIDENCE
    ↓
UPDATE HYPOTHESIS
    ↓
IDENTIFY GAPS
    ↓
EVALUATE STOPPING
    ├── CONTINUE → NAVIGATE
    └── STOP → GENERATE ANSWER
```

Avoid implementing this as one giant agent prompt.

Each stage must be independently testable.

---

# 21. Observability

Non-deterministic retrieval requires strong traceability.

Store:

```text
_agent_retrieval.retrieval_traces
```

Example:

```json
{
  "session_id": "...",
  "step": 4,

  "operation": "hybrid_search",
  "reason": "Need evidence for C3",

  "query": "...",
  "scope": "...",

  "results": [],
  "selected_result": "...",

  "candidate_scores": {},

  "latency_ms": 75,
  "tokens": 430
}
```

A developer must be able to answer:

```text
Why did the agent search here?

Why did it choose this result?

What changed its hypothesis?

Why did it retrieve again?

Why did it stop?
```

---

# 22. Security

Mongo authorization must remain authoritative.

Never let the model determine authorization.

```text
User
 ↓
Security Context
 ↓
Mandatory Mongo filters / credentials
 ↓
Retrieval
 ↓
Agent
```

Every retrieval operation must receive tenant/user scope.

---

# 23. Freshness

Navigation data is derived state.

Initial indexing:

```text
Mongo collections
    ↓
batch navigation builder
```

Future incremental update:

```text
Mongo Change Stream
    ↓
identify affected node
    ↓
mark dirty
    ↓
batch/debounce regeneration
```

Never regenerate entire collection summaries on every write.

---

# 24. Model Abstractions

Do not couple the system to a specific model provider.

```python
class ReasoningModel:
    generate(...)
    structured_generate(...)
```

```python
class EmbeddingModel:
    embed(...)
```

Different models may be configured for:

- summary generation,
- navigation reasoning,
- evidence extraction,
- answer generation,
- embeddings.

---

# 25. Suggested MVP Stack

```text
Python 3.12+
FastAPI
PyMongo
Pydantic
MongoDB Atlas
MongoDB Search
MongoDB Vector Search
```

Avoid large agent frameworks unless clearly necessary.

The retrieval state machine should remain application code.

---

# 26. Suggested Repository Structure

```text
/
├── app/
│   ├── api/
│   ├── config/
│   ├── mongo/
│   │
│   ├── indexing/
│   │   ├── schema_discovery.py
│   │   ├── hierarchy_builder.py
│   │   ├── grouping.py
│   │   └── summaries.py
│   │
│   ├── search/
│   │   ├── lexical.py
│   │   ├── vector.py
│   │   ├── hybrid.py
│   │   └── router.py
│   │
│   ├── retrieval/
│   │   ├── state.py
│   │   ├── candidate.py
│   │   ├── best_first.py
│   │   ├── hypothesis.py
│   │   ├── evidence.py
│   │   └── stopping.py
│   │
│   ├── llm/
│   ├── observability/
│   └── models/
│
├── tests/
├── benchmarks/
└── scripts/
```

---

# 27. MVP Scope

Implement:

1. Mongo schema inspection.
2. Database summaries.
3. Collection summaries.
4. Navigation node persistence.
5. Deterministic/logical grouping.
6. Lexical search.
7. Navigation-level vector search.
8. Hybrid search.
9. Structured Mongo query interface.
10. Retrieval router.
11. Best-first traversal.
12. Hypothesis generation.
13. Claim decomposition.
14. Evidence ledger.
15. Evidence-gap retrieval.
16. Configurable stopping.
17. Full traces.
18. Source-grounded final answers.
19. Conventional RAG baseline.

Do NOT prioritize semantic clustering until this loop works end-to-end.

---

# 28. Conventional RAG Baseline

The same repository must contain a baseline implementation:

```text
Raw Mongo Data
    ↓
Chunk
    ↓
Embed every chunk
    ↓
MongoDB Vector Search
    ↓
Top-K
    ↓
LLM
```

Support:

```text
configurable chunk size
configurable overlap
configurable top_k
vector retrieval
hybrid retrieval
```

The baseline is mandatory for validating the product thesis.

---

# 29. Benchmarking Requirement

Every evaluation query must eventually be runnable through both:

```text
Adaptive Retrieval
```

and:

```text
Conventional RAG
```

Benchmarking should compare three workload classes.

## A. Simple Lookup

Example:

```text
What is customer X's current subscription tier?
```

Likely winner:

```text
direct query / conventional retrieval
```

## B. Semantic Retrieval

Example:

```text
Find incidents involving authentication failures.
```

RAG may remain highly competitive.

## C. Complex / Multi-Hop

Example:

```text
Why did customer X begin experiencing deployment
failures after migration Y, and what evidence supports
the most likely root cause?
```

This is the primary target workload for adaptive retrieval.

---

# 30. Benchmark Metrics

## Quality

- correctness,
- completeness,
- grounding,
- citation correctness,
- hallucination rate.

## Retrieval

- evidence recall,
- evidence precision,
- gold-source discovery,
- missed evidence.

## Cost

- embedding tokens,
- LLM tokens,
- retrieval operations,
- indexing cost.

## Latency

- retrieval latency,
- end-to-end latency.

## Vector Footprint

Mandatory metrics:

```text
number_of_vectors
```

```text
vector_index_size_bytes
```

```text
embedding_generation_cost
```

```text
adaptive_vector_count / rag_vector_count
```

```text
adaptive_index_size / rag_index_size
```

This is a primary success criterion, not a secondary metric.

## Retrieval Efficiency

- searches executed,
- documents read,
- retrieval rounds,
- duplicate retrievals,
- retrievals yielding no useful evidence.

---

# 31. Research Hypotheses

### H1 — Better Complex-Query Quality

Adaptive retrieval produces more complete and grounded answers for multi-hop questions.

### H2 — Reduced Vector Dependency

Navigation-level embeddings require substantially fewer vectors than chunk-everything RAG.

### H3 — Lower Vector Index Footprint

The adaptive architecture requires less dense-vector storage and indexing overhead.

### H4 — Better Context Efficiency

Less irrelevant context reaches the final answering model.

### H5 — Competitive Simple-Query Performance

Simple queries can remain on conventional Mongo Search/RAG paths.

### H6 — Mongo-Native Infrastructure Advantage

The architecture avoids forcing users to export Mongo data into another retrieval/storage platform.

---

# 32. Ablation Studies

After the MVP works, compare:

```text
Full Adaptive System

vs

no evidence ledger
no vector navigation
no lexical navigation
no hybrid search
no answer-stability stopping
no marginal-information stopping
no intermediate grouping
LLM-only routing
deterministic routing only
```

Also test:

```text
all navigation nodes embedded
vs
only coarse nodes embedded
vs
no vectors / lexical only
```

This is particularly important for determining the actual value of dense vectors.

---

# 33. Future Adaptive Router

Eventually:

```text
Query
  ↓
Complexity / Retrieval Router
  ├── direct Mongo query
  ├── lexical search
  ├── conventional RAG
  └── adaptive retrieval
```

Potential routing signals:

- query type,
- expected source count,
- multi-hop likelihood,
- entity count,
- Top-K confidence,
- score distribution,
- initial retrieval quality.

---

# 34. Product Success Criteria

The system should not be considered successful merely because adaptive retrieval works.

It must demonstrate a meaningful Pareto improvement across:

```text
answer quality
retrieval quality
vector count
index size
token cost
latency
```

The strongest intended result is:

> **Conventional MongoDB RAG remains the fast path for simple retrieval, while Mongo Adaptive Retrieval provides a higher-quality path for complex information needs using significantly fewer persistent dense vectors than chunk-everything RAG.**

---

# 35. MongoDB Product Positioning

Do NOT position the product as:

> "RAG is obsolete."

Position it as:

> **MongoDB Adaptive Retrieval**

MongoDB provides the underlying primitives:

```text
Mongo Query
Mongo Search
Mongo Vector Search
Mongo aggregation/direct reads
```

The adaptive layer determines:

```text
where to search
which search mechanism to use
what to retrieve
what evidence is missing
how much additional retrieval is worthwhile
when to stop
```

Result:

```text
                    AI Application
                          ↓
                 Adaptive Retrieval
                          ↓
        ┌─────────────────┼─────────────────┐
        ↓                 ↓                 ↓
   Mongo Search      Vector Search      Mongo Query
        └─────────────────┼─────────────────┘
                          ↓
                       MongoDB
```

MongoDB becomes the **retrieval substrate for agentic AI**, rather than merely a vector store feeding static context into an LLM.

---

# 36. Long-Term Developer Experience

Target experience:

```text
Connect MongoDB
    ↓
Select collections
    ↓
Discover schema
    ↓
Build navigation hierarchy
    ↓
Create minimal required indexes
    ↓
Expose adaptive retrieval endpoint/tools
    ↓
Agent navigates existing Mongo data
```

The developer should not need to:

- export data,
- convert data into PDFs/Markdown,
- manually label millions of documents,
- chunk every field,
- embed every record,
- operate another vector database,
- manually define every retrieval path.

---

# 37. Implementation Order

## Phase 1 — Foundations

1. Repository skeleton.
2. Mongo connection.
3. configuration.
4. model abstractions.
5. shared schemas.

## Phase 2 — Navigation

6. schema discovery.
7. database/collection summaries.
8. navigation nodes.
9. deterministic grouping.
10. hierarchy traversal.

## Phase 3 — Search

11. lexical search.
12. navigation-level vector search.
13. hybrid search.
14. structured query interface.
15. retrieval router.

## Phase 4 — Adaptive Retrieval

16. retrieval state.
17. candidate priority queue.
18. best-first traversal.
19. hypothesis generation.
20. claim decomposition.
21. evidence extraction.
22. evidence ledger.
23. evidence-gap search.

## Phase 5 — Stopping

24. claim coverage.
25. answer stability.
26. marginal information gain.
27. frontier exhaustion.
28. hard budgets.

## Phase 6 — Observability

29. tracing.
30. evidence inspection.
31. retrieval statistics.
32. cost/latency accounting.

## Phase 7 — Baseline & Evaluation

33. conventional RAG.
34. benchmark runner.
35. vector footprint measurement.
36. quality metrics.
37. ablation runner.

---

# 38. MVP Definition of Done

A developer must be able to:

1. Connect to MongoDB.
2. Select databases/collections.
3. Build a navigation hierarchy without exporting raw data.
4. Embed only required navigation representations.
5. Ask a complex question.
6. Observe navigation decisions.
7. Observe retrieval mechanism selection.
8. See the current hypothesis.
9. Inspect claims and evidence.
10. Observe evidence-gap searches.
11. See why retrieval stopped.
12. Receive a grounded answer with Mongo source references.
13. Run the same query against conventional RAG.
14. Compare quality, latency, tokens, retrieval operations, number of vectors and vector-index size.

---

# 39. Guiding Principle

### Conventional RAG

> **Pre-index as much information as possible and retrieve a fixed context before generation.**

### Mongo Adaptive Retrieval

> **Maintain the minimum useful navigation index, then allow the agent to progressively acquire evidence from MongoDB only as required.**

Or more simply:

> **Index enough to know where to look. Retrieve only enough to know the answer.**