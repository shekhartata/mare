"""A second OS process loads the saved index and reads the live collections."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.constants import AGENT_DB
from app.datagen.shop_fixture import documents as shop_documents
from app.indexing.signals.store import ACTIVE_ID, CARDS, CATALOG
from app.mongo.client import get_client, ping

ROOT = Path(__file__).resolve().parents[1]
PROBE = "mare_generic_probe"
_URI = re.compile(r"mongodb(?:\+srv)?://\S+")

_QUERY = """
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from app.indexing.signals.store import load_generic_handlers
from app.mongo.client import get_client

handlers = load_generic_handlers(get_client(), None)
found = handlers["search_information"](
    "sweater pilled after one wash",
    tenant_id="generic",
    scope=None,
    mode="lexical",
    limit=4,
)
bound = next(row for row in found["related_nodes"] if row["node_id"].endswith("ord_1044"))
evidence = handlers["retrieve_evidence"](
    [bound["node_id"]],
    tenant_id="generic",
    query=None,
    max_documents=4,
)
order = evidence["documents"][0]["ref"]["document_id"]
wool = handlers["query_documents"](
    "mare_generic_probe.refunds",
    {"sku": "sku_wool"},
    tenant_id="generic",
    projection=None,
    limit=5,
)
none = handlers["query_documents"](
    "mare_generic_probe.refunds",
    {"sku": "sku_mug"},
    tenant_id="generic",
    projection=None,
    limit=5,
)
print(f"order={order} wool={wool['count']} none={none['count']}")
"""


def _redact(text: str) -> str:
    return _URI.sub("[mongodb-uri]", text or "")


def _run(args: list[str], script: str | None = None) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, *args]
    return subprocess.run(
        command,
        cwd=ROOT,
        input=script,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )


def test_saved_index_is_queried_by_another_process():
    try:
        ping()
    except Exception as exc:
        pytest.skip(f"MongoDB is not reachable ({type(exc).__name__})")

    client = get_client()
    agent = client[AGENT_DB]
    previous_catalog = agent[CATALOG].find_one({"_id": ACTIVE_ID})
    previous_cards = list(agent[CARDS].find({}))
    try:
        client.drop_database(PROBE)
        probe = client[PROBE]
        for name, rows in shop_documents().items():
            probe[name].insert_many(rows)
        indexed = _run(["scripts/index_generic.py", "--database", PROBE])
        assert indexed.returncode == 0, _redact(indexed.stderr or indexed.stdout)
        queried = _run(["-c", _QUERY])
        assert queried.returncode == 0, _redact(queried.stderr or queried.stdout)
        assert "order=ord_1044 wool=1 none=0" in queried.stdout
    finally:
        client.drop_database(PROBE)
        agent[CARDS].delete_many({})
        agent[CATALOG].delete_many({})
        if previous_catalog:
            agent[CATALOG].replace_one({"_id": ACTIVE_ID}, previous_catalog, upsert=True)
        if previous_cards:
            agent[CARDS].insert_many(previous_cards)
