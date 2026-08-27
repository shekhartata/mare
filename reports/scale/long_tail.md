# Long-tail recall (pilot, 10K, K=10)

Held-out breakout from `retrieval_10000_k10_heldout.json`.

## By frequency tier

| Tier | MARE Recall@10 | RAG Recall@10 |
| --- | ---: | ---: |
| common | 0.057 | 0.285 |
| medium | 0.067 | 0.101 |
| rare | 0.245 | 0.249 |

Rare-topic recall is **not** the place MARE collapses at this density. Common topics are, because gold sets are larger and Top-K=10 cannot cover them on either engine — but RAG still covers more.

## By query category

| Category | MARE | RAG |
| --- | ---: | ---: |
| direct_semantic | 0.173 | 0.132 |
| paraphrase | 0.105 | 0.148 |
| fine_grained | 0.036 | 0.373 |
| rare | 0.190 | 0.286 |
| similar_distractors | 0.080 | 0.486 |

Fine-grained sibling distinction and same-symptom / different-customer distractors are where coarse topical groups lose. Direct semantic is the only category where MARE matched or beat RAG on this run.
