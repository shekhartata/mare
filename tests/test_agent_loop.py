import json
from types import SimpleNamespace

from app.llm.heuristic import HeuristicReasoningModel
from app.models.schemas import SessionStatus
from app.retrieval.agent_loop import (
    BLIND_SYSTEM_PROMPT,
    INFORMED_SYSTEM_PROMPT,
    run_agent,
)

SEARCH_HIT = {
    "method": "hybrid",
    "count": 1,
    "results": [
        {
            "node_id": "nav:group:cust_007",
            "name": "logs for cust_007",
            "node_type": "group",
            "summary": "AUTH_401 after mig_auth_sso",
            "source": {"database": "mare_demo", "collection": "logs"},
            "score": 0.9,
            "children_preview": [],
        }
    ],
}

LOG_DOC = {
    "count": 1,
    "documents": [
        {
            "ref": {
                "database": "mare_demo",
                "collection": "logs",
                "document_id": "log_1001",
                "fields": [],
            },
            "text": "AUTH_401 jwt issuer mismatch after mig_auth_sso for cust_007",
            "score": 1.0,
        }
    ],
    "missing_nodes": [],
    "hints": [],
}

SUBMIT = {
    "answer": "SSO failed because of AUTH_401 jwt issuer mismatch after mig_auth_sso.",
    "hypothesis": "Migration broke JWT issuer validation.",
    "claims": [
        {
            "claim_id": "C1",
            "claim": "mig_auth_sso caused AUTH_401 for cust_007",
            "status": "supported",
            "confidence": 0.9,
        }
    ],
    "cited_source_ids": ["mare_demo.logs:log_1001"],
}


class FakeClient:
    def __init__(self, script: list) -> None:
        self._script = list(script)
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._script:
            raise AssertionError("unexpected extra LLM call")
        return self._script.pop(0)


def _tool_call(call_id: str, name: str, args: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


def _response(tool_calls=None, content=None) -> SimpleNamespace:
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    usage = SimpleNamespace(prompt_tokens=8, completion_tokens=4, total_tokens=12)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def _handlers() -> dict:
    return {
        "search_information": lambda query, **kwargs: SEARCH_HIT,
        "retrieve_evidence": lambda node_ids, **kwargs: LOG_DOC,
        "query_documents": lambda namespace, filter, **kwargs: {"count": 0, "documents": []},
    }


def _run(script, **kwargs):
    client = FakeClient(script)
    params = {
        "client": client,
        "handlers": _handlers(),
        "persist": False,
        "agent_model": "gpt-5-mini",
        "answer_model": "gpt-5-mini",
        "reasoning_effort": "low",
    }
    params.update(kwargs)
    session = run_agent("Why did Apex Logistics fail after mig_auth_sso?", **params)
    return session, client


def test_loop_search_retrieve_submit():
    session, client = _run(
        [
            _response([_tool_call("c1", "search_information", {"query": "mig_auth_sso"})]),
            _response(
                [_tool_call("c2", "retrieve_evidence", {"node_ids": ["nav:group:cust_007"]})]
            ),
            _response([_tool_call("c3", "submit_answer", SUBMIT)]),
        ]
    )
    assert session.status == SessionStatus.complete
    assert session.stop_reason == "completed"
    assert session.agent_turns == 3
    assert session.tool_calls == 3
    assert session.retrieval_count == 1
    assert session.tokens_consumed == 36
    assert session.answer.startswith("SSO failed")
    assert session.hypothesis.startswith("Migration broke")
    assert session.claims[0].claim_id == "C1"
    assert session.citations[0].document_id == "log_1001"
    assert session.citations[0].collection == "logs"
    assert client._script == []
    assert client.calls[0]["reasoning_effort"] == "low"
    assert client.calls[0]["tool_choice"] == "auto"


def test_budget_forces_submit_answer():
    session, client = _run(
        [
            _response(
                [_tool_call("c1", "retrieve_evidence", {"node_ids": ["nav:group:cust_007"]})]
            ),
            _response([_tool_call("c2", "submit_answer", SUBMIT)]),
        ],
        max_turns=1,
    )
    assert session.status == SessionStatus.budget_exhausted
    assert session.stop_reason == "max_agent_turns"
    assert session.agent_turns == 2
    assert session.citations[0].document_id == "log_1001"
    assert client.calls[1]["tool_choice"] == {
        "type": "function",
        "function": {"name": "submit_answer"},
    }
    user_text = " ".join(
        str(m.get("content") or "") for m in client.calls[1]["messages"] if m.get("role") == "user"
    )
    assert "budget" in user_text.lower()


def test_citations_harvested_even_without_cited_ids():
    draft = dict(SUBMIT)
    draft["cited_source_ids"] = []
    session, _ = _run(
        [
            _response(
                [_tool_call("c1", "retrieve_evidence", {"node_ids": ["nav:group:cust_007"]})]
            ),
            _response([_tool_call("c2", "submit_answer", draft)]),
        ]
    )
    assert [c.document_id for c in session.citations] == ["log_1001"]


def test_same_model_skips_synthesis():
    reasoner = HeuristicReasoningModel()
    calls_before = 0

    def generate(prompt, *, system=None):
        nonlocal calls_before
        calls_before += 1
        return HeuristicReasoningModel.generate(reasoner, prompt, system=system)

    reasoner.generate = generate  # type: ignore[method-assign]
    session, _ = _run(
        [
            _response(
                [_tool_call("c1", "retrieve_evidence", {"node_ids": ["nav:group:cust_007"]})]
            ),
            _response([_tool_call("c2", "submit_answer", SUBMIT)]),
        ],
        answer_reasoner=reasoner,
    )
    assert calls_before == 0
    assert session.answer.startswith("SSO failed")


def test_different_model_synthesizes_from_evidence():
    class Counter(HeuristicReasoningModel):
        def __init__(self) -> None:
            self.calls = 0

        def generate(self, prompt, *, system=None):
            self.calls += 1
            return super().generate(prompt, system=system)

    reasoner = Counter()
    session, client = _run(
        [
            _response(
                [_tool_call("c1", "retrieve_evidence", {"node_ids": ["nav:group:cust_007"]})]
            ),
            _response([_tool_call("c2", "submit_answer", SUBMIT)]),
        ],
        answer_model="gpt-5",
        answer_reasoner=reasoner,
    )
    assert reasoner.calls == 1
    assert session.agent_turns == 3  # 2 tool turns + synthesis
    assert "AUTH_401" in session.answer or "mig_auth_sso" in session.answer
    assert session.citations[0].document_id == "log_1001"
    assert len(client.calls) == 2


SCHEMA_LEAKS = (
    "mare_demo",
    "customers",
    "tickets",
    "deployments",
    "migrations",
    "incidents",
    "subscription_tier",
    "customer_id",
    "error_code",
)


def test_blind_prompt_has_no_dataset_schema():
    low = BLIND_SYSTEM_PROMPT.lower()
    for token in SCHEMA_LEAKS:
        assert token not in low, token
    assert "related_nodes" in low
    assert "mare_demo" in INFORMED_SYSTEM_PROMPT
    assert "customers" in INFORMED_SYSTEM_PROMPT


def test_default_loop_uses_blind_prompt():
    session, client = _run(
        [
            _response([_tool_call("c1", "search_information", {"query": "mig_auth_sso"})]),
            _response(
                [_tool_call("c2", "retrieve_evidence", {"node_ids": ["nav:group:cust_007"]})]
            ),
            _response([_tool_call("c3", "submit_answer", SUBMIT)]),
        ]
    )
    assert session.status == SessionStatus.complete
    system = client.calls[0]["messages"][0]["content"]
    assert system == BLIND_SYSTEM_PROMPT
    assert "mare_demo" not in system


def test_informed_loop_opt_in():
    _, client = _run(
        [
            _response(
                [_tool_call("c1", "retrieve_evidence", {"node_ids": ["nav:group:cust_007"]})]
            ),
            _response([_tool_call("c2", "submit_answer", SUBMIT)]),
        ],
        schema_in_prompt=True,
    )
    system = client.calls[0]["messages"][0]["content"]
    assert system == INFORMED_SYSTEM_PROMPT
    assert "mare_demo" in system
