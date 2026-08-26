from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel

from app.llm.base import EmbeddingModel, GenerationResult, ReasoningModel, StructuredResult, Usage
from app.models.schemas import Claim, ClaimObservation, ClaimStatus, EvidenceExtraction, HypothesisUpdate

T = TypeVar("T", bound=BaseModel)

_ID_RE = re.compile(
    r"\b(cust_\d+|mig_[a-z0-9_]+|dep_[a-z0-9_]+|tkt_\d+|inc_\d+|AUTH_\d+|TLS_[A-Z_]+)\b",
    re.I,
)


class HeuristicReasoningModel(ReasoningModel):
    """Deterministic reasoner for tests and runs without an API key.

    It only uses the prompt contents (retrieved evidence + question). It does
    not consult gold labels.
    """

    def generate(self, prompt: str, *, system: str | None = None) -> GenerationResult:
        text = _heuristic_answer(prompt)
        return GenerationResult(text=text, usage=Usage(total_tokens=len(prompt) // 4))

    def structured_generate(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
    ) -> StructuredResult[T]:
        if schema is HypothesisUpdate:
            value = _heuristic_hypothesis(prompt)  # type: ignore[assignment]
        elif schema is EvidenceExtraction:
            value = _heuristic_extraction(prompt)  # type: ignore[assignment]
        else:
            value = schema.model_validate(_loose_object(prompt, schema))
        return StructuredResult(
            value=value,
            usage=Usage(total_tokens=len(prompt) // 4),
            raw_text=value.model_dump_json(),
        )


class NullEmbeddingModel(EmbeddingModel):
    @property
    def dimensions(self) -> int:
        return 8

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            vec = [0.0] * 8
            for i, ch in enumerate(t[:64]):
                vec[i % 8] += (ord(ch) % 13) / 13.0
            out.append(vec)
        return out


def _ids(text: str) -> list[str]:
    return list(dict.fromkeys(_ID_RE.findall(text)))


def _heuristic_hypothesis(prompt: str) -> HypothesisUpdate:
    question = prompt.split("Initial navigation", 1)[0]
    ids = _ids(question)
    q = question
    hypothesis = (
        "The question likely depends on records related to "
        + (", ".join(ids[:6]) if ids else "the named customer/event")
        + ". Investigating migrations, deployments, logs, tickets, and incidents."
    )
    claims: list[Claim] = []
    if ids:
        for i, ident in enumerate(ids[:4], start=1):
            claims.append(
                Claim(
                    claim_id=f"C{i}",
                    claim=f"Identifier {ident} is involved in the outcome described by the question.",
                    status=ClaimStatus.unsupported,
                    confidence=0.2,
                )
            )
    if re.search(r"\bwhy\b|\broot cause\b|\bfail", q, re.I):
        claims.append(
            Claim(
                claim_id=f"C{len(claims)+1}",
                claim="A configuration or migration change preceded the observed failures.",
                status=ClaimStatus.unsupported,
                confidence=0.2,
                material=True,
            )
        )
    if not claims:
        claims.append(
            Claim(
                claim_id="C1",
                claim="Relevant MongoDB records exist that answer the question.",
                status=ClaimStatus.unsupported,
                confidence=0.2,
            )
        )
    return HypothesisUpdate(
        hypothesis=hypothesis,
        claims=claims,
        open_questions=["What evidence in logs or migrations confirms the causal chain?"],
        changed=True,
    )


def _heuristic_extraction(prompt: str) -> EvidenceExtraction:
    lower = prompt.lower()
    claims_supported: list[ClaimObservation] = []
    claims_contradicted: list[ClaimObservation] = []
    for match in re.finditer(r"(C\d+)\s*[:\-]\s*(.+)", prompt):
        cid, text = match.group(1), match.group(2).lower()
        keywords = [w for w in re.findall(r"[a-z0-9_]{4,}", text) if w not in {"this", "that", "with"}]
        hits = sum(1 for k in keywords[:8] if k in lower)
        if hits >= 2:
            claims_supported.append(
                ClaimObservation(
                    claim_id=cid,
                    support_strength=min(0.95, 0.4 + 0.1 * hits),
                    evidence="Keyword overlap between claim and retrieved Mongo documents.",
                )
            )
    relevant = bool(claims_supported) or "error" in lower or "fail" in lower
    new_questions: list[str] = []
    if "migration" in lower and "log" not in lower:
        new_questions.append("Are there matching error logs after the migration timestamp?")
    return EvidenceExtraction(
        relevant=relevant,
        claims_supported=claims_supported,
        claims_contradicted=claims_contradicted,
        new_claims=[],
        new_questions=new_questions,
    )


def _heuristic_answer(prompt: str) -> str:
    ids = _ids(prompt)
    facts: list[str] = []
    for label, pattern in (
        ("subscription tier", r"subscription_tier:\s*(\w+)"),
        ("region", r"region:\s*([\w-]+)"),
        ("error code", r"error_code:\s*([A-Za-z0-9_]+)"),
        ("AUTH_ISSUER", r"AUTH_ISSUER['\":\s]+(https?://\S+)"),
        ("jwt issuer", r"jwt issuer mismatch:[^\n]+"),
        ("root cause", r"root_cause:\s*(.+)"),
    ):
        m = re.search(pattern, prompt)
        if m:
            facts.append(f"- {label}: {m.group(1).strip() if m.lastindex else m.group(0).strip()}")
    lines = ["Based on retrieved MongoDB evidence:"]
    lines.extend(facts or ["- Cross-collection records were inspected."])
    if ids:
        lines.append("- Key identifiers: " + ", ".join(ids[:8]) + ".")
    lines.append("See citations for the supporting Mongo source references.")
    return "\n".join(lines)


def _loose_object(prompt: str, schema: type[BaseModel]) -> dict:
    try:
        start = prompt.rfind("{")
        end = prompt.rfind("}")
        if start >= 0 and end > start:
            return json.loads(prompt[start : end + 1])
    except Exception:
        pass
    fields = {}
    for name, finfo in schema.model_fields.items():
        if finfo.annotation is str:
            fields[name] = ""
        elif finfo.annotation is bool:
            fields[name] = False
        elif finfo.annotation is float:
            fields[name] = 0.0
        elif finfo.annotation is int:
            fields[name] = 0
        else:
            fields[name] = [] if "list" in str(finfo.annotation).lower() else None
    return fields
