# Scale / vector-efficiency benchmark

This directory holds **measurements**, not claims. Do not update the top-level README with a quality-vs-vectors sentence until a held-out run exists.

## What is implemented

- Corpus: `app/datagen/scale_corpus.py` (100K-capable, nested 10K prefix for gold).
- Topical navigation: `app/indexing/topical_grouping.py` (TF-IDF; never reads `topic_id`).
- Equal-budget retrieval (no LLM): `app/eval/pipelines.py`, `scripts/run_scale_retrieval.py`.
- Footprint estimates: `app/eval/accounting.py`.
- Churn: `scripts/run_churn_bench.py` (scattered vs clustered).

## Run order (pilot = 10K)

```bash
python scripts/seed_scale.py --n 10000
python scripts/build_scale.py --n 10000 --strategy topical --density 100 --chunk-size 512
python scripts/run_scale_retrieval.py --n 10000 --budget 10 --split heldout
python scripts/run_churn_bench.py --n 10000 --pct 5 --pattern scattered
python scripts/run_churn_bench.py --n 10000 --pct 5 --pattern clustered
```

Index builds wait for Atlas `autoEmbed`. The 10K RAG index became queryable in ~3 minutes on the current M30. 100K will be several times that.

## Pilot result (10K, density 100, K=10, held-out)

MARE used **0.7%** as many persistent vectors as RAG (418 vs 60,000) and cheaper churn (~0.5 vs ~4 vectors per changed doc). Held-out Recall@10 was **0.128 vs 0.230** (−10 points). Fine-grained and similar-distractor queries are where MARE lost. Direct semantic was the one category MARE matched. Full write-up: [density_pareto.md](density_pareto.md), [long_tail.md](long_tail.md), [update_cost.md](update_cost.md), [index_footprint.md](index_footprint.md).

## Density sweep (10K)

```text
python scripts/build_scale.py --n 10000 --strategy topical --density {20,50,100,250,500}
python scripts/build_scale.py --n 10000 --strategy entity --density 0
```

Chunk-size sweep (rebuilds RAG only; reuse nav): `--chunk-size {256,512,1024}`.

## Files this directory will grow

| File | Meaning |
| --- | --- |
| `build_*.json` | Index build wall-clock, vector counts, embedding-token estimates |
| `retrieval_*.json` | Recall@K / long-tail / latency |
| `churn_*.json` | Update amplification |
| `density_pareto.md` | Fill after the 10K density sweep |
| `long_tail.md` | Fill from `by_tier` in retrieval JSON |
| `update_cost.md` | Fill from churn JSON |
| `index_footprint.md` | Fill from build JSON |

Measurements have not been produced yet.
