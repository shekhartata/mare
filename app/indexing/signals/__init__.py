"""Generic indexing. Opt-in; the SaaS demo path does not import this package."""

from app.indexing.signals.orchestrator import (
    GenericIndex,
    active_generation,
    build_generic_index,
    reset_index_state,
    rollback_generation,
)

__all__ = [
    "GenericIndex",
    "active_generation",
    "build_generic_index",
    "reset_index_state",
    "rollback_generation",
]
