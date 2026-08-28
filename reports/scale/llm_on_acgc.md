# LLM-on with ACGC compact (scale, semantic nav)

Same 20 held-out queries as [llm_on.md](llm_on.md). **MARE_ACGC default remains off.** This run is `--acgc` only (`--engine mare`). RAG was not rerun.

ACGC repo was not modified. The sidecar received `CaptureEvent` / `TriggerGC` / `GetMetrics`. Prompt compact is **in MARE** (`app/retrieval/context_compact.py`) because ACGC `GetState` returns tree stats, not node bodies. Old tool JSON is replaced with receipts (`node_id`, fields, `related_nodes`, short doc text). OpenAI tool pairing is preserved.

Sidecar: `localhost:50051`, `ACGC_TOKEN_BUDGET=8000`, `ACGC_STALE_TURNS=2`, `ACGC_GC_MAX_ACTIVE_NODES=10`, semantic off, cache-stable render on. Started with env overrides; ACGC `.env` was not edited.

## Headlines vs yesterday (no ACGC)

| | MARE + ACGC flag | MARE (llm_on.md) | RAG (llm_on.md) |
| --- | ---: | ---: | ---: |
| Answer correct | **20/20 (1.00)** | 19/20 (0.95) | 18/20 |
| Hallucination | **0/20** | 1/20 | 0/20 |
| Mean gold-evidence recall | **0.458** | 0.255 | 0.276 |
| Mean tokens | **19,662** | 40,639 | 2,134 |
| Max tokens (this sample) | 52,898 | 255,410 | — |
| Mean latency | 34.7 s | 25.4 s | 11.6 s |
| Mean tool calls / turns | 5.3 / 6.3 | 4.4 / 5.3 | 0 / 0 |

Tokens are about **52% of the no-ACGC mean**. The 255k outlier is gone (worst case here ~53k on 12-turn loops). Compact estimate on tool transcripts: **~5700 → ~2600 tokens** before the next LLM call. First-turn prompt stays ~780; last-turn prompt mean ~2960 (not climbing with the full dump).

Quality did not drop. Needle score is 20/20 on this sample (one extra hit vs yesterday; treat as noise, not a product claim). Gold-id recall also rose; more retrieve calls per query (5.3 vs 4.4).

Latency is higher (~9 s): extra turns + sidecar `CaptureEvent`/`TriggerGC` after every tool.

## Compact signal (this run)

| | Mean |
| --- | ---: |
| First-turn `prompt_tokens` | 783 |
| Last-turn `prompt_tokens` | 2,960 |
| Pre-compact size estimate | 5,707 |
| Post-compact size estimate | 2,594 |

Q019 and Q017 still spend ~12 turns / ~53k tokens (budget-capped receipts, not unbounded JSON). That is remaining agent-loop cost, not the old quadratic dump.

## How to reproduce

ACGC gRPC must be up (`./bin/acgc` in the ACGC project). Then:

```bash
pip install -e ".[acgc]"
python scripts/run_scale_llm.py --n 10000 --strategy semantic --density 20 \
  --per-category 4 --split heldout --engine mare --acgc
```

Without `--acgc` / `MARE_ACGC=false`, the tool loop is unchanged. Output: `llm_on_10000_semantic_d20_heldout_acgc.json`.
