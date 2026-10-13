# Generic MARE vs RAG

- generated: 2026-10-13T10:14:29.251697+00:00
- answering model: `gpt-5`
- embeddings: openai hybrid

Generic MARE is one `investigate` call plus this answer model. It is not the SaaS tool loop. RAG is hybrid Top-K over one chunk per document, in memory, because these fixtures are not in Atlas.

These corpora have 5 and 7 documents, so K=8 is the whole database. K=1 is the single nearest chunk.

Vectors: mare_shop cards **3** / chunks **5**; mare_warehouse cards **3** / chunks **7**.

| case | kind | MARE | recall | ms | tok | RAG K=1 | recall | ms | tok | RAG K=8 | recall | ms | tok |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Shop lookup | lookup | yes | 1.00 | 8406 | 771 | yes | 1.00 | 3935 | 314 | yes | 1.00 | 2428 | 393 |
| Shop hop | hop | yes | 1.00 | 8123 | 831 | yes | 0.00 | 6568 | 373 | yes | 1.00 | 12841 | 587 |
| Shop count | count | yes | 1.00 | 9351 | 631 | yes | 1.00 | 4219 | 238 | yes | 1.00 | 4941 | 580 |
| Shop absence | absence | yes | n/a | 9763 | 710 | yes | n/a | 6865 | 501 | yes | n/a | 13214 | 843 |
| Warehouse lookup | lookup | yes | 1.00 | 7246 | 675 | yes | 1.00 | 5312 | 412 | yes | 1.00 | 5365 | 600 |
| Warehouse count | count | yes | 1.00 | 9812 | 755 | yes | 1.00 | 5509 | 363 | yes | 1.00 | 4451 | 529 |
| Warehouse absence | absence | yes | n/a | 6058 | 523 | yes | n/a | 8185 | 430 | yes | n/a | 8424 | 794 |
| Warehouse hop | hop | yes | 1.00 | 7634 | 743 | yes | 0.00 | 3406 | 216 | yes | 1.00 | 4852 | 530 |
| mean |  | **8/8** |  | **8299** | **705** | **8/8** |  | **5500** | **356** | **8/8** |  | **7064** | **607** |

## What differed

Hops, gold-document recall:

- Shop hop: MARE returned orders:ord_1044. RAG K=1 returned refunds:ref_9. The answer was on that chunk, so the model still matched.
- Warehouse hop: MARE returned skus:sku_bolt. RAG K=1 returned bins:bin_a3. The answer was on that chunk, so the model still matched.

Absence:

- Shop absence: MARE receipt is an exact count of 0 over collection. RAG K=1 answered from orders:ord_2001.
- Warehouse absence: MARE receipt is an exact count of 0 over collection. RAG K=1 answered from movements:mov_1.

## Answers

### Shop lookup

What is the status of order ord_1044?

MARE: Shipped [orders ord_1044]

receipt exact=True count=1 absence_scope=None docs=orders:ord_1044 tokens=771 ms=8406

RAG K=1: Status: shipped. [ord_1044]

docs=orders:ord_1044 tokens=314 ms=3935

RAG K=8: Shipped [orders ord_1044]

docs=orders:ord_1044, orders:ord_2001, refunds:ref_9, products:sku_mug, products:sku_wool tokens=393 ms=2428

### Shop hop

Which order was refunded because a sweater pilled after one wash?

MARE: ord_1044 [ref_9; ord_1044]

receipt exact=False count=1 absence_scope=None docs=orders:ord_1044 tokens=831 ms=8123

RAG K=1: ord_1044 [ref_9]

docs=refunds:ref_9 tokens=373 ms=6568

RAG K=8: ord_1044 [ref_9]

docs=refunds:ref_9, products:sku_wool, orders:ord_1044, orders:ord_2001, products:sku_mug tokens=587 ms=12841

### Shop count

How many refunds are for sku_wool?

MARE: 1 [ref_9]

receipt exact=True count=1 absence_scope=None docs=refunds:ref_9 tokens=631 ms=9351

RAG K=1: 1 [ref_9]

docs=refunds:ref_9 tokens=238 ms=4219

RAG K=8: 1 [ref_9]

docs=refunds:ref_9, orders:ord_1044, products:sku_wool, orders:ord_2001, products:sku_mug tokens=580 ms=4941

### Shop absence

How many refunds are for sku_mug?

MARE: 0

receipt exact=True count=0 absence_scope=collection docs=(none) tokens=710 ms=9763

RAG K=1: 0 [ord_2001]

docs=orders:ord_2001 tokens=501 ms=6865

RAG K=8: 0 [refunds ref_9; products sku_mug]

docs=orders:ord_2001, products:sku_mug, orders:ord_1044, refunds:ref_9, products:sku_wool tokens=843 ms=13214

### Warehouse lookup

Where is bin_a3?

MARE: In location code A3. [bins bin_a3]

receipt exact=True count=1 absence_scope=None docs=bins:bin_a3 tokens=675 ms=7246

RAG K=1: bin_a3 is at location code A3. [bin_a3]

docs=bins:bin_a3 tokens=412 ms=5312

RAG K=8: bin_a3 is at bin location code A3. [bins bin_a3]

docs=bins:bin_a3, bins:bin_b1, movements:mov_1, movements:mov_3, movements:mov_2, skus:sku_bolt, skus:sku_nut tokens=600 ms=5365

### Warehouse count

How many movements of sku_bolt are recorded?

MARE: 1 [mov_1]

receipt exact=True count=1 absence_scope=None docs=movements:mov_1 tokens=755 ms=9812

RAG K=1: 1 movement (mov_1)

docs=movements:mov_1 tokens=363 ms=5509

RAG K=8: 1 [mov_1]

docs=movements:mov_1, skus:sku_bolt, bins:bin_a3, movements:mov_2, bins:bin_b1, movements:mov_3, skus:sku_nut tokens=529 ms=4451

### Warehouse absence

How many movements of sku_bolt happened in April 2024?

MARE: 0

receipt exact=True count=0 absence_scope=collection docs=(none) tokens=523 ms=6058

RAG K=1: 0 [mov_1]

docs=movements:mov_1 tokens=430 ms=8185

RAG K=8: 0 [mov_1] [mov_3]

docs=movements:mov_1, movements:mov_2, bins:bin_a3, skus:sku_bolt, movements:mov_3, bins:bin_b1, skus:sku_nut tokens=794 ms=8424

### Warehouse hop

Which sku is stored in bin_a3?

MARE: sku_bolt (sources: bin_a3, sku_bolt)

receipt exact=False count=1 absence_scope=None docs=skus:sku_bolt tokens=743 ms=7634

RAG K=1: sku_bolt [bin_a3]

docs=bins:bin_a3 tokens=216 ms=3406

RAG K=8: sku_bolt [bin_a3]

docs=bins:bin_a3, bins:bin_b1, movements:mov_1, movements:mov_2, movements:mov_3, skus:sku_bolt, skus:sku_nut tokens=530 ms=4852

Machine-readable: [generic_comparison.json](generic_comparison.json).
