"""Tests of the scorer agent (src/agents/scorer.py) and of the shared MCP client code
(src/mcp_servers/call_server_tool.py: call_mcp_tool, work_on_task, answer_planner_task).

They start the real MCP servers and use the real graph (Neo4j must be running).
The LLM is a fake that returns scripted answers, so nothing costs money.
The expected score comes from the scoring engine, called directly, and not from the server.
"""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agents import scorer as scorer_module
from src.graph.connection import open_neo4j_driver
from src.mcp_servers import call_server_tool
from src.mcp_servers.call_server_tool import (
    CLAIM_RECORDS_SERVER,
    MAX_TOOL_ROUNDS,
    TOOL_SERVERS,
    call_mcp_tool,
)
from src.scoring.engine import score_facts
from src.scoring.facts import read_claim_facts


def tool_call(name, arguments, call_id):
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": arguments, "id": call_id}]
    )


def planner_asks(task):
    """The state a search agent gets: the planner's last message is a call with the task."""
    return {
        "messages": [
            HumanMessage("question"),
            AIMessage(
                content="",
                tool_calls=[{"name": "ask_scorer", "args": {"task": task}, "id": "r1"}],
            ),
        ]
    }


@pytest.fixture
def model(monkeypatch):
    """A fake strong model: gives the scripted answers in order and records what it received."""

    class FakeModel:
        def __init__(self):
            self.script = []
            self.calls = []

        def __call__(
            self, messages, tools, system_prompt, one_tool_at_a_time=False, **settings
        ):
            self.calls.append(
                {"messages": list(messages), "tools": [tool["name"] for tool in tools]}
            )
            assert self.script, "the model was called more often than the test expected"
            answer = self.script.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

    fake = FakeModel()
    fake.script, fake.calls = [], []
    monkeypatch.setattr(call_server_tool, "ask_llm_with_tools", fake)
    return fake


def findings_of(result):
    return json.loads(result["messages"][0].content)


def test_the_scorer_returns_the_score_of_the_engine(model):
    model.script = [
        tool_call("get_claim_score", {"claim_id": "C-1088"}, "t1"),
        AIMessage("C-1088 scores 22.2, band High."),
    ]
    result = scorer_module.scorer(planner_asks("Get the score of C-1088"))
    findings = findings_of(result)
    driver = open_neo4j_driver()
    try:
        expected = score_facts(read_claim_facts(driver, "C-1088"))
    finally:
        driver.close()
    score = findings["tool_answers"][0]["answer"]["facts"]
    assert (
        (score["total_score"], score["band"])
        == (expected["total_score"], expected["band"])
        == (22.2, "High")
    )
    assert (
        findings["agent"] == "scorer" and findings["task"] == "Get the score of C-1088"
    )
    assert findings["findings"] == "C-1088 scores 22.2, band High."
    assert (
        result["messages"][0].tool_call_id == "r1"
    )  # the answer goes to the planner's call


def test_the_scorer_sees_only_its_own_tools(model):
    model.script = [AIMessage("Nothing to do.")]
    scorer_module.scorer(planner_asks("x"))
    assert model.calls[0]["tools"] == ["get_claim_score", "list_claims_by_score"]
    assert all(name in TOOL_SERVERS for name in scorer_module.TOOL_NAMES)


def test_the_saved_scores_of_all_claims(model):
    model.script = [
        tool_call("list_claims_by_score", {"band": "High"}, "t1"),
        AIMessage("10 claims are High."),
    ]
    facts = findings_of(
        scorer_module.scorer(planner_asks("How many claims are High?"))
    )["tool_answers"][0]["answer"]["facts"]
    assert (
        facts["band_filter"] == "High"
        and facts["matching_claim_count"] == facts["band_counts"]["High"]
    )


def test_a_tool_outside_the_agents_list_is_refused(model):
    model.script = [
        tool_call("search_claim_documents", {"claim_id": "C-1088", "topic": "x"}, "t1"),
        AIMessage("I cannot search documents."),
    ]
    answer = findings_of(scorer_module.scorer(planner_asks("x")))["tool_answers"][0][
        "answer"
    ]
    assert answer["message"] == "There is no tool named search_claim_documents."


def test_a_bad_value_is_refused_by_the_server(model):
    model.script = [
        tool_call("get_claim_score", {"claim_id": "MATCH (n) DETACH DELETE n"}, "t1"),
        AIMessage("No."),
    ]
    answer = findings_of(scorer_module.scorer(planner_asks("x")))["tool_answers"][0][
        "answer"
    ]
    assert "not a claim ID" in answer["message"]


def test_the_tool_answer_goes_back_to_the_model(model):
    model.script = [
        tool_call("get_claim_score", {"claim_id": "C-1088"}, "t1"),
        AIMessage("Done."),
    ]
    scorer_module.scorer(planner_asks("x"))
    second_call = model.calls[1]["messages"]
    assert [message.type for message in second_call] == ["human", "ai", "tool"]
    assert '"total_score": 22.2' in second_call[2].content


def test_too_many_tool_rounds_stop_the_agent(model):
    model.script = [
        tool_call("get_claim_score", {"claim_id": "C-1088"}, f"t{number}")
        for number in range(MAX_TOOL_ROUNDS)
    ]
    findings = findings_of(scorer_module.scorer(planner_asks("x")))
    assert (
        "stopped after" in findings["findings"]
        and len(findings["tool_answers"]) == MAX_TOOL_ROUNDS
    )


def test_an_llm_failure_becomes_findings_not_a_crash(model):
    model.script = [RuntimeError("Cannot reach the Anthropic API.")]
    findings = findings_of(scorer_module.scorer(planner_asks("x")))
    assert "could not work: Cannot reach the Anthropic API." in findings["findings"]


# --- call_mcp_tool ---


def test_call_mcp_tool_returns_the_answer_of_the_tool():
    answer = call_mcp_tool(
        CLAIM_RECORDS_SERVER, "get_claim_record", {"claim_id": "C-1088"}
    )
    assert answer["facts"]["claim_id"] == "C-1088" and answer["sources"]


def test_an_unknown_tool_becomes_a_message():
    assert call_mcp_tool(CLAIM_RECORDS_SERVER, "no_such_tool", {}) == {
        "message": "The tool no_such_tool returned an error.",
        "sources": [],
    }


def test_a_server_that_does_not_start_becomes_a_message():
    answer = call_mcp_tool("src.mcp_servers.no_such_server", "x", {})
    assert (
        "no_such_server could not be used" in answer["message"]
        and answer["sources"] == []
    )


def test_a_crash_of_the_client_becomes_a_message(monkeypatch):
    def broken_use_server(server_module, calls):
        raise OSError("pipe closed")

    monkeypatch.setattr(call_server_tool, "use_server", broken_use_server)
    assert (
        "pipe closed"
        in call_mcp_tool(CLAIM_RECORDS_SERVER, "get_claim_record", {})["message"]
    )
