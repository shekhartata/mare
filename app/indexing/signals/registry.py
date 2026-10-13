"""Provider registry. Core orchestration looks up names; it does not import extras."""

from __future__ import annotations

from typing import Any

from app.indexing.signals.contracts import SignalProvider

_REGISTRY: dict[str, SignalProvider] = {}


def register(provider: SignalProvider) -> None:
    _REGISTRY[provider.name] = provider


def get(name: str) -> SignalProvider:
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"unknown signal provider {name}") from exc


def registered() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def clear() -> None:
    _REGISTRY.clear()


def run_enabled(names: list[str], context: Any) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    done: set[str] = set()
    pending = list(names)
    spins = 0
    while pending:
        spins += 1
        if spins > max(8, len(names) * 4):
            break
        name = pending.pop(0)
        if name in done:
            continue
        provider = get(name)
        missing = [req for req in provider.requires if req not in done]
        if missing:
            pending.append(name)
            if all(req not in pending and req not in names for req in missing):
                results.append(
                    {
                        "contract_version": "1",
                        "provider": name,
                        "provider_version": provider.version,
                        "status": "degraded",
                        "warnings": [f"missing dependencies: {missing}"],
                        "claims": [],
                        "card_facets": [],
                        "route_candidates": [],
                        "grouping_hints": [],
                        "evidence_refs": [],
                        "coverage": {"complete": False},
                        "scope": {},
                        "input_fingerprint": "",
                        "created_at": "",
                    }
                )
                done.add(name)
            continue
        try:
            result = provider.evaluate(context)
        except Exception as exc:
            result = {
                "contract_version": "1",
                "provider": name,
                "provider_version": provider.version,
                "status": "degraded",
                "warnings": [str(exc)],
                "claims": [],
                "card_facets": [],
                "route_candidates": [],
                "grouping_hints": [],
                "evidence_refs": [],
                "coverage": {"complete": False},
                "scope": {},
                "input_fingerprint": "",
                "created_at": "",
            }
        if result.get("contract_version") != "1" or result.get("provider") != name:
            result = {
                **result,
                "status": "degraded",
                "warnings": list(result.get("warnings") or []) + ["invalid provider envelope"],
                "claims": [],
                "route_candidates": [],
            }
        results.append(result)
        done.add(name)
    return results
