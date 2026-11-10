# Scale / vector-efficiency benchmark

Two different questions. Do not collapse them into one quality-vs-vectors sentence in the product README.

| | What was measured | Result |
| --- | --- | --- |
| **LLM-off** | Can the navigation index match chunk-level RAG retrieval? | **No.** Semantic nav Recall@10 is 0.137 vs RAG 0.230. |
| **LLM-on** | Can the agent, with that weaker index plus Mongo tools, match RAG *answers*? | **On a 20-query sample, yes on needle correctness** (19/20 vs 18/20), at ~1% of RAG vectors. The 10 Nov receipts run is **21 s** and **13.8k tokens** against RAG at **12 s** and **2.1k**. |

LLM-off used 197 held-out queries. LLM-on used 20 of those (4 per category). On the 10 Nov receipts run, gold-id recall is **0.35** for MARE and **0.28** for RAG. Chunk-level Recall@10 of the navigation index stays **0.137**.

## LLM-off: retrieval only (197 held-out, K=10)

RAG frozen at chunk 512. No answer generation.

| Arm | Vectors | vs RAG | Recall@10 | nDCG@10 | MRR |
| --- | ---: | ---: | ---: | ---: | ---: |
| RAG | 60,000 | 100% | **0.230** | **0.265** | **0.488** |
| Topical 1:10 | 1,513 | 2.5% | 0.119 | 0.142 | 0.254 |
| Topical 1:20 | 947 | 1.6% | 0.119 | 0.162 | 0.342 |
| Topical 1:50 | 664 | 1.1% | 0.119 | 0.171 | 0.400 |
| Topical 1:100 | 418 | 0.7% | 0.128 | 0.192 | 0.454 |
| Semantic prototypes | 604 | 1.0% | 0.137 | 0.201 | 0.481 |

Hash density has no quality knee — more vectors on the same lossy summaries made nDCG worse. Semantic grouping recovered topic identity (offline purity 0.998, MRR ≈ RAG) but Recall@10 stayed at 0.137. Fine-grained remains ~0.05 vs RAG 0.37.

Full write-up: [density_pareto.md](density_pareto.md), [semantic_nav.md](semantic_nav.md), [long_tail.md](long_tail.md).

## LLM-on: agent vs RAG answers (20 held-out)

Same semantic nav (604 vectors). Blind agent (`gpt-5-mini` tools, `gpt-5` answers) vs hybrid Top-K RAG (`gpt-5`). Scoring is vocabulary needles plus gold document ids, not a human or LLM judge. The table below is the earlier full-history loop.

| | MARE | RAG |
| --- | ---: | ---: |
| Persistent vectors | 604 (1%) | 60,000 |
| Answer correct | **19/20** | 18/20 |
| Hallucination flag | 1/20 (`draft` cite, not a fake incident) | 0/20 |
| Mean gold-evidence recall | 0.26 | 0.28 |
| Mean latency | 25 s | 12 s |
| Mean tokens | 40.6k | 2.1k |
| Mean tool calls | 4.4 | 0 |

Fine-grained answers were 4/4 needle-correct on both engines, while MARE gold-slice recall there was 0.03 vs RAG 0.28 — the agent names the cause from the neighborhood without recovering the same gold ids.

Full write-up (vanilla, full tool JSON): [llm_on.md](llm_on.md). The 10 Nov receipts rerun, same 20 questions and the same 604-vector index, is **19/20**, gold-id recall **0.35**, **21 s**, **13.8k** tokens, 5.0 tool calls. RAG on that run is **18/20**, **12 s**, **2.1k**. August ablation: [llm_on_acgc_ablation.md](llm_on_acgc_ablation.md). Opt-in ACGC sidecar: [llm_on_acgc.md](llm_on_acgc.md).

## Commands

```bash
python scripts/seed_scale.py --n 10000
python scripts/build_scale.py --n 10000 --strategy topical --density 100 --chunk-size 512
python scripts/run_scale_retrieval.py --n 10000 --budget 10 --split heldout

python scripts/build_scale.py --n 10000 --strategy semantic --density 20 --chunk-size 512 --skip-rag
python scripts/run_scale_retrieval.py --n 10000 --budget 10 --split heldout --engine mare --density 20 --strategy semantic
python scripts/run_scale_llm.py --n 10000 --strategy semantic --density 20 --per-category 4 --split heldout
```

## Files

| File | Meaning |
| --- | --- |
| `build_*.json` | Index build wall-clock, vector counts, embedding-token estimates |
| `retrieval_*_d{N}.json` | MARE-only retrieval at density N |
| `retrieval_*_semantic_d20.json` | Semantic-prototype arm |
| `retrieval_10000_k10_heldout.json` | Topical density 100 + RAG |
| `llm_on_*.json` | Per-query LLM-on scores |
| `churn_*.json` | Update amplification |
| `density_pareto.md` | Hash-density curve |
| `semantic_nav.md` | Representation change + stop criterion |
| `llm_on.md` | End-to-end agent vs RAG answers |
| `llm_on_acgc.md` | Same 20 queries with opt-in [ACGC](https://github.com/shekhartata/acgcProject) compact |
| `llm_on_acgc_ablation.md` | A vanilla vs B receipts-only vs C sidecar |
| `long_tail.md` | Category and frequency-tier breakout |
| `update_cost.md` | Churn (density 100 only) |
| `index_footprint.md` | Vector / byte estimates |
