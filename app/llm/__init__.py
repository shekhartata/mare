from app.config import get_settings
from app.llm.base import EmbeddingModel, ReasoningModel
from app.llm.heuristic import HeuristicReasoningModel, NullEmbeddingModel
from app.llm.openai_model import OpenAIEmbeddingModel, OpenAIReasoningModel


def get_reasoning_model(
    model: str | None = None, *, reasoning_effort: str | None = None
) -> ReasoningModel:
    settings = get_settings()
    if settings.openai_api_key:
        return OpenAIReasoningModel(
            settings.openai_api_key,
            model or settings.openai_model,
            reasoning_effort=reasoning_effort,
        )
    return HeuristicReasoningModel()


def get_embedding_model() -> EmbeddingModel:
    settings = get_settings()
    if settings.openai_api_key:
        return OpenAIEmbeddingModel(settings.openai_api_key, settings.openai_embedding_model)
    return NullEmbeddingModel()
