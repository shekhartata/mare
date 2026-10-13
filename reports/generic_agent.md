# Generic MARE agent vs RAG

- generated: 2026-10-13T10:42:23.857135+00:00
- agent model: `gpt-5-mini`
- answering model: `gpt-5`
- schema-blind tool loop: search, retrieve, query, submit
- receipts compact on, same as the SaaS demo. No schema in the prompt.
- RAG is one hybrid Top-K over one chunk per document, then the answering model.

Shop has 5 documents and warehouse has 7, so K=8 is the whole corpus.

| case | MARE | recall | ms | tok | turns | tools | RAG K=1 | recall | ms | tok | RAG K=8 | recall | ms | tok |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Shop lookup | yes | 1.00 | 9794 | 4032 | 4 | 3 | yes | 1.00 | 6006 | 311 | yes | 1.00 | 3671 | 454 |
| Shop hop | yes | 0.00 | 10166 | 4199 | 4 | 3 | yes | 0.00 | 4652 | 306 | yes | 1.00 | 5076 | 584 |
| Shop count | yes | 1.00 | 12102 | 4289 | 4 | 3 | yes | 1.00 | 6004 | 491 | yes | 1.00 | 4178 | 513 |
| Shop absence | yes | n/a | 16496 | 6143 | 5 | 4 | yes | n/a | 12371 | 897 | yes | n/a | 11340 | 1089 |
| Warehouse lookup | yes | 1.00 | 10668 | 4331 | 4 | 3 | yes | 1.00 | 5335 | 345 | yes | 1.00 | 6836 | 789 |
| Warehouse count | yes | 1.00 | 10599 | 4684 | 4 | 3 | yes | 1.00 | 4280 | 359 | yes | 1.00 | 3996 | 592 |
| Warehouse absence | yes | n/a | 15007 | 6488 | 5 | 4 | yes | n/a | 5752 | 557 | yes | n/a | 7641 | 1020 |
| Warehouse hop | yes | 1.00 | 10747 | 4617 | 4 | 3 | yes | 0.00 | 4871 | 405 | yes | 1.00 | 4038 | 592 |
| mean | **8/8** |  | **11947** | **4848** | **4** | **3** | **8/8** |  | **6159** | **459** | **8/8** |  | **5847** | **704** |

## Answers

### Shop lookup

What is the status of order ord_1044?

MARE: Order ord_1044 is shipped (mare_shop.orders:ord_1044).

stop=completed turns=4 tools=3 tokens=4032 ms=9794 docs=orders:ord_1044, orders:ord_2001

RAG K=1: Shipped. [orders ord_1044]

docs=orders:ord_1044 tokens=311 ms=6006

RAG K=8: Shipped [orders ord_1044]

docs=orders:ord_1044, orders:ord_2001, refunds:ref_9, products:sku_mug, products:sku_wool tokens=454 ms=3671

### Shop hop

Which order was refunded because a sweater pilled after one wash?

MARE: Order ord_1044 (mare_shop.refunds:ref_9).

stop=completed turns=4 tools=3 tokens=4199 ms=10166 docs=refunds:ref_9

RAG K=1: ord_1044 [ref_9]

docs=refunds:ref_9 tokens=306 ms=4652

RAG K=8: ord_1044 [ref_9]

docs=refunds:ref_9, products:sku_wool, orders:ord_1044, orders:ord_2001, products:sku_mug tokens=584 ms=5076

### Shop count

How many refunds are for sku_wool?

MARE: 1 refund for sku_wool (mare_shop.refunds:ref_9). This count is based only on the provided evidence; there may be additional refunds not shown.

stop=completed turns=4 tools=3 tokens=4289 ms=12102 docs=refunds:ref_9

RAG K=1: 1 (ref_9)

docs=refunds:ref_9 tokens=491 ms=6004

RAG K=8: 1 (ref_9)

docs=refunds:ref_9, orders:ord_1044, products:sku_wool, orders:ord_2001, products:sku_mug tokens=513 ms=4178

### Shop absence

How many refunds are for sku_mug?

MARE: 0 refunds for sku_mug in the provided evidence (mare_shop.refunds:ref_9). Only one refund record was provided, so the evidence may be incomplete.

stop=completed turns=5 tools=4 tokens=6143 ms=16496 docs=refunds:ref_9

RAG K=1: 0 — the provided chunk shows an order for sku_mug with no refunds listed (ord_2001).

docs=orders:ord_2001 tokens=897 ms=12371

RAG K=8: 0 [ref_9]

docs=orders:ord_2001, products:sku_mug, orders:ord_1044, refunds:ref_9, products:sku_wool tokens=1089 ms=11340

### Warehouse lookup

Where is bin_a3?

MARE: bin_a3 is at location code A3 (mare_warehouse.bins:bin_a3). No additional location details are provided in the evidence.

stop=completed turns=4 tools=3 tokens=4331 ms=10668 docs=bins:bin_a3, bins:bin_b1

RAG K=1: bin_a3 is at location code A3. [bin_a3]

docs=bins:bin_a3 tokens=345 ms=5335

RAG K=8: bin_a3 is the bin with code A3. [bins bin_a3]

docs=bins:bin_a3, bins:bin_b1, movements:mov_1, movements:mov_3, movements:mov_2, skus:sku_bolt, skus:sku_nut tokens=789 ms=6836

### Warehouse count

How many movements of sku_bolt are recorded?

MARE: 1 movement is recorded for sku_bolt (mare_warehouse.movements:mov_1).

stop=completed turns=4 tools=3 tokens=4684 ms=10599 docs=movements:mov_1, movements:mov_2, movements:mov_3, skus:sku_bolt, skus:sku_nut

RAG K=1: 1 [mov_1]

docs=movements:mov_1 tokens=359 ms=4280

RAG K=8: 1 [movements mov_1]

docs=movements:mov_1, skus:sku_bolt, bins:bin_a3, movements:mov_2, bins:bin_b1, movements:mov_3, skus:sku_nut tokens=592 ms=3996

### Warehouse absence

How many movements of sku_bolt happened in April 2024?

MARE: 0. Based on the provided records, the only sku_bolt movement is in January 2024 (mare_warehouse.movements:mov_1), and the April record is for sku_nut, not sku_bolt (mare_warehouse.movements:mov_3).

stop=completed turns=5 tools=4 tokens=6488 ms=15007 docs=movements:mov_1, movements:mov_2, movements:mov_3

RAG K=1: 0 (source: mov_1)

docs=movements:mov_1 tokens=557 ms=5752

RAG K=8: 0

Reason: The only sku_bolt movement shown is on 2024-01-15 (January) [mov_1]. The only April movement listed is for sku_nut, not sku_bolt [mov_3].

docs=movements:mov_1, movements:mov_2, bins:bin_a3, skus:sku_bolt, movements:mov_3, bins:bin_b1, skus:sku_nut tokens=1020 ms=7641

### Warehouse hop

Which sku is stored in bin_a3?

MARE: sku_bolt (mare_warehouse.bins:bin_a3)

stop=completed turns=4 tools=3 tokens=4617 ms=10747 docs=bins:bin_a3, bins:bin_b1, skus:sku_bolt, skus:sku_nut

RAG K=1: sku_bolt [bin_a3]

docs=bins:bin_a3 tokens=405 ms=4871

RAG K=8: sku_bolt [bins bin_a3]

docs=bins:bin_a3, bins:bin_b1, movements:mov_1, movements:mov_2, movements:mov_3, skus:sku_bolt, skus:sku_nut tokens=592 ms=4038

Machine-readable: [generic_agent.json](generic_agent.json).
