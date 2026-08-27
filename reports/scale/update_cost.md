# Update cost (pilot, 10K, 5% churn)

500 source documents changed. RAG chunk size 512. MARE topical density 100.

| Pattern | Engine | Vectors invalidated | Vectors regenerated | Amplification |
| --- | --- | ---: | ---: | ---: |
| scattered | MARE | 268 | 268 | 0.54 |
| scattered | RAG | 3000 | 2012 | 4.02 |
| clustered | MARE | 264 | 264 | 0.53 |
| clustered | RAG | 2953 | 2007 | 4.01 |

MARE regenerates fewer vectors per changed document. Clustered vs scattered barely differs here because groups are **topical**, not per-customer, so 500 docs from a few customers still dirty hundreds of neighborhoods.

MARE numbers count dirty group nodes (the incremental path). They are not a full `build_hierarchy` rebuild. RAG numbers are actual chunk delete+insert.

See `churn_10000_scattered_5.json` and `churn_10000_clustered_5.json`.
