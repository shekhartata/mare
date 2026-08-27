# LLM-on end-to-end (scale, semantic nav)

Does **not** replace the LLM-off retrieval reports. Those already answered: the navigation index alone does not match chunk-level RAG Recall@10.

This run asks the broader original question: **can an agent, given ~1% as many persistent vectors plus Mongo tools, answer as well as RAG?**

## Setup

- Corpus: 10K scale incidents, same held-out gold as LLM-off.
- Sample: **20 queries**, 4 per category, first by `query_id` (deterministic). Not the full 197.
- MARE: blind agent (`gpt-5-mini` tools, `gpt-5` answers), semantic nav `_agent_scale_10000_semantic_d20`, tenant `scale`, max 10 turns / 90s.
- RAG: hybrid Top-K over `_rag_scale_10000` chunks, one `gpt-5` answer.
- Scoring: deterministic needles from topic vocabulary (allowed to use `topic_id` here), gold document-id recall, citation inventiveness. No LLM-as-judge.

## Headlines

| | MARE | RAG |
| --- | ---: | ---: |
| Persistent vectors | 604 | 60,000 (build) / 58,066 (collstats) |
| Vector ratio | **1.0%** | 100% |
| Answer correct | **19/20 (0.95)** | 18/20 (0.90) |
| Hallucination (invented cite or sibling leak) | 1/20 (0.05) | 0/20 |
| Mean gold-evidence recall | 0.255 | 0.276 |
| Mean citation recall | 0.255 | 0.276 |
| Mean latency | 25.4 s | 11.6 s |
| Mean LLM tokens | 40,639 | 2,134 |
| Mean tool calls / agent turns | 4.4 / 5.3 | 0 / 0 |

The one MARE “hallucination” is a `draft` citation id, not a fabricated incident. Both engines missed the same paraphrase (Q019, connection-pool saturation). RAG also missed a rare resolver question (Q054) that MARE got.

## By category (correct rate / gold-evidence recall)

| Category | MARE correct | RAG correct | MARE gold R | RAG gold R |
| --- | ---: | ---: | ---: | ---: |
| direct_semantic | 4/4 | 4/4 | 0.33 | 0.27 |
| fine_grained | 4/4 | 4/4 | **0.03** | 0.28 |
| paraphrase | 3/4 | 3/4 | 0.17 | 0.15 |
| rare | 4/4 | 3/4 | 0.38 | 0.19 |
| similar_distractors | 4/4 | 4/4 | 0.38 | 0.50 |

Fine-grained is the important split: **the agent names the right cause (needle-correct) while still almost never retrieving the gold document slice.** That is the MRR story in LLM form — it gets into the right neighborhood, then answers from whatever records it reads there. RAG still wins gold-id recall on that class.

## What this supports

Keep the claims separate:

1. **LLM-off:** MARE is not a drop-in semantic index. Recall@10 0.137 vs 0.230.
2. **LLM-on (this 20-query sample):** the agentic loop can **match or beat RAG answer correctness** on this needle spec while storing **~1% of the vectors**, at **~2× latency** and **~19× tokens**.

That is closer to the original thesis than the retrieval-only scoreboard. It is not yet a 197-query held-out proof, and correctness here is vocabulary needles, not human judgment of completeness.

## Files

- `llm_on_10000_semantic_d20_heldout.json`
- LLM-off curve unchanged: [density_pareto.md](density_pareto.md), [semantic_nav.md](semantic_nav.md)
