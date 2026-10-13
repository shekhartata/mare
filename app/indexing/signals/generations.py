"""Candidate generations. A failed candidate does not replace the active map."""

from __future__ import annotations

from typing import Any


class ActivationError(RuntimeError):
    pass


class GenerationBook:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.active: str | None = None
        self.previous: str | None = None
        self._seq = 0

    def stage(self, fingerprint: str, *, valid: bool) -> str:
        self._seq += 1
        generation_id = f"gen_{self._seq}"
        self.records[generation_id] = {
            "fingerprint": fingerprint,
            "status": "candidate" if valid else "failed",
        }
        return generation_id

    def activate(self, generation_id: str) -> None:
        record = self.records[generation_id]
        if record["status"] == "failed":
            raise ActivationError(f"{generation_id} failed validation; active map unchanged")
        self.previous = self.active
        self.active = generation_id
        record["status"] = "active"

    def rollback(self) -> str | None:
        if self.previous is None:
            return self.active
        self.active, self.previous = self.previous, self.active
        if self.active is not None:
            self.records[self.active]["status"] = "active"
        return self.active
