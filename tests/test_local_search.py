"""Tests of src/agents/local_search.py (new system).
Real MCP servers and graph (Neo4j must be running). The LLM is a scripted fake."""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agents import local_search
from src.mcp_servers import call_server_tool
from src.mcp_servers.call_server_tool import TOOL_SERVERS


def tool_call(name, arguments, call_id):
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": arguments, "id": call_id}]
    )


def planner_asks(task):
    return {
        "messages": [
            HumanMessage("question"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "ask_local_search",
                        "args": {"task": task},
                        "id": "r1",
                    }
                ],
            ),
        ]
    }


@pytest.fixture
def model(monkeypatch):
    class FakeModel:
        def __init__(self):
            self.script = []
            self.tools_seen = []

        def __call__(
            self, messages, tools, system_prompt, one_tool_at_a_time=False, **settings
        ):
            self.tools_seen = [tool["name"] for tool in tools]
            return self.script.pop(0)

    fake = FakeModel()
    fake.script = []
    monkeypatch.setattr(call_server_tool, "ask_llm_with_tools", fake)
    return fake


def answers_of(result):
    return [
        item["answer"]
        for item in json.loads(result["messages"][0].content)["tool_answers"]
    ]


def test_it_sees_only_the_link_tools(model):
    model.script = [AIMessage("Nothing.")]
    local_search.local_search(planner_asks("x"))
    assert model.tools_seen == local_search.TOOL_NAMES
    assert all(name in TOOL_SERVERS for name in local_search.TOOL_NAMES)
    assert (
        "get_claim_score" not in model.tools_seen
        and "search_claim_documents" not in model.tools_seen
    )


def test_the_group_tool_now_belongs_to_global_search(model):
    # Build step 5 moved find_shared_groups to the global search agent. Local search cannot run it.
    model.script = [
        tool_call("find_shared_groups", {"kind": "address"}, "t1"),
        AIMessage("No answer."),
    ]
    answer = answers_of(
        local_search.local_search(planner_asks("Which claims share an address?"))
    )[0]
    assert answer["message"] == "There is no tool named find_shared_groups."


def test_it_can_use_several_tools_for_one_task(model):
    model.script = [
        tool_call("get_claim_record", {"claim_id": "C-1088"}, "t1"),
        tool_call("get_claim_neighbourhood", {"claim_id": "C-1088"}, "t2"),
        AIMessage("C-1088 has 10 linked claims."),
    ]
    answers = answers_of(local_search.local_search(planner_asks("Look at C-1088")))
    assert (
        answers[0]["facts"]["loss_date"] == "2024-12-15"
        and answers[1]["facts"]["linked_claim_count"] == 10
    )


def test_a_phone_lookup_returns_the_claims(model):
    model.script = [
        tool_call("find_claims_sharing_phone", {"phone": "713-555-2172"}, "t1"),
        AIMessage("7 claims."),
    ]
    claims = answers_of(local_search.local_search(planner_asks("phone 713-555-2172")))[
        0
    ]["facts"]["claims"]
    assert "C-1026" in [claim["claim_id"] for claim in claims]
