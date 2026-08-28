"""Optional ACGC gRPC sidecar. Off by default; never used unless MARE_ACGC is on.

Does not call ACGC Run() (that path owns the LLM and has no tools). MARE still
calls OpenAI with tools; this client only CaptureEvent / TriggerGC / GetMetrics.
"""

from __future__ import annotations

from typing import Any, Protocol


class AcgcClient(Protocol):
    def capture(
        self,
        event_type: str,
        payload: str,
        metadata: dict[str, str] | None = None,
    ) -> None: ...

    def trigger_gc(self) -> None: ...

    def metrics(self) -> dict[str, Any]: ...

    def close(self) -> None: ...


class GrpcAcgcClient:
    def __init__(
        self,
        addr: str,
        session_id: str,
        *,
        task_id: str = "mare",
        timeout_s: float = 5.0,
    ) -> None:
        try:
            import grpc
        except ImportError as exc:
            raise RuntimeError(
                "MARE_ACGC is on but grpcio is not installed. pip install -e '.[acgc]'"
            ) from exc
        from app.retrieval.acgc_pb import acgc_pb2, acgc_pb2_grpc

        self._pb2 = acgc_pb2
        self._session_id = session_id
        self._task_id = task_id
        self._timeout = timeout_s
        self._channel = grpc.insecure_channel(addr)
        grpc.channel_ready_future(self._channel).result(timeout=timeout_s)
        self._stub = acgc_pb2_grpc.ACGCServiceStub(self._channel)
        self._stub.GetState(
            acgc_pb2.GetStateRequest(session_id=session_id),
            timeout=timeout_s,
        )

    def capture(
        self,
        event_type: str,
        payload: str,
        metadata: dict[str, str] | None = None,
    ) -> None:
        req = self._pb2.CaptureEventRequest(
            session_id=self._session_id,
            task_id=self._task_id,
            event_type=event_type,
            payload=payload[:24_000],
            metadata=metadata or {},
        )
        resp = self._stub.CaptureEvent(req, timeout=self._timeout)
        if not resp.accepted:
            raise RuntimeError(f"ACGC rejected CaptureEvent ({event_type})")

    def trigger_gc(self) -> None:
        self._stub.TriggerGC(
            self._pb2.TriggerGCRequest(session_id=self._session_id, force=True),
            timeout=self._timeout,
        )

    def metrics(self) -> dict[str, Any]:
        resp = self._stub.GetMetrics(
            self._pb2.GetMetricsRequest(session_id=self._session_id),
            timeout=self._timeout,
        )
        return {
            "session_id": resp.session_id,
            "total_events": resp.total_events,
            "total_turns": resp.total_turns,
            "gc_runs": resp.gc_runs,
            "total_tokens_saved": resp.total_tokens_saved,
            "avg_reduction_percent": resp.avg_reduction_percent,
            "branches_compressed": resp.branches_compressed,
        }

    def close(self) -> None:
        self._channel.close()


def connect_sidecar(addr: str, session_id: str, *, task_id: str = "mare") -> GrpcAcgcClient:
    if not (addr or "").strip():
        raise RuntimeError("MARE_ACGC is on but ACGC_GRPC_ADDR is empty")
    return GrpcAcgcClient(addr.strip(), session_id, task_id=task_id)
