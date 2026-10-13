#!/usr/bin/env python3
"""Score the in-memory generic index on the shop and warehouse fixtures.

No Mongo connection. Passes when each question returns the expected ids or count.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.datagen.shop_fixture import GOLD as SHOP_GOLD
from app.datagen.shop_fixture import documents as shop_documents
from app.datagen.warehouse_fixture import GOLD as WAREHOUSE_GOLD
from app.datagen.warehouse_fixture import documents as warehouse_documents
from app.indexing.signals import build_generic_index, reset_index_state


def score(database: str, docs: dict, gold: tuple) -> int:
    index = build_generic_index(docs, database=database)
    failed = 0
    for question, expect_ids, expect_count in gold:
        result = index.investigate(question)
        receipt = result["evidence_receipt"]
        got_ids = tuple(result["document_ids"])
        ok = not receipt["exhaustive_database"]
        if expect_ids is not None and got_ids != tuple(expect_ids):
            ok = False
        if expect_count is not None and result["count"] != expect_count:
            ok = False
        print(
            f"{'ok' if ok else 'FAIL'}\t{database}\t{question}\t"
            f"ids={list(got_ids)}\tcount={result['count']}"
        )
        failed += not ok
    return failed


def main() -> int:
    reset_index_state()
    failed = score("mare_shop", shop_documents(), SHOP_GOLD)
    failed += score("mare_warehouse", warehouse_documents(), WAREHOUSE_GOLD)
    print(f"{'passed' if not failed else 'failed'}: {failed} mismatch(es)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
