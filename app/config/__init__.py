from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.constants import DEFAULT_TENANT, RAW_COLLECTIONS


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    mongodb_uri: str = Field(default="", validation_alias=AliasChoices("MONGODB_URI", "mongodb_uri"))
    openai_api_key: str = Field(default="", validation_alias=AliasChoices("OPENAI_API_KEY", "openai_api_key"))
    openai_model: str = Field(default="gpt-4o-mini", validation_alias=AliasChoices("OPENAI_MODEL", "openai_model"))
    openai_model_agent: str = Field(
        default="gpt-5-mini",
        validation_alias=AliasChoices("OPENAI_MODEL_AGENT", "openai_model_agent"),
    )
    openai_reasoning_effort: str = Field(
        default="low",
        validation_alias=AliasChoices("OPENAI_REASONING_EFFORT", "openai_reasoning_effort"),
    )
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        validation_alias=AliasChoices("OPENAI_EMBEDDING_MODEL", "openai_embedding_model"),
    )
    max_agent_turns: int = Field(
        default=10, validation_alias=AliasChoices("MARE_MAX_AGENT_TURNS", "max_agent_turns")
    )
    schema_in_prompt: bool = Field(
        default=False,
        validation_alias=AliasChoices("MARE_SCHEMA_IN_PROMPT", "schema_in_prompt"),
    )
    tenant_id: str = Field(default=DEFAULT_TENANT, validation_alias=AliasChoices("MARE_TENANT_ID", "tenant_id"))
    log_level: str = Field(default="INFO", validation_alias=AliasChoices("MARE_LOG_LEVEL", "log_level"))

    source_database: str = "mare_demo"
    source_collections: tuple[str, ...] = RAW_COLLECTIONS

    # Best-first weights (PRD §13)
    w_relevance: float = 0.30
    w_evidence_gap: float = 0.30
    w_uncertainty: float = 0.15
    w_novelty: float = 0.10
    w_diversity: float = 0.05
    w_cost: float = 0.10

    # Stopping (PRD §19)
    coverage_threshold: float = 0.75
    min_gain: float = 0.05
    consecutive_low_gain_rounds: int = 2
    min_priority: float = 0.12
    answer_stability_rounds: int = 2

    # Hard budgets
    max_retrieval_operations: int = Field(
        default=12, validation_alias=AliasChoices("MARE_MAX_RETRIEVAL_OPERATIONS", "max_retrieval_operations")
    )
    max_search_operations: int = Field(
        default=16, validation_alias=AliasChoices("MARE_MAX_SEARCH_OPERATIONS", "max_search_operations")
    )
    max_documents_read: int = Field(
        default=40, validation_alias=AliasChoices("MARE_MAX_DOCUMENTS_READ", "max_documents_read")
    )
    max_llm_tokens: int = Field(
        default=80_000, validation_alias=AliasChoices("MARE_MAX_LLM_TOKENS", "max_llm_tokens")
    )
    max_elapsed_ms: int = Field(
        default=90_000, validation_alias=AliasChoices("MARE_MAX_ELAPSED_MS", "max_elapsed_ms")
    )
    max_loop_rounds: int = Field(
        default=8, validation_alias=AliasChoices("MARE_MAX_LOOP_ROUNDS", "max_loop_rounds")
    )

    # Search
    default_search_limit: int = 8
    vector_num_candidates: int = 80
    rrf_k: int = 60

    # RAG baseline
    chunk_size: int = 700
    chunk_overlap: int = 80
    rag_top_k: int = 8

    # Indexing
    schema_sample_size: int = 80
    auto_embed_model: str = "voyage-4-lite"

    # Optional ACGC sidecar (tool-loop context compact). Default off.
    acgc_enabled: bool = Field(
        default=False, validation_alias=AliasChoices("MARE_ACGC", "acgc_enabled")
    )
    acgc_grpc_addr: str = Field(
        default="localhost:50051",
        validation_alias=AliasChoices("ACGC_GRPC_ADDR", "acgc_grpc_addr"),
    )
    acgc_token_budget: int = Field(
        default=8_000, validation_alias=AliasChoices("ACGC_TOKEN_BUDGET", "acgc_token_budget")
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
