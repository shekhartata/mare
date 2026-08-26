from __future__ import annotations

import json
from typing import Any, TypeVar

from openai import OpenAI
from pydantic import BaseModel

from app.llm.base import EmbeddingModel, GenerationResult, ReasoningModel, StructuredResult, Usage

T = TypeVar("T", bound=BaseModel)


def chat_complete(client: Any, **params: Any) -> Any:
    """Chat Completions wrapper that drops `reasoning_effort` if the model rejects it."""
    try:
        return client.chat.completions.create(**params)
    except Exception as exc:
        if params.get("reasoning_effort") is not None and "reasoning_effort" in str(exc).lower():
            retry = dict(params)
            retry.pop("reasoning_effort", None)
            return client.chat.completions.create(**retry)
        raise


def usage_from_response(resp: Any) -> Usage:
    usage = Usage()
    raw = getattr(resp, "usage", None)
    if not raw:
        return usage
    return Usage(
        prompt_tokens=int(getattr(raw, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(raw, "completion_tokens", 0) or 0),
        total_tokens=int(getattr(raw, "total_tokens", 0) or 0),
    )


class OpenAIReasoningModel(ReasoningModel):
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        *,
        reasoning_effort: str | None = None,
    ) -> None:
        self.model = model
        self.client = OpenAI(api_key=api_key)
        self.reasoning_effort = reasoning_effort

    def generate(self, prompt: str, *, system: str | None = None) -> GenerationResult:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        params: dict[str, Any] = {"model": self.model, "messages": messages}
        if self.reasoning_effort:
            params["reasoning_effort"] = self.reasoning_effort
        resp = chat_complete(self.client, **params)
        choice = resp.choices[0].message.content or ""
        return GenerationResult(text=choice, usage=usage_from_response(resp))

    def structured_generate(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
    ) -> StructuredResult[T]:
        messages: list[dict[str, str]] = []
        sys = system or "Return only valid data matching the requested schema."
        messages.append({"role": "system", "content": sys})
        messages.append({"role": "user", "content": prompt})
        parse_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "response_format": schema,
        }
        if self.reasoning_effort:
            parse_kwargs["reasoning_effort"] = self.reasoning_effort
        try:
            try:
                resp = self.client.beta.chat.completions.parse(**parse_kwargs)
            except Exception as exc:
                if self.reasoning_effort and "reasoning_effort" in str(exc).lower():
                    parse_kwargs.pop("reasoning_effort", None)
                    resp = self.client.beta.chat.completions.parse(**parse_kwargs)
                else:
                    raise
            parsed = resp.choices[0].message.parsed
            usage = Usage()
            if resp.usage:
                usage = Usage(
                    prompt_tokens=resp.usage.prompt_tokens or 0,
                    completion_tokens=resp.usage.completion_tokens or 0,
                    total_tokens=resp.usage.total_tokens or 0,
                )
            if parsed is None:
                raise ValueError("empty structured parse")
            return StructuredResult(value=parsed, usage=usage, raw_text=parsed.model_dump_json())
        except Exception:
            fallback = self.generate(
                prompt + f"\n\nRespond as JSON matching this schema:\n{schema.model_json_schema()}",
                system=sys,
            )
            data = _extract_json(fallback.text)
            return StructuredResult(
                value=schema.model_validate(data),
                usage=fallback.usage,
                raw_text=fallback.text,
            )


class OpenAIEmbeddingModel(EmbeddingModel):
    def __init__(self, api_key: str, model: str = "text-embedding-3-small") -> None:
        self.model = model
        self.client = OpenAI(api_key=api_key)
        self._dims = 1536 if "small" in model else 3072

    @property
    def dimensions(self) -> int:
        return self._dims

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        batch = 64
        for i in range(0, len(texts), batch):
            chunk = texts[i : i + batch]
            resp = self.client.embeddings.create(model=self.model, input=chunk)
            ordered = sorted(resp.data, key=lambda d: d.index)
            out.extend([list(d.embedding) for d in ordered])
        return out


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    return json.loads(text)
