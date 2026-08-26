from __future__ import annotations

from collections import defaultdict

from app.models.schemas import Candidate, NodeType
from app.retrieval.best_first import apply_priority


class CandidateQueue:
    def __init__(self) -> None:
        self._items: dict[str, Candidate] = {}
        self._visited: set[str] = set()
        self._by_collection: dict[str, int] = defaultdict(int)

    def add(self, candidate: Candidate) -> None:
        if candidate.node_id in self._visited:
            candidate.novelty = 0.0
            candidate.already_visited = True
        collection = ""
        if candidate.source and candidate.source.collection:
            collection = candidate.source.collection
            candidate.diversity = 1.0 / (1 + self._by_collection[collection])
        apply_priority(candidate)
        existing = self._items.get(candidate.node_id)
        if existing is None or candidate.priority > existing.priority:
            self._items[candidate.node_id] = candidate

    def extend(self, candidates: list[Candidate]) -> None:
        for c in candidates:
            self.add(c)

    def pop_best(self) -> Candidate | None:
        open_items = [c for c in self._items.values() if c.node_id not in self._visited]
        if not open_items:
            return None
        best = max(open_items, key=lambda c: c.priority)
        self.mark_visited(best)
        return best

    def mark_visited(self, candidate: Candidate) -> None:
        self._visited.add(candidate.node_id)
        if candidate.source and candidate.source.collection:
            self._by_collection[candidate.source.collection] += 1
        candidate.already_visited = True
        candidate.novelty = 0.0

    def highest_priority(self) -> float:
        open_items = [c for c in self._items.values() if c.node_id not in self._visited]
        if not open_items:
            return 0.0
        return max(c.priority for c in open_items)

    def as_scores(self) -> dict[str, float]:
        return {c.node_id: round(c.priority, 4) for c in self._items.values()}

    def rerank_for_gaps(self, gap_terms: list[str]) -> None:
        lowered = [t.lower() for t in gap_terms if t]
        if not lowered:
            return
        for c in self._items.values():
            blob = f"{c.name} {c.summary} {c.reason}".lower()
            hits = sum(1 for t in lowered if t in blob)
            if hits:
                c.evidence_gap = min(1.0, c.evidence_gap + 0.15 * hits)
                c.uncertainty_reduction = min(1.0, c.uncertainty_reduction + 0.1 * hits)
                apply_priority(c)

    @staticmethod
    def from_nodes(
        nodes: list[dict],
        *,
        query: str,
        method,
        reason: str,
    ) -> list[Candidate]:
        out: list[Candidate] = []
        for node in nodes:
            source = node.get("source") or {}
            from app.models.schemas import SourcePointer

            out.append(
                Candidate(
                    node_id=str(node.get("_id")),
                    node_type=node.get("node_type") or NodeType.group,
                    name=node.get("name") or "",
                    summary=node.get("summary") or "",
                    source=SourcePointer.model_validate(source) if source else None,
                    relevance=float(node.get("_score") or 0.5),
                    evidence_gap=0.6 if node.get("node_type") in {"group", "collection"} else 0.4,
                    uncertainty_reduction=0.5,
                    novelty=1.0,
                    diversity=0.5,
                    retrieval_cost=0.2 if node.get("node_type") == "document" else 0.35,
                    search_method=method,
                    query=query,
                    reason=reason,
                )
            )
        return out
