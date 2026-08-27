from app.constants import SCALE_RAW_DB, is_scale_database, scale_agent_db_name
from app.search.service import allowed_databases


def test_scale_databases_are_allowed():
    assert SCALE_RAW_DB in allowed_databases()
    assert scale_agent_db_name(10_000) in allowed_databases()
    assert scale_agent_db_name(10_000, 10) in allowed_databases()
    assert is_scale_database("_rag_scale_50000")
    assert scale_agent_db_name(10_000, 20, "semantic") in allowed_databases()
    assert is_scale_database("_agent_scale_10000_semantic_d20")
