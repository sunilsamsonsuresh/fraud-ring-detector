"""Tests of src/agents/planner.py (new system). The LLM is a fake. No Neo4j."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents import planner
from src.agents.planner import (
    AGENT_OF_TOOL,
    AGENT_TOOLS,
    MAX_AGENT_CALLS,
    find_claim_ids,
    messages_of_this_turn,
)


@pytest.fixture
def model(monkeypatch):
    class FakeModel:
        answer = AIMessage("Note: answer the greeting.")

        def __init__(self):
            self.calls = []

        def __call__(
            self, messages, tools, system_prompt, one_tool_at_a_time=False, **settings
        ):
            self.calls.append(
                {"messages": list(messages), "tools": tools, "one": one_tool_at_a_time}
            )
            if isinstance(self.answer, Exception):
                raise self.answer
            return self.answer

    fake = FakeModel()
    fake.calls = []
    monkeypatch.setattr(planner, "ask_llm_with_tools", fake)
    return fake


def agent_call(tool_name, task, call_id):
    return AIMessage(
        content="",
        tool_calls=[{"name": tool_name, "args": {"task": task}, "id": call_id}],
    )


def test_claim_ids_are_found_cleaned_and_listed_once():
    assert find_claim_ids("Compare c-1001 with C-1002, and c-1001 again.") == [
        "C-1001",
        "C-1002",
    ]
    assert find_claim_ids("AC-10012 and C-12 are not claim IDs") == []


def test_the_planner_sees_the_whole_conversation_and_only_the_agents(model):
    history = [
        HumanMessage("Hi"),
        AIMessage("Hello.", name="answer_writer"),
        HumanMessage("Why is C-1088 High?"),
    ]
    model.answer = agent_call("ask_scorer", "Get the score of C-1088", "r1")
    result = planner.planner({"messages": history})
    assert result == {"messages": [model.answer]}
    call = model.calls[0]
    assert call["messages"] == history and call["one"] is True
    assert sorted(tool["name"] for tool in call["tools"]) == sorted(AGENT_OF_TOOL)


def test_every_agent_tool_takes_one_task_and_has_a_node():
    for tool in AGENT_TOOLS:
        assert (
            tool["input_schema"]["required"] == ["task"]
            and tool["name"] in AGENT_OF_TOOL
        )
    assert set(AGENT_OF_TOOL.values()) == {
        "local_search",
        "document_search",
        "scorer",
        "graph_query",
        "global_search",
    }


def test_the_planner_stops_after_too_many_agent_calls(model):
    history = [HumanMessage("Look again and again")]
    for number in range(MAX_AGENT_CALLS):
        history += [
            agent_call("ask_scorer", "x", f"r{number}"),
            ToolMessage("{}", tool_call_id=f"r{number}"),
        ]
    result = planner.planner({"messages": history})
    assert "stopped after" in result["messages"][0].text and model.calls == []


def test_an_llm_failure_becomes_a_note_not_a_crash(model):
    model.answer = RuntimeError("Cannot reach the Anthropic API.")
    result = planner.planner({"messages": [HumanMessage("Hi")]})
    assert "Cannot reach the Anthropic API." in result["messages"][0].text


def test_messages_of_this_turn_start_after_the_last_question():
    history = [
        HumanMessage("one"),
        AIMessage("a"),
        HumanMessage("two"),
        AIMessage("b"),
        AIMessage("c"),
    ]
    assert [message.text for message in messages_of_this_turn(history)] == ["b", "c"]


def test_the_planner_splits_the_question_and_does_not_write_the_answer():
    prompt = planner.SYSTEM_PROMPT
    assert "Split the question into its parts" in prompt
    assert "Ask one agent at a time" in prompt
    assert (
        "at most two sentences" in prompt
        and "Do NOT write the answer yourself" in prompt
    )
