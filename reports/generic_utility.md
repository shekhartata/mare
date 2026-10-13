# Generic MARE vs RAG where Top-K cannot see the answer

- generated: 2026-10-13T11:02:22.304817+00:00
- agent model: `gpt-5-mini`
- answering model: `gpt-5`
- schema-blind tool loop: search, retrieve, query, submit
- receipts compact on, same as the SaaS demo. No schema in the prompt.
- RAG is one hybrid Top-K over one chunk per document, then the answering model.

`mare_utility` has 74 documents. K=8 is the product default and is not the whole database.

Bridge: `northwind` is only on the order. The return that matches the question stores the order id and does not store the lane.
Distributed: `chlorogenic` is only on the assay. The complaint that matches the question stores the lot id and does not store the finding.
Absence: no refund has sku `sku_plain`. The nearest refund is `sku_plain_plus` and its reason mentions `sku_plain`.

A related node is bound to the foreign key on the matched document, so retrieve opens that target. Gold recall is the hidden document. Absence has no gold document, so recall is n/a.

| case | MARE | recall | ms | tok | turns | tools | RAG K=1 | recall | ms | tok | RAG K=8 | recall | ms | tok |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Bridge carrier | yes | 1.00 | 23264 | 8334 | 5 | 4 | no | 0.00 | 6578 | 438 | no | 0.00 | 7554 | 861 |
| Distributed assay | yes | 1.00 | 14453 | 8218 | 5 | 4 | no | 0.00 | 7145 | 565 | no | 0.00 | 7067 | 858 |
| Absence sku_plain | yes | n/a | 24483 | 8415 | 5 | 4 | yes | n/a | 10087 | 745 | yes | n/a | 6655 | 798 |
| mean | **3/3** |  | **20733** | **8322** | **5** | **4** | **1/3** |  | **7937** | **583** | **1/3** |  | **7092** | **839** |

## Answers

### Bridge carrier

A sweater was returned because it pilled after one wash. Which carrier lane handled that order?

MARE: northwind (mare_utility.orders:ord_pill; mare_utility.returns:ret_pill)

stop=completed turns=5 tools=4 tokens=8334 ms=23264 docs=returns:ret_pill, returns:ret_00, returns:ret_01, returns:ret_02, returns:ret_03, returns:ret_04, returns:ret_05, returns:ret_06, returns:ret_07, returns:ret_08, orders:ord_pill

RAG K=1: The carrier lane is not specified in the provided data [ret_pill].

docs=returns:ret_pill tokens=438 ms=6578

RAG K=8: Cannot determine from provided chunks. The return for “sweater pilled after one wash” is order ord_pill, but no carrier lane is listed [ret_pill].

docs=returns:ret_pill, returns:ret_01, returns:ret_02, returns:ret_03, returns:ret_08, returns:ret_00, returns:ret_04, returns:ret_14 tokens=861 ms=7554

### Distributed assay

A guest reported a bitter aftertaste in the house blend. What assay finding explains it?

MARE: Chlorogenic acid measured above the roast ceiling in lot_77, which can cause bitterness (mare_utility.assays:lot_77; mare_utility.notes:note_house).

stop=completed turns=5 tools=4 tokens=8218 ms=14453 docs=notes:note_house, notes:note_00, notes:note_01, notes:note_02, notes:note_03, notes:note_04, notes:note_05, notes:note_06, notes:note_07, notes:note_08, notes:note_09, notes:note_10, notes:note_11, notes:note_12, notes:note_13, assays:lot_77, assays:lot_00, assays:lot_01, assays:lot_02, assays:lot_03

RAG K=1: None provided — the note only reports a bitter aftertaste; no assay results are given to explain it [note_house].

docs=notes:note_house tokens=565 ms=7145

RAG K=8: No assay finding is provided in the given data—only the guest’s report of a bitter aftertaste in the house blend is recorded [note_house].

docs=notes:note_house, notes:note_00, notes:note_06, notes:note_05, notes:note_01, notes:note_04, notes:note_02, notes:note_03 tokens=858 ms=7067

### Absence sku_plain

How many refunds for sku_plain were requested in April 2024?

MARE: 0

Based on the provided April 2024 refund records, none list sku_plain as the sku (entries are for other skus, including a sku_plain_plus on 2024-04-12): mare_utility.refunds:ref_00, mare_utility.refunds:ref_01, mare_utility.refunds:ref_02, mare_utility.refunds:ref_03, mare_utility.refunds:ref_04, mare_utility.refunds:ref_05, mare_utility.refunds:ref_06, mare_utility.refunds:ref_07, mare_utility.refunds:ref_look. If there are additional records not provided here, they are not reflected in this count.

stop=completed turns=5 tools=4 tokens=8415 ms=24483 docs=refunds:ref_look, refunds:ref_jan, refunds:ref_00, refunds:ref_01, refunds:ref_02, refunds:ref_03, refunds:ref_04, refunds:ref_05, refunds:ref_06, refunds:ref_07

RAG K=1: 0 [ref_00]

docs=refunds:ref_00 tokens=745 ms=10087

RAG K=8: 0 [ref_00; ref_look; ref_07; ref_05; ref_03; ref_04; ref_01; ref_02]

docs=refunds:ref_00, refunds:ref_look, refunds:ref_07, refunds:ref_05, refunds:ref_03, refunds:ref_04, refunds:ref_01, refunds:ref_02 tokens=798 ms=6655

Machine-readable: [generic_utility.json](generic_utility.json).
