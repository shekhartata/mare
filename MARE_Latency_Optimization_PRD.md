# MARE latency optimization PRD

**Scope:** two changes only: persisted navigation embeddings and conservative parallel execution of independent tools.  
**Date:** 19 October 2026.  
**Implementation baseline:** `main`, commit `2de82706341536b6ed296ae53e6d95093bc73b2f`.  
**Audience:** implementation in the existing MARE repository using Cursor.  
**Status:** proposed requirements; no repository changes or performance improvements have been implemented by this document.

## 1. Product decision and priorities

MARE should retain its current retrieval behavior while avoiding repeated index preparation and unnecessary serialization of independent reads.

| Priority | Change | Decision |
| --- | --- | --- |
| P0 — highest priority; ship first | Create navigation embeddings during indexing and persist them for reuse across queries and process restarts. | Required. Query handling must never embed navigation cards. |
| P1 — next priority; independently gated | Execute provably eligible read-only tool calls concurrently within one agent turn. | Include, using deterministic execution metadata and argument validation. Default to sequential execution when eligibility is uncertain. |

P1 must not delay P0. P1's expected benefit depends on how frequently the model actually emits independent calls together. It does not eliminate sequential reasoning turns.

This is a new, narrowly scoped change document. It does not replace the earlier abstraction PRD or move human-reviewed adaptation out of Phase 2.

## 2. Problem and current implementation

The user observed approximately 17–18 seconds to answer a question. There is no component-level trace of that particular run, so this PRD does not assign a percentage of that delay to either change or promise a target response time.

### 2.1 P0: the cards are saved, but their vectors are not

`index_database()` builds the generic index. `save_generic_index()` persists card text, source references, profile, plans, and scope, but not embedding vectors. `load_generic_handlers()` subsequently constructs `GenericSurface` for a query. Its constructor calls `embed()` for every node returned by `_nodes(index)`, including group cards and collection nodes. The vectors live only in that surface's in-memory map.

The saved index is not fully regrouped on every query. The repeated work is navigation-node embedding and runtime initialization. The agent does not request this work: it happens before the agent loop starts.

The current generic benchmark and UI expose `session.elapsed_ms`, whose timer starts after handler initialization. That excludes this embedding overhead. Full request timing is necessary to measure the improvement honestly.

### 2.2 P1: a tool-call batch exists, but execution is serial

The agent loop already receives an array of `tool_calls`, with call IDs, tool names, and JSON arguments. It iterates through that array and calls `dispatch_tool()` synchronously. It collects documents, updates counters, appends tool responses, and writes traces during that loop.

The generic handlers expose `search_information`, `retrieve_evidence`, and `query_documents`. Their source-data operations are reads. `submit_answer` is a finalization action handled by the loop, not an ordinary retrieval tool.

There is no runtime `depends_on` graph, parameter-binding mechanism for sibling outputs, or explicit per-handler concurrency contract today.

## 3. Dependency signals: what exists and what must be derived

**Decision:** existing information is sufficient for conservative same-turn scheduling, after adding explicit handler policies and deterministic validation. It is insufficient for arbitrary natural-language dependency inference or automatic parallelization across future agent turns.

| Signal | Current availability | What it supports | What it does not prove |
| --- | --- | --- | --- |
| Calls emitted in the same model response | Existing `tool_calls` array | Identifies a candidate batch whose arguments have already been generated. | The batch alone does not establish safety, correctness, or independence. |
| Tool name and parsed arguments | Existing dispatch input | Determine what operation is requested and whether required inputs are concrete. | Syntactically complete arguments can still contain invalid or invented references. |
| Handler implementation | Current built-in generic handlers read data | Allows a code-reviewed read-only/parallel-safe allowlist. | A familiar tool name does not certify a custom replacement handler. |
| Node IDs, namespaces, fields, and bound hop references from earlier results | Existing result payloads and conversation history | Provide a basis for checking that reference inputs are available before this batch. | There is no dedicated, authoritative provenance tracker today. |
| Validated relationship routes and `related_nodes` | Existing generic index/results | Explain a possible data path and, once bound, a concrete next-hop target. | A relationship is not a runtime dependency graph; its existence does not make two calls independent. |
| Call ID | Existing model response | Pairs each tool response with its request. | It does not encode dependencies. |
| `submit_answer`, forced-submit state, budgets | Existing loop controls | Identify finalization and execution barriers. | They do not authorize additional retrieval after exhaustion. |
| Index signal-provider `requires` | Existing indexing registry | Orders indexing providers. | It describes build-time dependencies, not query-time tool dependencies. Do not reuse it as a scheduling classifier. |
| Timing and tool counts | Partial existing traces | Help measure whether a proposed optimization matters. | Timing, similarity, different collections, or distinct tool names do not establish independence. |

### 3.1 Proposed execution policy

Add a small policy registry keyed by tool surface and actual handler registration. Policies are application-controlled and versioned with their handler, never supplied by the model.

At minimum, record:

- Whether the handler is read-only with respect to source data.
- Whether its implementation is safe for concurrent invocation.
- Whether it uses mutable shared execution state or an ordering-sensitive session.
- Whether it is a finalization/control barrier.
- How to validate and resolve its reference-bearing arguments.

Derive a per-call scheduling decision from the policy, validated arguments, prior reference provenance, fixed request scope, and remaining budget. Log `parallel_eligible`, `sequential_reason`, or `invalid_input_reason`. No extra LLM call is needed.

Unknown policies default to sequential. A custom handler must opt in after review; it must not inherit parallel safety merely by using a built-in name.

### 3.2 Examples and boundary cases

| Calls or question pattern | Decision | Reason |
| --- | --- | --- |
| Two searches with complete query strings, issued together | Parallel candidate | Neither requires the other's output, if the handlers and scope pass policy checks. |
| Fetch two node IDs already observed before this turn | Parallel candidate | Both references are already available. A single existing multi-node retrieval call may also be appropriate. |
| Two queries for a known customer, with namespaces/fields already established | Parallel candidate | Both filters are bound; different collections are not the reason they are safe. |
| Two read-only queries against the same collection | Potentially parallel | Sharing a collection is not a dependency; consistency and handler policies still apply. |
| Search for a complaint, then fetch the order ID discovered in its result | Sequential | The order ID is not available until the first operation completes. |
| Search plus retrieve using a node ID known from an earlier turn | Potentially parallel | The retrieval does not depend on the new search merely because the tool names suggest a sequence. |
| Fetch using an unresolved sibling-output placeholder or an unvalidated reference | Do not execute as an eligible parallel call | The current protocol cannot bind sibling outputs. Return a structured validation error or request a later valid call; serial ordering alone cannot repair missing arguments. |
| Read plus a mutation or an unknown/stateful tool | Sequential/control barrier | No approved side-effect-free concurrency contract. |
| `submit_answer` plus retrieval in the same response | No parallel finalization | A draft emitted before retrieval cannot incorporate those new results. Apply the finalization rules below. |

Do not build a question-level classifier such as “count questions are parallel” or “different collections are independent.” Independence is a property of concrete operations, inputs, side effects, and execution state.

## 4. P0 requirements: persist navigation embeddings

### 4.1 Index-build behavior

**P0-01.** Use one canonical navigation-node builder for indexing and querying. It must produce identical stable node IDs and embedding text for both group and collection nodes. Do not persist only group vectors while leaving collection nodes to be embedded on each request.

**P0-02.** During explicit index creation or maintenance, generate the node embeddings and save them with their identity and compatibility metadata before declaring the semantic index ready.

Required metadata includes source/index identity, generation/build identity, node ID and type, exact embedding-text hash, embedding provider/model identifier, dimensions, any embedding-space-affecting settings, node-builder version, vector, and completion status. Use stable, durable build identity rather than assuming the existing process-local generation counter is globally unique.

**P0-03.** On a later explicit build, reuse compatible vectors for unchanged embedding text. Embed new/changed nodes only; do not reuse vectors across incompatible models, dimensions, settings, or serialization versions. Metadata-only source-reference changes must update references even when their embedding text is unchanged.

**P0-04.** Publish a coherent set of nodes and vectors. A failed or partial build must not expose a mixed or incomplete semantic generation. Stage versioned artifacts and publish the catalog reference only after validation. Preserve the prior usable generation on failure. This is the minimum publication protection needed for this change, not a request for a general index-management redesign.

**P0-05.** Keep source documents where they are; persist compact navigation vectors and references. Do not introduce embedding of every raw record or mandatory additional infrastructure.

### 4.2 Query behavior

**P0-06.** Constructors, handler loaders, and ask endpoints must perform zero navigation-node embedding calls. Load persisted vectors and validate their compatibility instead. This invariant applies even to the first request after a process restart.

**P0-07.** Preserve the intended online flow: the agent selects a search; the search query is embedded with a model compatible with the saved navigation vectors; retrieval uses those vectors. A question may lead to several distinct search queries, so the requirement is not “one embedding request per user question.”

**P0-08.** Model configuration changes must not silently compare query vectors against a different embedding space. Resolve the compatible query embedder from the active index contract or expose the semantic-unavailable state below.

**P0-09.** An in-memory cache may accelerate loading, but it is optional and never substitutes for durable persistence. Key it by source/index identity, generation, and embedding contract; invalidate when those change. Request state and authorization must remain isolated.

**P0-10.** Preserve current ranking inputs, fusion, node IDs, retrieval scope, citations, and source reads. Switching to Atlas Vector Search, changing ranking, or changing models is outside this PRD.

### 4.3 Existing indexes and failure behavior

Existing generic indexes without saved vectors require an explicit upgrade/backfill action, preferably through the existing index maintenance flow. Where saved card/profile data reconstructs the canonical nodes reliably, backfill from it without regrouping or rereading the entire source dataset. Otherwise require explicit re-indexing.

No query may trigger that backfill, change the active index, or silently invoke mass embedding.

Define an explicit semantic-unavailable behavior:

- If lexical fallback is enabled, continue lexically and expose a machine-readable warning/status that the UI/CLI/API can explain.
- If semantic retrieval is required, return a clear index-upgrade/model-compatibility error.
- Do not use fake/null vectors as a semantic index or conceal missing vectors as a semantic success.

The no-embedding-provider path may create a clearly marked lexical-only index, retaining the existing offline/test use case. Building a semantic index must fail or remain incomplete if required vectors cannot be generated.

### 4.4 P0 acceptance criteria

| ID | Required verification |
| --- | --- |
| E1 | Build an index with a counting/mock embedder. Every searchable group/collection node has a compatible persisted vector and metadata. |
| E2 | Reload the saved index in a fresh process. Handler initialization invokes no embedding provider and performs no navigation writes. |
| E3 | Execute several questions and search calls. Recorded embedding inputs contain search queries only, never the navigation corpus. |
| E4 | Rebuild unchanged content with the same embedding contract: zero node re-embeddings. Modify one node's embedding text: only changed/new nodes are embedded. |
| E5 | A model/dimension/version mismatch, corrupt vector, or missing vector cannot produce mixed-space search. The documented fallback/error is visible. |
| E6 | A simulated build failure preserves the prior usable active generation; a query during a successful publication loads one coherent generation. |
| E7 | Existing lexical-only fixtures still work. With fixed vectors, ranking and citation results match the baseline; source scope remains enforced. |
| E8 | Full request timings include handler/vector initialization, so savings are not hidden by the existing agent-only timer. |

## 5. P1 requirements: conservative parallel tool execution

### 5.1 Scope and eligibility

**P1-01.** Add a scheduler between parsing a completed model response and dispatching its tools. Limit the first release to eligible calls within that one response. Do not speculate across turns, infer missing values, generate new tool calls, or add a planning model.

**P1-02.** A call is eligible only when its actual handler has an approved read-only/parallel-safe policy, required arguments validate, reference inputs are resolved before the batch begins, request scope is fixed, no ordering-sensitive shared session/state is involved, and execution budgets allow it.

**P1-03.** Audit the three generic retrieval handlers first. Custom handlers and alternative surfaces, including the demo and `mongo_mcp`, remain sequential unless explicitly reviewed and opted in. This avoids assuming all handlers behind the shared loop behave identically.

**P1-04.** Treat unknown or ordering-sensitive operations as barriers: finish eligible preceding calls, execute the barrier in its existing order, then consider subsequent calls. Invalid arguments receive structured tool errors; they must not be guessed or treated as safe just because execution is serial.

**P1-05.** Keep reference provenance in request-local execution state, separate from model-authored text. Seed it from validated user-supplied scope/references and actual prior tool outputs. Arbitrary search text is not a reference. Distinguish a literal validated node ID from an unresolved future result.

### 5.2 Execution and result handling

**P1-06.** Use bounded concurrency, initially configurable with a conservative default cap of two calls per request. Also enforce service-wide limits so multiple requests cannot create unbounded worker, connection, or embedding-provider load. A suitable thread pool is acceptable for the current synchronous stack; a full async rewrite is not required.

**P1-07.** Worker tasks return results and timings only. The coordinator alone appends conversation messages, updates counters and gathered evidence, assigns logical trace ordering, and performs session mutations. Preserve model-issued tool-call order when merging results, regardless of completion order. Preserve each `tool_call_id` exactly.

**P1-08.** Propagate tenant, namespace overrides, authorization, request IDs, and other context explicitly to each worker. If using `ContextVar`-based context with threads, create a distinct context copy for each task. Do not share a mutable database session/cursor across concurrent calls. Review any shared model client/cache for concurrency support before opting in its handler.

**P1-09.** Preserve current read-consistency semantics. Parallel reads do not provide a shared snapshot, and serial reads do not inherently provide one either. Do not enable concurrency for ordering-sensitive or transaction/session-bound workflows without explicit support; stronger snapshot semantics are outside scope.

**P1-10.** One failed read must not discard successful siblings. Produce one result or structured error for every issued tool call before continuing the model conversation. Preserve existing citation harvesting, deduplication, limits, and error visibility.

**P1-11.** Apply per-call deadlines constrained by the remaining request budget. Stop scheduling when the budget expires. Cancellation of a Python future does not stop an in-flight network request: configure appropriate client/operation timeouts, bound outstanding work, and prevent late completions from mutating a closed session. Avoid stacking scheduler retries on provider retries.

### 5.3 Submission and budget barriers

**P1-12.** Never run `submit_answer` as a parallel worker. A submission-only response follows the existing finalization path.

If a normal response mixes submission with reads, execute permitted reads, return their results plus a structured submission-deferred response, and request a new submission using the resulting evidence. Do not silently finalize the stale draft as though it incorporated concurrent results. This correctness change needs a dedicated regression test and a budget bound.

If forced-submit mode is active, retain the current budget rule: reject further retrieval and finalize from evidence already available. Do not open another retrieval wave to repair a mixed response.

### 5.4 Rollout and acceptance criteria

Provide a separate feature flag and concurrency cap. First record scheduling decisions without changing execution; then enable concurrency for eligible calls. Rollback must restore sequential tool execution without undoing P0 embedding persistence.

| ID | Required verification |
| --- | --- |
| C1 | Two approved, fully bound read calls emitted together overlap in execution. Use synchronization primitives in tests to verify overlap, not only brittle wall-clock assertions. |
| C2 | Known-reference calls can be eligible even against the same collection; different collection names alone never establish eligibility. |
| C3 | A true search-then-use-new-ID sequence remains across sequential turns. Unresolved/invalid references receive errors rather than invented bindings. |
| C4 | Unknown/custom/stateful tools remain serial unless their actual handler policy opts in. A same-name custom replacement does not inherit approval. |
| C5 | Reverse completion order produces the same ordered tool messages, evidence union, citation processing, and counters as the serial baseline on fixed data. |
| C6 | A sibling failure or timeout leaves successful results available; every tool call receives a correctly paired response. |
| C7 | Per-request/global concurrency caps and deadlines hold under concurrent requests; late work cannot mutate finished sessions. |
| C8 | Scope/context propagation preserves tenant/namespace restrictions. No concurrent shared-session misuse occurs. |
| C9 | Mixed submission/retrieval is deferred correctly; forced-submit mode launches no extra retrieval. No protocol-orphaned tool responses occur. |
| C10 | A request with one eligible call, or zero eligible batches, stays behaviorally equivalent to sequential execution and is not reported as a parallel speedup. |

## 6. Instrumentation and success measures

Instrument these two changes without requiring a separate observability deployment:

- Full request wall time from handler entry through final response preparation; retain agent-only time as a separate metric.
- Navigation load time, node-embedding calls/input count, query-embedding calls/input count, and embedding-contract validation outcomes.
- Model time, tool execution time, and actual database/embedding sub-operations separately. The current `mongo_latency_ms` wraps entire tools and can include embeddings, so do not present it as database-only latency.
- Calls per model turn; eligible/ineligible counts and reasons; parallel batches executed; maximum concurrency; queue wait; per-call duration; batch wall time; errors/timeouts.
- Answer quality, evidence recall, source-scope compliance, and embedding/model cost per question.

For parallel batches, report summed call durations separately from batch wall time; their sum is not end-to-end latency. Any estimated serial-equivalent saving must be labeled an estimate and checked against controlled serial runs.

**P0 release gate:** zero navigation embedding calls during all ask/handler-load paths, including a cold process; durable vectors; coherent publication; fixed-vector retrieval parity; working legacy-index handling.

**P1 release gate:** concurrency is correct for the approved policies, bounded, observable, and measurably beneficial on controlled eligible batches without correctness regression. Report the real-workload eligible-batch rate. If real requests are almost entirely single-call turns, leave P1 disabled by default; do not manufacture parallelism or expand scope to justify the feature.

Measure warm/cold p50 and p95 on the same questions, data, models, and configuration. Include simple lookup, independent multi-read, dependent multi-hop, missing-data, and failure cases. Start with deterministic scheduler/vector tests and existing fixtures; use live-model runs only to assess remaining quality/latency questions. No overall latency reduction or universal accuracy advantage is assumed.

## 7. Implementation guidance for Cursor

1. Confirm the target checkout against the baseline commit. Inspect repository instructions and current behavior before editing; adapt these names to existing conventions.
2. Implement P0 in a separate change: canonical node construction, build-time embedding, durable storage/load, compatibility checks, explicit migration, and ask-path removal of corpus embedding. Update UI/CLI/API status and README accurately.
3. Verify P0 before P1. Preserve existing ranking and agent behavior so performance differences can be attributed.
4. Implement the P1 policy/argument-provenance checks and report eligibility in sequential mode. Add bounded execution only after its regression tests pass.
5. Keep code modular: node serialization, embedding persistence, tool policy, eligibility evaluation, execution, and result merging should have separate contracts. A future audited tool should require a policy/validator registration, not rewrites throughout the agent loop.
6. Produce a before/after report covering full request latency, eligible-batch frequency, quality, and costs. Update docs to distinguish implemented behavior from future options.

Suggested integration points, not a mandatory new directory structure:

| Existing file | Intended change |
| --- | --- |
| `app/retrieval/generic_tools.py` | Reuse canonical node identities; accept saved vectors; remove corpus embedding from initialization; retain query embedding. |
| `app/indexing/signals/store.py` | Build/store/load node vectors and compatibility metadata; publish coherent generations; support explicit legacy upgrades. |
| `app/llm/openai_model.py` / `app/llm/__init__.py` | Expose a reliable embedding contract; separate build/query accounting; ensure compatibility. |
| `app/retrieval/agent_loop.py` | Evaluate same-turn eligibility, dispatch through scheduler, merge results deterministically, and preserve budget/finalization rules. |
| `app/retrieval/tools.py` | Register trusted per-handler policies and argument validators without model-controlled safety flags. |
| `app/api/generic_ui.py`, `app/api/routes.py`, `app/mcp_server/server.py`, generic CLI/evaluation scripts | Ensure every generic load path honors saved vectors, full timing, and explicit fallback/upgrade status. |
| Existing generic/agent tests plus focused new tests | Cover persistence across restart, compatibility/failure handling, scheduling correctness, and protocol pairing. |

## 8. Explicit non-goals

No model replacement, conditional answer synthesis, automatic first search, tool fusion, speculative reads, answer caching, learned query classifier, cross-turn DAG planner, or intra-tool fan-out optimization. No mandatory Atlas search migration, distributed cache, or async framework rewrite. Connection pooling is a separate optimization. Existing numeric-filter/count correctness issues remain separate work and must not be declared fixed by this PRD.

Human-reviewed adaptation remains Phase 2; scheduled maintenance remains later work. Indexing/backfill is explicitly initiated, not triggered by a user question. Future indexing-signal providers remain separate from runtime tool execution policies.

## 9. Code references

All findings refer to the same `main` snapshot:

- [Generic surface initialization and query ranking](https://github.com/shekhartata/mare/blob/2de82706341536b6ed296ae53e6d95093bc73b2f/app/retrieval/generic_tools.py)
- [Generic index persistence and handler loading](https://github.com/shekhartata/mare/blob/2de82706341536b6ed296ae53e6d95093bc73b2f/app/indexing/signals/store.py)
- [Agent loop, serial tool dispatch, and submission](https://github.com/shekhartata/mare/blob/2de82706341536b6ed296ae53e6d95093bc73b2f/app/retrieval/agent_loop.py)
- [Tool schemas and dispatcher](https://github.com/shekhartata/mare/blob/2de82706341536b6ed296ae53e6d95093bc73b2f/app/retrieval/tools.py)
- [Index signal contracts](https://github.com/shekhartata/mare/blob/2de82706341536b6ed296ae53e6d95093bc73b2f/app/indexing/signals/contracts.py)
- [Index signal dependency registry](https://github.com/shekhartata/mare/blob/2de82706341536b6ed296ae53e6d95093bc73b2f/app/indexing/signals/registry.py)
- [Compiled relationship plans](https://github.com/shekhartata/mare/blob/2de82706341536b6ed296ae53e6d95093bc73b2f/app/indexing/signals/plans.py)
- [Connect-page query initialization](https://github.com/shekhartata/mare/blob/2de82706341536b6ed296ae53e6d95093bc73b2f/app/api/generic_ui.py)
- [Generic benchmark timing](https://github.com/shekhartata/mare/blob/2de82706341536b6ed296ae53e6d95093bc73b2f/scripts/run_generic_agent.py)

