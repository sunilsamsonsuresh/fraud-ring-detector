"""Tests of src/agents/graph_query.py (build step 4).
Real MCP server and graph (Neo4j must be running). Scripted fake LLM: no LLM call, no cost."""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agents import graph_query
from src.mcp_servers import call_server_tool


def planner_asks(task):
    return {
        "messages": [
            HumanMessage("question"),
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "ask_graph_query", "args": {"task": task}, "id": "r1"}
                ],
            ),
        ]
    }


def call(name, arguments, call_id):
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": arguments, "id": call_id}]
    )


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


def test_it_sees_only_its_two_tools(model):
    model.script = [AIMessage("Nothing.")]
    graph_query.graph_query(planner_asks("x"))
    assert model.tools_seen == ["get_graph_map", "run_read_query"]


def test_a_refused_query_comes_back_and_the_fixed_query_runs(model, capsys):
    model.script = [
        call("get_graph_map", {}, "t1"),
        call("run_read_query", {"query": "MATCH (c:Claim) SET c.x = 1 RETURN c"}, "t2"),
        call(
            "run_read_query",
            {
                "query": "MATCH (c:Claim) RETURN c.status AS status, count(*) AS claims ORDER BY status LIMIT 10"
            },
            "t3",
        ),
        AIMessage("There are 500 claims: closed, open and in litigation."),
    ]
    result = graph_query.graph_query(planner_asks("How many claims per status?"))
    findings = json.loads(result["messages"][0].content)
    answers = [item["answer"] for item in findings["tool_answers"]]
    assert "nodes" in answers[0]["facts"]
    assert "word SET is not allowed" in answers[1]["message"]
    rows = answers[2]["facts"]["rows"]
    assert sum(row["claims"] for row in rows) == 500
    # The generated query shows in the chat log.
    assert (
        "[graph_query] calls run_read_query(query=MATCH (c:Claim) SET"
        in capsys.readouterr().out
    )
