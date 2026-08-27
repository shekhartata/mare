RAW_DB = "mare_demo"
AGENT_DB = "_agent_retrieval"
RAG_DB = "_rag_baseline"

RAW_COLLECTIONS = (
    "customers",
    "tickets",
    "deployments",
    "migrations",
    "incidents",
    "logs",
)

NAV_NODES = "navigation_nodes"
EVIDENCE_SESSIONS = "evidence_sessions"
RETRIEVAL_TRACES = "retrieval_traces"
RUNTIME_CONFIG = "config"
RAG_CHUNKS = "chunks"

NAV_LEXICAL_INDEX = "nav_lexical"
NAV_VECTOR_INDEX = "nav_vector"
RAG_LEXICAL_INDEX = "rag_lexical"
RAG_VECTOR_INDEX = "rag_vector"
RAW_LEXICAL_INDEX = "raw_lexical"

AUTO_EMBED_MODEL = "voyage-4-lite"
DEFAULT_TENANT = "demo"
DEFAULT_VECTOR_DIMS = 1024

SCALE_RAW_DB = "mare_scale"
SCALE_COLLECTION = "incidents"
SCALE_TENANT = "scale"
SCALE_GOLD_PREFIX = 10_000
SCALE_SLICES = (10_000, 50_000, 100_000)
SCALE_DENSITIES = (10, 20, 50, 100, 250, 500)
SCALE_RAG_CHUNK_SIZES = (256, 512, 1024)
SCALE_RAG_OVERLAP_RATIO = 0.10
SCALE_RETRIEVAL_BUDGETS = (5, 10, 20, 40)


def scale_agent_db_name(
    n: int, density: int | None = None, strategy: str | None = None
) -> str:
    base = f"_agent_scale_{n}"
    if strategy and strategy not in {"topical", "entity"}:
        base = f"{base}_{strategy}"
    if density is None:
        return base
    return f"{base}_d{density}"


def scale_rag_db_name(n: int) -> str:
    return f"_rag_scale_{n}"


def is_scale_database(name: str) -> bool:
    return name == SCALE_RAW_DB or name.startswith(("_agent_scale_", "_rag_scale_", "mare_scale"))


def is_nav_database(name: str) -> bool:
    return name == AGENT_DB or name.startswith("_agent")
