# LLM-on ablation: vanilla vs receipts vs ACGC sidecar

Same 20 held-out queries as [llm_on.md](llm_on.md). Default loop is now B.

| Arm | What ran |
| --- | --- |
| **A** vanilla | Existing `llm_on_10000_semantic_d20_heldout.json` |
| **B** receipts only | Default / `--compact` — MARE `context_compact.py`, **no** ACGC gRPC |
| **C** receipts + sidecar | Existing `--acgc` run — compact **and** CaptureEvent/TriggerGC |

RAG columns are from A (not rerun).

## Headlines

| | A vanilla | B receipts | C + sidecar | RAG |
| --- | ---: | ---: | ---: | ---: |
| Answer correct | 19/20 | 19/20 | 20/20 | 18/20 |
| Gold-id recall | 0.255 | 0.322 | 0.458 | 0.276 |
| Mean tokens | 40.6k | **15.7k** | 19.7k | 2.1k |
| Max tokens | 255k | **44k** | 53k | — |
| Latency | 25.4 s | 36.8 s | 34.7 s | 11.6 s |
| Tool calls / turns | 4.4 / 5.3 | 4.5 / 5.6 | 5.3 / 6.3 | 0 |
| First-turn prompt | — | 783 | 783 | — |
| Last-turn prompt | — | 2,438 | 2,960 | — |
| Pre → post compact est. | — | 5.3k → 2.3k | 5.7k → 2.6k | — |

**Almost all of the token cut is B.** C is not cheaper than B (19.7k vs 15.7k). The sidecar did not add incremental token savings on this sample. Receipts also kill the 255k outlier (B 44k / C 53k).

**Latency +9–11 s vs vanilla is in both B and C**, so it is mostly extra model time / slightly longer loops, not gRPC-after-every-tool. C is not slower than B.

**Gold 0.46 in C does not replicate in B** (0.32). Fine-grained gold-id stays **0.025 in A and B**; C’s 0.60 is Q095/Q097 going 0→1.0 with more retrieves. Treat C’s quality bump as run noise until it shows up without the sidecar too.

## Gold-id by category

| Category | A | B | C | RAG |
| --- | ---: | ---: | ---: | ---: |
| direct_semantic | 0.33 | 0.27 | 0.23 | 0.27 |
| fine_grained | 0.03 | 0.03 | **0.60** | 0.28 |
| paraphrase | 0.17 | 0.13 | 0.15 | 0.15 |
| rare | 0.38 | 0.31 | 0.31 | 0.19 |
| similar_distractors | 0.38 | 0.88 | 1.00 | 0.50 |

## What this supports

```text
A  40.6k   full tool JSON replay
B  15.7k   MARE receipts          ← the ACGC-shaped win in this integration
C  19.7k   receipts + sidecar     ← no extra token win; more turns
```

For **ACGC as a product**: this integration does not yet show GC/policy beating application-level compact. `GetState` still does not feed the OpenAI messages. Re-test C vs B after the compiled working set actually comes from ACGC.

For **MARE**: receipts are enough to go from ~19× RAG tokens to ~7× (15.7k / 2.1k), with bounded last-turn prompts. Default loop is now B (`MARE_COMPACT=true`). Vanilla A is `--no-compact`. Sidecar stays opt-in (`MARE_ACGC=false`).

## Reproduce B

```bash
python scripts/run_scale_llm.py --n 10000 --strategy semantic --density 20 \
  --per-category 4 --split heldout --engine mare --compact
```

No sidecar. Output: `llm_on_10000_semantic_d20_heldout_compact.json`.
