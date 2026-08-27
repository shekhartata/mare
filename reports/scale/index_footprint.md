# Index footprint (pilot, 10K)

From `build_10000_topical_100_512.json`. Embedding tokens are **estimated** from character counts (Atlas `autoEmbed` is not metered). Index bytes are **estimated** as `vectors × 1024 × 4`. `storageSize` is measured collection bytes.

| | MARE nav | RAG chunks |
| --- | ---: | ---: |
| Persistent vectors | 418 | 60,000 |
| Ratio | 0.7% | 100% |
| Est. index bytes | 1.7 MB | 246 MB |
| Measured storageSize | 340 KB | 6.7 MB |
| Est. embedding tokens | 78k | 6.9M |
| Build wall-clock | 2.2s nodes | 11s chunk insert |
| autoEmbed index wait | ~3 min (both indexes) | ~3 min |

Extrapolation: 100K at the same chunking is ~600K RAG vectors. Index wait will dominate. Gate 50K/100K on whether you want a 20–40 minute embed cycle on this M30.
