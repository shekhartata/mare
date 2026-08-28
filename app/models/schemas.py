from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class NodeType(str, Enum):
    database = "database"
    collection = "collection"
    group = "group"
    document = "document"


class PointerType(str, Enum):
    document = "document"
    query = "query"
    range = "range"


class ClaimStatus(str, Enum):
    supported = "supported"
    partially_supported = "partially_supported"
    unsupported = "unsupported"
    contradicted = "contradicted"


class SessionStatus(str, Enum):
    complete = "complete"
    partial = "partial"
    insufficient_evidence = "insufficient_evidence"
    budget_exhausted = "budget_exhausted"
    running = "running"


class SearchMethod(str, Enum):
    lexical = "lexical"
    semantic = "semantic"
    hybrid = "hybrid"
    mongo_query = "mongo_query"


class SourcePointer(BaseModel):
    database: str
    collection: str | None = None
    document_ids: list[str] = Field(default_factory=list)
    filter: dict[str, Any] = Field(default_factory=dict)
    pointer_type: PointerType = PointerType.query


class NodeSchema(BaseModel):
    important_fields: list[str] = Field(default_factory=list)
    field_descriptions: dict[str, str] = Field(default_factory=dict)


class NodeMetadata(BaseModel):
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    time_min: datetime | None = None
    time_max: datetime | None = None
    document_count: int = 0


class NavigationNode(BaseModel):
    id: str = Field(alias="_id")
    tenant_id: str
    node_type: NodeType
    name: str
    description: str = ""
    summary: str = ""
    search_text: str = ""
    parent_id: str | None = None
    depth: int = 0
    source: SourcePointer
    schema_info: NodeSchema = Field(default_factory=NodeSchema, alias="schema")
    metadata: NodeMetadata = Field(default_factory=NodeMetadata)
    embedding: list[float] = Field(default_factory=list)
    children_count: int = 0
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"populate_by_name": True}


class MongoRef(BaseModel):
    database: str
    collection: str
    document_id: str
    fields: list[str] = Field(default_factory=list)


class Claim(BaseModel):
    claim_id: str
    claim: str
    status: ClaimStatus = ClaimStatus.unsupported
    confidence: float = 0.0
    supporting_sources: list[MongoRef] = Field(default_factory=list)
    contradicting_sources: list[MongoRef] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    material: bool = True


class ClaimObservation(BaseModel):
    claim_id: str
    support_strength: float
    evidence: str


class EvidenceExtraction(BaseModel):
    relevant: bool = True
    claims_supported: list[ClaimObservation] = Field(default_factory=list)
    claims_contradicted: list[ClaimObservation] = Field(default_factory=list)
    new_claims: list[str] = Field(default_factory=list)
    new_questions: list[str] = Field(default_factory=list)


class HypothesisUpdate(BaseModel):
    hypothesis: str
    claims: list[Claim] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    changed: bool = False


class Candidate(BaseModel):
    node_id: str
    node_type: NodeType | str = NodeType.group
    name: str = ""
    summary: str = ""
    source: SourcePointer | None = None
    relevance: float = 0.0
    evidence_gap: float = 0.5
    uncertainty_reduction: float = 0.5
    novelty: float = 1.0
    diversity: float = 0.5
    retrieval_cost: float = 0.3
    priority: float = 0.0
    already_visited: bool = False
    search_method: SearchMethod | None = None
    query: str = ""
    reason: str = ""


class RetrievedDocument(BaseModel):
    ref: MongoRef
    content: dict[str, Any]
    text: str
    score: float = 0.0


class TraceEvent(BaseModel):
    session_id: str
    step: int
    operation: str
    reason: str = ""
    query: str = ""
    scope: str = ""
    results: list[dict[str, Any]] = Field(default_factory=list)
    selected_result: str = ""
    candidate_scores: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = 0
    tokens: int = 0
    extra: dict[str, Any] = Field(default_factory=dict)


class Budgets(BaseModel):
    max_retrieval_operations: int
    max_search_operations: int
    max_documents_read: int
    max_llm_tokens: int
    max_elapsed_ms: int
    max_loop_rounds: int


class Accounting(BaseModel):
    retrieval_count: int = 0
    search_count: int = 0
    documents_read: int = 0
    tokens_consumed: int = 0
    elapsed_ms: float = 0
    llm_calls: int = 0
    embedding_tokens: int = 0


class EvidenceSession(BaseModel):
    id: str = Field(alias="_id")
    tenant_id: str
    question: str
    hypothesis: str = ""
    claims: list[Claim] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    status: SessionStatus = SessionStatus.running
    stop_reason: str = ""
    router_recommendation: SearchMethod | None = None
    agent_selected_method: SearchMethod | None = None
    retrieval_count: int = 0
    tokens_consumed: int = 0
    elapsed_ms: float = 0
    agent_turns: int = 0
    tool_calls: int = 0
    llm_latency_ms: float = 0
    mongo_latency_ms: float = 0
    answer: str = ""
    citations: list[MongoRef] = Field(default_factory=list)
    retrieved_docs: list[dict[str, Any]] = Field(default_factory=list)
    hypothesis_versions: list[str] = Field(default_factory=list)
    acgc_stats: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"populate_by_name": True}


class AskRequest(BaseModel):
    question: str
    tenant_id: str | None = None
    method: Literal["adaptive", "rag", "legacy"] = "adaptive"


class AskResponse(BaseModel):
    session_id: str
    question: str
    answer: str
    status: SessionStatus
    stop_reason: str = ""
    hypothesis: str = ""
    claims: list[Claim] = Field(default_factory=list)
    citations: list[MongoRef] = Field(default_factory=list)
    retrieval_count: int = 0
    tokens_consumed: int = 0
    elapsed_ms: float = 0
    agent_turns: int = 0
    tool_calls: int = 0
    llm_latency_ms: float = 0
    mongo_latency_ms: float = 0
    router_recommendation: str | None = None
    engine: str = "adaptive"


class GoldSource(BaseModel):
    database: str
    collection: str
    document_id: str


class GoldQuery(BaseModel):
    id: str
    class_name: str = Field(alias="class")
    question: str
    gold_answer: str
    gold_sources: list[GoldSource] = Field(default_factory=list)
    story_id: str | None = None

    model_config = {"populate_by_name": True}


class ClusterCapabilities(BaseModel):
    auto_embed: bool = False
    rank_fusion: bool = False
    hybrid_strategy: Literal["rank_fusion", "rrf"] = "rrf"
    embedding_path: Literal["atlas_auto", "manual"] = "manual"
    embedding_model: str = "voyage-4-lite"
    vector_dims: int = 1024
    mongo_version: str = ""
    notes: list[str] = Field(default_factory=list)
