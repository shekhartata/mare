from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class GenerationResult(BaseModel):
    text: str
    usage: Usage = Usage()


class StructuredResult(BaseModel, Generic[T]):
    value: T
    usage: Usage = Usage()
    raw_text: str = ""


class ReasoningModel(ABC):
    @abstractmethod
    def generate(self, prompt: str, *, system: str | None = None) -> GenerationResult:
        ...

    @abstractmethod
    def structured_generate(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
    ) -> StructuredResult[T]:
        ...


class EmbeddingModel(ABC):
    @property
    @abstractmethod
    def dimensions(self) -> int:
        ...

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        ...
