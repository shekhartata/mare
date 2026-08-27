# Density Pareto (10K)

Held-out 197 queries, budget K=10, topical TF-IDF groups, RAG frozen at chunk 512. MARE arms 10 / 20 / 50 were built into isolated nav DBs (`_agent_scale_10000_d{N}`) without rebuilding RAG. Density 100 is the earlier pilot (`_agent_scale_10000`).

Vector ratios use the original RAG build of **60,000** chunk vectors. Skip-rag `count_documents` later read 58,066; that drift does not change the quality comparison.

## Overall

| Arm | Persistent vectors | vs RAG | Recall@10 | nDCG@10 | MRR | p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| RAG hybrid, chunk 512 | 60,000 | 100% | **0.230** | **0.265** | **0.488** | **436** |
| MARE density 10 | 1,513 | 2.5% | 0.119 | 0.142 | 0.254 | 1139 |
| MARE density 20 | 947 | 1.6% | 0.119 | 0.162 | 0.342 | 836 |
| MARE density 50 | 664 | 1.1% | 0.119 | 0.171 | 0.400 | 531 |
| MARE density 100 | 418 | 0.7% | 0.128 | 0.192 | 0.454 | 538 |

There is **no quality–cost knee** on this axis. Spending 3.6× more navigation vectors (1,513 vs 418) did not recover RAG recall. Overall recall is flat at ~0.12. nDCG and MRR **worsen** as groups get smaller. Density 100 remains the least-bad **hash-grouped** MARE point, and it is still **−10.2 recall points** vs RAG (56% of RAG recall). The 1–3 point target is not in range of this grouping method.

A later **semantic prototype** arm (604 vectors, 1.0% of RAG) reached Recall@10 **0.137** / MRR **0.481**. That is still in the 0.12–0.15 stop band. See [semantic_nav.md](semantic_nav.md).

## By query category (Recall@10)

| Category | d=10 | d=20 | d=50 | d=100 | RAG |
| --- | ---: | ---: | ---: | ---: | ---: |
| direct_semantic | 0.128 | 0.151 | 0.154 | **0.173** | 0.132 |
| paraphrase | 0.100 | 0.099 | 0.101 | 0.105 | 0.148 |
| fine_grained | 0.055 | 0.046 | 0.036 | 0.036 | **0.373** |
| rare (category) | 0.202 | 0.214 | 0.191 | 0.191 | 0.286 |
| similar_distractors | 0.109 | 0.064 | 0.075 | 0.080 | **0.486** |

Fine-grained and similar-distractors stay broken at every density. The one MARE win (direct semantic) is **strongest at the coarsest density** and disappears at 1:10.

## By frequency tier (Recall@10)

| Tier | d=10 | d=20 | d=50 | d=100 | RAG |
| --- | ---: | ---: | ---: | ---: | ---: |
| common | 0.054 | 0.037 | 0.045 | 0.057 | 0.285 |
| medium | 0.047 | 0.049 | 0.052 | 0.067 | 0.101 |
| rare | 0.236 | 0.253 | 0.244 | 0.245 | 0.249 |

Rare-topic recall stays tied with RAG at every density. Common-topic recall does not move.

## How to read this

The density knob in the current builder is **not semantic resolution**. Oversized TF-IDF buckets split by month, then by `md5(_id)`. Finer density makes more groups with **near-duplicate summaries**, which hurts navigation (nDCG/MRR down, latency up) without separating invalid-issuer from expired-cert, or customer A from customer B.

That is why extra vectors here are not a Pareto trade. They are a more expensive version of the same partition.

## What this does *not* decide

- 250 / 500 (coarser than 100): not run; overall recall is already insensitive from 10→100, so coarser is unlikely to close a 10-point gap.
- 50K / 100K: not needed to see that this navigation representation is underpowered.
- Multiple embeddings on the **same** `document_ids` bag: would not change the second-stage lexical ranking.

The semantic-split follow-up **was** measured: [semantic_nav.md](semantic_nav.md). It recovered topic purity and MRR, not Recall@10.

## Files

- `build_10000_topical_{10,20,50,100}_512.json`
- `retrieval_10000_k10_heldout_d{10,20,50}.json`
- `retrieval_10000_k10_heldout.json` (density 100 + RAG)
- `build_10000_semantic_20_512.json`, `retrieval_10000_k10_heldout_semantic_d20.json`
