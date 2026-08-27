# Long-tail recall (10K, K=10)

Density 100 numbers from `retrieval_10000_k10_heldout.json`. Densities 10 / 20 / 50 from `retrieval_10000_k10_heldout_d{N}.json`.

## By frequency tier (Recall@10)

| Tier | d=10 | d=20 | d=50 | d=100 | RAG |
| --- | ---: | ---: | ---: | ---: | ---: |
| common | 0.054 | 0.037 | 0.045 | 0.057 | 0.285 |
| medium | 0.047 | 0.049 | 0.052 | 0.067 | 0.101 |
| rare | 0.236 | 0.253 | 0.244 | 0.245 | 0.249 |

Rare-topic recall is **not** where MARE collapses, at any density in this sweep. Common topics stay far behind RAG because gold sets are larger and Top-K=10 cannot cover them — but RAG still covers more, and shrinking groups does not close that gap.

## By query category (Recall@10)

| Category | d=10 | d=20 | d=50 | d=100 | RAG |
| --- | ---: | ---: | ---: | ---: | ---: |
| direct_semantic | 0.128 | 0.151 | 0.154 | 0.173 | 0.132 |
| paraphrase | 0.100 | 0.099 | 0.101 | 0.105 | 0.148 |
| fine_grained | 0.055 | 0.046 | 0.036 | 0.036 | 0.373 |
| rare | 0.202 | 0.214 | 0.191 | 0.191 | 0.286 |
| similar_distractors | 0.109 | 0.064 | 0.075 | 0.080 | 0.486 |

Fine-grained sibling distinction and same-symptom / different-customer distractors stay near zero across the dense sweep. Direct semantic is the only category where MARE beat RAG, and only at the **coarser** densities.
