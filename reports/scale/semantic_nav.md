# Semantic navigation (last attempt at the original thesis)

Hash-density failed: 418 → 1,513 vectors moved Recall@10 from 0.128 → 0.119. This arm changes **representation**, not density.

Hypothesis: recursive distinctive-term clustering + k-medoid prototypes, with contrastive summaries (entities, distinguishing terms, example snippets), can preserve fine-grained retrieval information at a tiny vector budget.

Stop rule, set before the run:

- Continue if held-out Recall@10 ≥ **0.20–0.22** at **<5–10%** of RAG vectors.
- Stop if Recall@10 stays in **0.12–0.15**.

## Operating point

10K docs, K=10, held-out 197 queries, RAG frozen at chunk 512. Isolated nav DB `_agent_scale_10000_semantic_d20`. Target ~20 docs/prototype, max 4 medoids per leftover neighborhood. Grouping still cannot see `topic_id`.

| Arm | Persistent vectors | vs RAG (60k) | Recall@10 | nDCG@10 | MRR | p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| RAG hybrid, chunk 512 | 60,000 | 100% | **0.230** | **0.265** | **0.488** | **436** |
| Topical hash, density 100 | 418 | 0.7% | 0.128 | 0.192 | 0.454 | 538 |
| Topical hash, density 10 | 1,513 | 2.5% | 0.119 | 0.142 | 0.254 | 1139 |
| **Semantic prototypes, target 20** | **604** | **1.0%** | **0.137** | **0.201** | **0.481** | **565** |

Offline, the same grouping on the 10K corpus produced **602** leaves with **mean majority-topic purity 0.998** (labels used only to score, never to group). Issuer / certificate / expired-token majority groups are distinct.

## By query category (Recall@10)

| Category | Topical d=100 | Semantic | RAG |
| --- | ---: | ---: | ---: |
| direct_semantic | 0.173 | 0.148 | 0.132 |
| paraphrase | 0.105 | 0.125 | 0.148 |
| fine_grained | 0.036 | 0.046 | **0.373** |
| rare | 0.191 | 0.191 | 0.286 |
| similar_distractors | 0.080 | 0.135 | **0.486** |

Paraphrase and similar-distractors moved in the right direction. Fine-grained did not. Overall recall is **0.137** — inside the stop band, **−9.3 points** vs RAG (60% of RAG recall).

## Verdict

**The original “near-RAG semantic quality with far fewer vectors” thesis is not supported.**

What worked: semantic organization. One navigation vector per ~17 documents, 1% of RAG’s vectors, almost-perfect topic purity, MRR 0.481 vs RAG 0.488. Broad-topic hit rate is real.

What did not: equal-budget Recall@10, especially fine-grained sibling distinction (0.046 vs 0.373). Gold sets are a 10-doc slice of a topic; the index splits that topic across many pure prototypes, then the retriever fills K=10 from the first groups. Finding the neighborhood (MRR) is not the same as recovering the gold slice (recall). Chunk-level embeddings still do that job; group-level prototypes do not, at this budget and this metric.

Do not scale this to 100K/1M. Do not sweep 1:5 / 1:2. Do not tune the agent loop to recover this scoreboard. The representation change was the last serious attempt at MARE as a general semantic RAG alternative.

Files: `build_10000_semantic_20_512.json`, `retrieval_10000_k10_heldout_semantic_d20.json`.
