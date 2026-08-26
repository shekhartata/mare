from app.config import get_settings
from app.models.schemas import Budgets


def budgets_from_settings() -> Budgets:
    s = get_settings()
    return Budgets(
        max_retrieval_operations=s.max_retrieval_operations,
        max_search_operations=s.max_search_operations,
        max_documents_read=s.max_documents_read,
        max_llm_tokens=s.max_llm_tokens,
        max_elapsed_ms=s.max_elapsed_ms,
        max_loop_rounds=s.max_loop_rounds,
    )
