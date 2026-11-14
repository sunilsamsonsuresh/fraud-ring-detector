"""Tests of src/agents/global_search.py (build step 5).
Real MCP server and graph (Neo4j must be running, with the communities loaded). Scripted fake LLM: no cost."""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agents import global_search
from src.mcp_servers import call_server_tool


def call(name, arguments, call_id):
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": arguments, "id": call_id}]
    )


def planner_asks(task):
    return {
        "messages": [
            HumanMessage("question"),
            call("ask_global_search", {"task": task}, "r1"),
        ]
    }


@pytest.fixture
def model(monkeypatch):
    class FakeModel:
        def __init__(self):
            self.script, self.tools_seen = [], []

        def __call__(
            self, messages, tools, system_prompt, one_tool_at_a_time=False, **settings
        ):
            self.tools_seen = [tool["name"] for tool in tools]
            return self.script.pop(0)

    fake = FakeModel()
    monkeypatch.setattr(call_server_tool, "ask_llm_with_tools", fake)
    return fake


def answers_of(result):
    return [
        item["answer"]
        for item in json.loads(result["messages"][0].content)["tool_answers"]
    ]


def test_it_sees_only_its_three_tools(model):
    model.script = [AIMessage("Nothing.")]
    global_search.global_search(planner_asks("x"))
    assert model.tools_seen == [
        "list_communities",
        "get_community",
        "find_shared_groups",
    ]


def test_it_reads_the_communities_then_the_biggest_one(model):
    model.script = [
        call("list_communities", {}, "t1"),
        call("get_community", {"community_or_claim_id": "COM-01"}, "t2"),
        AIMessage("COM-01 has 12 claims that share one clinic and one attorney."),
    ]
    answers = answers_of(global_search.global_search(planner_asks("Are there rings?")))
    listed = answers[0]["facts"]["communities"]
    assert [item["community_id"] for item in listed][:3] == [
        "COM-01",
        "COM-02",
        "COM-03",
    ]
    assert answers[1]["facts"]["claim_count"] == listed[0]["claim_count"]
    assert "C-1088" in answers[1]["facts"]["claim_ids"]


def test_it_finds_the_address_groups_without_a_claim_id(model):
    model.script = [
        call("find_shared_groups", {"kind": "address"}, "t1"),
        AIMessage("9 groups."),
    ]
    facts = answers_of(
        global_search.global_search(planner_asks("Which claims share an address?"))
    )[0]["facts"]
    assert facts["group_count"] == 9 and facts["groups"][0]["claim_count"] == 6
