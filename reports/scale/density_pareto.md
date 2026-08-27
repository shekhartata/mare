# Density Pareto (pilot)

One operating point so far. **Not a curve.** Do not read this as the original thesis being confirmed.

## 10K documents, held-out 197 queries, budget K=10

| Arm | Persistent vectors | Vector ratio vs RAG | Recall@10 | nDCG@10 | p50 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| RAG hybrid, chunk 512 / overlap 10% | 60,000 | 100% | 0.230 | 0.265 | 436 |
| MARE topical, ~1 group / 100 docs | 418 | **0.7%** | 0.128 | 0.192 | 538 |

Absolute recall gap: **−10.2 points** (MARE is 55% of RAG recall). That is outside the 1–3 point target. Index wait for this build was ~3 minutes (autoEmbed).

Next measurements needed: densities 20 / 50 / 250 / 500, chunk sizes 256 and 1024 on the dev split, then freeze RAG and re-run held-out.

See `build_10000_topical_100_512.json` and `retrieval_10000_k10_heldout.json`.
