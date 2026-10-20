"""Same-turn parallel reads stay ordered, and everything else stays serial."""

import json
import threading
import time

from app.retrieval.agent_loop import run_agent
from app.retrieval.tool_policy import (
    ToolHandlers,
    ToolPolicy,
    validate_retrieve,
    validate_search,
)
from app.retrieval.tool_scheduler import plan_calls, run_bounded, segments
from tests.test_agent_loop import SEARCH_HIT, SUBMIT, FakeClient, _response, _tool_call


def _search_script(*queries: str):
    calls = [
        _tool_call(f"c{i}", "search_information", {"query": query})
        for i, query in enumerate(queries, start=1)
    ]
    return [
        _response(calls),
        _response([_tool_call("done", "submit_answer", SUBMIT)]),
        _response([_tool_call("done-2", "submit_answer", SUBMIT)]),
    ]


def _messages(client: FakeClient) -> list[dict]:
    return [message for message in client.calls[-1]["messages"] if message.get("role") == "tool"]


def _approved(mapping: dict) -> ToolHandlers:
    handlers = ToolHandlers(mapping)
    if "search_information" in mapping:
        handlers.policies["search_information"] = ToolPolicy(
            True, True, False, validate_search, mapping["search_information"]
        )
    if "retrieve_evidence" in mapping:
        handlers.policies["retrieve_evidence"] = ToolPolicy(
            True, True, False, validate_retrieve, mapping["retrieve_evidence"]
        )
    return handlers


def test_two_reads_overlap_and_keep_request_order():
    barrier = threading.Barrier(2, timeout=2)
    order: list[str] = []

    def search(query, **kwargs):
        del kwargs
        barrier.wait()
        order.append(query)
        return SEARCH_HIT

    client = FakeClient(_search_script("first query", "second query"))
    session = run_agent(
        "question",
        client=client,
        handlers=_approved({"search_information": search}),
        persist=False,
        agent_model="gpt-5-mini",
        answer_model="gpt-5-mini",
        reasoning_effort=None,
        parallel_tools="on",
    )
    assert session.stop_reason == "completed"
    assert [message["tool_call_id"] for message in _messages(client)[:2]] == ["c1", "c2"]
    assert session.tool_stats["turns"][0]["parallel_batches"] == 1
    assert set(order) == {"first query", "second query"}


def test_same_collection_queries_can_be_eligible():
    handlers = ToolHandlers(
        {
            "query_documents": lambda namespace, filter, **kwargs: {
                "count": 0,
                "documents": [],
                "namespace": namespace,
            }
        }
    )
    handlers.policies = {
        "query_documents": ToolPolicy(
            True,
            True,
            False,
            lambda args, ledger: None
            if args.get("namespace") in ledger.namespaces
            else "namespace was not returned by an earlier tool",
            handlers["query_documents"],
        )
    }
    from app.retrieval.tool_policy import Ledger

    ledger = Ledger(namespaces={"mare_shop.orders"})
    calls = [
        {"id": "a", "function": {"name": "query_documents", "arguments": json.dumps({
            "namespace": "mare_shop.orders", "filter": {"sku": "a"}
        })}},
        {"id": "b", "function": {"name": "query_documents", "arguments": json.dumps({
            "namespace": "mare_shop.orders", "filter": {"sku": "b"}
        })}},
    ]
    planned = plan_calls(calls, handlers, ledger, cap=2)
    assert [call.decision for call in planned] == ["parallel_eligible", "parallel_eligible"]


def test_unresolved_reference_is_not_executed():
    called = {"retrieve": 0}

    def retrieve(node_ids, **kwargs):
        del node_ids, kwargs
        called["retrieve"] += 1
        return {"count": 0, "documents": []}

    def search(query, **kwargs):
        del query, kwargs
        return SEARCH_HIT

    client = FakeClient(
        [
            _response(
                [
                    _tool_call("c1", "search_information", {"query": "pilled"}),
                    _tool_call("c2", "retrieve_evidence", {"node_ids": ["card:not-yet"]}),
                ]
            ),
            _response([_tool_call("c3", "submit_answer", SUBMIT)]),
            _response([_tool_call("c4", "submit_answer", SUBMIT)]),
        ]
    )
    run_agent(
        "question",
        client=client,
        handlers=_approved(
            {"search_information": search, "retrieve_evidence": retrieve}
        ),
        persist=False,
        agent_model="gpt-5-mini",
        answer_model="gpt-5-mini",
        reasoning_effort=None,
        parallel_tools="on",
    )
    assert called["retrieve"] == 0
    body = json.loads(_messages(client)[1]["content"])
    assert "not returned" in body["error"]


def test_custom_handler_does_not_inherit_parallel_approval():
    overlap = {"value": False}
    held = threading.Lock()

    def search(query, **kwargs):
        del query, kwargs
        if not held.acquire(blocking=False):
            overlap["value"] = True
            return SEARCH_HIT
        try:
            time.sleep(0.05)
            return SEARCH_HIT
        finally:
            held.release()

    handlers = ToolHandlers({"search_information": search})
    handlers.policies = {
        "search_information": ToolPolicy(True, True, False, validate_search, lambda *a, **k: None)
    }
    run_agent(
        "question",
        client=FakeClient(_search_script("one", "two")),
        handlers=handlers,
        persist=False,
        agent_model="gpt-5-mini",
        answer_model="gpt-5-mini",
        reasoning_effort=None,
        parallel_tools="on",
    )
    assert overlap["value"] is False


def test_completion_order_does_not_reorder_messages():
    started = threading.Event()

    def search(query, **kwargs):
        del kwargs
        if query == "first query":
            assert started.wait(2)
        else:
            started.set()
        return SEARCH_HIT

    client = FakeClient(_search_script("first query", "second query"))
    run_agent(
        "question",
        client=client,
        handlers=_approved({"search_information": search}),
        persist=False,
        agent_model="gpt-5-mini",
        answer_model="gpt-5-mini",
        reasoning_effort=None,
        parallel_tools="on",
    )
    assert [message["tool_call_id"] for message in _messages(client)[:2]] == ["c1", "c2"]


def test_sibling_error_keeps_the_other_result():
    def search(query, **kwargs):
        del kwargs
        if query == "boom":
            raise RuntimeError("nope")
        return SEARCH_HIT

    client = FakeClient(_search_script("boom", "ok"))
    run_agent(
        "question",
        client=client,
        handlers=_approved({"search_information": search}),
        persist=False,
        agent_model="gpt-5-mini",
        answer_model="gpt-5-mini",
        reasoning_effort=None,
        parallel_tools="on",
    )
    bodies = [json.loads(message["content"]) for message in _messages(client)[:2]]
    assert bodies[0]["error"] == "nope"
    assert bodies[1]["count"] == 1


def test_global_semaphore_caps_concurrency():
    state = {"current": 0, "max": 0}
    lock = threading.Lock()

    def worker(call):
        del call
        with lock:
            state["current"] += 1
            state["max"] = max(state["max"], state["current"])
        time.sleep(0.05)
        with lock:
            state["current"] -= 1
        return {"ok": True}

    from app.retrieval.tool_scheduler import PlannedCall

    calls = [
        PlannedCall(i, str(i), "search_information", {}, {}, "parallel_eligible", "")
        for i in range(3)
    ]
    run_bounded(
        calls,
        worker,
        deadline=time.perf_counter() + 5,
        semaphore=threading.BoundedSemaphore(1),
    )
    assert state["max"] == 1


def test_cap_splits_a_batch():
    calls = plan_calls(
        [
            {"id": str(i), "function": {"name": "search_information", "arguments": {"query": "q"}}}
            for i in range(3)
        ],
        ToolHandlers({}),
        None,
        cap=2,
    )
    for call in calls:
        call.decision = "parallel_eligible"
    grouped = segments(calls, 2)
    assert [len(segment.calls) for segment in grouped] == [2, 1]


def test_parallel_preserves_tenant_on_each_call():
    seen: list[str] = []
    barrier = threading.Barrier(2, timeout=2)

    def search(query, tenant_id=None, **kwargs):
        del query, kwargs
        seen.append(tenant_id)
        barrier.wait()
        return SEARCH_HIT

    run_agent(
        "question",
        client=FakeClient(_search_script("one", "two")),
        handlers=_approved({"search_information": search}),
        persist=False,
        tenant_id="tenant-a",
        agent_model="gpt-5-mini",
        answer_model="gpt-5-mini",
        reasoning_effort=None,
        parallel_tools="on",
    )
    assert seen == ["tenant-a", "tenant-a"]


def test_mixed_submit_is_deferred_and_forced_mode_does_not_retrieve():
    searches = {"n": 0}

    def search(query, **kwargs):
        del query, kwargs
        searches["n"] += 1
        return SEARCH_HIT

    client = FakeClient(
        [
            _response(
                [
                    _tool_call("c1", "search_information", {"query": "pilled"}),
                    _tool_call("c2", "submit_answer", SUBMIT),
                ]
            ),
            _response([_tool_call("c3", "submit_answer", SUBMIT)]),
            _response([_tool_call("c4", "submit_answer", SUBMIT)]),
        ]
    )
    session = run_agent(
        "question",
        client=client,
        handlers={"search_information": search},
        persist=False,
        agent_model="gpt-5-mini",
        answer_model="gpt-5-mini",
        reasoning_effort=None,
        parallel_tools="on",
    )
    assert searches["n"] == 1
    assert json.loads(_messages(client)[1]["content"])["deferred"] is True
    assert session.answer.startswith("SSO failed")

    searches["n"] = 0
    forced = run_agent(
        "question",
        client=FakeClient(
            [
                _response(
                    [
                        _tool_call("c1", "search_information", {"query": "pilled"}),
                        _tool_call("c2", "submit_answer", SUBMIT),
                    ]
                )
            ]
        ),
        handlers={"search_information": search},
        persist=False,
        max_turns=0,
        agent_model="gpt-5-mini",
        answer_model="gpt-5-mini",
        reasoning_effort=None,
        parallel_tools="on",
    )
    assert searches["n"] == 0
    assert forced.answer.startswith("SSO failed")


def test_shadow_and_off_do_not_overlap():
    for mode in ("off", "shadow"):
        overlap = {"value": False}
        held = threading.Lock()

        def search(query, **kwargs):
            del query, kwargs
            if not held.acquire(blocking=False):
                overlap["value"] = True
                return SEARCH_HIT
            try:
                time.sleep(0.04)
                return SEARCH_HIT
            finally:
                held.release()

        session = run_agent(
            "question",
            client=FakeClient(_search_script("one", "two")),
            handlers=_approved({"search_information": search}),
            persist=False,
            agent_model="gpt-5-mini",
            answer_model="gpt-5-mini",
            reasoning_effort=None,
            parallel_tools=mode,
        )
        assert overlap["value"] is False
        assert session.answer.startswith("SSO failed")
        if mode == "shadow":
            assert session.tool_stats["turns"][0]["parallel_batches"] == 0
            assert session.tool_stats["turns"][0]["eligible"] == 2
