# Ask latency: index cache, cheaper search, fewer turns, fewer rewrites

Four changes, measured against commit `31e09e9` in the same session. Both trees ran side by side against the same Atlas cluster and the same OpenAI models (`gpt-5-mini` agent, `gpt-5` answer model). Across days this environment moved by up to 60%, so only same-session pairs are compared.

| Change | What it does |
| --- | --- |
| Index cache | The loaded cards and vectors are kept per process while the active `build_id` and the embedding contract are unchanged. Each ask reads only the catalog's `build_id` and still gets a fresh surface and reader. |
| Search reads | Within one ask, repeated reads and query embeddings are reused. Cards whose collection has no hop plan are not read. Members of several cards in one collection are read together, and `_id` hop targets are resolved in one read per target. When the question names a document, that document's hops are bound first, and hit cards are read only if it has none. |
| Rewrite skip | `MARE_SYNTHESIS=auto` (default) keeps the agent's answer when it cites at least one document, every cited id is a document read in this ask, and the loop did not stop on budget. Otherwise the answer model rewrites it as before. `MARE_SYNTHESIS=always` restores the old behavior. |
| Stall stop | After two tool turns that return no new document, node, or first-time empty query, the agent is asked to submit with what it has (`stop_reason` `no_new_evidence`, status complete). It only applies after at least one document read. Repeat reads carry a note saying the documents were already returned. |

The system prompts are unchanged. A reworded prompt that discouraged extra hops was tried and removed: it made the demo agent skip incident documents on bridge, distributed, and deep questions (6/9 vs 8/9).

## Generic index, `mi_transformation` (6 questions, 2 rounds each)

`scripts/run_latency_set.py`. Each question lists values the answer must contain.

| | Before | After |
| --- | ---: | ---: |
| Answers with every expected value | 12/12 | 12/12 |
| Mean request | 29.6 s | 14.3 s |
| Model time | 22.0 s | 11.8 s |
| Mongo and embedding time | 3.4 s | 1.9 s |
| Index load, after the first ask | 4,081 ms | 70 ms |
| Turns | 4.8 | 3.5 |
| Tokens | 9,316 | 6,888 |
| Answers rewritten by `gpt-5` | 12 | 1 |

| Question | Before | After |
| --- | ---: | ---: |
| Desktop underwriter recommendation, price, and loan amount | 24.7 s | 9.5 s |
| Raw payload and loan for quote `5ce9fcf5…` | 33.8 s | 12.2 s |
| Loan for order `74546ada…` | 26.4 s | 10.1 s |
| Loan purpose behind the underwriting message | 27.6 s | 16.5 s |
| Trading partner `A0000094` status and MISMO version | 27.4 s | 16.2 s |
| Event `6ac3f1d8…` type and loan | 37.7 s | 21.5 s |

The first ask in a process still loads the index (7.1 s here).

## Demo suite, `mare_demo` (`scripts/run_comparison.py`, MARE blind)

| Run | Before correct | After correct | Before mean | After mean |
| --- | ---: | ---: | ---: | ---: |
| Round 2 | 8/9 | 8/9 | 38.9 s | 23.2 s |
| Final | 7/9 | 6/9 | 39.0 s | 21.9 s |

Round 2 ran before the last change: a line in the `submit_answer` description asking the agent to name the entity a question describes. Without a rewrite, the agent's answer to the bridge question gave the right cause but did not name the customer. The final round includes that line. Tokens per question fell from 18.2k to 15.3k and turns from 7.0 to 5.8 in the final round.

Bridge, distributed, and deep fail intermittently on both versions. The final-round misses were rerun three more times each:

| Case | Before, final + reruns | After, final + reruns |
| --- | ---: | ---: |
| bridge | 0/1 (2/2 in earlier rounds) | 2/4 |
| distributed | 2/4 | 2/4 |
| vk_deep | 3/4 | 3/4 |

The final-round `vk_deep` miss on the new code read no documents. The agent took "the last three months" relative to today's date while the data is from 2024, its date-filtered queries returned nothing, and it asked for clarification. No rewrite was involved, because nothing was gathered.

## Utility suite (`scripts/run_generic_agent.py --utility`)

| | Before | After |
| --- | ---: | ---: |
| Correct | 3/3 | 3/3 |
| Mean request | 25.5 s | 13.1 s |

## Unchanged results

With an in-memory reader and without one, the search, retrieve, hop, and query outputs of the old and new tool code were compared on the shop, utility, and warehouse fixtures before the named-document change. That covered 208 calls producing 446 related nodes, and the outputs were byte-identical.

## Remaining cost: time-series `_id` reads

`event_transactions` is a time-series collection, so `_id` has no index. A read of about 110 of its documents by `_id` takes 7–11 s on the server. A single-id read takes about 50 ms. This read happens when search hits several `event_transactions` cards (the partner and underwriter questions above) and is the same before and after. It accounts for most of the remaining Mongo time.

---

# Earlier: loan-purpose question, before and after saved navigation vectors

Question: "What loan purpose is on the loan instance that the automated underwriting system response message points to?"

Both runs answered Purchase and cited `mare_lat_hop.au_system_response_messages:da13d9c6-75b1-5289-8336-2be1f807a8e9` and `mare_lat_hop.api_loan_instances:415c5349-d293-5e99-9e29-34949c4b8c54`. Same path: 4 turns, 3 tool calls.

The cluster used for the live UI was unreachable from this machine (TCP timeout to all three Atlas shard hosts). The comparison is a local mongod with those two documents and the same question. The index has 4 navigation nodes, not the 95-node `mi_transformation` index. Parallel tool execution stayed off, so this delta is the saved navigation vectors only.

| | Before | After |
| --- | ---: | ---: |
| Load saved index | 4,526 ms | 1 ms |
| Navigation embeds during the ask | 4 texts, 4,525 ms | 0 |
| Query embed | 1,141 ms | 1,269 ms |
| Answer model | 16,241 ms | 12,766 ms |
| Full request | 21,920 ms | 14,052 ms |

Building the vectors once, outside the ask, took 1,305 ms for the same 4 texts. Later asks reuse them.

The code change removes one embedding round trip from every question. On the before run that round trip was 4.5 seconds, so load time went from 4,526 ms to 1 ms. The full request fell from 21.9 s to 14.1 s. About 3.5 s of that gap is the answer model finishing faster (16.2 s vs 12.8 s), which this change does not control. The query embedding and the three tool calls are still inside the request.

On the real index the same change removes one or two embedding calls (95 texts, batches of 64) from each question. It does not shorten the read that pulls every id on the 76,912-id loan card. That read is still a follow-up.
