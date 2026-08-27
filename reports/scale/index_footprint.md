# Index footprint (10K)

Embedding tokens are **estimated** from character counts (Atlas `autoEmbed` is not metered). Index bytes are **estimated** as `vectors × 1024 × 4`. `storageSize` is measured collection bytes. RAG column is the original chunk-512 build (`build_10000_topical_100_512.json`).

| | d=10 | d=20 | d=50 | d=100 | RAG chunks |
| --- | ---: | ---: | ---: | ---: | ---: |
| Persistent vectors | 1,513 | 947 | 664 | 418 | 60,000 |
| vs RAG | 2.5% | 1.6% | 1.1% | 0.7% | 100% |
| Est. index bytes | 6.2 MB | 3.9 MB | 2.7 MB | 1.7 MB | 246 MB |
| Est. nav embed tokens | 212k | 151k | 114k | 78k | 6.9M |
| Nav index wait | ~67s | ~72s | ~56s | ~3 min (with RAG) | ~3 min |

The 10K RAG index wait remains the slow step. Nav-only rebuilds for the density sweep were about one minute each. 100K at the same chunking is still ~600K RAG vectors; do not spend that cycle until navigation quality is in range of RAG.

